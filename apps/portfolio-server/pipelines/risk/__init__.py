"""
Risk monitoring pipeline package.

Exports helpers for running the Pathway-based risk agent pipeline from the
portfolio server service layer.

TWO MODES:
1. Batch mode (legacy): run_risk_monitor_requests() - for testing and one-off sweeps
2. Streaming mode (production): StreamingRiskMonitor - for real-time <1 sec alerts
"""

from .risk_monitor_pipeline import (  # noqa: F401
    # Data models
    RiskMonitorRequest,
    RiskAlertEvent,
    # Batch mode (legacy)
    prepare_risk_alerts,
    run_risk_monitor_requests,
    publish_risk_alerts_to_kafka,
    # Streaming mode (production)
    StreamingRiskMonitor,
    StreamingRiskSubject,
)

__all__ = [
    # Data models
    "RiskMonitorRequest",
    "RiskAlertEvent",
    # Batch mode
    "prepare_risk_alerts",
    "run_risk_monitor_requests",
    "publish_risk_alerts_to_kafka",
    # Streaming mode
    "StreamingRiskMonitor",
    "StreamingRiskSubject",
]

