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

# Suppress verbose Pathway sink logging - MUST be set before Pathway imports
os.environ["PATHWAY_LOG_LEVEL"] = "ERROR"
os.environ["PATHWAY_MONITORING_LEVEL"] = "NONE"
os.environ["PATHWAY_PERSISTENT_STORAGE"] = ""

# Suppress ALL Pathway-related loggers
for logger_name in [
    "pathway",
    "pathway.io",
    "pathway.io.kafka",
    "pathway.io.jsonlines",
    "pathway.xpacks",
    "pathway.stdlib",
]:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)
    logging.getLogger(logger_name).propagate = False

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
    agent_id: Optional[str]
    agent_type: Optional[str]
    agent_status: Optional[str]


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
    # Parse JSON directly inside UDF (can't use other UDFs that return Pathway expressions)
    try:
        import json
        data = json.loads(payload_json)
        if isinstance(data, dict):
            value = data.get(field, default)
            try:
                result = float(value)
                if field == "reference_price" and result == 0.0:
                    LOGGER.warning("⚠️ reference_price is 0.0 in payload! Payload keys: %s", list(data.keys()))
                return result
            except (TypeError, ValueError):
                if field == "reference_price":
                    LOGGER.warning("⚠️ Failed to convert reference_price to float: %s (type: %s)", value, type(value))
                return default
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        if field == "reference_price":
            LOGGER.warning("⚠️ Failed to parse JSON payload for reference_price: %s", e)
        return default
    return default


@pw.udf
def _payload_field_int(payload_json: str, field: str, default: int = 0) -> int:
    # Parse JSON directly inside UDF (can't use other UDFs that return Pathway expressions)
    try:
        import json
        data = json.loads(payload_json)
        if isinstance(data, dict):
            value = data.get(field, default)
            try:
                return int(value)
            except (TypeError, ValueError):
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    return default
    except (json.JSONDecodeError, TypeError, AttributeError):
        return default
    return default


@pw.udf
def _payload_field_str(payload_json: str, field: str, default: str = "") -> str:
    # Parse JSON directly inside UDF (can't use other UDFs that return Pathway expressions)
    try:
        import json
        data = json.loads(payload_json)
        if isinstance(data, dict):
            value = data.get(field, default)
            if value is None:
                return default
            return str(value)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return default
    return default


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
    """Calculate allocation based on capital and confidence - UDF works with scalar values only."""
    # Parse JSON directly to get scalar values (not Pathway expressions)
    try:
        data = json.loads(payload_json)
        capital = float(data.get("capital", 0.0))
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError, KeyError) as e:
        LOGGER.warning("Failed to parse allocation inputs: %s", e)
        return 0.0
    
    # Use scalar conditional logic
    if confidence > 0.8:
        fraction = 0.40
    elif confidence > 0.49:
        fraction = 0.25
    else:
        fraction = 0.0
    allocation = capital * fraction
    result = round(float(allocation), 4)
    if result <= 0:
        LOGGER.warning("⚠️ Allocation is 0 or negative: capital=%.2f, confidence=%.2f, fraction=%.2f, result=%.2f", 
                      capital, confidence, fraction, result)
    else:
        LOGGER.info("✅ Allocation calculation: capital=%.2f, confidence=%.2f, fraction=%.2f, result=%.2f", 
                   capital, confidence, fraction, result)
    return result


@pw.udf
def _resolve_side(payload_json: str) -> str:
    """
    Resolve side from signal - SHORT SELLING ENABLED.
    
    Signal > 0 → BUY (open long position)
    Signal < 0 → SHORT_SELL (open short position)
    
    UDF works with scalar values only.
    """
    # Parse JSON directly to get scalar values (not Pathway expressions)
    try:
        data = json.loads(payload_json)
        signal = int(data.get("signal", 0))
    except (TypeError, ValueError, KeyError):
        return "HOLD"
    
    # Use scalar conditional logic
    if signal > 0:
        return "BUY"
    if signal < 0:
        # PRODUCTION: SELL signals now trigger SHORT_SELL (not regular SELL)
        return "SHORT_SELL"
    return "HOLD"


@pw.udf
def _resolve_quantity(payload_json: str, allocation: float) -> int:
    """Resolve quantity from allocation and price - UDF works with scalar values only."""
    # Parse JSON directly to get scalar values (not Pathway expressions)
    try:
        data = json.loads(payload_json)
        price = float(data.get("reference_price", 0.0))
    except (TypeError, ValueError, KeyError):
        LOGGER.warning("⚠️ Failed to parse reference_price from payload")
        return 0
    
    # Convert allocation to float if needed (it might be a Pathway expression)
    try:
        alloc_value = float(allocation)
    except (TypeError, ValueError):
        LOGGER.warning("⚠️ Failed to convert allocation to float: %s", allocation)
        return 0
    
    # Use scalar conditional logic
    if alloc_value <= 0:
        LOGGER.warning("⚠️ Allocation is 0 or negative: %.2f", alloc_value)
        return 0
    if price <= 0:
        LOGGER.warning("⚠️ Reference price is 0 or negative: %.2f", price)
        return 0
    
    quantity = int(alloc_value // price)
    if quantity <= 0:
        LOGGER.warning("⚠️ Calculated quantity is 0: allocation=%.2f, price=%.2f, quantity=%d", alloc_value, price, quantity)
    else:
        LOGGER.info("✅ Quantity calculation: allocation=%.2f, price=%.2f, quantity=%d", alloc_value, price, quantity)
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
        agent_id=_payload_field_str(pw.this.payload, "agent_id"),
        agent_type=_payload_field_str(pw.this.payload, "agent_type"),
        agent_status=_payload_field_str(pw.this.payload, "agent_status"),
    )

    enriched = with_allocation.select(
        *pw.this,
        quantity=_resolve_quantity(pw.this.payload, pw.this.allocation),
    )

    # Debug: Log filter conditions
    actionable = enriched.filter(
        (pw.this.side != "HOLD")
        & (pw.this.quantity > 0)
        & (pw.this.reference_price > 0)
        & (pw.this.allocation > 0)
    )
    
    # Add debug logging to see what's being filtered
    def _log_filter_debug(key, row, time, is_addition):
        if is_addition:
            row_dict = dict(row)
            side = row_dict.get("side", "unknown")
            quantity = row_dict.get("quantity", 0)
            ref_price = row_dict.get("reference_price", 0.0)
            allocation = row_dict.get("allocation", 0.0)
            LOGGER.info(
                "🔍 Filter check: side=%s, quantity=%d, ref_price=%.2f, allocation=%.2f | "
                "Passes: side!=HOLD=%s, qty>0=%s, price>0=%s, alloc>0=%s",
                side, quantity, ref_price, allocation,
                side != "HOLD", quantity > 0, ref_price > 0, allocation > 0
            )
    
    # Subscribe to enriched table to see what's being filtered
    pw.io.subscribe(enriched, _log_filter_debug)

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
        agent_id=pw.this.agent_id,
        agent_type=pw.this.agent_type,
        agent_status=pw.this.agent_status,
    )


class _TradeCollector:
    """Collects trade job rows from the Pathway subscription."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._rows: List[Dict[str, Any]] = []
        self.logger = logger or LOGGER

    def __call__(self, key: Any, row: Mapping[str, Any], time: Any, is_addition: bool) -> None:
        if not is_addition:
            return
        row_dict = dict(row)
        self._rows.append(row_dict)
        self.logger.info(
            "✅ Collected trade job: %s %s x %d | Allocation: %.2f | Price: %.2f | Agent: %s",
            row_dict.get("symbol", "unknown"),
            row_dict.get("side", "unknown"),
            row_dict.get("quantity", 0),
            row_dict.get("allocated_capital", 0.0),
            row_dict.get("reference_price", 0.0),
            row_dict.get("agent_id", "unknown"),
        )

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

    # Use unique name for each pipeline run to avoid Pathway name conflicts
    pipeline_name = f"trade_execution_pipeline_{uuid.uuid4().hex[:8]}"
    results_table = build_trade_execution_pipeline(subject, name=pipeline_name)
    collector = _TradeCollector(logger=logger)
    pw.io.subscribe(results_table, collector)

    for item in requests:
        request = TradeExecutionRequest(request_id=item["request_id"], payload_json=item["payload"])
        event_queue.put(request)
    event_queue.put(None)

    try:
        # Run pathway computation with timeout
        import signal as sig
        import time
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Pathway computation timed out")
        
        # Set 10 second timeout
        old_handler = sig.signal(sig.SIGALRM, timeout_handler)
        sig.alarm(10)
        
        try:
            pw.run(monitoring_level=pw.MonitoringLevel.NONE)
        except TimeoutError:
            logger.warning("⚠️ Pathway computation timed out after 10s, using collected results")
        finally:
            sig.alarm(0)
            sig.signal(sig.SIGALRM, old_handler)
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
    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    agent_status: Optional[str] = None


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

