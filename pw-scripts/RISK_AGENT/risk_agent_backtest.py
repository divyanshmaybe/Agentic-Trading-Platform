# -*- coding: utf-8 -*-
"""
Risk Agent Backtesting Module - Pathway Implementation

This module provides backtesting functionality for risk alerts,
simulating portfolio performance if actions were taken based on alerts.
"""

import pathway as pw
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional


# Configuration
HOLDING_HOURS = 24  # Track for 24 hours after alert
INTERVAL = "1h"  # Hourly data for backtest
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


class RiskAlertSchema(pw.Schema):
    """Schema for risk alerts"""
    ticker: str
    name: str
    alert: str
    severity: str
    fall_percent: float
    current_price: float
    current_change: float


class BacktestResultSchema(pw.Schema):
    """Schema for backtest results"""
    ticker: str
    alert_time: str
    severity: str
    alert_price: float
    exit_price: float
    exit_time: str
    pnl_percent: float
    exit_reason: str


@pw.udf
def simulate_risk_action(
    ticker: str,
    alert_price: float,
    alert_time_str: str,
    severity: str
) -> tuple[float, str, str]:
    """
    Simulate action taken based on risk alert
    Assumes: SELL on alert, then check if we should have bought back
    
    Returns: (pnl_percent, exit_time_str, exit_reason)
    """
    try:
        import yfinance as yf
        
        alert_time = pd.to_datetime(alert_time_str)
        end_time = alert_time + timedelta(hours=HOLDING_HOURS)
        
        # Get ticker symbol (remove .NS if present for yfinance)
        ticker_symbol = ticker.replace(".NS", "")
        yf_ticker = f"{ticker_symbol}.NS"
        
        # Fetch historical data
        data = yf.download(
            yf_ticker,
            start=alert_time - timedelta(hours=1),
            end=end_time,
            interval=INTERVAL,
            progress=False
        )
        
        if data.empty:
            return np.nan, alert_time_str, "no_data"
        
        # Filter data after alert time
        valid_data = data.loc[data.index >= alert_time]
        if valid_data.empty:
            return np.nan, alert_time_str, "no_data"
        
        # Simulate: SELL at alert price, then track if price recovered
        # If price goes down further, we avoided loss (positive PnL)
        # If price recovers, we missed gains (negative PnL)
        
        min_price = valid_data["Close"].min()
        max_price = valid_data["Close"].max()
        final_price = valid_data.iloc[-1]["Close"]
        final_time = valid_data.index[-1]
        
        # Calculate PnL based on severity
        # For "worst" severity: assume we sold, calculate avoided loss
        # For "worse" severity: moderate action
        # For "bad" severity: minimal action
        
        if severity == "worst":
            # Assume we sold immediately, calculate avoided loss
            # If price dropped further, we avoided that loss (positive PnL)
            if min_price < alert_price:
                avoided_loss = (alert_price - min_price) / alert_price
                pnl = avoided_loss  # Positive PnL = avoided loss
                exit_reason = "avoided_loss"
                exit_price = min_price
                exit_time = valid_data[valid_data["Close"] == min_price].index[0]
            else:
                # Price recovered, we missed gains
                missed_gain = (final_price - alert_price) / alert_price
                pnl = -missed_gain  # Negative PnL = missed gain
                exit_reason = "missed_gain"
                exit_price = final_price
                exit_time = final_time
        elif severity == "worse":
            # Moderate action - track recovery
            if final_price < alert_price * 0.95:  # Still down 5%+
                avoided_loss = (alert_price - final_price) / alert_price
                pnl = avoided_loss * 0.5  # Partial credit
                exit_reason = "partial_avoidance"
                exit_price = final_price
                exit_time = final_time
            else:
                # Recovered
                missed_gain = (final_price - alert_price) / alert_price
                pnl = -missed_gain * 0.3  # Partial penalty
                exit_reason = "partial_recovery"
                exit_price = final_price
                exit_time = final_time
        else:  # "bad"
            # Minimal action - just monitor
            price_change = (final_price - alert_price) / alert_price
            pnl = price_change * -0.1  # Small penalty if we overreacted
            exit_reason = "monitored"
            exit_price = final_price
            exit_time = final_time
        
        return (
            pnl,
            exit_time.strftime("%Y-%m-%d %H:%M:%S"),
            exit_reason
        )
        
    except Exception as e:
        return np.nan, alert_time_str, f"error: {str(e)}"


def create_risk_backtest_pipeline(alerts_table: pw.Table) -> pw.Table:
    """
    Create backtest pipeline from risk alerts
    
    Args:
        alerts_table: Table with risk alerts (ticker, alert, severity, current_price, etc.)
    
    Returns:
        Table with backtest results
    """
    
    # Get current timestamp for alert time
    alerts_with_time = alerts_table.select(
        *pw.this,
        alert_time=pw.apply(lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"), pw.this.ticker)
    )
    
    # Simulate actions
    backtest_results = alerts_with_time.select(
        ticker=pw.this.ticker,
        alert_time=pw.this.alert_time,
        severity=pw.this.severity,
        alert_price=pw.this.current_price,
        trade_result=pw.apply(
            simulate_risk_action,
            pw.this.ticker,
            pw.this.current_price,
            pw.this.alert_time,
            pw.this.severity
        )
    ).select(
        ticker=pw.this.ticker,
        alert_time=pw.this.alert_time,
        severity=pw.this.severity,
        alert_price=pw.this.alert_price,
        pnl_percent=pw.this.trade_result[0],
        exit_time=pw.this.trade_result[1],
        exit_reason=pw.this.trade_result[2]
    ).select(
        ticker=pw.this.ticker,
        alert_time=pw.this.alert_time,
        severity=pw.this.severity,
        alert_price=pw.this.alert_price,
        exit_price=pw.this.alert_price * (1 + pw.this.pnl_percent),  # Approximate
        exit_time=pw.this.exit_time,
        pnl_percent=pw.this.pnl_percent,
        exit_reason=pw.this.exit_reason
    )
    
    return backtest_results


def compute_risk_metrics(backtest_results: pw.Table) -> pw.Table:
    """
    Compute backtest metrics from results
    
    Returns:
        Table with aggregated metrics
    """
    # Aggregate metrics
    metrics = backtest_results.filter(pw.this.pnl_percent.is_not_none()).groupby().reduce(
        total_alerts=pw.reducers.count(),
        avoided_losses=pw.reducers.sum(pw.cast(int, pw.this.pnl_percent > 0)),
        missed_opportunities=pw.reducers.sum(pw.cast(int, pw.this.pnl_percent < 0)),
        total_pnl=pw.reducers.sum(pw.this.pnl_percent),
        avg_pnl=pw.reducers.avg(pw.this.pnl_percent),
        max_pnl=pw.reducers.max(pw.this.pnl_percent),
        min_pnl=pw.reducers.min(pw.this.pnl_percent),
    )
    
    # Calculate derived metrics
    metrics_with_derived = metrics.select(
        *pw.this,
        avoidance_rate=pw.if_else(
            pw.this.total_alerts > 0,
            pw.this.avoided_losses / pw.this.total_alerts * 100.0,
            0.0
        ),
        avg_avoided_loss=pw.if_else(
            pw.this.avoided_losses > 0,
            pw.this.total_pnl / pw.this.avoided_losses,
            0.0
        )
    )
    
    return metrics_with_derived


def main():
    """Example usage"""
    # Read alerts from JSONL
    alerts = pw.io.jsonlines.read(
        "risk_alerts.jsonl",
        schema=RiskAlertSchema,
        mode="streaming",
        autocommit_duration_ms=1000,
    )
    
    # Run backtest
    backtest_results = create_risk_backtest_pipeline(alerts)
    
    # Compute metrics
    metrics = compute_risk_metrics(backtest_results)
    
    # Output results
    pw.io.jsonlines.write(backtest_results, "risk_backtest_results.jsonl")
    pw.io.jsonlines.write(metrics, "risk_backtest_metrics.jsonl")
    
    pw.run()


if __name__ == "__main__":
    main()

