"""
Pipeline Utilities
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def get_pipeline_status(
    server_dir: str,
    pipeline_state: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get pipeline status information."""

    status_file = Path(server_dir) / "pipeline_status.json"
    news_status_file = Path(server_dir) / "news_pipeline_status.json"
    file_state: Optional[str] = None
    updated_at: Optional[str] = None
    news_state: Optional[str] = None
    news_updated_at: Optional[str] = None
    news_metadata: Optional[Dict[str, Any]] = None
    news_error: Optional[str] = None

    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            file_state = data.get("state")
            updated_at = data.get("updated_at")
        except Exception:  # pragma: no cover - defensive
            file_state = None

    if news_status_file.exists():
        try:
            news_data = json.loads(news_status_file.read_text(encoding="utf-8"))
            news_state = news_data.get("state")
            news_updated_at = news_data.get("updated_at")
            news_metadata = news_data.get("metadata")
            news_error = news_data.get("error")
        except Exception:  # pragma: no cover - defensive
            news_state = None

    state = pipeline_state or file_state or "unknown"
    pipeline_running = state in {"running", "starting"}

    nse_dir = os.path.join(server_dir, "pipelines/nse")
    signals_file = os.path.join(nse_dir, "trading_signals.jsonl")
    backtest_file = os.path.join(nse_dir, "backtest_results.jsonl")
    metrics_file = os.path.join(nse_dir, "backtest_metrics.jsonl")

    return {
        "state": state,
        "task_id": job_id,
        "updated_at": updated_at,
        "running": pipeline_running,
        "output_files": {
            "signals": os.path.exists(signals_file),
            "backtest_results": os.path.exists(backtest_file),
            "backtest_metrics": os.path.exists(metrics_file),
        },
        "news_pipeline": {
            "state": news_state or "unknown",
            "updated_at": news_updated_at,
            "metadata": news_metadata,
            "error": news_error,
        },
    }

