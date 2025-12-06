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
import os
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pathway as pw

# Suppress verbose Pathway sink logging
os.environ.setdefault("PATHWAY_LOG_LEVEL", "WARNING")
logging.getLogger("pathway").setLevel(logging.WARNING)
logging.getLogger("pathway.io").setLevel(logging.WARNING)
logging.getLogger("pathway.io.kafka").setLevel(logging.WARNING)

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
        lookback_semi_annual: Rolling window size when ``use_rolling_metrics`` is True.
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
    lookback_semi_annual: int = 4
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
            "lookback_semi_annual": self.lookback_semi_annual,
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


class WithAllocationSchema(pw.Schema):
    request_id: str
    user_id: str
    payload: str
    allocation_json: str


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
        lookback_semi_annual=int(payload.get("lookback_semi_annual", 4)),
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
def compute_allocation_json(payload_json: str) -> str:
    """Pathway UDF that returns allocation result as JSON string."""
    try:
        result = _optimise_allocation(payload_json)
        return json.dumps(result)
    except Exception as e:
        # Return a failure result as JSON
        error_result = {
            "weights": {},
            "weights_json": "{}",
            "expected_return": 0.0,
            "expected_risk": 0.0,
            "objective_value": 0.0,
            "drift": {},
            "drift_json": "{}",
            "success": False,
            "message": f"Allocation failed: {str(e)}",
            "regime": "unknown",
            "progress_ratio": 0.0,
        }
        return json.dumps(error_result)


@pw.udf
def extract_weights_json(result_json: str) -> str:
    """Extract weights_json from allocation result JSON."""
    result = json.loads(result_json)
    return result["weights_json"]


@pw.udf
def extract_weights(result_json: str) -> dict:
    """Extract weights from allocation result JSON."""
    result = json.loads(result_json)
    return result["weights"]


@pw.udf
def extract_expected_return(result_json: str) -> float:
    """Extract expected_return from allocation result JSON."""
    result = json.loads(result_json)
    return result["expected_return"]


@pw.udf
def extract_expected_risk(result_json: str) -> float:
    """Extract expected_risk from allocation result JSON."""
    result = json.loads(result_json)
    return result["expected_risk"]


@pw.udf
def extract_objective_value(result_json: str) -> float:
    """Extract objective_value from allocation result JSON."""
    result = json.loads(result_json)
    return result["objective_value"]


@pw.udf
def extract_drift_json(result_json: str) -> str:
    """Extract drift_json from allocation result JSON."""
    result = json.loads(result_json)
    return result["drift_json"]


@pw.udf
def extract_drift(result_json: str) -> dict:
    """Extract drift from allocation result JSON."""
    result = json.loads(result_json)
    return result["drift"]


@pw.udf
def extract_success(result_json: str) -> bool:
    """Extract success from allocation result JSON."""
    result = json.loads(result_json)
    return result["success"]


@pw.udf
def extract_message(result_json: str) -> str:
    """Extract message from allocation result JSON."""
    result = json.loads(result_json)
    return result["message"]


@pw.udf
def extract_regime(result_json: str) -> str:
    """Extract regime from allocation result JSON."""
    result = json.loads(result_json)
    return result["regime"]


@pw.udf
def extract_progress_ratio(result_json: str) -> float:
    """Extract progress_ratio from allocation result JSON."""
    result = json.loads(result_json)
    return result["progress_ratio"]


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

    # First compute allocation and store as JSON string
    with_allocation = requests.select(
        request_id=pw.this.request_id,
        user_id=pw.this.user_id,
        payload=pw.this.payload,
        allocation_json=compute_allocation_json(pw.this.payload),
    )

    # Then extract fields from the JSON string
    results = with_allocation.select(
        request_id=pw.this.request_id,
        user_id=pw.this.user_id,
        weights_json=extract_weights_json(pw.this.allocation_json),
        weights=extract_weights(pw.this.allocation_json),
        expected_return=extract_expected_return(pw.this.allocation_json),
        expected_risk=extract_expected_risk(pw.this.allocation_json),
        objective_value=extract_objective_value(pw.this.allocation_json),
        drift_json=extract_drift_json(pw.this.allocation_json),
        drift=extract_drift(pw.this.allocation_json),
        success=extract_success(pw.this.allocation_json),
        message=extract_message(pw.this.allocation_json),
        regime=extract_regime(pw.this.allocation_json),
        progress_ratio=extract_progress_ratio(pw.this.allocation_json),
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

    def __call__(self, key: Any, row: Mapping[str, Any], time: Any, is_addition: bool) -> None:
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
    unique_id = str(uuid.uuid4())
    subject = _AllocationSubject(unique_id, event_queue, stop_event)

    # Pass unique name to avoid Pathway connector name conflicts
    results_table = build_portfolio_allocation_pipeline(subject, name=f"portfolio_allocation_{unique_id}")

    collector = _AllocationCollector()
    pw.io.subscribe(results_table, collector)

    for request in requests:
        event = request.to_event()
        logger.debug("Queueing allocation request %s for user %s", event["request_id"], event["user_id"])
        event_queue.put(event)

    # Sentinel None value instructs the subject to terminate gracefully.
    event_queue.put(None)

    try:
        logger.debug("Starting Pathway allocation pipeline execution...")
        pw.run(monitoring_level=pw.MonitoringLevel.NONE)
        logger.debug("Pathway allocation pipeline execution completed")
    except Exception as exc:
        logger.error(f"Pathway allocation pipeline failed: {exc}", exc_info=True)
        raise
    finally:
        stop_event.set()

    rows = collector.rows
    normalised_rows: List[Dict[str, Any]] = []
    for row in rows:
        normalised = dict(row)

        weights_json = normalised.get("weights_json")
        if isinstance(weights_json, str):
            try:
                normalised["weights"] = json.loads(weights_json)
            except json.JSONDecodeError:
                normalised["weights"] = {}
        else:
            weights = normalised.get("weights")
            if isinstance(weights, dict):
                normalised["weights"] = weights
            elif hasattr(weights, "items"):
                normalised["weights"] = dict(weights)
            else:
                normalised["weights"] = {}

        drift_json = normalised.get("drift_json")
        if isinstance(drift_json, str):
            try:
                normalised["drift"] = json.loads(drift_json)
            except json.JSONDecodeError:
                normalised["drift"] = {}
        else:
            drift = normalised.get("drift")
            if isinstance(drift, dict):
                normalised["drift"] = drift
            elif hasattr(drift, "items"):
                normalised["drift"] = dict(drift)
            else:
                normalised["drift"] = {}

        metadata = normalised.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        elif isinstance(metadata, dict):
            pass
        elif hasattr(metadata, "items"):
            metadata = dict(metadata)
        elif metadata is None:
            metadata = {}
        else:
            metadata = {}
        normalised["metadata"] = metadata

        normalised_rows.append(normalised)

    rows = normalised_rows

    if write_to_path and rows:
        try:
            with open(write_to_path, "a", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, default=str))
                    handle.write("\n")
        except Exception:
            logger.exception("Failed to append allocation audit trail to %s", write_to_path)

    return rows

