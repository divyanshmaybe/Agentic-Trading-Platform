from __future__ import annotations

import math
import os
import sys
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

# Ensure shared utilities are importable when invoked from Celery/tasks
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

from market_data import get_market_data_service  # type: ignore


@dataclass
class BacktestConfig:
    """Configuration for NSE filings backtest."""

    initial_capital: float = 100000.0
    profit_target: float = 0.03
    stop_loss: float = 0.01
    holding_hours: float = 4.0
    lookback_minutes: int = 2
    intraday_interval: str = "ONE_MINUTE"
    market_open: Tuple[int, int] = (9, 15)
    market_close: Tuple[int, int] = (15, 30)


@dataclass
class BacktestTradeResult:
    symbol: str
    filing_type: str
    filing_time: datetime
    signal: int
    confidence: float
    pnl: float
    pnl_amount: float
    exit_time: Optional[datetime]
    exit_reason: str
    capital_after: float
    metadata: Mapping[str, object]


@dataclass
class BacktestSummary:
    total_trades: int
    wins: int
    losses: int
    holds: int
    final_capital: float
    total_return_pct: float
    win_rate_pct: float
    max_drawdown_pct: float


def _next_trading_start(
    current: datetime,
    market_open: Tuple[int, int],
) -> datetime:
    result = current.replace(
        hour=market_open[0],
        minute=market_open[1],
        second=0,
        microsecond=0,
    )
    if current.time() >= datetime.min.replace(hour=market_open[0], minute=market_open[1]).time():
        result += timedelta(days=1)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def align_to_session(
    ts: datetime,
    market_open: Tuple[int, int],
    market_close: Tuple[int, int],
) -> datetime:
    session_open = ts.replace(
        hour=market_open[0], minute=market_open[1], second=0, microsecond=0
    )
    session_close = ts.replace(
        hour=market_close[0], minute=market_close[1], second=0, microsecond=0
    )

    if ts.weekday() >= 5:
        return _next_trading_start(ts, market_open)
    if ts < session_open:
        return session_open
    if ts > session_close:
        return _next_trading_start(ts, market_open)
    return ts


def resolve_intraday_window(
    filing_dt: datetime,
    holding_hours: float,
    market_open: Tuple[int, int],
    market_close: Tuple[int, int],
    lookback_minutes: int = 2,
) -> Tuple[datetime, datetime]:
    entry_time = align_to_session(filing_dt, market_open, market_close)
    start_time = entry_time - timedelta(minutes=lookback_minutes)
    session_open = entry_time.replace(
        hour=market_open[0], minute=market_open[1], second=0, microsecond=0
    )
    if start_time < session_open:
        start_time = session_open
    end_time = entry_time + timedelta(hours=holding_hours)
    session_close = entry_time.replace(
        hour=market_close[0], minute=market_close[1], second=0, microsecond=0
    )
    if end_time > session_close:
        end_time = session_close
    return start_time, end_time


def fetch_intraday_candles(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = "ONE_MINUTE",
) -> pd.DataFrame:
    """
    Fetch intraday candles strictly from the central market data service.
    """
    service = get_market_data_service()
    adapter = getattr(service, "adapter", None)

    if not adapter or not hasattr(adapter, "get_historical_candles"):
        raise RuntimeError("Active market data adapter must support historical candles.")

    normalized_symbol = adapter.normalize_symbol(symbol)
    candles = adapter.get_historical_candles(
        symbol=normalized_symbol,
        interval=interval,
        fromdate=start.strftime("%Y-%m-%d %H:%M"),
        todate=end.strftime("%Y-%m-%d %H:%M"),
        exchange="NSE",
    )
    if not candles:
        logger = logging.getLogger(__name__)
        logger.warning(
            "No intraday candles returned for %s between %s and %s",
            normalized_symbol,
            start,
            end,
        )
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def simulate_trade(
    candles: pd.DataFrame,
    signal: int,
    entry_time: datetime,
    config: BacktestConfig,
    entry_price_override: Optional[float] = None,
) -> Tuple[float, Optional[datetime], str]:
    """Simulate trade outcome with profit target and stop loss."""
    if signal == 0 or candles.empty:
        return math.nan, None, "No Trade"

    df = candles[candles["timestamp"] >= entry_time].copy()
    if df.empty:
        return math.nan, None, "no_data"

    entry_price = entry_price_override if entry_price_override else df.iloc[0]["open"]
    if signal == 1:
        target = entry_price * (1 + config.profit_target)
        stop = entry_price * (1 - config.stop_loss)
    else:
        target = entry_price * (1 - config.profit_target)
        stop = entry_price * (1 + config.stop_loss)

    for _, row in df.iterrows():
        high = row["high"]
        low = row["low"]
        if signal == 1:
            if high >= target:
                return (target - entry_price) / entry_price, row["timestamp"], "Target Hit"
            if low <= stop:
                return (stop - entry_price) / entry_price, row["timestamp"], "Stop Loss"
        else:
            if low <= target:
                return (entry_price - target) / entry_price, row["timestamp"], "Target Hit"
            if high >= stop:
                return (entry_price - stop) / entry_price, row["timestamp"], "Stop Loss"

    exit_price = df.iloc[-1]["close"]
    if signal == 1:
        pnl = (exit_price - entry_price) / entry_price
    else:
        pnl = (entry_price - exit_price) / entry_price
    return pnl, df.iloc[-1]["timestamp"], "Time Exit"


def run_trade_backtest(
    row: Mapping[str, object],
    *,
    capital: float,
    config: BacktestConfig,
) -> Tuple[BacktestTradeResult, float]:
    """Run backtest for a single filing row."""
    symbol = str(row.get("symbol", ""))
    filing_type = str(row.get("desc", ""))
    filing_time_raw = row.get("filing_time") or row.get("sort_date") or row.get("time")
    confidence = float(row.get("confidence", 0.5) or 0.5)
    signal = int(row.get("signal", 0))

    try:
        filing_time = (
            filing_time_raw
            if isinstance(filing_time_raw, datetime)
            else datetime.strptime(str(filing_time_raw), "%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        filing_time = datetime.utcnow()

    entry_time = align_to_session(filing_time, config.market_open, config.market_close)
    start_time, end_time = resolve_intraday_window(
        filing_time,
        holding_hours=config.holding_hours,
        market_open=config.market_open,
        market_close=config.market_close,
        lookback_minutes=config.lookback_minutes,
    )

    candles = fetch_intraday_candles(
        symbol,
        start=start_time,
        end=end_time,
        interval=config.intraday_interval,
    )

    pnl, exit_time, exit_reason = simulate_trade(
        candles,
        signal,
        entry_time,
        config,
    )

    allocation = capital * max(0.0, min(1.0, confidence))
    pnl_amount = 0.0 if math.isnan(pnl) else allocation * pnl
    capital_after = capital + pnl_amount

    result = BacktestTradeResult(
        symbol=symbol,
        filing_type=filing_type,
        filing_time=filing_time,
        signal=signal,
        confidence=confidence,
        pnl=0.0 if math.isnan(pnl) else pnl,
        pnl_amount=pnl_amount,
        exit_time=exit_time,
        exit_reason=exit_reason,
        capital_after=capital_after,
        metadata={
            "candles_available": not candles.empty,
            "rows": len(candles.index),
        },
    )
    return result, capital_after


def compute_summary(results: Sequence[BacktestTradeResult], initial_capital: float) -> BacktestSummary:
    total_trades = len(results)
    wins = sum(1 for r in results if r.pnl_amount > 0)
    losses = sum(1 for r in results if r.pnl_amount < 0)
    holds = sum(1 for r in results if math.isclose(r.pnl_amount, 0.0, abs_tol=1e-9))

    final_capital = results[-1].capital_after if results else initial_capital
    total_return_pct = (
        ((final_capital - initial_capital) / initial_capital) * 100 if initial_capital else 0.0
    )
    win_rate_pct = (wins / max(1, wins + losses)) * 100

    running_capital = initial_capital
    peak = initial_capital
    max_drawdown_pct = 0.0
    for trade in results:
        running_capital = trade.capital_after
        if running_capital > peak:
            peak = running_capital
        drawdown = (running_capital - peak) / peak if peak else 0.0
        max_drawdown_pct = min(max_drawdown_pct, drawdown * 100)

    return BacktestSummary(
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        holds=holds,
        final_capital=final_capital,
        total_return_pct=total_return_pct,
        win_rate_pct=win_rate_pct,
        max_drawdown_pct=max_drawdown_pct,
    )


def run_backtest(
    filings: Iterable[Mapping[str, object]],
    config: Optional[BacktestConfig] = None,
) -> Tuple[List[BacktestTradeResult], BacktestSummary]:
    """Run sequential backtest over a collection of filings/signals."""
    cfg = config or BacktestConfig()
    capital = cfg.initial_capital
    results: List[BacktestTradeResult] = []

    for row in filings:
        trade_result, capital = run_trade_backtest(row, capital=capital, config=cfg)
        results.append(trade_result)

    summary = compute_summary(results, cfg.initial_capital)
    return results, summary


def serialise_results(results: Sequence[BacktestTradeResult]) -> List[Mapping[str, object]]:
    return [
        {
            **asdict(result),
            "filing_time": result.filing_time.isoformat(),
            "exit_time": result.exit_time.isoformat() if result.exit_time else None,
        }
        for result in results
    ]


__all__ = [
    "BacktestConfig",
    "BacktestTradeResult",
    "BacktestSummary",
    "align_to_session",
    "resolve_intraday_window",
    "run_backtest",
    "serialise_results",
]

