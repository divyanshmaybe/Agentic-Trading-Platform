"""
Risk monitoring Pathway pipeline.

Consumes portfolio holding snapshots, evaluates drawdown breaches against
configured thresholds, and emits structured risk alerts that can be forwarded to
Kafka or downstream notification channels.
"""

from __future__ import annotations

import json
import os
import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pathway as pw
from pydantic import BaseModel, Field, validator

from kafka_service import (  # type: ignore  # noqa: E402
    KafkaPublisher,
    PublisherAlreadyRegistered,
    default_kafka_bus,
)

LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Input payloads
# --------------------------------------------------------------------------- #


@dataclass
class RiskMonitorRequest:
    """Request payload representing a single holding to be evaluated."""

    request_id: str
    user_id: str
    portfolio_id: str
    portfolio_name: str
    symbol: str
    quantity: float
    average_price: float
    current_price: float
    threshold_pct: float
    risk_tolerance: str
    contact_emails: Sequence[str] = field(default_factory=list)
    day_change_pct: Optional[float] = None
    total_change_pct: Optional[float] = None
    organization_id: Optional[str] = None
    customer_id: Optional[str] = None
    exchange: Optional[str] = None
    segment: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_event(self) -> Dict[str, Any]:
        """Serialise request to the schema consumed by the Pathway subject."""

        payload = {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "portfolio_id": self.portfolio_id,
            "portfolio_name": self.portfolio_name,
            "symbol": self.symbol,
            "quantity": float(self.quantity),
            "average_price": float(self.average_price),
            "current_price": float(self.current_price),
            "threshold_pct": float(self.threshold_pct),
            "risk_tolerance": self.risk_tolerance,
            "contact_emails": list(self.contact_emails) if self.contact_emails else [],
            "day_change_pct": float(self.day_change_pct) if self.day_change_pct is not None else None,
            "total_change_pct": float(self.total_change_pct) if self.total_change_pct is not None else None,
            "organization_id": self.organization_id,
            "customer_id": self.customer_id,
            "exchange": self.exchange,
            "segment": self.segment,
            "metadata": self.metadata,
        }
        return {
            "request_id": self.request_id,
            "payload": json.dumps(payload, default=str),
        }


class RiskMonitorInputSchema(pw.Schema):
    """Schema for queue-backed subject ingesting risk monitor requests."""

    request_id: str
    payload: str


class RiskAlertSchema(pw.Schema):
    """Schema for the Pathway risk alert output table."""

    request_id: str
    user_id: str
    portfolio_id: str
    portfolio_name: str
    symbol: str
    severity: str
    message: str
    drawdown_pct: float
    day_change_pct: float
    threshold_pct: float
    risk_tolerance: str
    quantity: float
    current_price: float
    average_price: float
    contact_emails_json: str
    metadata_json: str
    organization_id: Optional[str]
    customer_id: Optional[str]


# --------------------------------------------------------------------------- #
# Queue subject
# --------------------------------------------------------------------------- #


class _RiskSubject(pw.io.python.ConnectorSubject):
    """Thread-safe queue-backed subject feeding Pathway with risk monitor events."""

    deletions_enabled = False

    def __init__(
        self,
        name: str,
        event_queue: "queue.Queue[Optional[Dict[str, Any]]]",
        stop_event: threading.Event,
    ) -> None:
        super().__init__(datasource_name=f"risk_monitor:{name}")
        self._name = name
        self._queue = event_queue
        self._stop_event = stop_event

    def run(self) -> None:  # pragma: no cover - exercised via integration tests
        LOGGER.debug("Risk monitor subject %s loop started", self._name)
        while True:
            if self._stop_event.is_set():
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    LOGGER.debug("Risk monitor subject %s drained after stop", self._name)
                    break

            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                LOGGER.debug("Risk monitor subject %s received sentinel", self._name)
                break

            try:
                self.next(**item)
            except Exception as exc:  # pragma: no cover - defensive logging
                LOGGER.exception("Risk monitor subject %s failed to emit %s: %s", self._name, item, exc)

        LOGGER.debug("Risk monitor subject %s loop exited", self._name)


# --------------------------------------------------------------------------- #
# Risk evaluation helpers (Pathway UDFs)
# --------------------------------------------------------------------------- #


@pw.udf
def _evaluate_risk(payload_json: str) -> str:
    """Evaluate drawdown breach and return JSON encoded metrics."""

    try:
        payload = json.loads(payload_json)
    except Exception as exc:  # pragma: no cover - defensive guard
        return json.dumps({"breached": False, "message": f"Failed to decode payload: {exc}"})

    average_price = float(payload.get("average_price") or 0.0)
    current_price = float(payload.get("current_price") or 0.0)
    threshold_pct = float(payload.get("threshold_pct") or 0.0)
    total_change_pct = float(payload.get("total_change_pct") or 0.0)
    day_change_pct = payload.get("day_change_pct")
    risk_tolerance = payload.get("risk_tolerance") or "unknown"

    if average_price <= 0 or current_price <= 0:
        return json.dumps(
            {
                "breached": False,
                "message": "Invalid price data; skipping risk evaluation",
                "drawdown_pct": 0.0,
                "day_change_pct": float(day_change_pct or 0.0),
                "threshold_pct": threshold_pct,
                "risk_tolerance": risk_tolerance,
            }
        )

    drawdown_pct = ((current_price - average_price) / average_price) * 100.0
    drawdown_pct = round(drawdown_pct, 2)

    if day_change_pct is None:
        day_change_pct = float(total_change_pct)
    else:
        day_change_pct = round(float(day_change_pct), 2)

    breached = drawdown_pct <= -abs(threshold_pct)

    severity = "info"
    if breached:
        magnitude = abs(drawdown_pct)
        threshold = abs(threshold_pct)
        if magnitude >= threshold * 2.0:
            severity = "worst"
        elif magnitude >= threshold * 1.5:
            severity = "worse"
        else:
            severity = "bad"

    elif day_change_pct <= -5.0:
        breached = True
        severity = "bad"
        threshold_pct = min(threshold_pct, 5.0) if threshold_pct else 5.0

    if breached:
        message = (
            f"{payload.get('symbol')} dropped {abs(drawdown_pct):.2f}% "
            f"(threshold {abs(threshold_pct):.2f}%) - severity {severity}"
        )
    else:
        message = "No risk breach detected"

    result = {
        "breached": bool(breached),
        "severity": severity,
        "message": message,
        "drawdown_pct": float(drawdown_pct),
        "day_change_pct": float(day_change_pct),
        "threshold_pct": float(threshold_pct),
        "risk_tolerance": risk_tolerance,
    }
    return json.dumps(result)


@pw.udf
def _evaluation_flag(evaluation_json: str) -> bool:
    try:
        return bool(json.loads(evaluation_json).get("breached"))
    except Exception:
        return False


@pw.udf
def _evaluation_field_str(evaluation_json: str, field: str, default: str = "") -> str:
    try:
        data = json.loads(evaluation_json)
        value = data.get(field, default)
        return str(value) if value is not None else default
    except Exception:
        return default


@pw.udf
def _evaluation_field_float(evaluation_json: str, field: str, default: float = 0.0) -> float:
    try:
        data = json.loads(evaluation_json)
        value = data.get(field, default)
        return float(value) if value is not None else default
    except Exception:
        return default


@pw.udf
def _payload_field_str(payload_json: str, field: str, default: str = "") -> str:
    try:
        data = json.loads(payload_json)
        value = data.get(field, default)
        return str(value) if value is not None else default
    except Exception:
        return default


@pw.udf
def _payload_field_float(payload_json: str, field: str, default: float = 0.0) -> float:
    try:
        data = json.loads(payload_json)
        value = data.get(field, default)
        return float(value) if value is not None else default
    except Exception:
        return default


@pw.udf
def _payload_field_json(payload_json: str, field: str) -> str:
    try:
        data = json.loads(payload_json)
        value = data.get(field)
        if value is None:
            value = []
        return json.dumps(value, default=str)
    except Exception:
        return json.dumps([] if field == "contact_emails" else {})


# --------------------------------------------------------------------------- #
# Pipeline builder
# --------------------------------------------------------------------------- #


def build_risk_monitor_pipeline(
    subject: pw.io.python.ConnectorSubject,
    *,
    autocommit_ms: int = 1_000,
    backlog_size: int = 4_096,
    name: str = "risk_monitor_pipeline",
) -> pw.Table:
    """Wire up Pathway risk monitor pipeline returning a table of alerts."""

    requests = pw.io.python.read(
        subject,
        schema=RiskMonitorInputSchema,
        autocommit_duration_ms=autocommit_ms,
        max_backlog_size=backlog_size,
        name=name,
    )

    evaluated = requests.select(
        request_id=pw.this.request_id,
        payload=pw.this.payload,
        evaluation=_evaluate_risk(pw.this.payload),
    )

    alerts = evaluated.filter(_evaluation_flag(pw.this.evaluation)).select(
        request_id=pw.this.request_id,
        payload=pw.this.payload,
        evaluation=pw.this.evaluation,
        user_id=_payload_field_str(pw.this.payload, "user_id"),
        portfolio_id=_payload_field_str(pw.this.payload, "portfolio_id"),
        portfolio_name=_payload_field_str(pw.this.payload, "portfolio_name"),
        symbol=_payload_field_str(pw.this.payload, "symbol"),
        severity=_evaluation_field_str(pw.this.evaluation, "severity", "bad"),
        message=_evaluation_field_str(pw.this.evaluation, "message", "Risk threshold breached"),
        drawdown_pct=_evaluation_field_float(pw.this.evaluation, "drawdown_pct", 0.0),
        day_change_pct=_evaluation_field_float(pw.this.evaluation, "day_change_pct", 0.0),
        threshold_pct=_evaluation_field_float(pw.this.evaluation, "threshold_pct", 0.0),
        risk_tolerance=_evaluation_field_str(pw.this.evaluation, "risk_tolerance", "unknown"),
        quantity=_payload_field_float(pw.this.payload, "quantity", 0.0),
        current_price=_payload_field_float(pw.this.payload, "current_price", 0.0),
        average_price=_payload_field_float(pw.this.payload, "average_price", 0.0),
        contact_emails_json=_payload_field_json(pw.this.payload, "contact_emails"),
        metadata_json=_payload_field_json(pw.this.payload, "metadata"),
        organization_id=_payload_field_str(pw.this.payload, "organization_id"),
        customer_id=_payload_field_str(pw.this.payload, "customer_id"),
    )

    return alerts


# --------------------------------------------------------------------------- #
# Batch execution helper
# --------------------------------------------------------------------------- #


class _RiskCollector:
    """Subscriber collecting risk alert rows into memory."""

    def __init__(self) -> None:
        self._rows: List[Dict[str, Any]] = []

    def __call__(self, _key: Any, row: Mapping[str, Any], _time: Any, is_addition: bool) -> None:
        if not is_addition:
            return
        self._rows.append(dict(row))

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return self._rows


def run_risk_monitor_requests(
    requests: Sequence[RiskMonitorRequest],
    *,
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """
    Execute the risk monitor pipeline for a batch of requests synchronously.
    """

    logger = logger or LOGGER
    if not requests:
        return []

    event_queue: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
    stop_event = threading.Event()
    subject = _RiskSubject(str(uuid.uuid4()), event_queue, stop_event)

    results_table = build_risk_monitor_pipeline(subject)
    collector = _RiskCollector()
    pw.io.subscribe(results_table, collector)

    for request in requests:
        event_queue.put(request.to_event())
    event_queue.put(None)

    try:
        pw.run(monitoring_level=pw.MonitoringLevel.NONE)
    finally:
        stop_event.set()

    logger.debug("Risk monitor pipeline produced %s alert(s)", len(collector.rows))
    return collector.rows


# --------------------------------------------------------------------------- #
# Kafka integration
# --------------------------------------------------------------------------- #


class RiskAlertEvent(BaseModel):
    """Pydantic schema for Kafka risk alert events."""

    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    portfolio_id: str
    portfolio_name: str
    symbol: str
    severity: str
    message: str
    drawdown_pct: float
    day_change_pct: float
    threshold_pct: float
    risk_tolerance: str
    quantity: float
    current_price: float
    average_price: float
    contact_emails: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    organization_id: Optional[str] = None
    customer_id: Optional[str] = None
    generated_at: str
    source: str = "risk_monitor_pipeline"

    @validator("contact_emails", pre=True)
    def _ensure_emails(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed if item]
            except Exception:
                return [value]
        return []

    @validator("metadata", pre=True)
    def _ensure_metadata(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                return {}
        return {}


RISK_ALERTS_TOPIC = os.getenv("RISK_ALERTS_TOPIC", "risk_agent_alerts")
RISK_ALERT_PUBLISHER_NAME = "risk_monitor_publisher"
_risk_alert_publisher: Optional[KafkaPublisher] = None


def _get_risk_alert_publisher() -> KafkaPublisher:
    global _risk_alert_publisher
    if _risk_alert_publisher is not None:
        return _risk_alert_publisher

    bus = default_kafka_bus
    try:
        _risk_alert_publisher = bus.register_publisher(
            RISK_ALERT_PUBLISHER_NAME,
            topic=RISK_ALERTS_TOPIC,
            value_model=RiskAlertEvent,
            default_headers={"source": "risk_monitor"},
        )
    except PublisherAlreadyRegistered:
        _risk_alert_publisher = bus.get_publisher(RISK_ALERT_PUBLISHER_NAME)

    return _risk_alert_publisher


def prepare_risk_alerts(
    rows: Iterable[Mapping[str, Any]],
    *,
    generated_at: Optional[str] = None,
) -> List[RiskAlertEvent]:
    """Convert raw pipeline rows into RiskAlertEvent objects."""

    alerts: List[RiskAlertEvent] = []
    for row in rows:
        try:
            alerts.append(
                RiskAlertEvent(
                    user_id=str(row.get("user_id")),
                    portfolio_id=str(row.get("portfolio_id")),
                    portfolio_name=str(row.get("portfolio_name", "")),
                    symbol=str(row.get("symbol")),
                    severity=str(row.get("severity", "bad")),
                    message=str(row.get("message", "")),
                    drawdown_pct=float(row.get("drawdown_pct", 0.0)),
                    day_change_pct=float(row.get("day_change_pct", 0.0)),
                    threshold_pct=float(row.get("threshold_pct", 0.0)),
                    risk_tolerance=str(row.get("risk_tolerance", "unknown")),
                    quantity=float(row.get("quantity", 0.0)),
                    current_price=float(row.get("current_price", 0.0)),
                    average_price=float(row.get("average_price", 0.0)),
                    contact_emails=row.get("contact_emails_json"),
                    metadata=row.get("metadata_json"),
                    organization_id=row.get("organization_id"),
                    customer_id=row.get("customer_id"),
                    generated_at=generated_at or "",
                )
            )
        except Exception as exc:
            LOGGER.warning("Failed to normalise risk alert row %s: %s", row, exc)
    return alerts


def publish_risk_alerts_to_kafka(alerts: Iterable[RiskAlertEvent], logger: Optional[logging.Logger] = None) -> int:
    """Publish risk alert events to Kafka via the central bus."""

    publisher = _get_risk_alert_publisher()
    count = 0
    for alert in alerts:
        try:
            publisher.publish(alert.model_dump(mode="json"), key=alert.portfolio_id)
            count += 1
        except Exception as exc:  # pragma: no cover - defensive logging
            (logger or LOGGER).warning("Failed to publish risk alert for %s: %s", alert.symbol, exc)
    return count


__all__ = [
    "RiskMonitorRequest",
    "RiskAlertEvent",
    "run_risk_monitor_requests",
    "prepare_risk_alerts",
    "publish_risk_alerts_to_kafka",
]

