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

# Low Risk Pipeline Log Messages
user_id = "user_12345"

# Log Event 1
publish_event(
    publisher_name="cli_low_risk_log_1",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": "2025-01-10T12:00:00Z",
        "level": "info",
        "message": "Starting industry selection pipeline...",
        "stage": "start",
    },
    headers={"source": "low_risk_pipeline"},
)

# Log Event 2
publish_event(
    publisher_name="cli_low_risk_log_2",
    topic_key="low_risk_logs",
    model=LowRiskLogEvent,
    payload={
        "user_id": user_id,
        "timestamp": "2025-01-10T12:01:00Z",
        "level": "info",
        "message": "✓ PMI value: 55.2",
        "stage": "pmi",
        "pmi_value": 55.2,
        "function": "get_pmi",
    },
    headers={"source": "low_risk_pipeline"},
)

# Low Risk Pipeline Notification Messages
# Notification Event 1: status="fetching" with content.industries (matching pipeline line 395-402)
publish_event(
    publisher_name="cli_low_risk_notification_1",
    topic_key="low_risk_logs",
    model=LowRiskNotificationEvent,
    payload={
        "user_id": user_id,
        "type": "industry",
        "status": "fetching",
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
        },
    },
    headers={"source": "low_risk_pipeline"},
)

# Notification Event 2: status="fetched" with content.industries and content.metrics (matching pipeline line 407-415)
publish_event(
    publisher_name="cli_low_risk_notification_2",
    topic_key="low_risk_logs",
    model=LowRiskNotificationEvent,
    payload={
        "user_id": user_id,
        "type": "industry",
        "status": "fetched",
        "content": {
            "industries": [
                "Automobile and Auto Components",
                "Financial Services",
                "Information Technology",
                "Healthcare",
                "Metals & Mining"
            ],
            "metrics": {
                "Automobile and Auto Components": {
                    "pct_above_ema50": 0.5555555555555556,
                    "pct_above_ema200": 0.6944444444444444,
                    "median_rsi": 45.883069988226744,
                    "pct_rsi_overbought": 0.1111111111111111,
                    "pct_rsi_oversold": 0.16666666666666666,
                    "industry_ret_6m": 0.12075537296317441,
                    "benchmark_ret_6m": 0.10
                },
                "Financial Services": {
                    "pct_above_ema50": 0.5789473684210527,
                    "pct_above_ema200": 0.7263157894736842,
                    "median_rsi": 48.273744433648936,
                    "pct_rsi_overbought": 0.08421052631578947,
                    "pct_rsi_oversold": 0.10526315789473684,
                    "industry_ret_6m": 0.11118703474490158,
                    "benchmark_ret_6m": 0.10
                },
                "Information Technology": {
                    "pct_above_ema50": 0.6071428571428571,
                    "pct_above_ema200": 0.5,
                    "median_rsi": 54.731702899203945,
                    "pct_rsi_overbought": 0.14285714285714285,
                    "pct_rsi_oversold": 0.03571428571428571,
                    "industry_ret_6m": 0.01020202491342549,
                    "benchmark_ret_6m": 0.10
                },
                "Healthcare": {
                    "pct_above_ema50": 0.4423076923076923,
                    "pct_above_ema200": 0.5,
                    "median_rsi": 50.25526766803576,
                    "pct_rsi_overbought": 0.057692307692307696,
                    "pct_rsi_oversold": 0.09615384615384616,
                    "industry_ret_6m": 0.04575339758323438,
                    "benchmark_ret_6m": 0.10
                },
                "Metals & Mining": {
                    "pct_above_ema50": 0.5294117647058824,
                    "pct_above_ema200": 0.8235294117647058,
                    "median_rsi": 44.23987028831953,
                    "pct_rsi_overbought": 0.0,
                    "pct_rsi_oversold": 0.11764705882352941,
                    "industry_ret_6m": 0.14648330974468488,
                    "benchmark_ret_6m": 0.10
                }
            }
        },
    },
    headers={"source": "low_risk_pipeline"},
)

print("\nAll low risk events published successfully.")
print("Waiting for messages to be flushed to Kafka...")
time.sleep(2.0)  # Final wait to ensure all messages are sent

# Stop all publishers gracefully
BUS.stop_all()
print("Publishers stopped.")
PY

