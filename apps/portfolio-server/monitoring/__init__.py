"""
Monitoring and observability components for Portfolio Server

Includes:
- Celery worker Prometheus metrics (prometheus_exporter.py)
- HTTP request metrics for FastAPI (http_metrics.py)
- Business-level metrics for trading (business_metrics.py)
"""

from .prometheus_exporter import setup_prometheus_exporter
from .http_metrics import PrometheusMiddleware, metrics_endpoint
from .business_metrics import (
    record_trade_start,
    record_trade_completion,
    record_trade_error,
    record_signal_start,
    record_signal_completion,
    record_pipeline_start,
    record_pipeline_completion,
    record_pipeline_error,
    record_risk_alert,
    set_risk_alerts_pending,
    record_allocation,
    record_regime_change,
    record_rebalance,
    record_alpha_signal,
    record_market_data_fetch,
    set_queue_depth,
    monitored_trade_task,
    monitored_pipeline_task,
    monitored_signal_task,
    init_business_metrics,
    BUSINESS_METRICS_ENABLED,
)

__all__ = [
    # Core exporters
    "setup_prometheus_exporter",
    "PrometheusMiddleware", 
    "metrics_endpoint",
    # Business metric recording functions
    "record_trade_start",
    "record_trade_completion",
    "record_trade_error",
    "record_signal_start",
    "record_signal_completion",
    "record_pipeline_start",
    "record_pipeline_completion",
    "record_pipeline_error",
    "record_risk_alert",
    "set_risk_alerts_pending",
    "record_allocation",
    "record_regime_change",
    "record_rebalance",
    "record_alpha_signal",
    "record_market_data_fetch",
    "set_queue_depth",
    # Decorators
    "monitored_trade_task",
    "monitored_pipeline_task",
    "monitored_signal_task",
    # Initialization
    "init_business_metrics",
    "BUSINESS_METRICS_ENABLED",
]