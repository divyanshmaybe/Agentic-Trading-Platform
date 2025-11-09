"""
Pathway-powered portfolio allocation pipeline.

The pipeline consumes allocation requests, executes the adaptive optimisation
engine and emits allocation recommendations. It is designed to run both in
batch mode (for synchronous API calls) and streaming mode (for asynchronous
workers).
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pathway as pw

from .portfolio_manager import (
    DEFAULT_SEGMENTS,
    PortfolioManager,
    PortfolioMonitor,
    ensure_segment_metrics,
)


LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Event schema / payload definitions
# --------------------------------------------------------------------------- #


@dataclass
class PortfolioAllocationRequest:
    """
    Request payload accepted by the allocation pipeline.

    Attributes:
        request_id: Unique identifier for this rebalance request.
        user_id: Identifier of the target user or account.
        current_regime: Market regime affecting the optimisation routine.
        user_inputs: Dictionary mirroring ``PortfolioManager`` configuration.
        initial_value: Portfolio initial value for cumulative return tracking.
        current_value: Latest portfolio value (defaults to initial value).
        value_history: Optional chronological portfolio values (quarterly granularity).
        segment_history: Optional mapping of segment → sequence of metric dicts.
        use_rolling_metrics: Whether to rely on rolling averages (default: True).
        lookback_quarters: Rolling window size when ``use_rolling_metrics`` is True.
    """

    request_id: str
    user_id: str
    current_regime: str
    user_inputs: Mapping[str, Any]
    initial_value: float
    current_value: Optional[float] = None
    value_history: Optional[Sequence[float]] = None
    segment_history: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None
    use_rolling_metrics: bool = True
    lookback_quarters: int = 4
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_event(self) -> Dict[str, Any]:
        """Serialise request into the schema consumed by Pathway."""

        payload = {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "current_regime": self.current_regime,
            "user_inputs": self.user_inputs,
            "initial_value": self.initial_value,
            "current_value": self.current_value,
            "value_history": self.value_history,
            "segment_history": self.segment_history,
            "use_rolling_metrics": self.use_rolling_metrics,
            "lookback_quarters": self.lookback_quarters,
            "metadata": self.metadata,
        }
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "payload": json.dumps(payload),
        }


class AllocationRequestSchema(pw.Schema):
    request_id: str
    user_id: str
    payload: str


class AllocationResultSchema(pw.Schema):
    request_id: str
    user_id: str
    weights_json: str
    weights: dict
    expected_return: float
    expected_risk: float
    objective_value: float
    drift_json: str
    drift: dict
    success: bool
    message: str
    regime: str
    progress_ratio: float
    metadata: dict


# --------------------------------------------------------------------------- #
# Connector subject feeding Pathway from a queue (shared with utils).
# --------------------------------------------------------------------------- #


class _AllocationSubject(pw.io.python.ConnectorSubject):
    """Thread-safe queue-backed subject feeding Pathway with allocation events."""

    deletions_enabled = False

    def __init__(self, name: str, event_queue: "queue.Queue[Optional[Dict[str, Any]]]", stop_event: threading.Event) -> None:
        super().__init__(datasource_name=f"portfolio_allocation:{name}")
        self._name = name
        self._queue = event_queue
        self._stop_event = stop_event

    def run(self) -> None:
        LOGGER.debug("Allocation subject %s loop started", self._name)
        while True:
            if self._stop_event.is_set():
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    LOGGER.debug("Allocation subject %s drained after stop", self._name)
                    break
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                LOGGER.debug("Allocation subject %s received sentinel", self._name)
                break
            try:
                self.next(**item)
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.exception("Allocation subject %s failed to emit %s: %s", self._name, item, exc)
        LOGGER.debug("Allocation subject %s loop exited", self._name)


# --------------------------------------------------------------------------- #
# UDFs powering the pipeline
# --------------------------------------------------------------------------- #


def _build_monitor_from_payload(payload: Mapping[str, Any]) -> PortfolioMonitor:
    """Construct a ``PortfolioMonitor`` instance from request payload."""

    segment_history = ensure_segment_metrics(payload.get("segment_history"), segments=DEFAULT_SEGMENTS)
    value_history = payload.get("value_history")
    current_value = payload.get("current_value")
    monitor = PortfolioMonitor(
        initial_value=float(payload["initial_value"]),
        current_value=float(current_value) if current_value is not None else None,
        value_history=[float(v) for v in value_history] if value_history else None,
        segment_history={
            segment: [
                {
                    "return_rate": metrics.return_rate,
                    "volatility": metrics.volatility,
                    "max_drawdown": metrics.max_drawdown,
                    "sharpe_ratio": metrics.sharpe_ratio,
                }
                for metrics in metrics_list
            ]
            for segment, metrics_list in segment_history.items()
        },
        segments=DEFAULT_SEGMENTS,
    )
    return monitor


def _optimise_allocation(payload_json: str) -> Dict[str, Any]:
    """Execute the optimisation engine for a single rebalance request."""

    payload = json.loads(payload_json)
    monitor = _build_monitor_from_payload(payload)
    manager = PortfolioManager(user_inputs=payload["user_inputs"], monitor=monitor, segments=DEFAULT_SEGMENTS)
    result = manager.rebalance(
        current_regime=payload.get("current_regime", "sideways"),
        use_rolling_metrics=bool(payload.get("use_rolling_metrics", True)),
        lookback_quarters=int(payload.get("lookback_quarters", 4)),
    )
    return {
        "weights": result.weights,
        "weights_json": json.dumps(result.weights),
        "expected_return": result.expected_return,
        "expected_risk": result.expected_risk,
        "objective_value": result.objective_value,
        "drift": result.drift_from_previous,
        "drift_json": json.dumps(result.drift_from_previous),
        "success": result.success,
        "message": result.message,
        "regime": result.regime,
        "progress_ratio": result.progress_ratio,
    }


@pw.udf
def compute_allocation(payload_json: str) -> Dict[str, Any]:
    """Pathway UDF wrapper around the optimisation compute step."""

    return _optimise_allocation(payload_json)


# --------------------------------------------------------------------------- #
# Pipeline builder
# --------------------------------------------------------------------------- #


def build_portfolio_allocation_pipeline(
    subject: pw.io.python.ConnectorSubject,
    *,
    autocommit_ms: int = 500,
    backlog_size: int = 1024,
    name: str = "portfolio_allocation",
) -> pw.Table:
    """
    Wire up the Pathway pipeline from a Python subject to allocation results.

    Args:
        subject: Input subject producing allocation requests.
        autocommit_ms: Autocommit interval for the Pathway reader.
        backlog_size: Maximum backlog entries retained by the reader.
        name: Friendly name attached to the reader.

    Returns:
        Pathway table containing allocation results.
    """

    requests = pw.io.python.read(
        subject,
        schema=AllocationRequestSchema,
        autocommit_duration_ms=autocommit_ms,
        max_backlog_size=backlog_size,
        name=name,
    )

    enriched = requests.select(
        request_id=pw.this.request_id,
        user_id=pw.this.user_id,
        payload=pw.this.payload,
        allocation=pw.apply(compute_allocation, pw.this.payload),
    )

    results = enriched.select(
        request_id=pw.this.request_id,
        user_id=pw.this.user_id,
        weights_json=pw.apply(lambda res: res["weights_json"], pw.this.allocation),
        weights=pw.apply(lambda res: res["weights"], pw.this.allocation),
        expected_return=pw.apply(lambda res: res["expected_return"], pw.this.allocation),
        expected_risk=pw.apply(lambda res: res["expected_risk"], pw.this.allocation),
        objective_value=pw.apply(lambda res: res["objective_value"], pw.this.allocation),
        drift_json=pw.apply(lambda res: res["drift_json"], pw.this.allocation),
        drift=pw.apply(lambda res: res["drift"], pw.this.allocation),
        success=pw.apply(lambda res: res["success"], pw.this.allocation),
        message=pw.apply(lambda res: res["message"], pw.this.allocation),
        regime=pw.apply(lambda res: res["regime"], pw.this.allocation),
        progress_ratio=pw.apply(lambda res: res["progress_ratio"], pw.this.allocation),
        metadata=pw.apply(
            lambda payload_json: json.loads(payload_json).get("metadata", {}),
            pw.this.payload,
        ),
    )

    return results


# --------------------------------------------------------------------------- #
# Batch execution helper
# --------------------------------------------------------------------------- #


class _AllocationCollector:
    """Subscriber collecting allocation rows into memory."""

    def __init__(self) -> None:
        self._rows: List[Dict[str, Any]] = []

    def __call__(self, _key: Any, row: Mapping[str, Any], _time: Any, is_addition: bool) -> None:
        if not is_addition:
            return
        self._rows.append(dict(row))

    @property
    def rows(self) -> List[Dict[str, Any]]:
        return self._rows


def run_portfolio_allocation_requests(
    requests: Sequence[PortfolioAllocationRequest],
    *,
    logger: Optional[logging.Logger] = None,
    write_to_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Execute the portfolio allocation pipeline for a batch of requests synchronously.

    This helper is convenient for API endpoints or job handlers that need a
    synchronous response. Under the hood it spins up an in-memory subject,
    ingests the provided requests, runs the Pathway graph once and collects the
    output rows.

    Args:
        requests: Sequence of allocation requests to evaluate.
        logger: Optional logger for diagnostic messages.
        write_to_path: Optional JSON Lines output path for audit trails.

    Returns:
        List of allocation result dictionaries aligned with ``AllocationResultSchema``.
    """

    logger = logger or LOGGER
    event_queue: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
    stop_event = threading.Event()
    subject = _AllocationSubject(str(uuid.uuid4()), event_queue, stop_event)

    results_table = build_portfolio_allocation_pipeline(subject)

    if write_to_path:
        pw.io.jsonlines.write(
            results_table,
            output_path=write_to_path,
            mode="append",
        )

    collector = _AllocationCollector()
    pw.io.subscribe(results_table, collector)

    for request in requests:
        event = request.to_event()
        logger.debug("Queueing allocation request %s for user %s", event["request_id"], event["user_id"])
        event_queue.put(event)

    # Sentinel None value instructs the subject to terminate gracefully.
    event_queue.put(None)

    try:
        pw.run()
    finally:
        stop_event.set()

    return collector.rows

