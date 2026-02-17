"""Moving averages and technical indicators."""

import pathway as pw
from quant_stream.functions.helpers import _apply_rolling_aggregation


def SMA(
    table: pw.Table,
    column: pw.ColumnReference,
    m: int = None,
    n: int = None,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Simple Moving Average.

    Two modes:
    1. If m is an integer >= 1 and n is None: Simple moving average with window size m
    2. Otherwise: Exponential weighted moving average with formula Y_{i+1} = m/n*X_i + (1 - m/n)*Y_i

    This is equivalent to pandas:
    - Mode 1: df.groupby('instrument').transform(lambda x: x.rolling(m, min_periods=1).mean())
    - Mode 2: df.groupby('instrument').transform(lambda x: x.ewm(alpha=n/m).mean())

    Args:
        table: Input table with market data
        column: Column to calculate SMA of
        m: Moving average period/numerator
        n: Optional denominator for EWM mode
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with sma column added
    """
    if isinstance(m, int) and m >= 1 and n is None:
        # Simple moving average mode
        def calculate_mean(*values):
            valid_values = [v for v in values if v is not None]
            return sum(valid_values) / len(valid_values) if valid_values else None

        return _apply_rolling_aggregation(
            table,
            column,
            m,
            calculate_mean,
            "sma",
            by_instrument=by_instrument,
            timestamp=timestamp,
        )
    else:
        # Exponential weighted moving average mode
        # Y_{i+1} = m/n*X_i + (1 - m/n)*Y_i which is ewm(alpha=m/n)
        alpha = m / n if n != 0 else 0
        result = EWM(
            table, column, alpha=alpha, by_instrument=by_instrument, timestamp=timestamp
        )
        # Rename ewm column to sma
        return result.select(*pw.this.without(pw.this.ewm), sma=pw.this.ewm)


def EMA(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Exponential Moving Average.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.ewm(span=int(p), min_periods=1).mean())

    Args:
        table: Input table with market data
        column: Column to calculate EMA of
        p: Span parameter for exponential weighting
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ema column added
    """
    # EWM with span: alpha = 2/(span+1)
    alpha = 2.0 / (int(p) + 1)
    result = EWM(
        table, column, alpha=alpha, by_instrument=by_instrument, timestamp=timestamp
    )
    # Rename ewm column to ema
    return result.select(*pw.this.without(pw.this.ewm), ema=pw.this.ewm)


def EWM(
    table: pw.Table,
    column: pw.ColumnReference,
    alpha: float,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Exponential Weighted Moving Average with custom alpha.

    Formula: EWM is computed by applying exponentially decaying weights to all previous values.
    For each position i, we compute: EWM_i = sum(alpha * (1-alpha)^j * X_{i-j}) / sum(alpha * (1-alpha)^j)
    where j ranges from 0 to i.

    This is equivalent to the iterative formula: EWM_t = alpha * X_t + (1 - alpha) * EWM_{t-1}

    Args:
        table: Input table with market data
        column: Column to calculate EWM of
        alpha: Smoothing factor (0 < alpha <= 1)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with ewm column added
    """
    # We'll use a large window to approximate "all history"
    # For practical purposes, (1-alpha)^50 is essentially 0 for most alpha values
    max_window = min(200, int(10 / alpha)) if alpha > 0.05 else 200

    def calculate_ewm(*values):
        """Calculate EWM using exponential weights on historical values"""
        if not values or all(v is None for v in values):
            return None

        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None

        # Current value is first, oldest is last (due to our collection order)
        n = len(valid_values)

        # Calculate weights: current gets alpha, previous gets alpha*(1-alpha), etc.
        weights = [alpha * ((1 - alpha) ** i) for i in range(n)]
        weight_sum = sum(weights)

        # Apply weights
        weighted_sum = sum(v * w for v, w in zip(valid_values, weights))
        return weighted_sum / weight_sum if weight_sum > 0 else valid_values[0]

    return _apply_rolling_aggregation(
        table,
        column,
        max_window,
        calculate_ewm,
        "ewm",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def WMA(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 20,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Weighted Moving Average with exponential decay weights.

    Weights are calculated as: [0.9^(p-1), 0.9^(p-2), ..., 0.9^1, 0.9^0]
    where the most recent value has weight 0.9^0 = 1.

    This is equivalent to pandas:
    weights = [0.9**i for i in range(p)][::-1]
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(
        lambda window: (window * weights[:len(window)]).sum() / sum(weights[:len(window)])))

    Args:
        table: Input table with market data
        column: Column to calculate WMA of
        p: Rolling window size (default: 20)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with wma column added
    """
    # Pre-compute weights: most recent = 0.9^0 = 1, oldest = 0.9^(p-1)
    weights = [0.9**i for i in range(p)]
    weights.reverse()  # Reverse so oldest comes first

    def calculate_wma(*values):
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        n = len(valid_values)
        # When we have fewer than p values, use the first n weights (not last n)
        # Values come as [newest, ..., oldest], weights are [0.9^(p-1), ..., 0.9^0=1]
        # Pandas uses weights[:n], so we take first n weights and reverse to match values
        applicable_weights = list(reversed(weights[:n]))
        weighted_sum = sum(v * w for v, w in zip(valid_values, applicable_weights))
        weight_sum = sum(applicable_weights)
        return weighted_sum / weight_sum if weight_sum > 0 else None

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_wma,
        "wma",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def COUNT(
    table: pw.Table,
    cond: pw.ColumnReference,
    p: int = 20,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Count number of True/1 values in a rolling window.

    This is equivalent to pandas:
    cond.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).sum())

    Args:
        table: Input table with market data
        cond: Boolean/numeric condition column
        p: Rolling window size (default: 20)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with count column added
    """

    def calculate_count(*values):
        valid_values = [v for v in values if v is not None]
        # Sum up the boolean/numeric values
        return sum(1 if v else 0 for v in valid_values) if valid_values else 0

    return _apply_rolling_aggregation(
        table,
        cond,
        p,
        calculate_count,
        "count",
        result_type=int,
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def SUMIF(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int,
    cond: pw.ColumnReference,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate rolling sum of values where condition is True.

    This is equivalent to pandas:
    (df * cond).groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).sum())

    Args:
        table: Input table with market data
        column: Column to sum
        p: Rolling window size
        cond: Boolean/numeric condition column
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with sumif column added
    """
    filtered_table = table.select(
        *pw.this,
        _filtered_value=pw.apply_with_type(
            lambda val, cond_val: (val if cond_val else 0.0) if val is not None else 0.0,
            float,
            column,
            cond,
        ),
    )

    # Then apply rolling sum
    def calculate_sum(*values):
        valid_values = [v for v in values if v is not None]
        return sum(valid_values) if valid_values else None

    result = _apply_rolling_aggregation(
        filtered_table,
        pw.this._filtered_value,
        p,
        calculate_sum,
        "sumif",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )

    # Remove the temporary column
    result = result.select(*pw.this.without(pw.this._filtered_value))

    return result


def FILTER(
    table: pw.Table, column: pw.ColumnReference, cond: pw.ColumnReference
) -> pw.Table:
    """
    Filter values based on condition, setting non-matching values to 0.

    This is equivalent to pandas:
    df.mul(cond)

    Args:
        table: Input table with market data
        column: Column to filter
        cond: Boolean/numeric condition column

    Returns:
        Table with filtered column added
    """
    return table.select(*pw.this, filtered=column * cond)


def PROD(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate rolling product of values.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(lambda x: x.prod(), raw=True))

    Args:
        table: Input table with market data
        column: Column to calculate product of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with prod column added
    """
    if isinstance(p, int):

        def calculate_prod(*values):
            valid_values = [v for v in values if v is not None]
            if not valid_values:
                return None
            result = 1
            for v in valid_values:
                result *= v
            return result

        return _apply_rolling_aggregation(
            table,
            column,
            p,
            calculate_prod,
            "prod",
            by_instrument=by_instrument,
            timestamp=timestamp,
        )
    else:
        # If p is not an integer, multiply column by p
        return table.select(*pw.this, prod=column * p)


def DECAYLINEAR(
    table: pw.Table,
    column: pw.ColumnReference,
    p: int = 5,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate linear decay weighted average.

    Weights increase linearly: [1, 2, 3, ..., p] where the most recent value has the highest weight.

    This is equivalent to pandas:
    decay_weights = np.arange(1, p+1, 1)
    decay_weights = decay_weights / decay_weights.sum()
    df.groupby('instrument').transform(lambda x: x.rolling(p, min_periods=1).apply(
        lambda window: (window * decay_weights[:len(window)]).sum(), raw=True))

    Args:
        table: Input table with market data
        column: Column to calculate decay linear average of
        p: Rolling window size (default: 5)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with decaylinear column added
    """
    assert isinstance(p, int), (
        f"DECAYLINEAR only accepts integer parameter p, received {type(p).__name__}"
    )

    # Pre-compute normalized weights
    decay_weights = [i for i in range(1, p + 1)]
    weight_sum = sum(decay_weights)
    normalized_weights = [w / weight_sum for w in decay_weights]

    def calculate_decaylinear(*values):
        valid_values = [v for v in values if v is not None]
        if not valid_values:
            return None
        n = len(valid_values)
        # When we have fewer than p values, use the first n weights (not last n)
        # Values come as [newest, ..., oldest], weights are [1/sum, 2/sum, ..., n/sum]
        # We want newest to get highest weight, so reverse the weights
        applicable_weights = list(reversed(normalized_weights[:n]))
        weighted_sum = sum(v * w for v, w in zip(valid_values, applicable_weights))
        return weighted_sum

    return _apply_rolling_aggregation(
        table,
        column,
        p,
        calculate_decaylinear,
        "decaylinear",
        by_instrument=by_instrument,
        timestamp=timestamp,
    )


def MACD(
    table: pw.Table,
    column: pw.ColumnReference,
    short_window: int = 12,
    long_window: int = 26,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Moving Average Convergence Divergence (MACD) indicator.

    MACD is the difference between short-term and long-term exponential moving averages.
    Formula: MACD = EMA(short) - EMA(long)

    This is equivalent to pandas:
    short_ema = df.groupby('instrument').transform(lambda x: x.ewm(span=short_window, min_periods=1).mean())
    long_ema = df.groupby('instrument').transform(lambda x: x.ewm(span=long_window, min_periods=1).mean())
    macd = short_ema - long_ema

    Args:
        table: Input table with market data
        column: Column to calculate MACD of (typically closing price)
        short_window: Short EMA window size (default: 12)
        long_window: Long EMA window size (default: 26)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with macd column added
    """
    # Calculate short EMA
    short_ema_table = EMA(
        table, column, short_window, by_instrument=by_instrument, timestamp=timestamp
    )
    # Rename ema to short_ema
    short_ema_table = short_ema_table.select(
        *pw.this.without(pw.this.ema), _short_ema=pw.this.ema
    )

    # Calculate long EMA
    long_ema_table = EMA(
        table, column, long_window, by_instrument=by_instrument, timestamp=timestamp
    )
    # Rename ema to long_ema
    long_ema_table = long_ema_table.select(
        *pw.this.without(pw.this.ema), _long_ema=pw.this.ema
    )

    # Join and calculate difference
    # Both tables have the same structure (same rows from original table)
    result = short_ema_table.select(
        *pw.this, _long_ema=long_ema_table.ix(pw.this.id)._long_ema
    ).select(
        *pw.this.without(pw.this._short_ema, pw.this._long_ema),
        macd=pw.apply_with_type(
            lambda short, long: (
                short - long if short is not None and long is not None else None
            ),
            float | None,
            pw.this._short_ema,
            pw.this._long_ema,
        ),
    )

    return result


def RSI(
    table: pw.Table,
    column: pw.ColumnReference,
    window: int = 14,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Relative Strength Index (RSI) indicator.

    RSI measures the magnitude of recent price changes to evaluate
    overbought or oversold conditions.

    Formula:
    - price_change = current_price - previous_price
    - up = max(price_change, 0)
    - down = max(-price_change, 0)
    - avg_up = EMA(up, window)
    - avg_down = EMA(down, window)
    - RSI = 100 - (100 / (1 + avg_up / avg_down))

    Args:
        table: Input table with market data
        column: Column to calculate RSI of (typically closing price)
        window: RSI window size (default: 14)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with rsi column added
    """
    from quant_stream.functions.timeseries import DELTA

    # Calculate price change (delta)
    delta_table = DELTA(table, column, periods=1, by_instrument=by_instrument)

    # Calculate up and down movements
    up_down_table = delta_table.select(
        *pw.this,
        _up=pw.apply_with_type(
            lambda d: max(d, 0.0) if d is not None else 0.0, float, pw.this.delta
        ),
        _down=pw.apply_with_type(
            lambda d: max(-d, 0.0) if d is not None else 0.0, float, pw.this.delta
        ),
    )

    # Calculate EMA of ups
    avg_up_table = EMA(
        up_down_table,
        pw.this._up,
        window,
        by_instrument=by_instrument,
        timestamp=timestamp,
    )
    avg_up_table = avg_up_table.select(
        *pw.this.without(pw.this.ema), _avg_up=pw.this.ema
    )

    # Calculate EMA of downs
    avg_down_table = EMA(
        avg_up_table,
        pw.this._down,
        window,
        by_instrument=by_instrument,
        timestamp=timestamp,
    )
    avg_down_table = avg_down_table.select(
        *pw.this.without(pw.this.ema), _avg_down=pw.this.ema
    )

    # Calculate RSI
    result = avg_down_table.select(
        *pw.this.without(
            pw.this.delta,
            pw.this._up,
            pw.this._down,
            pw.this._avg_up,
            pw.this._avg_down,
        ),
        rsi=pw.apply_with_type(
            lambda avg_up, avg_down: (
                100.0 - (100.0 / (1.0 + (avg_up / avg_down))) 
                if (avg_up is not None and avg_down is not None and avg_down > 0) 
                else (100.0 if avg_up is not None else 50.0)
            ),
            float,
            pw.this._avg_up,
            pw.this._avg_down,
        ),
    )

    return result


def BB_MIDDLE(
    table: pw.Table,
    column: pw.ColumnReference,
    window: int = 20,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Bollinger Bands middle band (simple moving average).

    The middle band is simply the simple moving average of the price.

    This is equivalent to pandas:
    df.groupby('instrument').transform(lambda x: x.rolling(window, min_periods=1).mean())

    Args:
        table: Input table with market data
        column: Column to calculate middle band of (typically closing price)
        window: Window size for moving average (default: 20)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with bb_middle column added
    """
    result = SMA(
        table, column, m=window, by_instrument=by_instrument, timestamp=timestamp
    )
    # Rename sma to bb_middle
    return result.select(*pw.this.without(pw.this.sma), bb_middle=pw.this.sma)


def BB_UPPER(
    table: pw.Table,
    column: pw.ColumnReference,
    window: int = 20,
    num_std: float = 2.0,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Bollinger Bands upper band.

    The upper band is the middle band plus a number of standard deviations.
    Formula: upper_band = middle_band + (num_std * rolling_std)

    This is equivalent to pandas:
    middle = df.groupby('instrument').transform(lambda x: x.rolling(window, min_periods=1).mean())
    std = df.groupby('instrument').transform(lambda x: x.rolling(window, min_periods=1).std())
    upper = middle + num_std * std

    Args:
        table: Input table with market data
        column: Column to calculate upper band of (typically closing price)
        window: Window size for moving average (default: 20)
        num_std: Number of standard deviations (default: 2.0)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with bb_upper column added
    """
    from quant_stream.functions.rolling import TS_STD

    # Calculate middle band
    middle_table = BB_MIDDLE(
        table, column, window, by_instrument=by_instrument, timestamp=timestamp
    )

    # Calculate rolling standard deviation
    std_table = TS_STD(
        middle_table, column, window, by_instrument=by_instrument, timestamp=timestamp
    )

    # Calculate upper band
    result = std_table.select(
        *pw.this.without(pw.this.bb_middle, pw.this.ts_std),
        bb_upper=pw.apply_with_type(
            lambda middle, std: (
                middle + (num_std * std)
                if middle is not None and std is not None
                else None
            ),
            float | None,
            pw.this.bb_middle,
            pw.this.ts_std,
        ),
    )

    return result


def BB_LOWER(
    table: pw.Table,
    column: pw.ColumnReference,
    window: int = 20,
    num_std: float = 2.0,
    by_instrument: pw.ColumnReference = None,
    timestamp: pw.ColumnReference = None,
) -> pw.Table:
    """
    Calculate Bollinger Bands lower band.

    The lower band is the middle band minus a number of standard deviations.
    Formula: lower_band = middle_band - (num_std * rolling_std)

    This is equivalent to pandas:
    middle = df.groupby('instrument').transform(lambda x: x.rolling(window, min_periods=1).mean())
    std = df.groupby('instrument').transform(lambda x: x.rolling(window, min_periods=1).std())
    lower = middle - num_std * std

    Args:
        table: Input table with market data
        column: Column to calculate lower band of (typically closing price)
        window: Window size for moving average (default: 20)
        num_std: Number of standard deviations (default: 2.0)
        by_instrument: Instrument column for grouping (optional, defaults to pw.this.instrument)
        timestamp: Timestamp column for ordering (optional, defaults to pw.this.timestamp)

    Returns:
        Table with bb_lower column added
    """
    from quant_stream.functions.rolling import TS_STD

    # Calculate middle band
    middle_table = BB_MIDDLE(
        table, column, window, by_instrument=by_instrument, timestamp=timestamp
    )

    # Calculate rolling standard deviation
    std_table = TS_STD(
        middle_table, column, window, by_instrument=by_instrument, timestamp=timestamp
    )

    # Calculate lower band
    result = std_table.select(
        *pw.this.without(pw.this.bb_middle, pw.this.ts_std),
        bb_lower=pw.apply_with_type(
            lambda middle, std: (
                middle - (num_std * std)
                if middle is not None and std is not None
                else None
            ),
            float | None,
            pw.this.bb_middle,
            pw.this.ts_std,
        ),
    )

    return result
