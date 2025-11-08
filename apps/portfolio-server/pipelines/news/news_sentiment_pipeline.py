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
from typing import Any, Dict, List, Optional

import pandas as pd
import pathway as pw
from dotenv import load_dotenv

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
# Defaults and fallbacks
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_ARTICLES: List[Dict[str, Any]] = [
    {
        "stream": "Information Technology",
        "title": "TCS inks multi-year cloud deal with global insurer",
        "content": "Tata Consultancy Services announced a five-year contract to modernise core insurance systems using hybrid cloud platforms.",
        "sentiment": "positive",
        "url": "https://news.example.com/tcs-cloud-contract",
    },
    {
        "stream": "Financial Services",
        "title": "RBI hints at calibrated rate pause amid moderating inflation",
        "content": "Policy minutes suggest a data-dependent approach with focus on liquidity absorption and targeted sectoral support.",
        "sentiment": "neutral",
        "url": "https://news.example.com/rbi-policy-minutes",
    },
    {
        "stream": "Oil Gas & Consumable Fuels",
        "title": "Oil marketing companies brace for Brent volatility",
        "content": "Upstream supply constraints in the Middle East keep margins in focus even as domestic demand remains resilient.",
        "sentiment": "negative",
        "url": "https://news.example.com/omc-margins-outlook",
    },
]

DEFAULT_SECTOR_ANALYSIS: str = (
    "Sector sentiment snapshot (placeholder) including IT strength, cautious banking outlook, "
    "and energy headwinds. Configure NEWS_ORG_API_KEY and GEMINI_API_KEY for live analysis."
)

DEFAULT_STOCK_RECOMMENDATIONS: List[Dict[str, Any]] = [
    {
        "sector": "Information Technology",
        "stock_name": "TCS",
        "trade_signal": "buy",
        "detailed_analysis": "Strong deal momentum and resilient margin profile support near-term upside.",
        "time_window_investment": "Next 5 trading sessions",
        "news_source": "https://news.example.com/tcs-cloud-contract",
    },
    {
        "sector": "Financial Services",
        "stock_name": "HDFCBANK",
        "trade_signal": "hold",
        "detailed_analysis": "Credit growth stable; monitor liquidity trends before adding exposure.",
        "time_window_investment": "No actionable window for hold signal",
        "news_source": "https://news.example.com/rbi-policy-minutes",
    },
    {
        "sector": "Oil Gas & Consumable Fuels",
        "stock_name": "RELIANCE",
        "trade_signal": "sell",
        "detailed_analysis": "Crack spread pressure and external supply risks limit near-term upside.",
        "time_window_investment": "Monitor over the next 2 weeks",
        "news_source": "https://news.example.com/omc-margins-outlook",
    },
]

SAMPLE_STOCKS: List[tuple[str, str]] = [
    ("RELIANCE", "Oil Gas & Consumable Fuels"),
    ("TCS", "Information Technology"),
    ("HDFCBANK", "Financial Services"),
    ("INFY", "Information Technology"),
    ("ICICIBANK", "Financial Services"),
    ("HINDUNILVR", "Fast Moving Consumer Goods"),
    ("SBIN", "Financial Services"),
    ("BHARTIARTL", "Telecommunication"),
    ("KOTAKBANK", "Financial Services"),
    ("LT", "Construction"),
]


# ---------------------------------------------------------------------------
# Kafka integration for stock recommendations
# ---------------------------------------------------------------------------

NEWS_RECO_TOPIC = os.getenv("NEWS_STOCK_RECOMMENDATIONS_TOPIC", "news_pipeline_stock_recomendations")
NEWS_RECO_PUBLISHER_NAME = "news_stock_recommendations_publisher"


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


_news_reco_publisher: Optional[KafkaPublisher] = None


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
    results: Dict[str, List[Dict[str, Any]]] = {}
    for article in DEFAULT_SAMPLE_ARTICLES:
        stream = article["stream"]
        results.setdefault(stream, []).append(article)
    return results


def _compute_technical_snapshot(logger: logging.Logger) -> List[Dict[str, Any]]:
    indicators: List[Dict[str, Any]] = []
    for symbol, industry in SAMPLE_STOCKS:
        logger.debug("Fetching technical indicators for %s", symbol)
        try:
            data = compute_technical_indicators(symbol)
        except Exception as exc:  # pragma: no cover - network/IO failures
            logger.warning("Technical indicator fetch failed for %s: %s", symbol, exc)
            continue
        if not data:
            continue
        data["Industry"] = industry
        indicators.append(data)
    return indicators


def _build_placeholder_recommendations() -> List[Dict[str, Any]]:
    return DEFAULT_STOCK_RECOMMENDATIONS.copy()


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
    # Stage 1: Pathway sentiment extraction
    # ------------------------------------------------------------------
    sentiment_source = "placeholder"
    if news_api_key:
        log.info("Fetching articles via NewsAPI")
        streams = _create_stream_table(top_k)
        sentiment_table = build_news_sentiment_pipeline(
            streams, news_api_key, top_k_default=top_k
        )
        pw.io.jsonlines.write(sentiment_table, str(sentiment_path))
        try:
            pw.run(monitoring_level=pw.MonitoringLevel.NONE)
            sentiment_source = "newsapi"
        except Exception as exc:  # pragma: no cover - runtime debug
            log.exception("Pathway run failed, using fallback data: %s", exc)
            sentiment_path.unlink(missing_ok=True)
    else:
        log.warning("NEWS_ORG_API_KEY not configured; using placeholder dataset")

    if sentiment_source == "placeholder":
        articles = DEFAULT_SAMPLE_ARTICLES
        sentiment_path.write_text(
            "\n".join(json.dumps(article) for article in articles),
            encoding="utf-8",
        )

    sentiment_by_stream = _aggregate_sentiment(sentiment_path)
    if not sentiment_by_stream:
        sentiment_by_stream = _fallback_sentiment()

    article_count = sum(len(v) for v in sentiment_by_stream.values())
    log.info("Aggregated %s analysed articles across %s streams", article_count, len(sentiment_by_stream))

    # ------------------------------------------------------------------
    # Stage 2: Gemini trading agent (optional)
    # ------------------------------------------------------------------
    sector_agent_source = "placeholder"
    sector_analysis_payload: Dict[str, Any]
    try:
        payload_json = json.dumps(sentiment_by_stream)
    except TypeError:
        payload_json = json.dumps({k: list(v) for k, v in sentiment_by_stream.items()})

    if gemini_api_key:
        log.info("Invoking Gemini trading agent for sector analysis")
        try:
            sector_analysis = trading_agent_llm(payload_json, gemini_api_key)
            if not isinstance(sector_analysis, str):
                sector_analysis = json.dumps(sector_analysis, indent=2)
            sector_agent_source = "gemini"
        except Exception as exc:  # pragma: no cover - external service issues
            log.exception("Gemini trading agent failed: %s", exc)
            sector_analysis = DEFAULT_SECTOR_ANALYSIS
    else:
        log.warning("GEMINI_API_KEY not configured; using placeholder sector analysis")
        sector_analysis = DEFAULT_SECTOR_ANALYSIS

    sector_analysis_payload = {
        "generated_at": run_started_at,
        "provider": sector_agent_source,
        "stream_count": len(sentiment_by_stream),
        "analysis": sector_analysis,
    }
    _write_json(sector_analysis_path, sector_analysis_payload)

    # ------------------------------------------------------------------
    # Stage 3: Stock recommendations (optional Gemini call)
    # ------------------------------------------------------------------
    recommendation_provider = "placeholder"
    technical_snapshot: List[Dict[str, Any]] = []

    if gemini_api_key:
        technical_snapshot = _compute_technical_snapshot(log)
        if not technical_snapshot:
            log.warning("Technical indicators unavailable; recommendations may be limited")

        try:
            tech_json = json.dumps(technical_snapshot)
            stock_recs = stock_recommender(
                sector_analysis_payload["analysis"],
                tech_json,
                gemini_api_key=gemini_api_key,
            )
            if isinstance(stock_recs, str):
                stock_recommendations = json.loads(stock_recs)
            else:
                stock_recommendations = stock_recs
            if not isinstance(stock_recommendations, list):
                raise ValueError("Unexpected recommendation payload")
            recommendation_provider = "gemini"
        except Exception as exc:  # pragma: no cover - external service issues
            log.exception("Gemini stock recommender failed: %s", exc)
            stock_recommendations = _build_placeholder_recommendations()
    else:
        stock_recommendations = _build_placeholder_recommendations()

    _write_json(recommendations_path, stock_recommendations)
    _publish_stock_recommendations_to_kafka(
        stock_recommendations,
        provider=recommendation_provider,
        generated_at=run_started_at,
        logger=log,
    )

    # ------------------------------------------------------------------
    # Stage 4: Summary metadata
    # ------------------------------------------------------------------
    summary_payload = {
        "run_started_at": run_started_at,
        "updated_at": datetime.utcnow().isoformat() + "Z",
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
    "DEFAULT_SAMPLE_ARTICLES",
    "DEFAULT_STOCK_RECOMMENDATIONS",
    "execute_news_sentiment_pipeline",
]
