"""Portfolio state tracking for backtesting."""

from typing import Dict

import pathway as pw


class PortfolioState:
    """Tracks portfolio state during backtesting.

    Maintains current positions, cash, and portfolio value as
    trades are executed and prices change. Supports both long
    and short positions with intraday short square-off for
    Indian market compliance.
    """

    def __init__(self, initial_capital: float = 1_000_000):
        """Initialize portfolio state.

        Args:
            initial_capital: Starting cash amount
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}  # {symbol: quantity} - positive=long, negative=short
        self.short_positions = {}  # Track short positions separately for square-off
        self.short_margin_blocked = 0.0  # Margin blocked for short positions
        self.value_history = []
        self.trade_history = []

    def execute_trade(
        self, symbol: str, quantity: float, price: float, cost: float = 0.0
    ):
        """Execute a trade and update portfolio state.

        Args:
            symbol: Instrument symbol
            quantity: Trade quantity (positive = buy, negative = sell/short)
            price: Execution price
            cost: Transaction cost

        Example:
            >>> portfolio.execute_trade("AAPL", 100, 150.0, cost=15.0)  # Buy
            >>> portfolio.execute_trade("AAPL", -50, 155.0, cost=7.75)  # Sell/Short
        """
        # Update position
        current_qty = self.positions.get(symbol, 0.0)
        new_qty = current_qty + quantity
        self.positions[symbol] = new_qty

        # Track short positions separately for square-off logic
        if new_qty < 0:
            self.short_positions[symbol] = new_qty
        elif symbol in self.short_positions:
            del self.short_positions[symbol]

        # Update cash
        trade_value = quantity * price
        self.cash -= trade_value + cost

        # Record trade
        self.trade_history.append(
            {
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "cost": cost,
                "cash_after": self.cash,
                "is_short": new_qty < 0,
            }
        )

    def calculate_value(self, prices: Dict[str, float]) -> float:
        """Calculate current portfolio value.

        Args:
            prices: Current prices {symbol: price}

        Returns:
            Total portfolio value (cash + positions)

        Example:
            >>> value = portfolio.calculate_value({"AAPL": 155.0, "MSFT": 320.0})
        """
        position_value = sum(
            qty * prices.get(symbol, 0.0) for symbol, qty in self.positions.items()
        )
        total_value = self.cash + position_value
        self.value_history.append(total_value)
        return total_value

    def get_positions(self) -> Dict[str, float]:
        """Get current positions.

        Returns:
            Dictionary of {symbol: quantity}
        """
        return self.positions.copy()

    def get_weights(self, prices: Dict[str, float]) -> Dict[str, float]:
        """Calculate position weights.

        Args:
            prices: Current prices {symbol: price}

        Returns:
            Dictionary of {symbol: weight} where weights sum to 1

        Example:
            >>> weights = portfolio.get_weights({"AAPL": 155.0})
        """
        total_value = self.calculate_value(prices)
        if total_value <= 0:
            return {}

        weights = {}
        for symbol, qty in self.positions.items():
            position_value = qty * prices.get(symbol, 0.0)
            weights[symbol] = position_value / total_value

        return weights

    def reset(self):
        """Reset portfolio to initial state."""
        self.cash = self.initial_capital
        self.positions = {}
        self.short_positions = {}
        self.short_margin_blocked = 0.0
        self.value_history = []
        self.trade_history = []

    def get_short_positions(self) -> Dict[str, float]:
        """Get current short positions.

        Returns:
            Dictionary of {symbol: quantity} for short positions only (negative quantities)
        """
        return self.short_positions.copy()

    def square_off_shorts(
        self, prices: Dict[str, float], commission_rate: float = 0.001, slippage_rate: float = 0.001
    ) -> float:
        """Square off all short positions (Indian market intraday requirement).

        Closes all short positions by buying back the shares.
        This must be called at end of each trading day for Indian market compliance.

        Args:
            prices: Current prices {symbol: price}
            commission_rate: Commission rate for the cover trades
            slippage_rate: Slippage rate for the cover trades

        Returns:
            Total cost of square-off trades (including P&L impact)

        Example:
            >>> cost = portfolio.square_off_shorts({"RELIANCE": 2500.0})
        """
        total_cost = 0.0
        shorts_to_close = list(self.short_positions.items())

        for symbol, qty in shorts_to_close:
            if qty >= 0:  # Not actually short
                continue

            price = prices.get(symbol, 0.0)
            if price <= 0:
                continue

            # Buy back to cover short (quantity is negative, so -qty is positive)
            cover_qty = -qty
            trade_value = cover_qty * price
            cost = trade_value * (commission_rate + slippage_rate)

            # Execute cover trade
            self.execute_trade(symbol, cover_qty, price, cost)
            total_cost += cost

        return total_cost

    def get_gross_exposure(self, prices: Dict[str, float]) -> float:
        """Calculate gross exposure (sum of absolute position values).

        Args:
            prices: Current prices {symbol: price}

        Returns:
            Gross exposure value
        """
        return sum(
            abs(qty) * prices.get(symbol, 0.0)
            for symbol, qty in self.positions.items()
        )

    def get_net_exposure(self, prices: Dict[str, float]) -> float:
        """Calculate net exposure (long value - short value).

        Args:
            prices: Current prices {symbol: price}

        Returns:
            Net exposure value (positive = net long, negative = net short)
        """
        return sum(
            qty * prices.get(symbol, 0.0)
            for symbol, qty in self.positions.items()
        )




def rebalance_portfolio(
    current_positions: Dict[str, float],
    target_weights: Dict[str, float],
    prices: Dict[str, float],
    total_value: float,
    allow_short: bool = False,
) -> Dict[str, float]:
    """Calculate trades needed to rebalance to target weights.

    Supports both long and short positions. Short positions are represented
    as negative weights (e.g., -0.1 = 10% short exposure).

    Args:
        current_positions: Current holdings {symbol: quantity}
        target_weights: Target weights {symbol: weight} (negative for shorts)
        prices: Current prices {symbol: price}
        total_value: Total portfolio value (gross or net, depending on strategy)
        allow_short: If True, allow negative target weights for short positions

    Returns:
        Dictionary of trades {symbol: quantity} (negative = sell/short)

    Example:
        >>> # Long-short portfolio: 50% long AAPL, 30% short MSFT
        >>> trades = rebalance_portfolio(
        ...     current_positions={},
        ...     target_weights={"AAPL": 0.5, "MSFT": -0.3},
        ...     prices={"AAPL": 150, "MSFT": 300},
        ...     total_value=100000,
        ...     allow_short=True
        ... )
    """
    trades = {}

    # Get all symbols (current and target)
    all_symbols = set(current_positions.keys()) | set(target_weights.keys())

    for symbol in all_symbols:
        current_qty = current_positions.get(symbol, 0.0)
        target_weight = target_weights.get(symbol, 0.0)
        price = prices.get(symbol, 0.0)

        if price <= 0:
            continue

        # Skip negative weights if shorts not allowed
        if target_weight < 0 and not allow_short:
            target_weight = 0.0

        # Calculate target quantity (can be negative for shorts)
        target_value = total_value * target_weight
        target_qty = target_value / price

        # Calculate required trade
        trade_qty = target_qty - current_qty

        if abs(trade_qty) > 1e-6:  # Minimum trade size threshold
            trades[symbol] = trade_qty

    return trades







