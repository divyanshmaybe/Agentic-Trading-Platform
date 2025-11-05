"""
Pipeline Utilities
"""

import os
import sys
from typing import Dict, Any, Optional


def get_pipeline_status(server_dir: str, pipeline_thread: Optional[Any] = None) -> Dict[str, Any]:
    """Get pipeline status information"""
    pipeline_running = (
        pipeline_thread is not None
        and hasattr(pipeline_thread, "is_alive")
        and pipeline_thread.is_alive()
    )
    
    nse_dir = os.path.join(server_dir, "pipelines/nse")
    signals_file = os.path.join(nse_dir, "trading_signals.jsonl")
    backtest_file = os.path.join(nse_dir, "backtest_results.jsonl")
    metrics_file = os.path.join(nse_dir, "backtest_metrics.jsonl")
    
    return {
        "pipeline_running": pipeline_running,
        "output_files": {
            "signals": os.path.exists(signals_file),
            "backtest_results": os.path.exists(backtest_file),
            "backtest_metrics": os.path.exists(metrics_file),
        },
    }

