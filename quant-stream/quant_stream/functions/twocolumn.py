"""Two-column rolling operations."""

import pathway as pw
from quant_stream.functions.helpers import (
    _get_default_columns,
    _collect_rolling_window_two_cols,
    _apply_rolling_aggregation,
)


def TS_CORR(
    table: pw.Table,
    col1: pw.ColumnReference,
    col2: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate time-series rolling correlation between two columns.

    For each row, computes the correlation between two columns within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas rolling correlation.

    Args:
        table: Input table with market data
        col1: First column
        col2: Second column
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_corr column added
    """
    cols = _get_default_columns(by_instrument=by_instrument, timestamp=timestamp)

    (
        current_table,
        prev_value1_cols,
        prev_value2_cols,
        temp_ptr_cols,
        col1_name,
        col2_name,
    ) = _collect_rolling_window_two_cols(
        table, col1, col2, p, cols["by_instrument"], cols["timestamp"]
    )

    def calculate_corr(curr1, curr2, *prev_values):
        n_prev = len(prev_values) // 2
        prev_vals1 = prev_values[:n_prev]
        prev_vals2 = prev_values[n_prev:]

        vals1 = [curr1] + list(prev_vals1)
        vals2 = [curr2] + list(prev_vals2)

        valid_pairs = [
            (v1, v2)
            for v1, v2 in zip(vals1, vals2)
            if v1 is not None and v2 is not None
        ]
        if len(valid_pairs) < 2:
            return None

        x = [pair[0] for pair in valid_pairs]
        y = [pair[1] for pair in valid_pairs]

        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = (sum((xi - mean_x) ** 2 for xi in x)) ** 0.5
        std_y = (sum((yi - mean_y) ** 2 for yi in y)) ** 0.5

        if std_x == 0 or std_y == 0:
            return None

        return cov / (std_x * std_y)

    value_refs = (
        [pw.this[col1_name], pw.this[col2_name]]
        + [pw.this[col] for col in prev_value1_cols]
        + [pw.this[col] for col in prev_value2_cols]
    )
    temp_cols = temp_ptr_cols + prev_value1_cols + prev_value2_cols

    result = current_table.select(
        *pw.this.without(*[pw.this[col] for col in temp_cols]),
        ts_corr=pw.apply_with_type(calculate_corr, float | None, *value_refs),
    )

    return result


def TS_COVARIANCE(
    table: pw.Table,
    col1: pw.ColumnReference,
    col2: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate time-series rolling covariance between two columns.

    For each row, computes the covariance between two columns within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas rolling covariance.

    Args:
        table: Input table with market data
        col1: First column
        col2: Second column
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ts_cov column added
    """
    cols = _get_default_columns(by_instrument=by_instrument, timestamp=timestamp)

    (
        current_table,
        prev_value1_cols,
        prev_value2_cols,
        temp_ptr_cols,
        col1_name,
        col2_name,
    ) = _collect_rolling_window_two_cols(
        table, col1, col2, p, cols["by_instrument"], cols["timestamp"]
    )

    def calculate_cov(curr1, curr2, *prev_values):
        n_prev = len(prev_values) // 2
        prev_vals1 = prev_values[:n_prev]
        prev_vals2 = prev_values[n_prev:]

        vals1 = [curr1] + list(prev_vals1)
        vals2 = [curr2] + list(prev_vals2)

        valid_pairs = [
            (v1, v2)
            for v1, v2 in zip(vals1, vals2)
            if v1 is not None and v2 is not None
        ]
        if len(valid_pairs) < 2:
            return None

        x = [pair[0] for pair in valid_pairs]
        y = [pair[1] for pair in valid_pairs]

        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)

        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (len(x) - 1)

        return cov

    value_refs = (
        [pw.this[col1_name], pw.this[col2_name]]
        + [pw.this[col] for col in prev_value1_cols]
        + [pw.this[col] for col in prev_value2_cols]
    )
    temp_cols = temp_ptr_cols + prev_value1_cols + prev_value2_cols

    result = current_table.select(
        *pw.this.without(*[pw.this[col] for col in temp_cols]),
        ts_cov=pw.apply_with_type(calculate_cov, float | None, *value_refs),
    )

    return result


def HIGHDAY(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate the number of days since the highest value occurred in rolling window.

    Returns the distance (in periods) from the current position to where the maximum
    value occurred within the last 'p' periods. Returns len(window) - argmax(window).

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(
        lambda window: len(window) - window.argmax(), raw=True))

    Args:
        table: Input table with market data
        column: Column to find high day of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with highday column added
    """
    assert isinstance(p, int), (
        f"HIGHDAY only accepts integer parameter p, received {type(p).__name__}"
    )

    def calculate_highday(*values):
        """Return number of periods since the highest value (len(window) - argmax)"""
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        # Values come as [newest, ..., oldest], need to reverse for argmax
        valid_values_chrono = list(reversed(valid_values))
        max_val = max(valid_values_chrono)
        max_idx = valid_values_chrono.index(max_val)
        return len(valid_values_chrono) - max_idx

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_highday,
        "highday",
        result_type=int | None,
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def LOWDAY(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate the number of days since the lowest value occurred in rolling window.

    Returns the distance (in periods) from the current position to where the minimum
    value occurred within the last 'p' periods. Returns len(window) - argmin(window).

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(
        lambda window: len(window) - window.argmin(), raw=True))

    Args:
        table: Input table with market data
        column: Column to find low day of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with lowday column added
    """
    assert isinstance(p, int), (
        f"LOWDAY only accepts integer parameter p, received {type(p).__name__}"
    )

    def calculate_lowday(*values):
        """Return number of periods since the lowest value (len(window) - argmin)"""
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        # Values come as [newest, ..., oldest], need to reverse for argmin
        valid_values_chrono = list(reversed(valid_values))
        min_val = min(valid_values_chrono)
        min_idx = valid_values_chrono.index(min_val)
        return len(valid_values_chrono) - min_idx

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_lowday,
        "lowday",
        result_type=int | None,
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def SUMAC(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 10,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate rolling cumulative sum (same as TS_SUM).

    For each row, computes the sum of values within the last 'p' periods
    (including the current period) for each instrument.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).sum())

    Args:
        table: Input table with market data
        column: Column to calculate cumulative sum of
        p: Rolling window size (default: 10)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with sumac column added
    """
    assert isinstance(p, int), (
        f"SUMAC only accepts integer parameter p, received {type(p).__name__}"
    )

    def calculate_sum(*values):
        valid_values = [v for v in values if v is not None]
        return sum(valid_values) if valid_values else None

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_sum,
        "sumac",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def REGBETA(
    table: pw.Table,
    col1: pw.ColumnReference,
    col2: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate rolling regression coefficient (beta) between two columns.

    Computes the slope of the linear regression of col1 (y) on col2 (x) within
    the last 'p' periods for each instrument.

    Args:
        table: Input table with market data
        col1: Dependent variable column (y)
        col2: Independent variable column (x)
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with regbeta column added
    """
    cols = _get_default_columns(by_instrument=by_instrument, timestamp=timestamp)

    (
        current_table,
        prev_value1_cols,
        prev_value2_cols,
        temp_ptr_cols,
        col1_name,
        col2_name,
    ) = _collect_rolling_window_two_cols(
        table, col1, col2, p, cols["by_instrument"], cols["timestamp"]
    )

    def calculate_beta(curr1, curr2, *prev_values):
        n_prev = len(prev_values) // 2
        prev_vals1 = prev_values[:n_prev]
        prev_vals2 = prev_values[n_prev:]

        y = [curr1] + list(prev_vals1)
        x = [curr2] + list(prev_vals2)

        # Filter out None values
        valid_pairs = [
            (yi, xi) for yi, xi in zip(y, x) if yi is not None and xi is not None
        ]

        # Require exactly p points (matching pandas behavior: starts at index p-1)
        if len(valid_pairs) < p:
            return None

        y_vals = [pair[0] for pair in valid_pairs]
        x_vals = [pair[1] for pair in valid_pairs]

        n = len(x_vals)
        mean_x = sum(x_vals) / n
        mean_y = sum(y_vals) / n

        # Calculate beta using least squares: beta = cov(x,y) / var(x)
        cov_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x_vals, y_vals))
        var_x = sum((xi - mean_x) ** 2 for xi in x_vals)

        if var_x == 0:
            return None

        beta = cov_xy / var_x
        return beta

    value_refs = (
        [pw.this[col1_name], pw.this[col2_name]]
        + [pw.this[col] for col in prev_value1_cols]
        + [pw.this[col] for col in prev_value2_cols]
    )
    temp_cols = temp_ptr_cols + prev_value1_cols + prev_value2_cols

    result = current_table.select(
        *pw.this.without(*[pw.this[col] for col in temp_cols]),
        regbeta=pw.apply_with_type(calculate_beta, float | None, *value_refs),
    )

    return result


def REGRESI(
    table: pw.Table,
    col1: pw.ColumnReference,
    col2: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate rolling regression residuals between two columns.

    Computes the residual (actual - predicted) of the linear regression of col1 (y) on col2 (x)
    within the last 'p' periods for each instrument. Returns the residual for the current period.

    Args:
        table: Input table with market data
        col1: Dependent variable column (y)
        col2: Independent variable column (x)
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with regresi column added
    """
    cols = _get_default_columns(by_instrument=by_instrument, timestamp=timestamp)

    (
        current_table,
        prev_value1_cols,
        prev_value2_cols,
        temp_ptr_cols,
        col1_name,
        col2_name,
    ) = _collect_rolling_window_two_cols(
        table, col1, col2, p, cols["by_instrument"], cols["timestamp"]
    )

    def calculate_residuals(curr1, curr2, *prev_values):
        n_prev = len(prev_values) // 2
        prev_vals1 = prev_values[:n_prev]
        prev_vals2 = prev_values[n_prev:]

        y = [curr1] + list(prev_vals1)
        x = [curr2] + list(prev_vals2)

        # Filter out None values
        valid_pairs = [
            (yi, xi) for yi, xi in zip(y, x) if yi is not None and xi is not None
        ]

        # Require exactly p points (matching pandas behavior: starts at index p-1)
        if len(valid_pairs) < p:
            return None

        y_vals = [pair[0] for pair in valid_pairs]
        x_vals = [pair[1] for pair in valid_pairs]

        n = len(x_vals)
        mean_x = sum(x_vals) / n
        mean_y = sum(y_vals) / n

        # Calculate beta and intercept using least squares
        cov_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x_vals, y_vals))
        var_x = sum((xi - mean_x) ** 2 for xi in x_vals)

        if var_x == 0:
            return None

        beta = cov_xy / var_x
        intercept = mean_y - beta * mean_x

        # Calculate residual for the most recent value (first in our list)
        y_pred = beta * x_vals[-1] + intercept
        residual = y_vals[-1] - y_pred

        return residual

    value_refs = (
        [pw.this[col1_name], pw.this[col2_name]]
        + [pw.this[col] for col in prev_value1_cols]
        + [pw.this[col] for col in prev_value2_cols]
    )
    temp_cols = temp_ptr_cols + prev_value1_cols + prev_value2_cols

    result = current_table.select(
        *pw.this.without(*[pw.this[col] for col in temp_cols]),
        regresi=pw.apply_with_type(calculate_residuals, float | None, *value_refs),
    )

    return result


# Basic binary operations
def ADD(
    table: pw.Table, col1: pw.ColumnReference, col2: pw.ColumnReference
) -> pw.Table:
    """
    Element-wise addition of two columns.

    This is equivalent to: df[col1] + df[col2]
    Handles None values by returning 0.0.

    Args:
        table: Input table with market data
        col1: First column
        col2: Second column

    Returns:
        Table with add column added (always float, never Optional)
    """
    result = table.select(
        *pw.this,
        _add_raw=pw.apply_with_type(
            lambda a, b: a + b if a is not None and b is not None else 0.0,
            float,
            col1,
            col2,
        ),
    )
    # Unwrap Optional type using coalesce
    return result.select(
        *pw.this.without(pw.this._add_raw),
        add=pw.coalesce(pw.this._add_raw, 0.0)
    )


def SUBTRACT(
    table: pw.Table, col1: pw.ColumnReference, col2: pw.ColumnReference
) -> pw.Table:
    """
    Element-wise subtraction of two columns.

    This is equivalent to: df[col1] - df[col2]
    Handles None values by returning 0.0.

    Args:
        table: Input table with market data
        col1: First column
        col2: Second column

    Returns:
        Table with subtract column added (always float, never Optional)
    """
    result = table.select(
        *pw.this,
        _subtract_raw=pw.apply_with_type(
            lambda a, b: a - b if a is not None and b is not None else 0.0,
            float,
            col1,
            col2,
        ),
    )
    # Unwrap Optional type using coalesce
    return result.select(
        *pw.this.without(pw.this._subtract_raw),
        subtract=pw.coalesce(pw.this._subtract_raw, 0.0)
    )


def MULTIPLY(
    table: pw.Table, col1: pw.ColumnReference, col2: pw.ColumnReference
) -> pw.Table:
    """
    Element-wise multiplication of two columns.

    This is equivalent to: df[col1] * df[col2]
    Handles None values by returning 0.0.

    Args:
        table: Input table with market data
        col1: First column
        col2: Second column

    Returns:
        Table with multiply column added (always float, never Optional)
    """
    result = table.select(
        *pw.this,
        _multiply_raw=pw.apply_with_type(
            lambda a, b: a * b if a is not None and b is not None else 0.0,
            float,
            col1,
            col2,
        ),
    )
    # Unwrap Optional type using coalesce
    return result.select(
        *pw.this.without(pw.this._multiply_raw),
        multiply=pw.coalesce(pw.this._multiply_raw, 0.0)
    )


def DIVIDE(
    table: pw.Table, col1: pw.ColumnReference, col2: pw.ColumnReference
) -> pw.Table:
    """
    Element-wise division of two columns.

    This is equivalent to: df[col1] / df[col2]
    Handles division by zero by returning 0.0.

    Args:
        table: Input table with market data
        col1: First column (numerator)
        col2: Second column (denominator)

    Returns:
        Table with divide column added (always float, never Optional)
    """
    result = table.select(
        *pw.this,
        _divide_raw=pw.apply_with_type(
            lambda a, b: a / b if (a is not None and b is not None and b != 0) else None,
            float | None,
            col1,
            col2,
        ),
    )
    # Unwrap Optional type using coalesce - convert None to 0.0
    return result.select(
        *pw.this.without(pw.this._divide_raw),
        divide=pw.coalesce(pw.this._divide_raw, 0.0)
    )


def AND(
    table: pw.Table, col1: pw.ColumnReference, col2: pw.ColumnReference
) -> pw.Table:
    """
    Element-wise logical AND of two columns.

    This is equivalent to: df[col1] & df[col2]

    Args:
        table: Input table with market data
        col1: First column (boolean or numeric)
        col2: Second column (boolean or numeric)

    Returns:
        Table with and column added (boolean values)
    """
    return table.select(
        *pw.this,
        and_result=pw.apply_with_type(
            lambda a, b: (
                bool(a) and bool(b) if a is not None and b is not None else False
            ),
            bool,
            col1,
            col2,
        ),
    )


def OR(table: pw.Table, col1: pw.ColumnReference, col2: pw.ColumnReference) -> pw.Table:
    """
    Element-wise logical OR of two columns.

    This is equivalent to: df[col1] | df[col2]

    Args:
        table: Input table with market data
        col1: First column (boolean or numeric)
        col2: Second column (boolean or numeric)

    Returns:
        Table with or column added (boolean values)
    """
    return table.select(
        *pw.this,
        or_result=pw.apply_with_type(
            lambda a, b: (
                bool(a) or bool(b) if a is not None or b is not None else False
            ),
            bool,
            col1,
            col2,
        ),
    )
