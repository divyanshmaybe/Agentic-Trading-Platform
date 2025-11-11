# -*- coding: utf-8 -*-
"""
NSE Filings Backtesting Module - Pathway Implementation

This module provides backtesting functionality for trading signals
generated from NSE filings sentiment analysis.
"""

import pathway as pw
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

from market_data import get_market_data_service  # type: ignore


# Configuration
TARGET = 0.03  # +3% profit target
STOPLOSS = 0.01  # -1% stoploss
HOLDING_HOURS = 1  # maximum hold time (1 hour)
INTERVAL = "ONE_MINUTE"  # data interval for Angel One
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


class TradingSignalSchema(pw.Schema):
    """Schema for trading signals"""
    symbol: str
    filing_time: str
    signal: int  # 1=BUY, -1=SELL, 0=HOLD
    explanation: str


class BacktestResultSchema(pw.Schema):
    """Schema for backtest results"""
    symbol: str
    entry_time: str
    signal: int
    pnl: float
    exit_time: str
    session: str
    exit_reason: str


@pw.udf
def adjust_entry_time(filing_time_str: str) -> str:
    """Adjust filing time to market hours - returns entry time"""
    try:
        filing_time = pd.to_datetime(filing_time_str)
        market_open = filing_time.replace(
            hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0
        )
        market_close = filing_time.replace(
            hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0
        )
        
        if filing_time.time() < market_open.time():
            adjusted_time = market_open
        elif filing_time.time() > market_close.time():
            next_day = (filing_time + timedelta(days=1)).replace(
                hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0
            )
            # Skip weekends
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            adjusted_time = next_day
        else:
            adjusted_time = filing_time
        
        return adjusted_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        return filing_time_str


@pw.udf
def get_session_type(filing_time_str: str) -> str:
    """Get session type based on filing time"""
    try:
        filing_time = pd.to_datetime(filing_time_str)
        market_open = filing_time.replace(
            hour=MARKET_OPEN[0], minute=MARKET_OPEN[1], second=0, microsecond=0
        )
        market_close = filing_time.replace(
            hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1], second=0, microsecond=0
        )
        
        if filing_time.time() < market_open.time():
            return "pre_open"
        elif filing_time.time() > market_close.time():
            return "post_close"
        else:
            return "during_market"
    except Exception as e:
        return "error"


def _simulate_trade_helper(symbol: str, signal: int, entry_time_str: str, target: float, stop: float):
    """Helper function to simulate trade - returns dict with results"""
    try:
        entry_time = pd.to_datetime(entry_time_str)
        start_time = entry_time - timedelta(minutes=2)
        end_time = entry_time + timedelta(hours=HOLDING_HOURS)

        service = get_market_data_service()
        adapter = getattr(service, "adapter", None)
        if not adapter or not hasattr(adapter, "get_historical_candles"):
            return {
                "pnl": np.nan,
                "exit_time": entry_time_str,
                "exit_reason": "adapter_unavailable",
            }

        normalized = adapter.normalize_symbol(symbol)
        candles = adapter.get_historical_candles(
            symbol=normalized,
            interval=INTERVAL,
            fromdate=start_time.strftime("%Y-%m-%d %H:%M"),
            todate=end_time.strftime("%Y-%m-%d %H:%M"),
            exchange="NSE",
        )

        if not candles:
            return {"pnl": np.nan, "exit_time": entry_time_str, "exit_reason": "no_data"}

        data = pd.DataFrame(candles)
        if data.empty:
            return {"pnl": np.nan, "exit_time": entry_time_str, "exit_reason": "no_data"}

        data.rename(
            columns={
                "timestamp": "Timestamp",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            },
            inplace=True,
        )
        data["Timestamp"] = pd.to_datetime(data["Timestamp"], utc=True, errors="coerce")
        data.dropna(subset=["Timestamp"], inplace=True)
        data.set_index("Timestamp", inplace=True)
        data.sort_index(inplace=True)

        # Convert entry time to UTC for comparison
        entry_time_utc = entry_time.tz_localize("Asia/Kolkata").tz_convert("UTC") if entry_time.tzinfo is None else entry_time.tz_convert("UTC")
        valid_data = data.loc[data.index >= entry_time_utc]
        if valid_data.empty:
            return {"pnl": np.nan, "exit_time": entry_time_str, "exit_reason": "no_data"}
        
        entry_price = valid_data.iloc[0]["Close"]
        
        for i, row in valid_data.iterrows():
            price = row["Close"]
            timestamp_local = i.tz_convert("Asia/Kolkata")

            if signal == 1:  # long
                if price >= entry_price * (1 + target):
                    return {"pnl": +target, "exit_time": timestamp_local.strftime("%Y-%m-%d %H:%M:%S"), "exit_reason": "target_hit"}
                elif price <= entry_price * (1 - stop):
                    return {"pnl": -stop, "exit_time": timestamp_local.strftime("%Y-%m-%d %H:%M:%S"), "exit_reason": "stoploss_hit"}
            elif signal == -1:  # short
                if price <= entry_price * (1 - target):
                    return {"pnl": +target, "exit_time": timestamp_local.strftime("%Y-%m-%d %H:%M:%S"), "exit_reason": "target_hit"}
                elif price >= entry_price * (1 + stop):
                    return {"pnl": -stop, "exit_time": timestamp_local.strftime("%Y-%m-%d %H:%M:%S"), "exit_reason": "stoploss_hit"}
        
        # Neither target nor stoploss hit
        exit_price = valid_data.iloc[-1]["Close"]
        pnl = (exit_price - entry_price) / entry_price * signal
        exit_time_local = valid_data.index[-1].tz_convert("Asia/Kolkata")
        return {"pnl": pnl, "exit_time": exit_time_local.strftime("%Y-%m-%d %H:%M:%S"), "exit_reason": "time_exit"}
    
    except Exception as e:
        return {"pnl": np.nan, "exit_time": entry_time_str, "exit_reason": f"error: {str(e)}"}


@pw.udf
def simulate_trade_pnl(symbol: str, signal: int, entry_time_str: str) -> float:
    """Get PnL from trade simulation"""
    print(f"[BACKTEST] Simulating trade for {symbol}, signal={signal}, entry={entry_time_str}")
    result = _simulate_trade_helper(symbol, signal, entry_time_str, TARGET, STOPLOSS)
    pnl = result["pnl"]
    print(f"[BACKTEST] Trade result for {symbol}: PnL={pnl}")
    return pnl if not (isinstance(pnl, float) and np.isnan(pnl)) else 0.0


@pw.udf
def simulate_trade_exit_time(symbol: str, signal: int, entry_time_str: str) -> str:
    """Get exit time from trade simulation"""
    result = _simulate_trade_helper(symbol, signal, entry_time_str, TARGET, STOPLOSS)
    return result["exit_time"]


@pw.udf
def simulate_trade_exit_reason(symbol: str, signal: int, entry_time_str: str) -> str:
    """Get exit reason from trade simulation"""
    result = _simulate_trade_helper(symbol, signal, entry_time_str, TARGET, STOPLOSS)
    return result["exit_reason"]


def create_backtest_pipeline(signals_table: pw.Table) -> pw.Table:
    """
    Create backtest pipeline from trading signals
    
    Args:
        signals_table: Table with trading signals (symbol, filing_time, signal, explanation)
    
    Returns:
        Table with backtest results
    """
    
    # Adjust filing times to market hours
    signals_adjusted = signals_table.select(
        symbol=pw.this.symbol,
        filing_time=pw.this.filing_time,
        signal=pw.this.signal,
        explanation=pw.this.explanation,
        entry_time=adjust_entry_time(pw.this.filing_time),
        session=get_session_type(pw.this.filing_time)
    )
    
    # Filter out HOLD signals (signal == 0) - only backtest BUY/SELL signals
    actionable_signals = signals_adjusted.filter(pw.this.signal != 0)
    
    # Debug: Count actionable signals
    print(f"[BACKTEST] Filtered signals - only processing BUY (1) and SELL (-1) signals")
    
    # Simulate trades
    backtest_results = actionable_signals.select(
        symbol=pw.this.symbol,
        entry_time=pw.this.entry_time,
        signal=pw.this.signal,
        session=pw.this.session,
        pnl=simulate_trade_pnl(pw.this.symbol, pw.this.signal, pw.this.entry_time),
        exit_time=simulate_trade_exit_time(pw.this.symbol, pw.this.signal, pw.this.entry_time),
        exit_reason=simulate_trade_exit_reason(pw.this.symbol, pw.this.signal, pw.this.entry_time)
    )
    
    return backtest_results


def compute_backtest_metrics(backtest_results: pw.Table) -> pw.Table:
    """
    Compute backtest metrics from results
    
    Returns:
        Table with aggregated metrics
    """
    # Aggregate metrics
    metrics = backtest_results.filter(pw.this.pnl.is_not_none()).groupby().reduce(
        total_trades=pw.reducers.count(),
        wins=pw.reducers.sum(pw.cast(int, pw.this.pnl > 0)),
        losses=pw.reducers.sum(pw.cast(int, pw.this.pnl < 0)),
        total_pnl=pw.reducers.sum(pw.this.pnl),
        avg_pnl=pw.reducers.avg(pw.this.pnl),
        max_pnl=pw.reducers.max(pw.this.pnl),
        min_pnl=pw.reducers.min(pw.this.pnl),
    )
    
    # Calculate derived metrics
    metrics_with_derived = metrics.select(
        *pw.this,
        win_rate=pw.this.wins / pw.this.total_trades * 100.0,
        profit_factor=pw.if_else(
            pw.this.losses > 0,
            pw.this.wins / pw.this.losses,
            0.0
        )
    )
    
    return metrics_with_derived


def main():
    """Example usage"""
    # Read signals from JSONL
    signals = pw.io.jsonlines.read(
        "trading_signals.jsonl",
        schema=TradingSignalSchema,
        mode="streaming",
        autocommit_duration_ms=1000,
    )
    
    # Run backtest
    backtest_results = create_backtest_pipeline(signals)
    
    # Compute metrics
    metrics = compute_backtest_metrics(backtest_results)
    
    # Output results
    pw.io.jsonlines.write(backtest_results, "backtest_results.jsonl")
    pw.io.jsonlines.write(metrics, "backtest_metrics.jsonl")
    
    pw.run()


if __name__ == "__main__":
    main()

