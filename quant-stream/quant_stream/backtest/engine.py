"""Backtesting engine for portfolio simulation."""

from typing import Optional, Dict

import pandas as pd
import pathway as pw

from quant_stream.strategy.base import Strategy
from quant_stream.recorder.recorder import Recorder
from quant_stream.backtest.portfolio import PortfolioState, rebalance_portfolio
from quant_stream.backtest.metrics import calculate_returns_metrics


class Backtester:
    """Backtesting engine with transaction costs and realistic simulation.

    Simulates portfolio performance by applying a strategy to signals,
    calculating required trades, applying transaction costs, and tracking
    portfolio value over time.

    Example:
        >>> backtester = Backtester(
        ...     initial_capital=1_000_000,
        ...     commission=0.001,
        ...     slippage=0.001
        ... )
        >>> results = backtester.run(signals, prices, strategy)
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000,
        commission: float = 0.001,
        slippage: float = 0.001,
        min_commission: float = 0.0,
        rebalance_frequency: int = 1,
        cost_reserve: float = 0.02,
        allow_short: bool = False,
        intraday_short_only: bool = True,
        short_funding_rate: float = 0.0002,
    ):
        """Initialize backtester.

        Args:
            initial_capital: Starting capital
            commission: Commission rate (fraction of trade value)
            slippage: Slippage rate (fraction of trade value)
            min_commission: Minimum commission per trade (set to 0 to disable)
            rebalance_frequency: Rebalance every N periods (1 = every period)
            cost_reserve: Fraction of capital to reserve for transaction costs (default: 0.02 = 2%)
            allow_short: If True, allow short positions (negative weights)
            intraday_short_only: If True, square off all shorts at end of each day (Indian market compliance)
            short_funding_rate: Daily funding/borrow rate for short positions (default: 0.02% per day)
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.min_commission = min_commission
        self.rebalance_frequency = rebalance_frequency
        self.cost_reserve = cost_reserve
        self.allow_short = allow_short
        self.intraday_short_only = intraday_short_only
        self.short_funding_rate = short_funding_rate

        self.portfolio = PortfolioState(initial_capital)
        self.results = None
        self.holdings_history = None

    def run(
        self,
        signals_df: pd.DataFrame,
        prices_df: pd.DataFrame,
        strategy: Strategy,
        recorder: Optional[Recorder] = None,
        artifact_prefix: Optional[str] = None,
    ) -> pd.DataFrame:
        """Run backtest using pandas for a realistic simulation.

        This is a more practical implementation that converts Pathway tables
        to pandas, runs the backtest, and returns results.
        
        FORWARD BIAS PREVENTION:
        -----------------------
        This implementation ensures no forward bias by:
        1. Signals at time t use only data available at close of period t
        2. Trades execute at the NEXT period (t+1) using next period's close price
        3. This simulates realistic trading where you:
           - Calculate signal after market close at t
           - Place orders that execute during period t+1
        
        Timeline:
        - t=0 close: Signal calculated using features at t=0
        - t=1 period: Trade executed at t+1 close price
        - t=1 close: Portfolio valued at t+1 close
        
        Note: This is conservative. In practice, you might execute at t+1 open,
        but using t+1 close is safer to avoid any intraday information leakage.

        Args:
            signals_df: DataFrame with [symbol, timestamp, signal]
            prices_df: DataFrame with [symbol, timestamp, close]
            strategy: Strategy instance
            recorder: Optional recorder for logging

        Returns:
            DataFrame with backtest results

        Example:
            >>> results_df = backtester.run(signals_df, prices_df, strategy)
        """
        # Reset portfolio
        self.portfolio.reset()
        self.holdings_history = None

        # OPTIMIZATION: Compute positions for ALL timestamps at once (not in loop)
        # This is much more efficient than calling Pathway for each timestamp
        signals_table = pw.debug.table_from_pandas(signals_df)
        positions_table = strategy.generate_positions(signals_table)
        all_positions_df = pw.debug.table_to_pandas(positions_table, include_id=False)
        
        # Get unique timestamps from signals (these may include non-trading days)
        signal_timestamps = sorted(signals_df["timestamp"].unique())
        
        # Get unique trading days from prices (these are actual market open days)
        trading_days = sorted(prices_df["timestamp"].unique())
        trading_days_set = set(trading_days)
        
        # Build a mapping: for each signal timestamp, find the NEXT available trading day
        # This handles weekends/holidays - if signal is generated on Saturday, execution is Monday
        def find_next_trading_day(signal_ts):
            """Find the next trading day AFTER the signal timestamp."""
            for td in trading_days:
                if td > signal_ts:
                    return td
            return None
        
        # Build mapping: execution_day -> signal_timestamp
        # Multiple signals might map to the same execution day (e.g., Fri, Sat, Sun all -> Monday)
        # We take the LATEST signal before the execution day
        execution_to_signal = {}
        for signal_ts in signal_timestamps:
            exec_day = find_next_trading_day(signal_ts)
            if exec_day is not None:
                # If multiple signals map to same execution day, keep the latest one
                if exec_day not in execution_to_signal or signal_ts > execution_to_signal[exec_day]:
                    execution_to_signal[exec_day] = signal_ts
        
        # Use trading days as the primary timeline for the backtest
        timestamps = trading_days

        results = []
        holdings_records = []
        prev_portfolio_value = None
        prev_prices_dict = {}  # Track previous period's prices for stock return calculation
        last_known_prices = {}  # Track last known prices for each symbol (for valuation when prices missing)

        if timestamps:
            prev_portfolio_value = self.initial_capital
            initial_timestamp = timestamps[0]
            initial_snapshot = {
                "timestamp": initial_timestamp,
                "portfolio_value": self.initial_capital,
                "cash": self.initial_capital,
                "num_positions": 0,
                "total_cost": 0.0,
                "positions": {},
                "position_values": {},
                "weights": {},
                "returns": 0.0,
                "stock_returns": {},
            }
            results.append(initial_snapshot)
            initial_timestamp_str = str(initial_timestamp)
            print(
                f"[BACKTEST][{initial_timestamp_str}] portfolio_value={self.initial_capital:,.2f} "
                f"cash={self.initial_capital:,.2f} return=0.0000%"
            )

        for i, timestamp in enumerate(timestamps):
            # Skip rebalancing if not at rebalance frequency
            if i % self.rebalance_frequency != 0:
                continue
            
            # Current timestamp is a trading day - get prices for this day
            current_prices = prices_df[prices_df["timestamp"] == timestamp]
            if len(current_prices) == 0:
                continue
            
            # Build prices dict for current trading day (for valuation)
            prices_dict = dict(zip(current_prices["symbol"], current_prices["close"]))
            
            # Update last known prices with current prices
            # This ensures we have prices for valuation even on days with partial data
            last_known_prices.update(prices_dict)
            
            # For portfolio valuation, use last known prices to handle missing price data
            # This prevents portfolio value from dropping to 0 when a stock has no price for this day
            valuation_prices = last_known_prices.copy()
            
            # Check if there's a signal that should execute on this trading day
            signal_timestamp = execution_to_signal.get(timestamp)
            
            if signal_timestamp is None:
                # No signal to execute today - just track portfolio value with current prices
                # Use valuation_prices (last known prices) to prevent 0-valuation when prices are missing
                final_value = self.portfolio.calculate_value(valuation_prices)
                
                period_return = None
                if prev_portfolio_value not in (None, 0) and prev_portfolio_value > 0:
                    period_return = (final_value / prev_portfolio_value) - 1
                prev_portfolio_value = final_value
                
                positions_snapshot = {
                    symbol: qty
                    for symbol, qty in self.portfolio.get_positions().items()
                    if abs(qty) > 1e-6
                }
                position_values = {
                    symbol: qty * valuation_prices.get(symbol, 0.0)
                    for symbol, qty in positions_snapshot.items()
                }
                weights = {}
                if final_value > 0:
                    weights = {
                        symbol: (position_values.get(symbol, 0.0) / final_value)
                        for symbol in position_values
                        if abs(position_values.get(symbol, 0.0)) > 1e-6
                    }
                
                # Calculate individual stock returns
                stock_returns = {}
                if prev_prices_dict:
                    for symbol in positions_snapshot.keys():
                        current_price = valuation_prices.get(symbol, 0.0)
                        prev_price = prev_prices_dict.get(symbol, 0.0)
                        if prev_price > 0 and current_price > 0:
                            stock_returns[symbol] = (current_price / prev_price) - 1
                        else:
                            stock_returns[symbol] = None
                else:
                    for symbol in positions_snapshot.keys():
                        stock_returns[symbol] = None
                
                prev_prices_dict = valuation_prices.copy()
                
                results.append({
                    "timestamp": timestamp,
                    "portfolio_value": final_value,
                    "cash": self.portfolio.cash,
                    "num_positions": len([p for p in self.portfolio.positions.values() if abs(p) > 1e-6]),
                    "total_cost": 0.0,
                    "positions": positions_snapshot,
                    "position_values": position_values,
                    "weights": weights,
                    "returns": period_return,
                    "stock_returns": stock_returns,
                })
                
                for symbol, quantity in positions_snapshot.items():
                    holdings_records.append({
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "quantity": quantity,
                        "position_value": position_values.get(symbol, 0.0),
                        "weight": weights.get(symbol, 0.0),
                    })
                
                timestamp_str = str(timestamp)
                log_msg = f"[BACKTEST][{timestamp_str}] portfolio_value={final_value:,.2f} cash={self.portfolio.cash:,.2f}"
                if period_return is not None:
                    log_msg += f" return={period_return:.4%}"
                print(log_msg)
                continue

            # We have a signal to execute today
            # Get signals from the signal_timestamp
            current_signals = signals_df[signals_df["timestamp"] == signal_timestamp]
            
            # Merge signals with today's execution prices
            merged = current_signals.merge(
                current_prices, on=["symbol"], how="inner", suffixes=("_signal", "_exec")
            )

            # Initialize total cost tracking
            total_cost = 0.0
            
            # Get target weights for the signal timestamp (when signal was generated)
            # Use .copy() to avoid SettingWithCopyWarning and ensure we have a clean DataFrame
            timestamp_mask = all_positions_df["timestamp"] == signal_timestamp
            # Ensure mask is a Series, not DataFrame
            if isinstance(timestamp_mask, pd.DataFrame):
                timestamp_mask = timestamp_mask.iloc[:, 0]
            positions_df = all_positions_df[timestamp_mask].copy()
            
            # Extract target weights as dictionary
            target_weights = {}
            for _, row in positions_df.iterrows():
                target_weight = row['target_weight']
                # Ensure target_weight is a scalar (not Series/DataFrame)
                if isinstance(target_weight, (pd.Series, pd.DataFrame)):
                    target_weight = target_weight.iloc[0] if hasattr(target_weight, 'iloc') else target_weight
                
                # Convert to float and check if valid weight
                try:
                    weight_value = float(target_weight)
                    # Include positive weights always, negative weights only if shorts allowed
                    if weight_value > 0 or (self.allow_short and weight_value < 0):
                        # Also ensure symbol is a scalar
                        symbol = row['symbol']
                        if isinstance(symbol, (pd.Series, pd.DataFrame)):
                            symbol = symbol.iloc[0] if hasattr(symbol, 'iloc') else str(symbol)
                        target_weights[str(symbol)] = weight_value
                except (ValueError, TypeError):
                    # Skip invalid weights
                    continue

            # First, close positions not in target (to free up cash)
            current_positions = self.portfolio.get_positions()
            for symbol in list(current_positions.keys()):
                if symbol not in target_weights and abs(current_positions[symbol]) > 1e-6:
                    # Close this position - use today's price if available, otherwise use last known price
                    price = prices_dict.get(symbol) or valuation_prices.get(symbol, 0.0)
                    if price > 0:
                        # quantity is negative to sell (close position)
                        quantity = -current_positions[symbol]
                        # Calculate cost based on absolute trade value
                        trade_value_abs = abs(quantity * price)
                        cost = max(
                            self.min_commission, trade_value_abs * (self.commission + self.slippage)
                        )
                        # execute_trade handles negative quantity correctly (adds cash when selling)
                        self.portfolio.execute_trade(symbol, quantity, price, cost)
                        total_cost += cost
            
            # Calculate value of positions we're keeping (those in target_weights)
            # Use valuation_prices to handle missing price data
            current_positions_after_close = self.portfolio.get_positions()
            kept_positions_value = sum(
                qty * valuation_prices.get(symbol, 0.0)
                for symbol, qty in current_positions_after_close.items()
                if symbol in target_weights
            )
            
            # Available capital = cash + value of positions we're keeping, minus cost reserve
            # This ensures we don't try to allocate more than we actually have
            available_capital = (self.portfolio.cash + kept_positions_value) * (1 - self.cost_reserve)
            
            # Calculate required trades with available capital
            # Use valuation_prices for rebalance calculation to handle missing current day prices
            trades = rebalance_portfolio(
                self.portfolio.get_positions(),
                target_weights,
                valuation_prices,
                available_capital,
                allow_short=self.allow_short,
            )

            # Execute trades with costs
            # Use today's price if available, otherwise use last known price for execution
            for symbol, quantity in trades.items():
                price = prices_dict.get(symbol) or valuation_prices.get(symbol, 0.0)
                if price > 0:
                    trade_value = abs(quantity * price)
                    # Apply higher cost for short trades (securities lending, etc.)
                    effective_commission = self.commission
                    if quantity < 0:  # Short/sell trade
                        effective_commission += self.short_funding_rate
                    cost = max(
                        self.min_commission, trade_value * (effective_commission + self.slippage)
                    )
                    self.portfolio.execute_trade(symbol, quantity, price, cost)
                    total_cost += cost

            # Square off shorts at end of day if intraday_short_only is enabled (Indian market)
            if self.allow_short and self.intraday_short_only:
                short_squareoff_cost = self.portfolio.square_off_shorts(
                    valuation_prices,
                    commission_rate=self.commission,
                    slippage_rate=self.slippage
                )
                total_cost += short_squareoff_cost

            # Record results
            # Use next_timestamp since this is when trades were actually executed
            # Calculate portfolio value AFTER all trades at current prices
            # Use valuation_prices to prevent 0-valuation when some prices are missing
            final_value = self.portfolio.calculate_value(valuation_prices)
            
            # Calculate return: compare end-of-period values
            # prev_portfolio_value is the value at the END of the previous period
            # final_value is the value at the END of this period (after trades)
            # This gives us the true return from holding positions and price changes
            period_return = None
            if prev_portfolio_value not in (None, 0) and prev_portfolio_value > 0:
                period_return = (final_value / prev_portfolio_value) - 1
            prev_portfolio_value = final_value

            positions_snapshot = {
                symbol: qty
                for symbol, qty in self.portfolio.get_positions().items()
                if abs(qty) > 1e-6
            }
            position_values = {
                symbol: qty * valuation_prices.get(symbol, 0.0)
                for symbol, qty in positions_snapshot.items()
            }
            weights = {}
            if final_value > 0:
                weights = {
                    symbol: (position_values.get(symbol, 0.0) / final_value)
                    for symbol in position_values
                    if abs(position_values.get(symbol, 0.0)) > 1e-6
                }

            # Calculate individual stock returns
            # For each stock, calculate return based on price change from previous period
            stock_returns = {}
            if prev_prices_dict:  # Can calculate returns if we have previous prices
                # Calculate returns for each current position
                for symbol in positions_snapshot.keys():
                    current_price = valuation_prices.get(symbol, 0.0)
                    prev_price = prev_prices_dict.get(symbol, 0.0)
                    
                    if prev_price > 0 and current_price > 0:
                        # Calculate return based on price change
                        stock_return = (current_price / prev_price) - 1
                        stock_returns[symbol] = stock_return
                    elif prev_price == 0 and current_price > 0:
                        # New position, no previous price available
                        stock_returns[symbol] = None
                    else:
                        # Price unavailable
                        stock_returns[symbol] = None
            else:
                # First period, no returns to calculate
                for symbol in positions_snapshot.keys():
                    stock_returns[symbol] = None
            
            # Update prev_prices_dict for next iteration
            prev_prices_dict = valuation_prices.copy()

            results.append(
                {
                    "timestamp": timestamp,  # Current trading day (execution day)
                    "portfolio_value": final_value,
                    "cash": self.portfolio.cash,
                    "num_positions": len(
                        [p for p in self.portfolio.positions.values() if abs(p) > 1e-6]
                    ),
                    "total_cost": total_cost,
                    "positions": positions_snapshot,
                    "position_values": position_values,
                    "weights": weights,
                    "returns": period_return,
                    "stock_returns": stock_returns,
                }
            )

            for symbol, quantity in positions_snapshot.items():
                holdings_records.append(
                    {
                        "timestamp": timestamp,
                        "symbol": symbol,
                        "quantity": quantity,
                        "position_value": position_values.get(symbol, 0.0),
                        "weight": weights.get(symbol, 0.0),
                    }
                )

            timestamp_str = str(timestamp)
            log_msg = (
                f"[BACKTEST][{timestamp_str}] portfolio_value={final_value:,.2f} "
                f"cash={self.portfolio.cash:,.2f}"
            )
            if period_return is not None:
                log_msg += f" return={period_return:.4%}"
            print(log_msg)
            # Detailed holdings output removed to avoid excessive terminal logging

        results_df = pd.DataFrame(results)

        # Calculate returns
        if len(results_df) > 0:
            pct_change_returns = results_df["portfolio_value"].pct_change()
            if "returns" in results_df.columns:
                results_df["returns"] = results_df["returns"].fillna(pct_change_returns)
            else:
                results_df["returns"] = pct_change_returns

        holdings_df = pd.DataFrame(holdings_records)
        if not holdings_df.empty:
            holdings_df["weight_pct"] = holdings_df["weight"] * 100.0

        self.holdings_history = holdings_df

        if recorder and recorder.active_run and len(results_df) > 0:
            metrics_log_df = results_df[
                ["timestamp", "portfolio_value", "cash", "returns", "num_positions", "total_cost"]
            ].copy()
            metrics_log_df = metrics_log_df.reset_index(drop=True)

            artifact_path = None
            if artifact_prefix:
                artifact_path = f"backtest/{artifact_prefix}"

            for step, row in metrics_log_df.iterrows():
                metrics_payload = {
                    "portfolio_value": float(row["portfolio_value"]),
                    "cash": float(row["cash"]),
                    "num_positions": float(row["num_positions"]),
                    "total_cost": float(row["total_cost"]),
                }
                if pd.notna(row.get("returns")):
                    metrics_payload["returns"] = float(row["returns"])
                recorder.log_metrics(step=step, **metrics_payload)

            try:
                recorder.log_artifact_dataframe(
                    metrics_log_df,
                    "daily_metrics",
                    artifact_path=artifact_path,
                )
                if not holdings_df.empty:
                    recorder.log_artifact_dataframe(
                        holdings_df,
                        "daily_holdings",
                        artifact_path=artifact_path,
                    )
            except Exception as artifact_exc:  # pragma: no cover - best effort logging
                print(f"[WARN] Failed to log daily artifacts: {artifact_exc}")

        # Calculate metrics
        if len(results_df) > 1 and recorder and recorder.active_run:
            metrics = calculate_returns_metrics(results_df["returns"].dropna())
            recorder.log_metrics(**metrics)
            recorder.set_tags(**strategy.get_config())

        return results_df

    def print_summary(self, results_df: Optional[pd.DataFrame] = None) -> None:
        """Print a summary of backtest results.
        
        Args:
            results_df: Optional results DataFrame from run()
        
        Example:
            >>> backtester.print_summary(results_df)
        """
        if results_df is None or len(results_df) < 2:
            print("No results to display. Run backtest first.")
            return
        
        from quant_stream.backtest.reporting import print_backtest_summary
        
        returns = results_df["returns"].dropna()
        metrics = calculate_returns_metrics(returns)
        
        config = {
            "initial_capital": self.initial_capital,
            "commission": self.commission,
            "slippage": self.slippage,
        }
        
        print_backtest_summary(results_df, metrics, config)
    
    def get_metrics(self) -> Dict[str, float]:
        """Calculate performance metrics from backtest results.

        Returns:
            Dictionary of performance metrics

        Example:
            >>> metrics = backtester.get_metrics()
            >>> print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        """
        if self.results is None:
            raise RuntimeError("No results available. Run backtest first.")

        # This would extract metrics from Pathway table
        # For now, return placeholder
        return {
            "total_return": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
        }

    def _log_metrics(self, recorder: Recorder):
        """Log metrics to recorder.

        Args:
            recorder: Recorder instance with active run
        """
        metrics = self.get_metrics()
        recorder.log_metrics(**metrics)

        # Log configuration
        config = {
            "initial_capital": self.initial_capital,
            "commission": self.commission,
            "slippage": self.slippage,
        }
        recorder.log_params(**config)


