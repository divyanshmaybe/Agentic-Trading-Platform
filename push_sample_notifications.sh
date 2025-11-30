#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

python <<'PY'
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover - defensive
    sys.stderr.write("pydantic is required to run this script.\n")
    raise

try:
    from shared.py.kafka_service import (
        KafkaEventBus,
        KafkaPublisher,
        KafkaSettings,
        PublisherAlreadyRegistered,
    )
except ImportError as exc:
    sys.stderr.write(
        "Failed to import shared Kafka service. Ensure PYTHONPATH includes the repo root.\n"
    )
    raise


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class NSESignalEvent(BaseModel):
    symbol: str
    filing_time: str
    filing_url: Optional[str] = None
    signal: int
    explanation: str
    confidence: float
    generated_at: str
    source: str = "nse_filings_pipeline"


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


class PortfolioRiskAlertEvent(BaseModel):
    ticker: str
    name: str
    alert: str
    severity: str
    urls: str
    fall_percent: float
    current_price: float
    current_change: float
    generated_at: str
    source: str = "risk_agent_pipeline"


TOPICS = {
    "nse_signal": os.getenv("NSE_FILINGS_SIGNAL_TOPIC", "nse_filings_trading_signal"),
    "news_recommendation": os.getenv(
        "NEWS_STOCK_RECOMMENDATIONS_TOPIC", "news_pipeline_stock_recomendations"
    ),
    "news_sentiment": os.getenv(
        "NEWS_SENTIMENT_ARTICLES_TOPIC", "news_pipeline_sentiment_articles"
    ),
    "news_sector": os.getenv("NEWS_SECTOR_ANALYSIS_TOPIC", "news_pipeline_sector_analysis"),
    "risk_alert": os.getenv("PORTFOLIO_RISK_ALERTS_TOPIC", os.getenv("RISK_ALERTS_TOPIC", "portfolio_risk_alerts")),
}

SETTINGS = KafkaSettings()
BUS = KafkaEventBus(SETTINGS)

# Ensure BUS is ready (publishers will auto-start when registered)
# Give a moment for any existing publishers to initialize
time.sleep(0.5)


def ensure_publisher(name: str, topic: str, model: type[BaseModel], headers: Optional[dict] = None) -> KafkaPublisher:
    try:
        publisher = BUS.register_publisher(
            name,
            topic=topic,
            value_model=model,
            default_headers=headers or {},
            auto_start=True,
        )
        return publisher
    except PublisherAlreadyRegistered:
        publisher = BUS.get_publisher(name)
        # Ensure publisher is started (idempotent)
        publisher.start()
        return publisher


def publish_event(
    publisher_name: str,
    topic_key: str,
    model: type[BaseModel],
    payload: dict,
    headers: Optional[dict] = None,
    partition_key: Optional[str] = None,
) -> None:
    topic = TOPICS[topic_key]
    # Get source header from headers or use default based on topic
    source_header = (headers or {}).get("source", "news_pipeline" if "news" in topic_key else "nse_filings")
    
    # Create publisher with model validation
    default_headers = {"source": source_header}
    publisher = ensure_publisher(publisher_name, topic, model, default_headers)

    # Ensure publisher is started and ready
    if not publisher._started.is_set():
        publisher.start()
        time.sleep(0.2)  # Give publisher a moment to initialize

    # Create event instance and publish directly
    event = model(**payload)
    
    # Publish using the proper API
    try:
        publisher.publish(
            event,
            key=partition_key,
            headers=headers,
            block=True,
            timeout=5.0,
        )
    except Exception as e:
        print(f"✗ Failed to publish {publisher_name} event: {e}")
        raise
    
    print(f"✓ Published {publisher_name} event to topic '{topic}':")
    print(json.dumps(event.model_dump(mode="json"), indent=2))
    # Give Pathway pipeline time to process and send the message
    time.sleep(1.0)  # allow pipeline to flush


now_ts = utc_timestamp()

# Format filing_time as "YYYY-MM-DD HH:MM:SS" for NSE signals
filing_time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

publish_event(
    publisher_name="cli_nse_signal",
    topic_key="nse_signal",
    model=NSESignalEvent,
    payload={
        "symbol": "MBEL",
        "filing_time": filing_time_str,
        "filing_url": None,  # Can be None as per schema
        "signal": 1,
        "explanation": "The earnings call transcript reveals strong revenue growth, a robust order book, significant capacity expansion plans, and confident management guidance for future growth, especially in exports. The slight price decline on the day of the transcript filing suggests the market has not fully priced in these strong underlying fundamentals.",
        "confidence": 0.85,
        "generated_at": now_ts,
        "source": "nse_filings_pipeline",
    },
    partition_key="MBEL",
    headers={"source": "nse_filings"},
)

publish_event(
    publisher_name="cli_news_recommendation",
    topic_key="news_recommendation",
    model=NewsStockRecommendationEvent,
    payload={
        "sector": "Information Technology",
        "stock_name": "INFY",
        "trade_signal": "HOLD",
        "detailed_analysis": "While the Information Technology sector has a positive sentiment, the specific news catalyst was for TCS, not directly for Infosys (INFY). Technically, INFY shows slight bullish short-term momentum with EMA20 (1501.05) above SMA20 (1497.50). However, its RSI14 (47.35) and STOCHK (40.33) are neutral to slightly weak, not indicating strong conviction for an immediate upward surge. Without a direct positive news catalyst for INFY itself and with less robust momentum indicators compared to TCS, a confident short-term BUY signal is not warranted. Therefore, a HOLD position is recommended for the current trading day.",
        "time_window_investment": "no time window valid for hold signals",
        "news_source": "",
        "news_source_url": None,
        "provider": "gemini",
        "generated_at": now_ts,
    },
    partition_key="INFY",
    headers={"source": "news_pipeline"},
)

publish_event(
    publisher_name="cli_news_sentiment",
    topic_key="news_sentiment",
    model=NewsSentimentArticleEvent,
    payload={
        "stream": "Financial Services",
        "title": "RBI hints at calibrated rate pause amid moderating inflation",
        "content": "Policy minutes suggest a data-dependent approach with focus on liquidity absorption and targeted sectoral support.",
        "sentiment": "neutral",
        "url": "https://news.example.com/rbi-policy-minutes",
        "provider": "placeholder",
        "generated_at": now_ts,
    },
    partition_key="Financial Services",
    headers={"source": "news_pipeline"},
)

publish_event(
    publisher_name="cli_news_sector",
    topic_key="news_sector",
    model=NewsSectorAnalysisEvent,
    payload={
        "stream_count": 3,
        "analysis": "Healthcare rallied on policy support while IT maintained momentum; maintain barbell allocation.",
        "provider": "news_sentiment_pipeline",
        "generated_at": now_ts,
    },
    partition_key="sector_analysis",
    headers={"source": "news_pipeline"},
)

publish_event(
    publisher_name="cli_risk_alert",
    topic_key="risk_alert",
    model=PortfolioRiskAlertEvent,
    payload={
        "ticker": "HDFCBANK",
        "name": "HDFC Bank",
        "alert": "Drawdown beyond volatility band detected; review exposure.",
        "severity": "worse",
        "urls": json.dumps(["https://www.youtube.com/", "https://codeforces.com/"]),
        "fall_percent": 5.4,
        "current_price": 1498.30,
        "current_change": -3.2,
        "generated_at": now_ts,
        "source": "risk_agent_pipeline",
    },
    partition_key="HDFCBANK",
    headers={"source": "risk_agent_pipeline"},
)

print("\nAll sample notifications published successfully.")
print("Waiting for messages to be flushed to Kafka...")
time.sleep(2.0)  # Final wait to ensure all messages are sent

# Stop all publishers gracefully
BUS.stop_all()
print("Publishers stopped.")
PY