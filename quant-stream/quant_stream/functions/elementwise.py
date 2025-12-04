"""Element-wise operations on table columns."""

import pathway as pw
from quant_stream.functions.helpers import _elementwise_operation


def MAX_ELEMENTWISE(
    table: pw.Table,
    col_x: pw.ColumnReference,
    col_y: pw.ColumnReference,
    col_z: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate element-wise maximum between 2 or 3 columns.

    This is equivalent to pandas: np.maximum(x, y) or np.maximum(np.maximum(x, y), z)

    Args:
        table: Input table
        col_x: First column
        col_y: Second column
        col_z: Optional third column

    Returns:
        Table with max_value column added
    """
    if col_z is None:
        return _elementwise_operation(
            table, 
            lambda x, y: max(x, y) if x is not None and y is not None else (x if y is None else y),
            "max_value", 
            col_x, 
            col_y
        )
    else:
        return _elementwise_operation(
            table, 
            lambda x, y, z: max(v for v in [x, y, z] if v is not None) if any(v is not None for v in [x, y, z]) else None,
            "max_value", 
            col_x, 
            col_y, 
            col_z
        )


def MIN_ELEMENTWISE(
    table: pw.Table,
    col_x: pw.ColumnReference,
    col_y: pw.ColumnReference,
    col_z: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate element-wise minimum between 2 or 3 columns.

    This is equivalent to pandas: np.minimum(x, y) or np.minimum(np.minimum(x, y), z)

    Args:
        table: Input table
        col_x: First column
        col_y: Second column
        col_z: Optional third column

    Returns:
        Table with min_value column added
    """
    if col_z is None:
        return _elementwise_operation(
            table, 
            lambda x, y: min(x, y) if x is not None and y is not None else (x if y is None else y),
            "min_value", 
            col_x, 
            col_y
        )
    else:
        return _elementwise_operation(
            table, 
            lambda x, y, z: min(v for v in [x, y, z] if v is not None) if any(v is not None for v in [x, y, z]) else None,
            "min_value", 
            col_x, 
            col_y, 
            col_z
        )


def ABS(table: pw.Table, column: pw.ColumnReference) -> pw.Table:
    """
    Calculate absolute value of each element in a column.

    This is equivalent to pandas: df.groupby('instrument').transform(lambda x: x.abs())

    Args:
        table: Input table
        column: Column to calculate absolute value of

    Returns:
        Table with abs_value column added
    """
    return _elementwise_operation(table, lambda x: abs(x) if x is not None else None, "abs_value", column)


def SIGN(table: pw.Table, column: pw.ColumnReference) -> pw.Table:
    """
    Calculate sign of each element in a column.

    Returns -1 for negative, 0 for zero, 1 for positive.
    This is equivalent to pandas: np.sign(df)

    Args:
        table: Input table
        column: Column to calculate sign of

    Returns:
        Table with sign_value column added
    """

    def sign_func(x):
        if x is None:
            return None
        elif x > 0:
            return 1
        elif x < 0:
            return -1
        else:
            return 0

    return _elementwise_operation(table, sign_func, "sign_value", column)


def IF(
    table: pw.Table,
    condition: pw.ColumnReference | bool | int | float,
    true_value: pw.ColumnReference | bool | int | float | None,
    false_value: pw.ColumnReference | bool | int | float | None,
) -> pw.Table:
    """Evaluate a conditional expression element-wise.

    Args:
        table: Input table.
        condition: Condition column or literal. Treated truthy via ``bool``.
        true_value: Value returned when condition is truthy (column or literal).
        false_value: Value returned when condition is falsy (column or literal).

    Returns:
        Table with ``if_result`` column added.
    """

    temp_cols: list[str] = []
    current_table = table

    def _ensure_column(
        tbl: pw.Table,
        value,
        suffix: str,
    ) -> tuple[pw.Table, pw.ColumnReference]:
        if hasattr(value, "_expression") or hasattr(value, "_name"):
            return tbl, value
        col_name = f"_if_{suffix}"
        new_tbl = tbl.select(*pw.this, **{col_name: value})
        temp_cols.append(col_name)
        return new_tbl, pw.this[col_name]

    current_table, cond_ref = _ensure_column(current_table, condition, "cond")
    current_table, true_ref = _ensure_column(current_table, true_value, "true")
    current_table, false_ref = _ensure_column(current_table, false_value, "false")

    def _if_func(cond, true_val, false_val):
        if cond is None:
            return false_val
        return true_val if bool(cond) else false_val

    result = current_table.select(
        *pw.this,
        _if_result_raw=pw.apply(_if_func, cond_ref, true_ref, false_ref),
    )

    cols_to_remove = [pw.this[col] for col in temp_cols] + [pw.this._if_result_raw]

    return result.select(
        *pw.this.without(*cols_to_remove),
        if_result=pw.this._if_result_raw,
    )


def TERNARY(
    table: pw.Table,
    condition: pw.ColumnReference | bool | int | float,
    true_value: pw.ColumnReference | bool | int | float | None,
    false_value: pw.ColumnReference | bool | int | float | None,
) -> pw.Table:
    """Evaluate a conditional expression using ternary semantics.

    This is a convenience wrapper around :func:`IF` that returns its result column
    as ``ternary`` to align with expression parser output for ``cond ? a : b``.
    """

    result = IF(table, condition, true_value, false_value)

    return result.select(
        *pw.this.without(pw.this.if_result),
        ternary=pw.this.if_result,
    )
