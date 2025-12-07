"""News sentiment pipeline integration for the portfolio server.

This module wraps the experimental scripts from ``pw-scripts/NEWS_SENTIMENT`` and
exposes a production-friendly helper that can be orchestrated by Celery.

The goal is to:

* Fetch sector-wise news using NewsAPI via Pathway tables/UDFs.
* Score articles with FinBERT sentiment.
* Aggregate the data and (optionally) call Gemini for sector and stock level
  suggestions.
* Persist artefacts in ``apps/portfolio-server/pipelines/news`` so that the API
  layer (or analysts) can consume them.

When API keys are missing the pipeline returns deterministic placeholder data so
downstream consumers always have a well-formed JSON payload to work with.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pandas as pd
import pathway as pw
from dotenv import load_dotenv

# Suppress verbose Pathway sink logging
os.environ.setdefault("PATHWAY_LOG_LEVEL", "WARNING")
# Suppress Pathway IO sink loggers specifically
logging.getLogger("pathway.io").setLevel(logging.WARNING)
logging.getLogger("pathway.io.kafka").setLevel(logging.WARNING)

from kafka_service import (  # type: ignore  # noqa: E402
    KafkaPublisher,
    PublisherAlreadyRegistered,
    default_kafka_bus,
)
from pydantic import BaseModel

from .research_pipeline import (
    NEWS_STREAMS,
    StreamSchema,
    build_news_sentiment_pipeline,
    compute_technical_indicators,
    stock_recommender,
    trading_agent_llm,
)


# Ensure environment variables from the portfolio server are loaded even when
# the pipeline is executed in isolation (e.g. via Celery worker).
PORTFOLIO_ENV_PATH = os.getenv("PORTFOLIO_SERVER_ENV_PATH")
if PORTFOLIO_ENV_PATH and Path(PORTFOLIO_ENV_PATH).exists():
    load_dotenv(PORTFOLIO_ENV_PATH, override=False)
else:
    server_env = Path(__file__).resolve().parents[3] / ".env"
    if server_env.exists():
        load_dotenv(server_env, override=False)


# ---------------------------------------------------------------------------
# Kafka integration for stock recommendations
# ---------------------------------------------------------------------------

NEWS_RECO_TOPIC = os.getenv("NEWS_STOCK_RECOMMENDATIONS_TOPIC", "news_pipeline_stock_recomendations")
NEWS_RECO_PUBLISHER_NAME = "news_stock_recommendations_publisher"

NEWS_SENTIMENT_TOPIC = os.getenv("NEWS_SENTIMENT_ARTICLES_TOPIC", "news_pipeline_sentiment_articles")
NEWS_SENTIMENT_PUBLISHER_NAME = "news_sentiment_articles_publisher"

NEWS_SECTOR_TOPIC = os.getenv("NEWS_SECTOR_ANALYSIS_TOPIC", "news_pipeline_sector_analysis")
NEWS_SECTOR_PUBLISHER_NAME = "news_sector_analysis_publisher"


class NewsStockRecommendationEvent(BaseModel):
    sector: Optional[str] = None
    stock_name: Optional[str] = None
    trade_signal: Optional[str] = None
    detailed_analysis: Optional[str] = None
    time_window_investment: Optional[str] = None
    news_source: Optional[str] = None
    news_source_url: Optional[str] = None
    provider: str
    generated_at: str


class NewsSentimentArticleEvent(BaseModel):
    stream: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    sentiment: Optional[str] = None
    url: Optional[str] = None
    provider: str
    generated_at: str


class NewsSectorAnalysisEvent(BaseModel):
    stream_count: int
    analysis: str
    provider: str
    generated_at: str


_news_reco_publisher: Optional[KafkaPublisher] = None
_news_sentiment_publisher: Optional[KafkaPublisher] = None
_news_sector_publisher: Optional[KafkaPublisher] = None


def _get_news_reco_publisher() -> KafkaPublisher:
    global _news_reco_publisher

    if _news_reco_publisher is not None:
        return _news_reco_publisher

    bus = default_kafka_bus
    try:
        _news_reco_publisher = bus.register_publisher(
            NEWS_RECO_PUBLISHER_NAME,
            topic=NEWS_RECO_TOPIC,
            value_model=NewsStockRecommendationEvent,
            default_headers={"source": "news_pipeline"},
        )
    except PublisherAlreadyRegistered:
        _news_reco_publisher = bus.get_publisher(NEWS_RECO_PUBLISHER_NAME)

    return _news_reco_publisher


def _get_news_sentiment_publisher() -> KafkaPublisher:
    global _news_sentiment_publisher

    if _news_sentiment_publisher is not None:
        return _news_sentiment_publisher

    bus = default_kafka_bus
    try:
        _news_sentiment_publisher = bus.register_publisher(
            NEWS_SENTIMENT_PUBLISHER_NAME,
            topic=NEWS_SENTIMENT_TOPIC,
            value_model=NewsSentimentArticleEvent,
            default_headers={"source": "news_pipeline"},
        )
    except PublisherAlreadyRegistered:
        _news_sentiment_publisher = bus.get_publisher(NEWS_SENTIMENT_PUBLISHER_NAME)

    return _news_sentiment_publisher


def _get_news_sector_publisher() -> KafkaPublisher:
    global _news_sector_publisher

    if _news_sector_publisher is not None:
        return _news_sector_publisher

    bus = default_kafka_bus
    try:
        _news_sector_publisher = bus.register_publisher(
            NEWS_SECTOR_PUBLISHER_NAME,
            topic=NEWS_SECTOR_TOPIC,
            value_model=NewsSectorAnalysisEvent,
            default_headers={"source": "news_pipeline"},
        )
    except PublisherAlreadyRegistered:
        _news_sector_publisher = bus.get_publisher(NEWS_SECTOR_PUBLISHER_NAME)

    return _news_sector_publisher


def _publish_stock_recommendations_to_kafka(
    recommendations: List[Dict[str, Any]],
    *,
    provider: str,
    generated_at: str,
    logger: logging.Logger,
) -> None:
    if not recommendations:
        logger.info("No stock recommendations produced; skipping Kafka publication")
        return

    try:
        publisher = _get_news_reco_publisher()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Unable to initialise news stock recommendation publisher: %s", exc)
        return

    published = 0
    for item in recommendations:
        try:
            event = NewsStockRecommendationEvent(
                sector=item.get("sector"),
                stock_name=item.get("stock_name"),
                trade_signal=item.get("trade_signal"),
                detailed_analysis=item.get("detailed_analysis"),
                time_window_investment=item.get("time_window_investment"),
                news_source=item.get("news_source"),
                news_source_url=item.get("news_source_url"),
                provider=provider,
                generated_at=generated_at,
            )
            publisher.publish(event.model_dump(), key=event.stock_name or event.sector)
            published += 1
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to publish stock recommendation for %s: %s",
                item.get("stock_name", "<unknown>"),
                exc,
            )

    logger.info(
        "Published %s news stock recommendation(s) to Kafka topic %s",
        published,
        NEWS_RECO_TOPIC,
    )


def _publish_sentiment_articles_to_kafka(
    sentiment_by_stream: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    provider: str,
    generated_at: str,
    logger: logging.Logger,
) -> None:
    articles = [
        (stream, article)
        for stream, items in sentiment_by_stream.items()
        for article in items
    ]
    if not articles:
        logger.info("No sentiment articles to publish; skipping Kafka publication")
        return

    try:
        publisher = _get_news_sentiment_publisher()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Unable to initialise news sentiment publisher: %s", exc)
        return

    published = 0
    for stream, article in articles:
        try:
            event = NewsSentimentArticleEvent(
                stream=stream,
                title=article.get("title"),
                content=article.get("content"),
                sentiment=article.get("sentiment"),
                url=article.get("url"),
                provider=provider,
                generated_at=generated_at,
            )
            publisher.publish(event.model_dump(), key=stream)
            published += 1
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "Failed to publish sentiment article for stream %s: %s",
                stream,
                exc,
            )

    logger.info(
        "Published %s sentiment article(s) to Kafka topic %s",
        published,
        NEWS_SENTIMENT_TOPIC,
    )


def _publish_sector_analysis_to_kafka(
    payload: Mapping[str, Any],
    *,
    provider: str,
    generated_at: str,
    logger: logging.Logger,
) -> None:
    analysis = str(payload.get("analysis") or "").strip()
    stream_count = int(payload.get("stream_count") or 0)
    if not analysis:
        logger.info("No sector analysis content to publish; skipping Kafka publication")
        return

    try:
        publisher = _get_news_sector_publisher()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Unable to initialise sector analysis publisher: %s", exc)
        return

    try:
        event = NewsSectorAnalysisEvent(
            stream_count=stream_count,
            analysis=analysis,
            provider=provider,
            generated_at=generated_at,
        )
        publisher.publish(event.model_dump(), key=provider or "sector_analysis")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to publish sector analysis event: %s", exc)
        return

    logger.info(
        "Published sector analysis update to Kafka topic %s (streams=%s, provider=%s)",
        NEWS_SECTOR_TOPIC,
        stream_count,
        provider,
    )


# Eagerly initialise the publisher so the topic exists before subscribers attach.
try:
    _get_news_reco_publisher()
    logging.getLogger(__name__).info(
        "[KAFKA] News stock recommendation publisher initialised; topic '%s' ready.",
        NEWS_RECO_TOPIC,
    )
except Exception as exc:  # pragma: no cover - defensive logging
    logging.getLogger(__name__).warning(
        "[KAFKA] Unable to initialise news stock recommendation publisher: %s",
        exc,
    )

try:
    _get_news_sentiment_publisher()
    logging.getLogger(__name__).info(
        "[KAFKA] News sentiment publisher initialised; topic '%s' ready.",
        NEWS_SENTIMENT_TOPIC,
    )
except Exception as exc:  # pragma: no cover - defensive logging
    logging.getLogger(__name__).warning(
        "[KAFKA] Unable to initialise news sentiment publisher: %s",
        exc,
    )

try:
    _get_news_sector_publisher()
    logging.getLogger(__name__).info(
        "[KAFKA] Sector analysis publisher initialised; topic '%s' ready.",
        NEWS_SECTOR_TOPIC,
    )
except Exception as exc:  # pragma: no cover - defensive logging
    logging.getLogger(__name__).warning(
        "[KAFKA] Unable to initialise sector analysis publisher: %s",
        exc,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_stream_table(top_k: int) -> pw.Table:
    """Materialise the NEWS_STREAMS mapping into a Pathway table."""

    rows = [(stream, query, top_k) for stream, query in NEWS_STREAMS.items()]
    return pw.debug.table_from_rows(schema=StreamSchema, rows=rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _prepare_sentiment_output(output_dir: Path) -> Path:
    sentiment_path = output_dir / "sentiment_articles.jsonl"
    if sentiment_path.exists():
        sentiment_path.unlink()
    return sentiment_path


def _aggregate_sentiment(sentiment_path: Path) -> Dict[str, List[Dict[str, Any]]]:
    if not sentiment_path.exists() or sentiment_path.stat().st_size == 0:
        return {}

    df = pd.read_json(sentiment_path, lines=True)
    aggregated: Dict[str, List[Dict[str, Any]]] = {}
    for row in df.itertuples(index=False):
        stream = getattr(row, "stream", "Unknown")
        aggregated.setdefault(stream, []).append(
            {
                "title": getattr(row, "title", ""),
                "content": getattr(row, "content", ""),
                "sentiment": getattr(row, "sentiment", "neutral"),
                "url": getattr(row, "url", ""),
            }
        )
    return aggregated


def _fallback_sentiment() -> Dict[str, List[Dict[str, Any]]]:
    # Return empty dict - no fake sentiment data
    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_news_sentiment_pipeline(
    output_dir: Path,
    *,
    news_api_key: Optional[str],
    gemini_api_key: Optional[str],
    top_k: int = 3,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Run the news sentiment workflow end-to-end.

    Parameters
    ----------
    output_dir:
        Directory where artefacts will be written.
    news_api_key / gemini_api_key:
        API credentials. When missing, the pipeline falls back to deterministic
        placeholder data so downstream consumers still receive structured JSON.
    top_k:
        Number of articles per sector to request from NewsAPI.
    logger:
        Optional logger; defaults to module logger.

    Returns
    -------
    dict
        Metadata describing the pipeline run (counts, file paths, providers).
    """

    log = logger or logging.getLogger(__name__)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_started_at = datetime.utcnow().isoformat() + "Z"
    sentiment_path = _prepare_sentiment_output(output_dir)
    sector_analysis_path = output_dir / "sector_analysis.json"
    recommendations_path = output_dir / "stock_recommendations.json"
    summary_path = output_dir / "news_pipeline_summary.json"

    log.info("Starting news sentiment pipeline (top_k=%s)", top_k)

    # ------------------------------------------------------------------
    # Stage 1: Sentiment extraction (bypassing Pathway for batch processing)
    # ------------------------------------------------------------------
    sentiment_source = "placeholder"
    if news_api_key:
        log.info("Fetching articles via NewsAPI and running sentiment analysis...")
        try:
            # Import the functions we need directly
            from pipelines.news import research_pipeline
            from pipelines.news.research_pipeline import (
                _fetch_news_api,
                _ensure_finbert_loaded,
            )
            import torch
            import torch.nn.functional as F
            
            # Ensure FinBERT is loaded
            _ensure_finbert_loaded()
            
            # Access the module-level variables AFTER loading
            _finbert_tok = research_pipeline._finbert_tok
            _finbert_model = research_pipeline._finbert_model
            _finbert_device = research_pipeline._finbert_device
            
            # Verify FinBERT components are available
            if _finbert_tok is None or _finbert_model is None or _finbert_device is None:
                raise RuntimeError("FinBERT components not properly loaded after _ensure_finbert_loaded()")
            
            # Process each stream
            articles_by_stream = {}
            total_articles = 0
            for stream, query in NEWS_STREAMS.items():
                try:
                    log.info(f"Fetching {top_k} articles for stream: {stream}")
                    articles = _fetch_news_api(stream, query, top_k, news_api_key)
                    
                    # Run sentiment analysis on each article
                    analyzed_articles = []
                    for title, content, url in articles:
                        try:
                            # FinBERT sentiment analysis
                            combined_text = f"{title}. {content}"
                            inputs = _finbert_tok(
                                combined_text,
                                return_tensors="pt",
                                truncation=True,
                                max_length=512,
                                padding=True
                            ).to(_finbert_device)
                            
                            with torch.no_grad():
                                outputs = _finbert_model(**inputs)
                                logits = outputs.logits if hasattr(outputs, "logits") else outputs
                                probs = F.softmax(logits, dim=-1)
                                sentiment_idx = torch.argmax(probs, dim=-1).item()
                                # FinBERT label order: 0=neutral, 1=positive, 2=negative
                                sentiment_map = {0: "neutral", 1: "positive", 2: "negative"}
                                sentiment_label = sentiment_map.get(sentiment_idx, "neutral")
                            
                            analyzed_articles.append({
                                "stream": stream,
                                "title": title,
                                "content": content,
                                "url": url,
                                "sentiment": sentiment_label,
                            })
                        except Exception as sent_exc:
                            log.warning(f"Sentiment analysis failed for article '{title[:50]}...': {sent_exc}")
                            # Still add article with neutral sentiment
                            analyzed_articles.append({
                                "stream": stream,
                                "title": title,
                                "content": content,
                                "url": url,
                                "sentiment": "neutral",
                            })
                    
                    articles_by_stream[stream] = analyzed_articles
                    total_articles += len(analyzed_articles)
                    log.info(f"Stream {stream}: analyzed {len(analyzed_articles)} articles")
                    
                except Exception as exc:
                    log.warning(f"Failed to fetch/analyze articles for {stream}: {exc}")
                    articles_by_stream[stream] = []
            
            # Write to sentiment_articles.jsonl
            with open(sentiment_path, 'w') as f:
                for stream_articles in articles_by_stream.values():
                    for article in stream_articles:
                        f.write(json.dumps(article) + "\n")
            
            if total_articles > 0:
                sentiment_source = "newsapi"
                log.info(f"Article fetching and sentiment analysis completed: {total_articles} articles across {len(articles_by_stream)} streams")
            else:
                log.warning("No articles fetched from NewsAPI, will use fallback")
            
        except Exception as exc:
            log.exception("Article fetching/sentiment failed, using fallback data: %s", exc)
            sentiment_path.unlink(missing_ok=True)
    else:
        log.warning("NEWS_ORG_API_KEY not configured; skipping article fetch (no fake data will be published)")

    if sentiment_source == "placeholder":
        # Don't write fake data - just create empty file
        log.info("No real sentiment data available - skipping placeholder data")
        sentiment_path.write_text("", encoding="utf-8")

    sentiment_by_stream = _aggregate_sentiment(sentiment_path)
    if not sentiment_by_stream:
        sentiment_by_stream = _fallback_sentiment()

    article_count = sum(len(v) for v in sentiment_by_stream.values())
    log.info("Aggregated %s analysed articles across %s streams", article_count, len(sentiment_by_stream))

    # Only publish to Kafka if we have real data
    if article_count > 0 and sentiment_source != "placeholder":
        _publish_sentiment_articles_to_kafka(
            sentiment_by_stream,
            provider=sentiment_source,
            generated_at=run_started_at,
            logger=log,
        )
    else:
        log.info("Skipping sentiment Kafka publish - no real articles to publish")

    # ------------------------------------------------------------------
    # Stage 2: Gemini trading agent (optional)
    # ------------------------------------------------------------------
    sector_agent_source = "placeholder"
    sector_analysis_payload: Dict[str, Any]
    try:
        payload_json = json.dumps(sentiment_by_stream)
    except TypeError:
        payload_json = json.dumps({k: list(v) for k, v in sentiment_by_stream.items()})

    # Normalize API key: treat empty strings as None
    gemini_key = gemini_api_key.strip() if gemini_api_key and isinstance(gemini_api_key, str) else gemini_api_key
    if not gemini_key:
        gemini_key = None

    if gemini_key:
        log.info("Invoking Gemini trading agent for sector analysis")
        try:
            sector_analysis = trading_agent_llm(payload_json, gemini_key)
            if not isinstance(sector_analysis, str):
                sector_analysis = json.dumps(sector_analysis, indent=2)
            sector_agent_source = "gemini"
        except Exception as exc:  # pragma: no cover - external service issues
            log.exception("Gemini trading agent failed: %s", exc)
            sector_analysis = ""  # Empty instead of placeholder
    else:
        log.warning("GEMINI_API_KEY not configured; skipping sector analysis (no fake data will be published)")
        sector_analysis = ""

    sector_analysis_payload = {
        "generated_at": run_started_at,
        "provider": sector_agent_source,
        "stream_count": len(sentiment_by_stream),
        "analysis": sector_analysis,
    }
    _write_json(sector_analysis_path, sector_analysis_payload)
    
    # Only publish to Kafka if we have real analysis
    if sector_analysis and sector_agent_source != "placeholder":
        _publish_sector_analysis_to_kafka(
            sector_analysis_payload,
            provider=sector_agent_source,
            generated_at=run_started_at,
            logger=log,
        )
    else:
        log.info("Skipping sector analysis Kafka publish - no real analysis to publish")

    # ------------------------------------------------------------------
    # Stage 3: Stock recommendations (optional Gemini call)
    # ------------------------------------------------------------------
    recommendation_provider = "placeholder"
    technical_snapshot: List[Dict[str, Any]] = []

    if gemini_key:
        log.info("Computing technical indicators for Nifty 500 stocks using AngelOne...")
        
        # Load Nifty 500 stock list from CSV
        csv_path = Path(__file__).resolve().parents[4] / "scripts" / "ind_nifty500listbrief.csv"
        if csv_path.exists():
            try:
                import pandas as pd
                nifty500_df = pd.read_csv(csv_path)
                log.info(f"Loaded {len(nifty500_df)} stocks from {csv_path.name}")
                
                # Compute technical indicators for each stock
                from .research_pipeline import compute_technical_indicators_for_stocks
                technical_snapshot = compute_technical_indicators_for_stocks(
                    nifty500_df,
                    logger=log,
                    max_stocks=100  # Limit to avoid rate limits and long processing times
                )
                log.info(f"Computed technical indicators for {len(technical_snapshot)} stocks")
            except Exception as exc:
                log.exception(f"Failed to compute technical indicators: {exc}")
                technical_snapshot = []
        else:
            log.warning(f"CSV file not found: {csv_path}, skipping technical indicators")
            technical_snapshot = []

        try:
            tech_json = json.dumps(technical_snapshot)  # Empty list
            log.info("Invoking Gemini stock recommender (sector analysis length: %s chars, tech data: %s stocks)...", 
                    len(sector_analysis_payload["analysis"]), len(technical_snapshot))
            
            # Pass sentiment_data for URL validation to prevent hallucination
            stock_recs = stock_recommender(
                sector_analysis_payload["analysis"],
                tech_json,
                gemini_api_key=gemini_key,
                sentiment_data=sentiment_by_stream,
            )
            if isinstance(stock_recs, str):
                stock_recommendations = json.loads(stock_recs)
            else:
                stock_recommendations = stock_recs
            
            # Handle error responses from stock_recommender
            if isinstance(stock_recommendations, dict) and "error" in stock_recommendations:
                error_detail = stock_recommendations.get("error", "Unknown error")
                raw_text = stock_recommendations.get("raw_text", "")
                log.error("❌ Stock recommender returned error: %s", error_detail)
                if raw_text:
                    log.error("Raw LLM response (first 500 chars): %s", raw_text[:500])
                log.warning("No recommendations generated due to error")
                stock_recommendations = []  # Empty instead of placeholder
            elif not isinstance(stock_recommendations, list):
                log.error("❌ Unexpected recommendation payload type: %s (value: %s)", 
                         type(stock_recommendations), str(stock_recommendations)[:200])
                log.warning("No recommendations generated due to unexpected response")
                stock_recommendations = []  # Empty instead of placeholder
            elif len(stock_recommendations) == 0:
                log.warning("⚠️ Stock recommender returned empty list - no recommendations generated")
                log.warning("This may indicate: 1) No positive signals in sector analysis, 2) Technical indicators don't support any trades, 3) LLM was too conservative")
                # Keep empty list - no fake recommendations
            else:
                recommendation_provider = "gemini"
                log.info("✅ Successfully generated %s stock recommendations from Gemini", len(stock_recommendations))
                # Log first recommendation as sample
                if stock_recommendations:
                    first_rec = stock_recommendations[0]
                    log.info("Sample recommendation: %s (%s) - Signal: %s", 
                            first_rec.get("stock_name", "N/A"),
                            first_rec.get("sector", "N/A"),
                            first_rec.get("trade_signal", "N/A"))
        except Exception as exc:  # pragma: no cover - external service issues
            log.exception("❌ Gemini stock recommender failed with exception: %s", exc)
            log.warning("No recommendations generated due to exception")
            stock_recommendations = []  # Empty instead of placeholder
    else:
        log.warning("GEMINI_API_KEY not configured; skipping stock recommendations (no fake data will be published)")
        stock_recommendations = []  # Empty instead of placeholder

    _write_json(recommendations_path, stock_recommendations)
    log.info("Wrote %d stock recommendations to %s", len(stock_recommendations), recommendations_path)

    # Publish stock recommendations to Kafka only if we have real data
    if stock_recommendations and recommendation_provider != "placeholder":
        _publish_stock_recommendations_to_kafka(
            stock_recommendations,
            provider=recommendation_provider,
            generated_at=run_started_at,
            logger=log,
        )
    else:
        log.info("Skipping stock recommendations Kafka publish - no real recommendations to publish")

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    summary_payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "article_count": article_count,
        "stream_count": len(sentiment_by_stream),
        "providers": {
            "sentiment": sentiment_source,
            "sector_agent": sector_agent_source,
            "stock_recommendation": recommendation_provider,
        },
        "artefacts": {
            "sentiment_articles": str(sentiment_path),
            "sector_analysis": str(sector_analysis_path),
            "stock_recommendations": str(recommendations_path),
        },
        "technical_snapshot_count": len(technical_snapshot),
    }

    _write_json(summary_path, summary_payload)

    log.info(
        "News sentiment pipeline completed (articles=%s, provider=%s)",
        article_count,
        sentiment_source,
    )

    return summary_payload


__all__ = [
    "execute_news_sentiment_pipeline",
]
