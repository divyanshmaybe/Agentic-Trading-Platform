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


def ensure_publisher(name: str, topic: str, model: type[BaseModel], headers: Optional[dict] = None) -> KafkaPublisher:
    try:
        return BUS.register_publisher(
            name,
            topic=topic,
            value_model=model,
            default_headers=headers or {},
        )
    except PublisherAlreadyRegistered:
        return BUS.get_publisher(name)


def publish_event(
    publisher_name: str,
    topic_key: str,
    model: type[BaseModel],
    payload: dict,
    headers: Optional[dict] = None,
    partition_key: Optional[str] = None,
) -> None:
    topic = TOPICS[topic_key]
    publisher = ensure_publisher(publisher_name, topic, model, headers)

    try:
        event = model(**payload)
        publisher.publish(event.model_dump(), key=partition_key)
        print(f"✓ Published {publisher_name} event to topic '{topic}':")
        print(json.dumps(event.model_dump(), indent=2))
        time.sleep(0.5)  # allow pipeline to flush
    finally:
        publisher.stop()


now_ts = utc_timestamp()

publish_event(
    publisher_name="cli_nse_signal",
    topic_key="nse_signal",
    model=NSESignalEvent,
    payload={
        "symbol": "INFY",
        "filing_time": now_ts,
        "filing_url": "https://example.com/filings/infy-buyback",
        "signal": 1,
        "explanation": "Post-filing sentiment indicates upside momentum; board approved buyback.",
        "confidence": 0.82,
        "generated_at": now_ts,
    },
    partition_key="INFY",
    headers={"source": "cli-sample"},
)

publish_event(
    publisher_name="cli_news_recommendation",
    topic_key="news_recommendation",
    model=NewsStockRecommendationEvent,
    payload={
        "sector": "Information Technology",
        "stock_name": "TCS",
        "trade_signal": "OVERWEIGHT",
        "detailed_analysis": "Positive analyst coverage and strong earnings beat projected to lift near-term returns.",
        "time_window_investment": "4-6 weeks",
        "news_source": "QuantWire",
        "news_source_url": "https://www.youtube.com/",
        "provider": "news_sentiment_pipeline",
        "generated_at": now_ts,
    },
    partition_key="TCS",
    headers={"source": "cli-sample"},
)

publish_event(
    publisher_name="cli_news_sentiment",
    topic_key="news_sentiment",
    model=NewsSentimentArticleEvent,
    payload={
        "stream": "global_macros",
        "title": "Fed retains dovish tone, rate cuts likely in Q3",
        "content": "Central bank minutes signalled flexibility to support soft landing, boosting defensives.",
        "sentiment": "positive",
        "url": "https://www.youtube.com/",
        "provider": "news_sentiment_pipeline",
        "generated_at": now_ts,
    },
    partition_key="global_macros",
    headers={"source": "cli-sample"},
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
    headers={"source": "cli-sample"},
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
    },
    partition_key="HDFCBANK",
    headers={"source": "cli-sample"},
)

print("\nAll sample notifications published successfully.")
PY


