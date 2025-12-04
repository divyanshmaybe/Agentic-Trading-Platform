"""Backtesting engine and utilities for portfolio simulation.

This module provides tools for simulating portfolio performance with
realistic transaction costs, slippage, and position tracking.

UNIFIED WORKFLOW APPROACH:
- run_ml_workflow() is the ONLY entry point
- Set model_type=None for direct factor trading
- Set model_type="LightGBM"|"XGBoost"|etc. for ML-based trading
"""

from quant_stream.backtest.engine import Backtester
from quant_stream.backtest.metrics import (
    calculate_returns_metrics,
    calculate_ic_metrics,
    calculate_drawdown,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
)
from quant_stream.backtest.reporting import (
    print_metrics_summary,
    generate_metrics_report,
    print_backtest_summary,
)
from quant_stream.backtest.runner import (
    run_ml_workflow,  # Unified workflow (with/without ML)
    load_market_data,
    calculate_factors,
)

__all__ = [
    "Backtester",
    "calculate_returns_metrics",
    "calculate_ic_metrics",
    "calculate_drawdown",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "print_metrics_summary",
    "generate_metrics_report",
    "print_backtest_summary",
    "run_ml_workflow",  # UNIFIED WORKFLOW
    "load_market_data",
    "calculate_factors",
]

