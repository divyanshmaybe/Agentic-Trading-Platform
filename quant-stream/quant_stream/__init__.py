"""Quant Stream - Quantitative finance operations library built on Pathway."""

# Factor evaluation and parsing (relocated to factors/)
from quant_stream.factors import AlphaEvaluator, parse_expression, ExpressionParser

# Data utilities
from quant_stream.data import MarketData, replay_market_data

# Workflow orchestration (relocated to workflows/)
from quant_stream.workflows import WorkflowRunner, run_from_yaml

# Utilities
from quant_stream.utils import train_test_split_by_date

# Recorder (experiment tracking)
from quant_stream.recorder import Recorder, Experiment

# Models (ML forecasting)
from quant_stream.models import (
    ForecastModel,
    LightGBMModel,
    LinearModel,
    RandomForestModel,
    XGBoostModel,
)

# Strategy (portfolio construction)
from quant_stream.strategy import Strategy, TopkDropoutStrategy, WeightStrategy

# Backtest (simulation)
from quant_stream.backtest import (
    Backtester,
    calculate_returns_metrics,
    calculate_ic_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
)

# Import all function operations for convenient access
from quant_stream.functions import (
    # Element-wise operations
    MAX_ELEMENTWISE,
    MIN_ELEMENTWISE,
    ABS,
    SIGN,
    # Time-series operations
    DELTA,
    DELAY,
    # Cross-sectional operations
    RANK,
    MEAN,
    STD,
    SKEW,
    MAX,
    MIN,
    MEDIAN,
    ZSCORE,
    SCALE,
    # Rolling window aggregations
    TS_MAX,
    TS_MIN,
    TS_MEAN,
    TS_MEDIAN,
    TS_SUM,
    TS_STD,
    TS_VAR,
    TS_ARGMAX,
    TS_ARGMIN,
    TS_RANK,
    PERCENTILE,
    TS_ZSCORE,
    TS_MAD,
    TS_QUANTILE,
    TS_PCTCHANGE,
    # Technical indicators
    SMA,
    EMA,
    EWM,
    WMA,
    COUNT,
    SUMIF,
    FILTER,
    PROD,
    DECAYLINEAR,
    MACD,
    RSI,
    BB_MIDDLE,
    BB_UPPER,
    BB_LOWER,
    # Two-column operations
    TS_CORR,
    TS_COVARIANCE,
    HIGHDAY,
    LOWDAY,
    SUMAC,
    REGBETA,
    REGRESI,
    ADD,
    SUBTRACT,
    MULTIPLY,
    DIVIDE,
    AND,
    OR,
    # Mathematical operations
    EXP,
    SQRT,
    LOG,
    INV,
    POW,
    FLOOR,
)

__version__ = "0.1.0"

__all__ = [
    # Core classes
    "AlphaEvaluator",
    "ExpressionParser",
    # Parser functions
    "parse_expression",
    # Data utilities
    "MarketData",
    "replay_market_data",
    "train_test_split_by_date",
    # Workflows
    "WorkflowRunner",
    "run_from_yaml",
    # Recorder
    "Recorder",
    "Experiment",
    # Models
    "ForecastModel",
    "LightGBMModel",
    "LinearModel",
    "RandomForestModel",
    "XGBoostModel",
    # Strategy
    "Strategy",
    "TopkDropoutStrategy",
    "WeightStrategy",
    # Backtest
    "Backtester",
    "calculate_returns_metrics",
    "calculate_ic_metrics",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    # Element-wise operations
    "MAX_ELEMENTWISE",
    "MIN_ELEMENTWISE",
    "ABS",
    "SIGN",
    # Time-series operations
    "DELTA",
    "DELAY",
    # Cross-sectional operations
    "RANK",
    "MEAN",
    "STD",
    "SKEW",
    "MAX",
    "MIN",
    "MEDIAN",
    "ZSCORE",
    "SCALE",
    # Rolling window aggregations
    "TS_MAX",
    "TS_MIN",
    "TS_MEAN",
    "TS_MEDIAN",
    "TS_SUM",
    "TS_STD",
    "TS_VAR",
    "TS_ARGMAX",
    "TS_ARGMIN",
    "TS_RANK",
    "PERCENTILE",
    "TS_ZSCORE",
    "TS_MAD",
    "TS_QUANTILE",
    "TS_PCTCHANGE",
    # Technical indicators
    "SMA",
    "EMA",
    "EWM",
    "WMA",
    "COUNT",
    "SUMIF",
    "FILTER",
    "PROD",
    "DECAYLINEAR",
    "MACD",
    "RSI",
    "BB_MIDDLE",
    "BB_UPPER",
    "BB_LOWER",
    # Two-column operations
    "TS_CORR",
    "TS_COVARIANCE",
    "HIGHDAY",
    "LOWDAY",
    "SUMAC",
    "REGBETA",
    "REGRESI",
    "ADD",
    "SUBTRACT",
    "MULTIPLY",
    "DIVIDE",
    "AND",
    "OR",
    # Mathematical operations
    "EXP",
    "SQRT",
    "LOG",
    "INV",
    "POW",
    "FLOOR",
]
