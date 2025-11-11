"""
Trade execution Pathway pipeline for NSE filings signals.

Transforms high-conviction signals into executable trade jobs with deterministic
allocation sizing and forwards them to Kafka / Celery for execution.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pathway as pw
from pydantic import BaseModel, Field

from kafka_service import (  # type: ignore  # noqa: E402
    KafkaPublisher,
    PublisherAlreadyRegistered,
    default_kafka_bus,
)
from utils.trade_execution import get_allocation  # type: ignore  # noqa: E402

LOGGER = logging.getLogger(__name__)


@dataclass
class TradeExecutionRequest:
    """Wrapper for request payload emitted into the Pathway subject."""

    request_id: str
    payload_json: str


class TradeExecutionInputSchema(pw.Schema):
    """Schema for the queue-backed subject feeding trade execution requests."""

    request_id: str
    payload: str


class TradeExecutionOutputSchema(pw.Schema):
    """Schema describing the structured trade jobs emitted by the pipeline."""

    request_id: str
    signal_id: str
    user_id: str
    portfolio_id: str
    portfolio_name: str
    organization_id: Optional[str]
    customer_id: Optional[str]
    symbol: str
    side: str
    quantity: int
    allocated_capital: float
    confidence: float
    reference_price: float
    take_profit_pct: float
    stop_loss_pct: float
    explanation: str
    filing_time: str
    generated_at: str
    metadata_json: str


class _TradeSubject(pw.io.python.ConnectorSubject):
    """Thread-safe queue-powered subject for trade execution requests."""

    deletions_enabled = False

    def __init__(
        self,
        name: str,
        event_queue: "queue.Queue[Optional[TradeExecutionRequest]]",
        stop_event: threading.Event,
    ) -> None:
        super().__init__(datasource_name=f"trade_execution:{name}")
        self._queue = event_queue
        self._stop_event = stop_event

    def run(self) -> None:  # pragma: no cover - infrastructure loop
        LOGGER.debug("Trade execution subject loop started")
        while True:
            if self._stop_event.is_set():
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    LOGGER.debug("Trade execution subject drained after stop signal")
                    break
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                LOGGER.debug("Trade execution subject received sentinel")
                break

            try:
                self.next(request_id=item.request_id, payload=item.payload_json)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.exception("Failed to emit trade request %s: %s", item.request_id, exc)

        LOGGER.debug("Trade execution subject loop exited")


@pw.udf
def _parse_payload(payload_json: str) -> Dict[str, Any]:
    try:
        data = json.loads(payload_json)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


@pw.udf
def _payload_field_float(payload_json: str, field: str, default: float = 0.0) -> float:
    data = _parse_payload(payload_json)
    value = data.get(field, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@pw.udf
def _payload_field_int(payload_json: str, field: str, default: int = 0) -> int:
    data = _parse_payload(payload_json)
    value = data.get(field, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


@pw.udf
def _payload_field_str(payload_json: str, field: str, default: str = "") -> str:
    data = _parse_payload(payload_json)
    value = data.get(field, default)
    if value is None:
        return default
    return str(value)


@pw.udf
def _payload_field_json(payload_json: str) -> str:
    try:
        data = json.loads(payload_json)
        metadata = data.get("metadata", {})
        return json.dumps(metadata if isinstance(metadata, dict) else {}, default=str)
    except Exception:
        return json.dumps({})


@pw.udf
def _calculate_allocation(payload_json: str) -> float:
    capital = _payload_field_float(payload_json, "capital", 0.0)
    confidence = _payload_field_float(payload_json, "confidence", 0.0)
    allocation = get_allocation(capital, confidence)
    return round(float(allocation), 4)


@pw.udf
def _resolve_side(payload_json: str) -> str:
    signal = _payload_field_int(payload_json, "signal", 0)
    if signal > 0:
        return "BUY"
    if signal < 0:
        return "SELL"
    return "HOLD"


@pw.udf
def _resolve_quantity(payload_json: str, allocation: float) -> int:
    price = _payload_field_float(payload_json, "reference_price", 0.0)
    if allocation <= 0 or price <= 0:
        return 0
    quantity = int(allocation // price)
    return quantity if quantity > 0 else 0


def build_trade_execution_pipeline(
    subject: pw.io.python.ConnectorSubject,
    *,
    autocommit_ms: int = 500,
    backlog_size: int = 2048,
    name: str = "trade_execution_pipeline",
) -> pw.Table:
    """Construct the Pathway trade execution pipeline."""

    requests_table = pw.io.python.read(
        subject,
        schema=TradeExecutionInputSchema,
        autocommit_duration_ms=autocommit_ms,
        max_backlog_size=backlog_size,
        name=name,
    )

    with_allocation = requests_table.select(
        request_id=pw.this.request_id,
        payload=pw.this.payload,
        allocation=_calculate_allocation(pw.this.payload),
        side=_resolve_side(pw.this.payload),
        signal_id=_payload_field_str(pw.this.payload, "signal_id"),
        user_id=_payload_field_str(pw.this.payload, "user_id"),
        portfolio_id=_payload_field_str(pw.this.payload, "portfolio_id"),
        portfolio_name=_payload_field_str(pw.this.payload, "portfolio_name"),
        organization_id=_payload_field_str(pw.this.payload, "organization_id"),
        customer_id=_payload_field_str(pw.this.payload, "customer_id"),
        symbol=_payload_field_str(pw.this.payload, "symbol"),
        confidence=_payload_field_float(pw.this.payload, "confidence"),
        reference_price=_payload_field_float(pw.this.payload, "reference_price"),
        take_profit_pct=_payload_field_float(pw.this.payload, "take_profit_pct"),
        stop_loss_pct=_payload_field_float(pw.this.payload, "stop_loss_pct"),
        explanation=_payload_field_str(pw.this.payload, "explanation"),
        filing_time=_payload_field_str(pw.this.payload, "filing_time"),
        generated_at=_payload_field_str(pw.this.payload, "generated_at"),
        metadata_json=_payload_field_json(pw.this.payload),
    )

    enriched = with_allocation.select(
        *pw.this,
        quantity=_resolve_quantity(pw.this.payload, pw.this.allocation),
    )

    actionable = enriched.filter(
        (pw.this.side != "HOLD")
        & (pw.this.quantity > 0)
        & (pw.this.reference_price > 0)
        & (pw.this.allocation > 0)
    )

    return actionable.select(
        request_id=pw.this.request_id,
        signal_id=pw.this.signal_id,
        user_id=pw.this.user_id,
        portfolio_id=pw.this.portfolio_id,
        portfolio_name=pw.this.portfolio_name,
        organization_id=pw.this.organization_id,
        customer_id=pw.this.customer_id,
        symbol=pw.this.symbol,
        side=pw.this.side,
        quantity=pw.this.quantity,
        allocated_capital=pw.this.allocation,
        confidence=pw.this.confidence,
        reference_price=pw.this.reference_price,
        take_profit_pct=pw.this.take_profit_pct,
        stop_loss_pct=pw.this.stop_loss_pct,
        explanation=pw.this.explanation,
        filing_time=pw.this.filing_time,
        generated_at=pw.this.generated_at,
        metadata_json=pw.this.metadata_json,
    )


class _TradeCollector:
    """Collects trade job rows from the Pathway subscription."""

    def __init__(self) -> None:
        self._rows: List[Dict[str, Any]] = []

    def __call__(self, key: Any, row: Mapping[str, Any], time: Any, is_addition: bool) -> None:
        if not is_addition:
            return
        self._rows.append(dict(row))

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return self._rows


def run_trade_execution_requests(
    requests: Sequence[Mapping[str, Any]],
    *,
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """Execute the trade pipeline for a batch of payloads synchronously."""

    logger = logger or LOGGER
    if not requests:
        return []

    event_queue: "queue.Queue[Optional[TradeExecutionRequest]]" = queue.Queue()
    stop_event = threading.Event()
    subject = _TradeSubject(str(uuid.uuid4()), event_queue, stop_event)

    results_table = build_trade_execution_pipeline(subject)
    collector = _TradeCollector()
    pw.io.subscribe(results_table, collector)

    for item in requests:
        request = TradeExecutionRequest(request_id=item["request_id"], payload_json=item["payload"])
        event_queue.put(request)
    event_queue.put(None)

    try:
        pw.run(monitoring_level=pw.MonitoringLevel.NONE)
    finally:
        stop_event.set()

    logger.debug("Trade execution pipeline produced %s job(s)", len(collector.rows))
    return collector.rows


class TradeExecutionEvent(BaseModel):
    """Pydantic schema for Kafka trade execution job events."""

    trade_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str
    signal_id: str
    user_id: str
    portfolio_id: str
    symbol: str
    side: str
    quantity: int
    allocated_capital: float
    confidence: float
    reference_price: float
    take_profit_pct: float
    stop_loss_pct: float
    explanation: str
    filing_time: str
    generated_at: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: str = "queued"
    source: str = "nse_trade_execution_pipeline"


TRADE_EXECUTION_TOPIC = os.getenv("TRADE_EXECUTION_TOPIC", "nse_pipeline_trade_logs")
TRADE_EXECUTION_PUBLISHER_NAME = "trade_execution_request_publisher"
_trade_publisher: Optional[KafkaPublisher] = None


def _get_trade_publisher() -> KafkaPublisher:
    global _trade_publisher

    if _trade_publisher is not None:
        return _trade_publisher

    bus = default_kafka_bus
    topic = os.getenv("TRADE_EXECUTION_TOPIC", TRADE_EXECUTION_TOPIC)

    try:
        _trade_publisher = bus.register_publisher(
            TRADE_EXECUTION_PUBLISHER_NAME,
            topic=topic,
            value_model=TradeExecutionEvent,
            default_headers={"stream": "nse_trade"},
        )
    except PublisherAlreadyRegistered:
        _trade_publisher = bus.get_publisher(TRADE_EXECUTION_PUBLISHER_NAME)

    return _trade_publisher


def publish_trade_execution_events(
    events: Iterable[TradeExecutionEvent],
    *,
    logger: Optional[logging.Logger] = None,
) -> int:
    publisher = _get_trade_publisher()
    count = 0
    for event in events:
        payload = event.model_dump()
        publisher.publish(payload, key=event.request_id)
        count += 1
    if count and logger:
        logger.info("Published %s trade execution event(s) to Kafka", count)
    return count


__all__ = [
    "TradeExecutionRequest",
    "TradeExecutionEvent",
    "run_trade_execution_requests",
    "publish_trade_execution_events",
    "build_trade_execution_pipeline",
]

