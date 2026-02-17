"""Cross-sectional operations (GROUP BY TIME)."""

import pathway as pw
from quant_stream.functions.helpers import _get_default_columns, StdDevAccumulator, SkewnessAccumulator


_stddev_reducer = pw.reducers.udf_reducer(StdDevAccumulator)
_skewness_reducer = pw.reducers.udf_reducer(SkewnessAccumulator)


def RANK(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate cross-sectional rank (percentile) for each timestamp.

    Note: This approach uses groupby + reducer + UDF. For very large groups, consider:
    - Using windowby with temporal windows if you need rolling ranks
    - Pre-filtering data to reduce group sizes
    - Using count-based ranks instead of percentiles if possible

    Args:
        table: Input table with market data
        column: Column to rank
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with rank column added (0.0 to 1.0 percentile)
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    grouped = table.groupby(by_time).reduce(
        by_time, values=pw.reducers.sorted_tuple(column), count=pw.reducers.count()
    )

    joined = table.join(grouped, by_time == grouped[by_time._name]).select(
        *pw.left, _sorted_values=pw.right.values, _count=pw.right.count
    )

    def calculate_rank(v, vals, cnt):
        """Calculate rank handling None values.
        
        Note: vals from sorted_tuple is already sorted, so we don't need to sort again.
        Uses binary search for O(log n) rank lookup instead of O(n) linear search.
        """
        if v is None or cnt == 0:
            return None
        # Filter out None values from the list
        # Note: sorted_tuple preserves order, but None values may be at the end
        valid_vals = [x for x in vals if x is not None]
        if not valid_vals:
            return None
        # Use binary search for O(log n) lookup - much faster for large groups
        # This is critical for cross-sectional ranking with many instruments per timestamp
        import bisect
        n = len(valid_vals)
        # Find leftmost position of value (handles duplicates correctly)
        rank_idx = bisect.bisect_left(valid_vals, v)
        # Verify we found the value (handles edge cases)
        if rank_idx < n and valid_vals[rank_idx] == v:
            return float(rank_idx + 1) / n
        # Value not in list (shouldn't happen, but handle gracefully)
        return None

    result = joined.select(
        *pw.this.without(pw.this._sorted_values, pw.this._count),
        rank=pw.apply_with_type(
            calculate_rank, float | None, column, pw.this._sorted_values, pw.this._count
        ),
    )

    return result


def MEAN(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate the mean of a column for each timestamp.

    This is already using the optimal approach with built-in reducers.
    Reducers like avg(), sum(), count() are highly optimized in Pathway.

    Args:
        table: Input table with market data
        column: Column to calculate the mean of
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with mean column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    # Coalesce None to 0 before reducer since Pathway reducers don't support Optional(FLOAT)
    # This allows the reducer to work, and we preserve None semantics in the final result
    table_with_coalesced = table.select(
        *pw.this, _coalesced_col=pw.coalesce(column, 0.0)
    )

    grouped = table_with_coalesced.groupby(by_time).reduce(
        by_time, mean=pw.reducers.avg(pw.this._coalesced_col)
    )

    result = table.join(grouped, by_time == grouped[by_time._name]).select(
        *pw.left,
        mean=pw.right.mean,
    )

    return result


def STD(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate the standard deviation of a column for each timestamp.

    Uses a custom stateful reducer that efficiently handles incremental updates.
    The accumulator tracks count, sum, and sum of squares to compute variance.

    Args:
        table: Input table with market data
        column: Column to calculate the standard deviation of
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with standard deviation column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    # Coalesce None to 0 before reducer since Pathway reducers don't support Optional(FLOAT)
    # This allows the reducer to work, and we preserve None semantics in the final result
    table_with_coalesced = table.select(
        *pw.this, _coalesced_col=pw.coalesce(column, 0.0)
    )

    grouped = table_with_coalesced.groupby(by_time).reduce(
        by_time, std=_stddev_reducer(pw.this._coalesced_col)
    )

    result = table.join(grouped, by_time == grouped[by_time._name]).select(
        *pw.left,
        std=pw.right.std,
    )

    return result


def SKEW(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate the skewness of a column for each timestamp.

    Skewness measures the asymmetry of a distribution. Uses a custom stateful reducer
    that efficiently handles incremental updates. The accumulator tracks count, sum,
    sum of squares, and sum of cubes to compute the third standardized moment.

    Returns sample skewness with bias adjustment (matching pandas/scipy).
    Requires at least 3 values per group; returns None otherwise.

    Args:
        table: Input table with market data
        column: Column to calculate the skewness of
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with skewness column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    # Coalesce None to 0 before reducer since Pathway reducers don't support Optional(FLOAT)
    # This allows the reducer to work, and we preserve None semantics in the final result
    table_with_coalesced = table.select(
        *pw.this, _coalesced_col=pw.coalesce(column, 0.0)
    )

    grouped = table_with_coalesced.groupby(by_time).reduce(
        by_time, skew=_skewness_reducer(pw.this._coalesced_col)
    )

    result = table.join(grouped, by_time == grouped[by_time._name]).select(
        *pw.left,
        skew=pw.right.skew,
    )

    return result


def MAX(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate the maximum value of a column for each timestamp.

    Uses Pathway's built-in max reducer which is highly optimized.

    Args:
        table: Input table with market data
        column: Column to find the maximum of
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with max column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    grouped = table.groupby(by_time).reduce(
        by_time, max=pw.reducers.max(column)
    )

    result = table.join(grouped, by_time == grouped[by_time._name]).select(
        *pw.left,
        max=pw.right.max,
    )

    return result


def MIN(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate the minimum value of a column for each timestamp.

    Uses Pathway's built-in min reducer which is highly optimized.

    Args:
        table: Input table with market data
        column: Column to find the minimum of
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with min column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    grouped = table.groupby(by_time).reduce(
        by_time, min=pw.reducers.min(column)
    )

    result = table.join(grouped, by_time == grouped[by_time._name]).select(
        *pw.left,
        min=pw.right.min,
    )

    return result


def MEDIAN(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate the median value of a column for each timestamp.

    Note: This implementation collects all values per group in memory to compute
    the median. For very large groups, this may be memory-intensive. Consider
    using approximate quantile methods for massive datasets.

    Args:
        table: Input table with market data
        column: Column to find the median of
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with median column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    grouped = table.groupby(by_time).reduce(
        by_time, values=pw.reducers.sorted_tuple(column), count=pw.reducers.count()
    )

    median_table = grouped.select(
        pw.this[by_time._name],
        median=pw.apply_with_type(
            lambda vals, cnt: (
                float(vals[cnt // 2])
                if cnt % 2 == 1
                else float(vals[cnt // 2 - 1] + vals[cnt // 2]) / 2
                if cnt > 0
                else None
            ),
            float | None,
            pw.this.values,
            pw.this.count,
        ),
    )

    result = table.join(median_table, by_time == median_table[by_time._name]).select(
        *pw.left,
        median=pw.right.median,
    )

    return result


def ZSCORE(
    table: pw.Table, column: pw.ColumnReference, by_time: pw.ColumnReference = None
) -> pw.Table:
    """
    Calculate cross-sectional z-score for each timestamp.

    For each timestamp, computes z-score = (x - mean) / std across all instruments.
    This standardizes values to have mean=0 and std=1 at each time point.

    This is equivalent to pandas:
    mean = df.groupby('datetime').mean()
    std = df.groupby('datetime').std()
    zscore = (df - mean) / std

    Args:
        table: Input table with market data
        column: Column to calculate z-score of
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with zscore column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    # Coalesce None to 0 before reducer since Pathway reducers don't support Optional(FLOAT)
    # This allows the reducer to work, and we preserve None semantics in the final result
    table_with_coalesced = table.select(
        *pw.this, _coalesced_col=pw.coalesce(column, 0.0)
    )

    # Calculate mean and std for each timestamp
    stats = table_with_coalesced.groupby(by_time).reduce(
        by_time, mean=pw.reducers.avg(pw.this._coalesced_col), std=_stddev_reducer(pw.this._coalesced_col)
    )

    # Join back to original table and calculate z-score
    result = table.join(stats, by_time == stats[by_time._name]).select(
        *pw.left,
        zscore=pw.apply_with_type(
            lambda val, mean, std: (
                (val - mean) / std if (val is not None and mean is not None and std is not None and std > 1e-10) else 0.0
            ),
            float,
            column,
            pw.right.mean,
            pw.right.std,
        ),
    )

    return result


def SCALE(
    table: pw.Table,
    column: pw.ColumnReference,
    target_sum: float = 1.0,
    by_time: pw.ColumnReference = None,
) -> pw.Table:
    """
    Scale values so the sum of absolute values equals target_sum at each timestamp.

    For each timestamp, computes: scaled = value * target_sum / sum(abs(values))
    This normalizes the absolute values to sum to target_sum across instruments.

    This is equivalent to pandas:
    abs_sum = abs(df).groupby('datetime').sum()
    scaled = df.multiply(target_sum).div(abs_sum, axis=0)

    Args:
        table: Input table with market data
        column: Column to scale
        target_sum: Target sum for absolute values (default: 1.0)
        by_time: Timestamp column for grouping (optional)

    Returns:
        Table with scaled column added
    """
    cols = _get_default_columns(by_time=by_time)
    by_time = cols["by_time"]

    # Create table with absolute values
    abs_table = table.select(
        *pw.this,
        _abs_value=pw.apply_with_type(
            lambda x: abs(x) if x is not None else 0.0, float, column
        ),
    )

    # Calculate sum of absolute values for each timestamp
    abs_sum_table = abs_table.groupby(by_time).reduce(
        by_time, abs_sum=pw.reducers.sum(abs_table._abs_value)
    )

    # Join and scale
    result = (
        abs_table.join(abs_sum_table, by_time == abs_sum_table[by_time._name])
        .select(*pw.left, _abs_sum=pw.right.abs_sum)
        .select(
            *pw.this.without(pw.this._abs_value, pw.this._abs_sum),
            scaled=pw.apply_with_type(
                lambda val, abs_sum: (
                    (val * target_sum / abs_sum)
                    if (val is not None and abs_sum is not None and abs_sum > 0)
                    else 0.0
                ),
                float,
                column,
                pw.this._abs_sum,
            ),
        )
    )

    return result
