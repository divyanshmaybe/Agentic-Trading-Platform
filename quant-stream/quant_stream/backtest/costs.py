"""Transaction cost models for realistic backtesting."""

import pathway as pw


def calculate_transaction_costs(
    trades: pw.Table,
    commission: float = 0.001,
    slippage: float = 0.001,
    min_commission: float = 5.0,
) -> pw.Table:
    """Calculate transaction costs for trades.

    Args:
        trades: Table with columns [symbol, timestamp, quantity, price]
        commission: Commission rate as a fraction of trade value
        slippage: Slippage rate as a fraction of trade value
        min_commission: Minimum commission per trade

    Returns:
        Table with added 'cost' column

    Example:
        >>> trades_with_costs = calculate_transaction_costs(
        ...     trades,
        ...     commission=0.001,
        ...     slippage=0.001,
        ...     min_commission=5.0
        ... )
    """
    # Calculate trade value (with safety check for non-negative prices)
    trades = trades.select(
        *pw.this,
        trade_value=pw.apply_with_type(
            lambda qty, price: abs(qty) * max(0.0, price),
            float,
            pw.this.quantity,
            pw.this.price,
        ),
    )

    # Calculate commission (percentage-based with minimum)
    trades = trades.select(
        *pw.this,
        commission_cost=pw.cast(
            float,
            pw.apply(
                lambda value: max(min_commission, value * commission),
                pw.this.trade_value,
            ),
        ),
    )

    # Calculate slippage (percentage of trade value)
    trades = trades.select(
        *pw.this,
        slippage_cost=pw.cast(float, pw.this.trade_value * slippage),
    )

    # Total cost
    trades = trades.select(
        *pw.this,
        cost=pw.this.commission_cost + pw.this.slippage_cost,
    )

    return trades


def apply_market_impact(
    trades: pw.Table, volume: pw.Table, impact_coefficient: float = 0.1
) -> pw.Table:
    """Apply market impact model to trades.

    Simple square-root market impact model based on trade size relative to volume.

    Args:
        trades: Table with [symbol, timestamp, quantity]
        volume: Table with [symbol, timestamp, volume]
        impact_coefficient: Market impact coefficient

    Returns:
        Table with added 'impact_cost' column

    Example:
        >>> trades_with_impact = apply_market_impact(trades, volume_data)
    """
    # Join trades with volume
    trades = trades.join(
        volume,
        pw.left.symbol == pw.right.symbol,
        pw.left.timestamp == pw.right.timestamp,
    ).select(
        symbol=pw.left.symbol,
        timestamp=pw.left.timestamp,
        quantity=pw.left.quantity,
        price=pw.left.price,
        volume=pw.right.volume,
    )

    # Calculate market impact: cost ∝ sqrt(trade_size / volume)
    # First calculate trade fraction (with zero-volume protection)
    trades = trades.select(
        *pw.this,
        trade_fraction=pw.if_else(
            pw.this.volume > 0,
            pw.cast(float, pw.apply(abs, pw.this.quantity)) / pw.this.volume,
            0.0,
        ),
    )
    
    # Then calculate impact cost using the trade_fraction
    trades = trades.select(
        *pw.this,
        impact_cost=pw.apply_with_type(
            lambda frac, price, qty: impact_coefficient
            * (frac**0.5)
            * max(0.0, price)
            * abs(qty),
            float,
            pw.this.trade_fraction,
            pw.this.price,
            pw.this.quantity,
        ),
    )

    return trades


def calculate_position_costs(
    positions: pw.Table,
    holding_cost: float = 0.0,
    funding_rate: float = 0.0,
) -> pw.Table:
    """Calculate costs for holding positions.

    Args:
        positions: Table with [symbol, timestamp, quantity, price]
        holding_cost: Daily holding cost as fraction of position value
        funding_rate: Daily funding/borrowing rate

    Returns:
        Table with added 'holding_cost' column

    Example:
        >>> positions_with_costs = calculate_position_costs(
        ...     positions,
        ...     holding_cost=0.0001
        ... )
    """
    # Calculate position value
    positions = positions.select(
        *pw.this,
        position_value=pw.this.quantity * pw.this.price,
    )

    # Calculate holding cost
    positions = positions.select(
        *pw.this,
        holding_cost=pw.cast(float, pw.apply(abs, pw.this.position_value)) * holding_cost,
    )

    # Add funding cost for short positions
    positions = positions.select(
        *pw.this,
        funding_cost=pw.cast(
            float,
            pw.if_else(
                pw.this.quantity < 0,
                pw.cast(float, pw.apply(abs, pw.this.position_value)) * funding_rate,
                0.0,
            ),
        ),
    )

    # Total position cost
    positions = positions.select(
        *pw.this,
        total_holding_cost=pw.this.holding_cost + pw.this.funding_cost,
    )

    return positions

