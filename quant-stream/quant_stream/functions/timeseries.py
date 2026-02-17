"""Time-series operations (DELTA, DELAY)."""

import pathway as pw
from pathway.stdlib.ordered import diff as pw_diff
from quant_stream.functions.helpers import _get_default_columns
import uuid


def DELTA(
    table: pw.Table,
    column: pw.ColumnReference,
    periods: int = 1,
    by_instrument: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate the delta (difference) of a column over time using Pathway's efficient operations.

    This uses Pathway's sort() and ix() operations instead of collecting all data in memory.
    Much more efficient than the previous groupby + UDF approach.

    Args:
        table: Input table with market data
        column: Column to calculate the delta of
        periods: Number of periods to calculate the delta over (default: 1)
        by_instrument: Instrument column for grouping (optional)

    Returns:
        Table with delta column added (named 'delta')
    """
    cols = _get_default_columns(by_instrument=by_instrument)
    timestamp_col = cols["timestamp"]
    by_instrument = cols["by_instrument"]

    # Use Pathway's built-in diff method from stdlib.ordered
    if periods == 1:
        diff_table = pw_diff(table, timestamp_col, column, instance=by_instrument)
        diff_col_name = f"diff_{column._name}"
        # Join diff results back to preserve all original columns
        result = table.select(
            *pw.this, delta=diff_table.ix(table.id, optional=True)[diff_col_name]
        )
    else:
        # For periods > 1, use DELAY to get the lagged value, then subtract
        lagged_table = DELAY(table, column, p=periods, by_instrument=by_instrument, timestamp=timestamp_col)
        
        # Get column name for explicit reference after join
        col_name = column._name
        
        # Join to get both current and lagged values
        joined = table.join(lagged_table, pw.left.id == pw.right.id)

        delta_expr = pw.apply_with_type(
            lambda current, delayed: current - delayed
            if current is not None and delayed is not None
            else None,
            float | None,
            pw.left[col_name],
            pw.right.delayed,
        )

        result = joined.select(
            *pw.left,
            delta=delta_expr,
        )

    return result


def DELAY(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 1,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Delay/shift data by p periods (lag operation).

    This is equivalent to pandas: df.groupby('instrument').transform(lambda x: x.shift(p))

    Args:
        table: Input table with market data
        column: Column to delay
        p: Number of periods to delay (default: 1, must be >= 0)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with delayed column added
    """
    assert p >= 0, "DELAY period cannot be negative (would cause data leakage)"

    cols = _get_default_columns(by_instrument=by_instrument, timestamp=timestamp)

    if p == 0:
        return table.select(*pw.this, delayed=column)

    sorted_table = table.sort(key=cols["timestamp"], instance=cols["by_instrument"])
    
    # Generate unique suffix to avoid column name conflicts when DELAY is called multiple times
    unique_suffix = uuid.uuid4().hex[:8]

    current_table = table.select(*pw.this, **{f"_prev_ptr_0_{unique_suffix}": sorted_table.prev})
    col_name = column._name

    # Follow prev pointers p times
    for i in range(1, p + 1):
        prev_ptr_col = f"_prev_ptr_{i}_{unique_suffix}"
        prev_prev_col = f"_prev_ptr_{i - 1}_{unique_suffix}"

        if i == p:
            # Final step: get the value at position p
            prev_row = table.ix(current_table[prev_prev_col], optional=True)
            current_table = current_table.select(*pw.this, delayed=prev_row[col_name])
        else:
            # Intermediate steps: just get next prev pointer
            prev_sorted_row = sorted_table.ix(
                current_table[prev_prev_col], optional=True
            )
            current_table = current_table.select(
                *pw.this, **{prev_ptr_col: prev_sorted_row.prev}
            )

    # Clean up temporary columns
    temp_cols = [f"_prev_ptr_{i}_{unique_suffix}" for i in range(0, p)]
    result = current_table.select(
        *pw.this.without(
            *[pw.this[col] for col in temp_cols if col in current_table.column_names()]
        )
    )

    return result
