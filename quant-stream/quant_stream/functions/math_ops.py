"""Mathematical operations."""

import math
import pathway as pw
from quant_stream.functions.helpers import _elementwise_operation


def EXP(table: pw.Table, column: pw.ColumnReference) -> pw.Table:
    """
    Calculate exponential (e^x) of each element in a column.

    This is equivalent to pandas: df.apply(np.exp)

    Args:
        table: Input table
        column: Column to calculate exponential of

    Returns:
        Table with exp column added
    """
    return _elementwise_operation(
        table, lambda x: math.exp(x) if x is not None else None, "exp", column
    )


def SQRT(table: pw.Table, column: pw.ColumnReference) -> pw.Table:
    """
    Calculate square root of each element in a column.

    This is equivalent to pandas: df.apply(np.sqrt)

    Args:
        table: Input table
        column: Column to calculate square root of

    Returns:
        Table with sqrt column added
    """
    return _elementwise_operation(
        table,
        lambda x: math.sqrt(x) if x is not None and x >= 0 else None,
        "sqrt",
        column,
    )


def LOG(table: pw.Table, column: pw.ColumnReference) -> pw.Table:
    """
    Calculate natural logarithm of each element in a column.

    Applies log to (x + 1) to handle zero values safely.
    This is equivalent to pandas: (df+1).apply(np.log)

    Args:
        table: Input table
        column: Column to calculate logarithm of

    Returns:
        Table with log column added
    """
    return _elementwise_operation(
        table,
        lambda x: math.log(x + 1) if x is not None and x >= -1 else None,
        "log",
        column,
    )


def INV(table: pw.Table, column: pw.ColumnReference) -> pw.Table:
    """
    Calculate inverse (1/x) of each element in a column.

    This is equivalent to pandas: 1 / df

    Args:
        table: Input table
        column: Column to calculate inverse of

    Returns:
        Table with inv column added
    """
    return _elementwise_operation(
        table, lambda x: 1.0 / x if x is not None and x != 0 else None, "inv", column
    )


def POW(table: pw.Table, column: pw.ColumnReference, n: float) -> pw.Table:
    """
    Calculate power (x^n) of each element in a column.

    This is equivalent to pandas: np.power(df, n)

    Args:
        table: Input table
        column: Column to calculate power of
        n: Exponent

    Returns:
        Table with pow column added
    """
    return _elementwise_operation(
        table, lambda x: x**n if x is not None else None, "pow", column
    )


def FLOOR(table: pw.Table, column: pw.ColumnReference) -> pw.Table:
    """
    Calculate floor (round down) of each element in a column.

    This is equivalent to pandas: df.apply(np.floor)

    Args:
        table: Input table
        column: Column to calculate floor of

    Returns:
        Table with floor column added
    """
    return _elementwise_operation(
        table, lambda x: math.floor(x) if x is not None else None, "floor", column
    )
