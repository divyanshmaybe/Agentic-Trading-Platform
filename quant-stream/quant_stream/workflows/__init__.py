"""End-to-end workflow orchestration.

This module provides high-level workflow runners for complete quantitative research pipelines:
- YAML-based configuration workflows
- ML model training + backtesting
- Experiment tracking with MLflow
"""

from quant_stream.workflows.yaml_runner import WorkflowRunner, run_from_yaml

__all__ = [
    "WorkflowRunner",
    "run_from_yaml",
]

