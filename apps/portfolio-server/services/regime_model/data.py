"""
Data access helpers for fetching market data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta

try:
    from market_data import AngelOneAdapter, get_market_data_service  # type: ignore
except ImportError:  # pragma: no cover - defensive in case shared modules unavailable
    AngelOneAdapter = None  # type: ignore
    get_market_data_service = None  # type: ignore

logger = logging.getLogger(__name__)


def fetch_nse_data(
    ticker: str = "^NSEI",
    start_date: str = "2019-01-01",
    end_date: Optional[str] = None,
    *,
    provider_symbol: Optional[str] = None,
    interval: str = "ONE_DAY",
) -> pd.DataFrame:
    """
    Fetch historical NSE data prioritising the shared market data service.

    Falls back to yfinance if the configured market adapter cannot provide candles.

    Args:
        ticker: Market ticker symbol (default: ^NSEI) used for yfinance fallback.
        start_date: Start date for historical data (YYYY-MM-DD).
        end_date: Optional end date (defaults to current UTC date).
        provider_symbol: Symbol understood by the market data adapter (e.g. Angel One token name).
        interval: Adapter candle interval; defaults to ONE_DAY for daily bars.

    Returns:
        DataFrame of OHLCV data indexed by timestamp.
    """

    data = _fetch_via_market_service(
        provider_symbol=provider_symbol or ticker,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )

    if data is not None and not data.empty:
        logger.info(
            "Fetched %s candles via market data service for %s",
            len(data),
            provider_symbol or ticker,
        )
        return data

    logger.info("Falling back to yfinance for ticker %s", ticker)
    fallback = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if fallback.empty:
        raise ValueError(f"No market data retrieved for {ticker}.")
    return fallback


def _fetch_via_market_service(
    *,
    provider_symbol: str,
    start_date: str,
    end_date: Optional[str],
    interval: str = "ONE_DAY",
) -> Optional[pd.DataFrame]:
    """Best-effort retrieval using the shared market data service adapter."""

    if get_market_data_service is None:
        return None

    try:
        service = get_market_data_service()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Market data service unavailable (%s); falling back to yfinance", exc)
        return None

    adapter = getattr(service, "adapter", None)
    if not adapter or not hasattr(adapter, "get_historical_candles"):
        logger.debug("Active market adapter does not support historical candles")
        return None

    if AngelOneAdapter is not None and isinstance(adapter, AngelOneAdapter):
        return _fetch_with_angelone(
            adapter=adapter,
            symbol=provider_symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

    logger.debug(
        "Market adapter %s does not implement get_historical_candles; using fallback",
        getattr(adapter, "name", "unknown"),
    )
    return None


def _fetch_with_angelone(
    *,
    adapter: "AngelOneAdapter",
    symbol: str,
    start_date: str,
    end_date: Optional[str],
    interval: str,
) -> Optional[pd.DataFrame]:
    """Fetch historical candles from Angel One and convert to a pandas DataFrame."""

    normalized_symbol = adapter.normalize_symbol(symbol)

    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        logger.warning("Invalid start_date %s provided to fetch_nse_data", start_date)
        return None

    if end_date:
        try:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            logger.warning("Invalid end_date %s provided to fetch_nse_data", end_date)
            return None
    else:
        end_dt = datetime.utcnow()

    if start_dt >= end_dt:
        logger.warning("start_date %s must be earlier than end_date %s", start_dt, end_dt)
        return None

    cursor = start_dt
    candles: list[dict] = []
    # Angel One API performs best with <= 6 month windows for daily candles.
    step = relativedelta(months=6)

    while cursor < end_dt:
        window_end = min(cursor + step, end_dt)
        fromdate = cursor.strftime("%Y-%m-%d 09:15")
        todate = window_end.strftime("%Y-%m-%d 15:30")

        logger.debug(
            "Fetching candles for %s via Angel One [%s -> %s]",
            normalized_symbol,
            fromdate,
            todate,
        )

        chunk = adapter.get_historical_candles(
            symbol=normalized_symbol,
            interval=interval,
            fromdate=fromdate,
            todate=todate,
            exchange="NSE",
        )

        if chunk:
            candles.extend(chunk)
        else:
            logger.debug("No candles returned for window %s -> %s", fromdate, todate)

        cursor = window_end

    if not candles:
        logger.warning("Angel One returned no candles for %s; will fallback", normalized_symbol)
        return None

    frame = pd.DataFrame(candles)
    if frame.empty:
        return None

    frame.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        },
        inplace=True,
    )

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame.dropna(subset=["timestamp"], inplace=True)
    frame.set_index("timestamp", inplace=True)
    frame.sort_index(inplace=True)

    numeric_columns = ["Open", "High", "Low", "Close", "Volume"]
    frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    frame.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)

    return frame


__all__ = ["fetch_nse_data"]

