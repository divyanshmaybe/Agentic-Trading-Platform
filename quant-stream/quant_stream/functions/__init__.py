"""Quant Stream Engine - Financial data operations library."""

# Element-wise operations
from quant_stream.functions.elementwise import MAX_ELEMENTWISE, MIN_ELEMENTWISE, ABS, SIGN, IF, TERNARY

# Time-series operations
from quant_stream.functions.timeseries import DELTA, DELAY

# Cross-sectional operations (group by time)
from quant_stream.functions.crosssectional import RANK, MEAN, STD, SKEW, MAX, MIN, MEDIAN, ZSCORE, SCALE

# Rolling window aggregations
from quant_stream.functions.rolling import (
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
)

# Technical indicators
from quant_stream.functions.indicators import (
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
)

# Two-column operations
from quant_stream.functions.twocolumn import (
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
)

# Mathematical operations
from quant_stream.functions.math_ops import EXP, SQRT, LOG, INV, POW, FLOOR

__all__ = [
    # Element-wise
    "MAX_ELEMENTWISE",
    "MIN_ELEMENTWISE",
    "ABS",
    "SIGN",
    "IF",
    "TERNARY",
    # Time-series
    "DELTA",
    "DELAY",
    # Cross-sectional
    "RANK",
    "MEAN",
    "STD",
    "SKEW",
    "MAX",
    "MIN",
    "MEDIAN",
    "ZSCORE",
    "SCALE",
    # Rolling
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
    # Indicators
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
    # Two-column
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
    # Math
    "EXP",
    "SQRT",
    "LOG",
    "INV",
    "POW",
    "FLOOR",
]
