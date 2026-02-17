"""Helper functions and utilities for quant operations."""

import pathway as pw
from typing import Callable, Any
import uuid


def _get_default_columns(by_instrument=None, timestamp=None, by_time=None):
    """Get default column references if not provided."""
    result = {}
    if by_instrument is None:
        result["by_instrument"] = pw.this.instrument
    else:
        result["by_instrument"] = by_instrument

    if timestamp is None:
        result["timestamp"] = pw.this.timestamp
    else:
        result["timestamp"] = timestamp

    if by_time is None:
        result["by_time"] = pw.this.timestamp
    else:
        result["by_time"] = by_time

    return result


def _collect_rolling_window(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int,
    by_instrument: pw.ColumnReference,
    timestamp: pw.ColumnReference,
    unique_suffix: str = None,
):
    """
    Helper function to collect previous values in a rolling window.

    This is the core pattern used by all TS_* functions. It returns a table with:
    - All original columns
    - Previous values in columns named _prev_val_1, _prev_val_2, ..., _prev_val_{p-1}
    - Temporary pointer columns that need to be cleaned up

    Args:
        unique_suffix: Optional unique suffix to append to temporary column names to avoid conflicts

    Returns:
        tuple: (augmented_table, prev_value_cols, temp_ptr_cols, col_name)
    """
    sorted_table = table.sort(key=timestamp, instance=by_instrument)
    col_name = column._name
    
    # Generate unique suffix if not provided to avoid column name conflicts
    if unique_suffix is None:
        unique_suffix = uuid.uuid4().hex[:8]

    current_table = table.select(*pw.this, **{f"_prev_ptr_0_{unique_suffix}": sorted_table.prev})

    for i in range(1, p):
        prev_ptr_col = f"_prev_ptr_{i}_{unique_suffix}"
        prev_val_col = f"_prev_val_{i}_{unique_suffix}"
        prev_prev_col = f"_prev_ptr_{i - 1}_{unique_suffix}"

        prev_row = table.ix(current_table[prev_prev_col], optional=True)
        prev_sorted_row = sorted_table.ix(current_table[prev_prev_col], optional=True)
        current_table = current_table.select(
            *pw.this,
            **{prev_val_col: prev_row[col_name]},
            **{prev_ptr_col: prev_sorted_row.prev},
        )

    prev_value_cols = [f"_prev_val_{i}_{unique_suffix}" for i in range(1, p)]
    temp_ptr_cols = [f"_prev_ptr_{i}_{unique_suffix}" for i in range(0, p)]

    return current_table, prev_value_cols, temp_ptr_cols, col_name


def _collect_rolling_window_two_cols(
    table: pw.Table,
    col1: pw.ColumnReference,
    col2: pw.ColumnReference,
    p: int,
    by_instrument: pw.ColumnReference,
    timestamp: pw.ColumnReference,
    unique_suffix: str = None,
):
    """
    Helper function to collect previous values for two columns in a rolling window.

    Used by TS_CORR and TS_COVARIANCE.

    Args:
        unique_suffix: Optional unique suffix to append to temporary column names to avoid conflicts

    Returns:
        tuple: (augmented_table, prev_value1_cols, prev_value2_cols, temp_ptr_cols, col1_name, col2_name)
    """
    sorted_table = table.sort(key=timestamp, instance=by_instrument)
    col1_name = col1._name
    col2_name = col2._name
    
    # Generate unique suffix if not provided to avoid column name conflicts
    if unique_suffix is None:
        unique_suffix = uuid.uuid4().hex[:8]

    current_table = table.select(*pw.this, **{f"_prev_ptr_0_{unique_suffix}": sorted_table.prev})

    for i in range(1, p):
        prev_ptr_col = f"_prev_ptr_{i}_{unique_suffix}"
        prev_val1_col = f"_prev_val1_{i}_{unique_suffix}"
        prev_val2_col = f"_prev_val2_{i}_{unique_suffix}"
        prev_prev_col = f"_prev_ptr_{i - 1}_{unique_suffix}"

        prev_row = table.ix(current_table[prev_prev_col], optional=True)
        prev_sorted_row = sorted_table.ix(current_table[prev_prev_col], optional=True)
        current_table = current_table.select(
            *pw.this,
            **{prev_val1_col: prev_row[col1_name]},
            **{prev_val2_col: prev_row[col2_name]},
            **{prev_ptr_col: prev_sorted_row.prev},
        )

    prev_value1_cols = [f"_prev_val1_{i}_{unique_suffix}" for i in range(1, p)]
    prev_value2_cols = [f"_prev_val2_{i}_{unique_suffix}" for i in range(1, p)]
    temp_ptr_cols = [f"_prev_ptr_{i}_{unique_suffix}" for i in range(0, p)]

    return (
        current_table,
        prev_value1_cols,
        prev_value2_cols,
        temp_ptr_cols,
        col1_name,
        col2_name,
    )


def _apply_rolling_aggregation(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int,
    agg_func: Callable,
    result_col_name: str,
    result_type: Any = float | None,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
    unique_suffix: str = None,
) -> pw.Table:
    """
    Generic helper for applying rolling window aggregations.

    This eliminates duplication across TS_MAX, TS_MIN, TS_MEAN, TS_MEDIAN, TS_SUM, etc.

    Args:
        table: Input table
        column: Column to aggregate
        p: Rolling window size
        agg_func: Function to apply to window values (*values) -> result
        result_col_name: Name of the result column
        result_type: Type annotation for the result
        by_instrument: Grouping column (defaults to pw.this.instrument)
        timestamp: Ordering column (defaults to pw.this.timestamp)
        unique_suffix: Optional unique suffix to append to temporary column names to avoid conflicts

    Returns:
        Table with aggregation result column added
    """
    if not hasattr(column, "_name"):
        raise TypeError(
            "Rolling function '{0}' expects a column reference as the first argument, "
            "but received {1}. Did you forget to prefix the column with '$' in the expression?".format(
                result_col_name,
                type(column).__name__,
            )
        )

    cols = _get_default_columns(by_instrument=by_instrument, timestamp=timestamp)

    current_table, prev_value_cols, temp_ptr_cols, col_name = _collect_rolling_window(
        table, column, p, cols["by_instrument"], cols["timestamp"], unique_suffix=unique_suffix
    )

    value_refs = [pw.this[col_name]] + [pw.this[col] for col in prev_value_cols]

    result = current_table.select(
        *pw.this.without(*[pw.this[col] for col in temp_ptr_cols + prev_value_cols]),
        **{result_col_name: pw.apply_with_type(agg_func, result_type, *value_refs)},
    )

    # Pathway reducers do not support Optional[float] inputs. Some rolling aggregations
    # may legitimately yield None (e.g., insufficient history). We coalesce to 0.0 to
    # ensure downstream operators (like cross-sectional reducers) always see floats.
    return result.select(
        *pw.this.without(pw.this[result_col_name]),
        **{result_col_name: pw.coalesce(pw.this[result_col_name], 0.0)},
    )


def _elementwise_operation(
    table: pw.Table,
    operation: Callable,
    result_col_name: str,
    *columns: pw.ColumnReference,
) -> pw.Table:
    """Generic helper for element-wise operations."""
    return table.select(*pw.this, **{result_col_name: pw.apply(operation, *columns)})


# Custom accumulator for standard deviation calculation
class StdDevAccumulator(pw.BaseCustomAccumulator):
    """
    Stateful accumulator for computing standard deviation efficiently.

    This accumulator tracks count, sum, and sum of squares to compute variance
    incrementally without storing all values in memory. It efficiently handles
    both positive updates (via update()) and negative updates (via retract()).
    """

    def __init__(self, cnt, sum_val, sum_sq):
        self.cnt = cnt
        self.sum = sum_val
        self.sum_sq = sum_sq

    @classmethod
    def from_row(cls, row):
        """Create accumulator from a single row value"""
        [val] = row
        return cls(1, val, val**2)

    def update(self, other):
        """Merge two accumulators efficiently"""
        self.cnt += other.cnt
        self.sum += other.sum
        self.sum_sq += other.sum_sq

    def retract(self, other):
        """Handle negative updates efficiently without recomputing from scratch"""
        self.cnt -= other.cnt
        self.sum -= other.sum
        self.sum_sq -= other.sum_sq

    def compute_result(self) -> float:
        """Calculate sample standard deviation from accumulated statistics"""
        if self.cnt == 0:
            return None
        if self.cnt == 1:
            return 0.0
        mean = self.sum / self.cnt
        mean_sq = self.sum_sq / self.cnt
        variance = mean_sq - mean**2
        sample_variance = variance * self.cnt / (self.cnt - 1)
        return sample_variance**0.5 if sample_variance > 0 else 0.0


# Custom accumulator for skewness calculation
class SkewnessAccumulator(pw.BaseCustomAccumulator):
    """
    Stateful accumulator for computing skewness efficiently.

    Skewness measures the asymmetry of a distribution. This accumulator tracks
    count, sum, sum of squares, and sum of cubes to compute the third standardized
    moment incrementally without storing all values in memory.
    """

    def __init__(self, cnt, sum_val, sum_sq, sum_cube):
        self.cnt = cnt
        self.sum = sum_val
        self.sum_sq = sum_sq
        self.sum_cube = sum_cube

    @classmethod
    def from_row(cls, row):
        """Create accumulator from a single row value"""
        [val] = row
        return cls(1, val, val**2, val**3)

    def update(self, other):
        """Merge two accumulators efficiently"""
        self.cnt += other.cnt
        self.sum += other.sum
        self.sum_sq += other.sum_sq
        self.sum_cube += other.sum_cube

    def retract(self, other):
        """Handle negative updates efficiently without recomputing from scratch"""
        self.cnt -= other.cnt
        self.sum -= other.sum
        self.sum_sq -= other.sum_sq
        self.sum_cube -= other.sum_cube

    def compute_result(self) -> float:
        """Calculate sample skewness from accumulated statistics"""
        if self.cnt < 3:
            return None

        n = self.cnt
        mean = self.sum / n
        m2 = (self.sum_sq / n) - mean**2
        m3 = (self.sum_cube / n) - 3 * mean * (self.sum_sq / n) + 2 * mean**3

        if m2 <= 0:
            return None

        adjustment = (n * (n - 1)) ** 0.5 / (n - 2)
        skewness = adjustment * m3 / (m2**1.5)

        return skewness
