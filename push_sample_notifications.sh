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
from typing import Optional, Callable

# Set Kafka bootstrap servers to localhost:9092 for host machine execution
# This script is meant to run from the host, so override kafka:9092 if set in env
# Allow explicit override via KAFKA_BOOTSTRAP_SERVERS_HOST env var
if "KAFKA_BOOTSTRAP_SERVERS_HOST" in os.environ:
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = os.environ["KAFKA_BOOTSTRAP_SERVERS_HOST"]
elif "KAFKA_BOOTSTRAP_SERVERS" not in os.environ or os.environ.get("KAFKA_BOOTSTRAP_SERVERS") == "kafka:9092":
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "localhost:9092"

try:
    from pydantic import BaseModel, ConfigDict
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


class LowRiskLogEvent(BaseModel):
    """Log message from low_risk pipeline with flexible extra fields"""
    user_id: Optional[str] = None
    timestamp: str
    level: str
    message: str
    model_config = ConfigDict(extra='allow')


class LowRiskNotificationEvent(BaseModel):
    """Notification message from low_risk pipeline"""
    type: str
    fetching: int  # 1 for fetching, 0 for fetched
    content: dict  # Flexible content structure
    user_id: Optional[str] = None


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
    "low_risk_logs": os.getenv("LOW_RISK_AGENT_LOGS_TOPIC", "low_risk_agent_logs"),
}

# Create Kafka settings (environment variable already set above)
SETTINGS = KafkaSettings()
BUS = KafkaEventBus(SETTINGS)

# Ensure BUS is ready (publishers will auto-start when registered)
# Give a moment for any existing publishers to initialize
time.sleep(0.5)


def ensure_publisher(name: str, topic: str, model: Optional[type[BaseModel]], headers: Optional[dict] = None, partition_key_factory: Optional[Callable[[dict], Optional[str]]] = None) -> KafkaPublisher:
    try:
        publisher = BUS.register_publisher(
            name,
            topic=topic,
            value_model=model,
            default_headers=headers or {},
            partition_key_factory=partition_key_factory,
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
    if "low_risk" in topic_key:
        source_header = "low_risk_pipeline"
    elif "news" in topic_key:
        source_header = "news_pipeline"
    else:
        source_header = "nse_filings"
    source_header = (headers or {}).get("source", source_header)
    
    # Create publisher with model validation
    default_headers = {"source": source_header}
    # For low_risk pipeline, don't use value_model (set to None) to match actual pipeline behavior
    # The actual pipeline registers publisher without a model: register_publisher(name, topic=topic, ...)
    # This prevents double-wrapping of the payload
    if "low_risk" in topic_key:
        publisher_model = None  # No model validation for low_risk - publish dicts directly
        partition_key_factory = None
    else:
        publisher_model = model
        partition_key_factory = None
    publisher = ensure_publisher(publisher_name, topic, publisher_model, default_headers, partition_key_factory=partition_key_factory)

    # Ensure publisher is started and ready
    if not publisher._started.is_set():
        publisher.start()
        time.sleep(0.2)  # Give publisher a moment to initialize

    # For low_risk pipeline, publish as dict (not Pydantic model) to match actual pipeline behavior
    # The actual pipeline publishes dicts directly, not models
    if "low_risk" in topic_key:
        # Extract user_id from payload to use as partition key
        publish_key = payload.get("user_id")
        # Publish the payload dict directly (not as Pydantic model)
        # This matches how the actual pipeline publishes: pub.publish(log_data, block=False)
        publish_payload = payload
    else:
        # For other topics, use Pydantic model
        publish_payload = model(**payload)
        publish_key = partition_key
    
    try:
        publisher.publish(
            publish_payload,
            key=publish_key,
            headers=headers,
            block=True,
            timeout=5.0,
        )
    except Exception as e:
        print(f"✗ Failed to publish {publisher_name} event: {e}")
        raise
    
    print(f"✓ Published {publisher_name} event to topic '{topic}':")
    # For low_risk, payload is already a dict; for others, it's a Pydantic model
    if "low_risk" in topic_key:
        print(json.dumps(publish_payload, indent=2))
    else:
        print(json.dumps(publish_payload.model_dump(mode="json"), indent=2))
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

# Low Risk Pipeline Log Messages
user_id = "user_12345"

publish_event(
    publisher_name="cli_low_risk_log_start",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "Starting industry selection pipeline...",
        "stage": "start",
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_log_pmi",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "✓ PMI value: 55.2",
        "stage": "pmi",
        "pmi_value": 55.2,
        "function": "get_pmi",
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_log_cpi",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "✓ CPI data: 12 values",
        "stage": "cpi",
        "cpi_count": 12,
        "function": "get_cpi_list",
        "cpi_min": 4.5,
        "cpi_max": 6.2,
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_log_regime",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "✓ Economic regime: expansion",
        "stage": "regime",
        "economic_regime": "expansion",
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_log_cpi_latest",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "✓ Latest CPI value: 5.8",
        "stage": "cpi_latest",
        "cpi_value": 5.8,
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_log_pmi_latest",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "✓ Latest PMI value: 55.2",
        "stage": "pmi_latest",
        "pmi_value": 55.2,
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_log_industry_selector",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "Invoking industry selection agent...",
        "function": "industry_selector",
        "economic_regime": "expansion",
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_log_complete",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": now_ts,
        "level": "info",
        "message": "Industry selection complete: 5 industries",
        "stage": "complete",
        "industry_count": 5,
        "total_allocation": 100.0,
        "industries": [
            {
                "name": "Information Technology",
                "percentage": 30.0,
                "reasoning": "Strong growth prospects and digital transformation trends"
            },
            {
                "name": "Financial Services",
                "percentage": 25.0,
                "reasoning": "Benefiting from economic expansion and credit growth"
            },
            {
                "name": "Healthcare",
                "percentage": 20.0,
                "reasoning": "Defensive sector with stable demand"
            },
            {
                "name": "Consumer Goods",
                "percentage": 15.0,
                "reasoning": "Resilient consumption patterns"
            },
            {
                "name": "Energy",
                "percentage": 10.0,
                "reasoning": "Moderate allocation for diversification"
            }
        ],
    },
    headers={"source": "low_risk_pipeline"},
)

# Low Risk Pipeline Notification Messages
publish_event(
    publisher_name="cli_low_risk_notification_fetching",
    topic_key="low_risk_logs",
    model=LowRiskNotificationEvent,
    payload={
        "user_id": user_id,
        "type": "industry",
        "fetching": 1,
        "content": {
            "list": [
                "Automobile and Auto Components",
                "Financial Services",
                "Construction",
                "Capital Goods",
                "Consumer Durables",
                "Realty",
                "Information Technology",
                "Construction Materials",
                "Metals & Mining",
                "Fast Moving Consumer Goods",
                "Healthcare",
                "Power"
            ]
        },
    },
    headers={"source": "low_risk_pipeline"},
)

publish_event(
    publisher_name="cli_low_risk_notification_fetched",
    topic_key="low_risk_logs",
    model=LowRiskNotificationEvent,
    payload={
        "user_id": user_id,
        "type": "industry",
        "fetching": 0,
        "content": {
            "industries": [
                "Automobile and Auto Components",
                "Financial Services",
                "Construction",
                "Capital Goods",
                "Consumer Durables",
                "Realty",
                "Information Technology",
                "Construction Materials",
                "Metals & Mining",
                "Fast Moving Consumer Goods",
                "Healthcare",
                "Power"
            ],
            "metrics": {
                "Automobile and Auto Components": {
                    "pct_above_ema50": 0.5555555555555556,
                    "pct_above_ema200": 0.6944444444444444,
                    "median_rsi": 45.883069988226744,
                    "ema50": 1910.0760629216923,
                    "ema200": 2015.9613574239638,
                    "pct_rsi_overbought": 0.1111111111111111,
                    "pct_rsi_oversold": 0.16666666666666666,
                    "industry_ret_3m": 0.0470887604538,
                    "industry_ret_6m": 0.12075537296317441,
                    "industry_ret_12m": 0.12998012638210785,
                    "avg_volatility": 0.24298820716711708,
                    "RS": 2.384068108751268
                },
                "Financial Services": {
                    "pct_above_ema50": 0.5789473684210527,
                    "pct_above_ema200": 0.7263157894736842,
                    "median_rsi": 48.273744433648936,
                    "ema50": 700.6679770897704,
                    "ema200": 645.4228383888874,
                    "pct_rsi_overbought": 0.08421052631578947,
                    "pct_rsi_oversold": 0.10526315789473684,
                    "industry_ret_3m": 0.10320943623828378,
                    "industry_ret_6m": 0.11118703474490158,
                    "industry_ret_12m": 0.1767998918948755,
                    "avg_volatility": 0.2430877060522828,
                    "RS": 2.1951608209000946
                },
                "Information Technology": {
                    "pct_above_ema50": 0.6071428571428571,
                    "pct_above_ema200": 0.5,
                    "median_rsi": 54.731702899203945,
                    "ema50": 1477.5526814464642,
                    "ema200": 1506.7199410115923,
                    "pct_rsi_overbought": 0.14285714285714285,
                    "pct_rsi_oversold": 0.03571428571428571,
                    "industry_ret_3m": 0.05301345908239701,
                    "industry_ret_6m": 0.01020202491342549,
                    "industry_ret_12m": -0.07159099719940731,
                    "avg_volatility": 0.2750059913017907,
                    "RS": 0.20141813688241408
                },
                "Healthcare": {
                    "pct_above_ema50": 0.4423076923076923,
                    "pct_above_ema200": 0.5,
                    "median_rsi": 50.25526766803576,
                    "ema50": 1408.6987404098309,
                    "ema200": 1431.505226476538,
                    "pct_rsi_overbought": 0.057692307692307696,
                    "pct_rsi_oversold": 0.09615384615384616,
                    "industry_ret_3m": -0.001547370952235332,
                    "industry_ret_6m": 0.04575339758323438,
                    "industry_ret_12m": 0.030899480916748698,
                    "avg_volatility": 0.266712661111778,
                    "RS": 0.9033073507915151
                },
                "Metals & Mining": {
                    "pct_above_ema50": 0.5294117647058824,
                    "pct_above_ema200": 0.8235294117647058,
                    "median_rsi": 44.23987028831953,
                    "ema50": 520.3848828056689,
                    "ema200": 479.2723225557761,
                    "pct_rsi_overbought": 0.0,
                    "pct_rsi_oversold": 0.11764705882352941,
                    "industry_ret_3m": 0.12837137912278573,
                    "industry_ret_6m": 0.14648330974468488,
                    "industry_ret_12m": 0.1398124199828056,
                    "avg_volatility": 0.3045046193576674,
                    "RS": 2.8920136525364977
                }
            }
        },
    },
    headers={"source": "low_risk_pipeline"},
)

print("\nAll sample notifications published successfully.")
print("Waiting for messages to be flushed to Kafka...")
time.sleep(2.0)  # Final wait to ensure all messages are sent

# Stop all publishers gracefully
BUS.stop_all()
print("Publishers stopped.")
PY
