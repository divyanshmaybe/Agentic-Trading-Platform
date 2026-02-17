"""Rolling window aggregations (TS_* operations)."""

import pathway as pw
from quant_stream.functions.helpers import _apply_rolling_aggregation, _get_default_columns


def TS_MAX(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling maximum within a window.

    For each row, computes the maximum value within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).max())

    Args:
        table: Input table with market data
        column: Column to calculate max of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_max column added
    """

    def calculate_max(*values):
        valid_values = [v for v in values if v is not None]
        return max(valid_values) if valid_values else None

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_max,
        "ts_max",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_MIN(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling minimum within a window.

    For each row, computes the minimum value within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).min())

    Args:
        table: Input table with market data
        column: Column to calculate min of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_min column added
    """

    def calculate_min(*values):
        valid_values = [v for v in values if v is not None]
        return min(valid_values) if valid_values else None

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_min,
        "ts_min",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_MEAN(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling mean within a window.

    For each row, computes the average value within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).mean())

    Args:
        table: Input table with market data
        column: Column to calculate mean of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_mean column added
    """

    def calculate_mean(*values):
        """Calculate mean - optimized for large windows."""
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        # For very large windows, we could use incremental mean, but sum/len is already O(n)
        # and Python's sum is optimized, so this is fine
        return sum(valid_values) / len(valid_values)

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_mean,
        "ts_mean",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_MEDIAN(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling median within a window.

    For each row, computes the median value within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).median())

    Args:
        table: Input table with market data
        column: Column to calculate median of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_median column added
    """

    def calculate_median(*values):
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        sorted_vals = sorted(valid_values)
        n = len(sorted_vals)
        if n % 2 == 1:
            return float(sorted_vals[n // 2])
        else:
            return float(sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_median,
        "ts_median",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_SUM(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling sum within a window.

    For each row, computes the sum of values within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).sum())

    Args:
        table: Input table with market data
        column: Column to calculate sum of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_sum column added
    """

    def calculate_sum(*values):
        valid_values = [v for v in values if v is not None]
        return sum(valid_values) if valid_values else None

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_sum,
        "ts_sum",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_STD(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 20,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling standard deviation within a window.

    For each row, computes the standard deviation within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).std())

    Args:
        table: Input table with market data
        column: Column to calculate std of
        p: Rolling window size (default: 20)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_std column added
    """

    def calculate_std(*values):
        """Calculate standard deviation - optimized for performance."""
        valid_values = [v for v in values if v is not None]
        if len(valid_values) < 2:
            return None
        # Simple two-pass algorithm - Python's sum() is optimized
        mean = sum(valid_values) / len(valid_values)
        variance = sum((v - mean) ** 2 for v in valid_values) / (len(valid_values) - 1)
        return variance**0.5

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_std,
        "ts_std",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_VAR(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    ddof: int = 1,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate time-series rolling variance within a window.

    For each row, computes the variance within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).var(ddof=ddof))

    Args:
        table: Input table with market data
        column: Column to calculate variance of
        p: Rolling window size (default: 5)
        ddof: Delta degrees of freedom (default: 1 for sample variance)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_var column added
    """

    def calculate_var(*values):
        valid_values = [v for v in values if v is not None]
        if len(valid_values) <= ddof:
            return 0.0 if len(valid_values) == 1 and ddof == 0 else None
        mean = sum(valid_values) / len(valid_values)
        variance = sum((v - mean) ** 2 for v in valid_values) / (
            len(valid_values) - ddof
        )
        return variance

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_var,
        "ts_var",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_ARGMAX(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate the number of periods since the maximum value occurred in rolling window.

    Returns the distance (in periods) from the current position to where the maximum
    value occurred within the last 'p' periods. 0 means max is at current position,
    1 means max was 1 period ago, etc.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(
        lambda window: len(window) - window.argmax() - 1, raw=True))

    Args:
        table: Input table with market data
        column: Column to find argmax of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_argmax column added (0 = current position, higher = further back)
    """

    def calculate_argmax(*values):
        """Return number of periods since max value occurred"""
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        valid_values_chrono = list(reversed(valid_values))
        max_val = max(valid_values_chrono)
        max_idx = valid_values_chrono.index(max_val)
        return len(valid_values_chrono) - max_idx - 1

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_argmax,
        "ts_argmax",
        result_type=int | None,
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_ARGMIN(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate the number of periods since the minimum value occurred in rolling window.

    Returns the distance (in periods) from the current position to where the minimum
    value occurred within the last 'p' periods. 0 means min is at current position,
    1 means min was 1 period ago, etc.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(
        lambda window: len(window) - window.argmin() - 1, raw=True))

    Args:
        table: Input table with market data
        column: Column to find argmin of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_argmin column added (0 = current position, higher = further back)
    """

    def calculate_argmin(*values):
        """Return number of periods since min value occurred"""
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        valid_values_chrono = list(reversed(valid_values))
        min_val = min(valid_values_chrono)
        min_idx = valid_values_chrono.index(min_val)
        return len(valid_values_chrono) - min_idx - 1

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_argmin,
        "ts_argmin",
        result_type=int | None,
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_RANK(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series percentile rank within a rolling window.

    For each row, computes the percentile rank of the current value within the
    last 'p' periods (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).rank(pct=True))

    Args:
        table: Input table with market data
        column: Column to rank
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_rank column added (0.0 to 1.0 percentile)
    """

    def calculate_percentile_rank(*values):
        """Calculate percentile rank of first value among all values in window"""
        valid_values = [v for v in values if v is not None]
        if len(valid_values) == 0:
            return None

        current_val = valid_values[0]
        sorted_vals = sorted(valid_values)
        rank_position = sorted_vals.index(current_val) + 1
        percentile = float(rank_position) / len(valid_values)

        return percentile

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_percentile_rank,
        "ts_rank",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def PERCENTILE(
    table: pw.Table,
    column: pw.ColumnReference,
    q: float,
    p: int = None,
    by_instrument: pw.ColumnReference = None,
    by_time: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate percentile/quantile of data.

    Two modes:
    1. If p is provided: rolling quantile over window of size p per instrument
    2. If p is None: cross-sectional quantile across instruments at each timestamp

    This is equivalent to pandas:
    - With p: df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).quantile(q))
    - Without p: df.groupby('instrument').transform(lambda x: x.quantile(q))

    Args:
        table: Input table with market data
        column: Column to calculate percentile of
        q: Quantile to compute (0.0 to 1.0)
        p: Rolling window size (optional, if None does cross-sectional)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        by_time: Timestamp column for cross-sectional grouping (only used when p is None)
        timestamp: Timestamp column for ordering in rolling mode (only used when p is not None)

    Returns:
        Table with percentile column added
    """
    assert 0 <= q <= 1, "Quantile q must be between [0, 1]"

    if p is not None:
        # Rolling quantile mode
        def calculate_quantile(*values):
            valid_values = [v for v in values if v is not None]
            if not valid_values:
                return None
            sorted_vals = sorted(valid_values)
            n = len(sorted_vals)
            index = q * (n - 1)
            lower_idx = int(index)
            upper_idx = min(lower_idx + 1, n - 1)
            weight = index - lower_idx
            return float(
                sorted_vals[lower_idx] * (1 - weight) + sorted_vals[upper_idx] * weight
            )

        return _apply_rolling_aggregation(
            table,
            column,
            p,
            calculate_quantile,
            "percentile",
            by_instrument=by_instrument,
            timestamp=timestamp,
        )
    else:
        # Cross-sectional quantile mode
        cols = _get_default_columns(by_time=by_time)
        by_time = cols["by_time"]

        grouped = table.groupby(by_time).reduce(
            by_time, values=pw.reducers.sorted_tuple(column), count=pw.reducers.count()
        )

        def compute_quantile(vals, cnt):
            if cnt == 0:
                return None
            n = cnt
            index = q * (n - 1)
            lower_idx = int(index)
            upper_idx = min(lower_idx + 1, n - 1)
            weight = index - lower_idx
            return float(vals[lower_idx] * (1 - weight) + vals[upper_idx] * weight)

        quantile_table = grouped.select(
            pw.this[by_time._name],
            percentile=pw.apply_with_type(
                compute_quantile, float | None, pw.this.values, pw.this.count
            ),
        )

        result = table.join(
            quantile_table, by_time == quantile_table[by_time._name]
        ).select(*pw.left, percentile=pw.right.percentile)

        return result


def TS_ZSCORE(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling z-score within a window.

    For each row, computes z-score = (x - mean) / std within the last 'p' periods.
    Uses a small epsilon (1e-8) to avoid division by zero when std is zero.

    This is equivalent to pandas:
    mean = df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).mean())
    std = df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).std())
    zscore = (df - mean) / std.replace(0, 1e-8)

    Args:
        table: Input table with market data
        column: Column to calculate z-score of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_zscore column added
    """
    assert isinstance(p, int) and p > 0, (
        f"TS_ZSCORE only accepts positive integer parameter p, received {type(p).__name__}"
    )

    def calculate_zscore(*values):
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None

        if len(valid_values) < 2:
            return None

        mean = sum(valid_values) / len(valid_values)
        variance = sum((v - mean) ** 2 for v in valid_values) / (len(valid_values) - 1)
        std = variance**0.5

        # Replace zero std with epsilon
        if std < 1e-10:
            std = 1e-8

        current_val = valid_values[0]
        return (current_val - mean) / std

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_zscore,
        "ts_zscore",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_MAD(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling Median Absolute Deviation (MAD).

    MAD = median(|X_i - median(X)|)

    For each row, computes MAD within the last 'p' periods.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(
        lambda window: np.median(np.abs(window - np.median(window)))))

    Args:
        table: Input table with market data
        column: Column to calculate MAD of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_mad column added
    """

    def calculate_mad(*values):
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None

        # Calculate median
        sorted_vals = sorted(valid_values)
        n = len(sorted_vals)
        if n % 2 == 1:
            median_val = sorted_vals[n // 2]
        else:
            median_val = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2

        # Calculate absolute deviations
        abs_devs = [abs(v - median_val) for v in valid_values]
        abs_devs_sorted = sorted(abs_devs)

        # Return median of absolute deviations
        if n % 2 == 1:
            return abs_devs_sorted[n // 2]
        else:
            return (abs_devs_sorted[n // 2 - 1] + abs_devs_sorted[n // 2]) / 2

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_mad,
        "ts_mad",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_QUANTILE(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    q: float = 0.5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    sorted_table: pw.Table | None = None,
) -> pw.Table:
    """
    Calculate time-series rolling quantile within a window.

    For each row, computes the q-th quantile within the last 'p' periods.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).quantile(q))

    Args:
        table: Input table with market data
        column: Column to calculate quantile of
        p: Rolling window size (default: 5)
        q: Quantile to compute, must be in [0, 1] (default: 0.5 for median)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_quantile column added
    """
    assert 0 <= q <= 1, f"Quantile q must be in [0, 1], received {q}"

    def calculate_quantile(*values):
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None

        sorted_vals = sorted(valid_values)
        n = len(sorted_vals)
        index = q * (n - 1)
        lower_idx = int(index)
        upper_idx = min(lower_idx + 1, n - 1)
        weight = index - lower_idx
        return float(
            sorted_vals[lower_idx] * (1 - weight) + sorted_vals[upper_idx] * weight
        )

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_quantile,
        "ts_quantile",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def TS_PCTCHANGE(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 1,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate time-series percentage change.

    For each row, computes: (current_value - value_p_periods_ago) / value_p_periods_ago

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.pct_change(periods=p).fillna(0))

    Args:
        table: Input table with market data
        column: Column to calculate percentage change of
        p: Number of periods to look back (default: 1)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_pctchange column added
    """
    from quant_stream.functions.timeseries import DELAY

    cols = _get_default_columns(by_instrument=by_instrument, timestamp=timestamp)

    # Get delayed value
    delayed_table = DELAY(
        table,
        column,
        p,
        by_instrument=cols["by_instrument"],
        timestamp=cols["timestamp"],
    )

    # Calculate percentage change
    # Note: We use pw.apply_with_type to ensure the result is always float (not Optional)
    # by handling None cases explicitly and returning 0.0
    result = delayed_table.select(
        *pw.this,
        _ts_pctchange_raw=pw.apply_with_type(
            lambda curr, prev: (
                ((curr - prev) / prev) if prev is not None and prev != 0 else 0.0
            ),
            float,
            column,
            pw.this.delayed,
        ),
    )
    
    # Ensure the result is non-Optional by using pw.coalesce (convert Optional to non-Optional)
    # This removes the Optional wrapper from the type system
    result = result.select(
        *pw.this.without(pw.this.delayed, pw.this._ts_pctchange_raw),
        ts_pctchange=pw.coalesce(pw.this._ts_pctchange_raw, 0.0)
    )

    return result
