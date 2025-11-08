"""
Data access helpers for fetching market data.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import yfinance as yf


def fetch_nse_data(
    ticker: str = "^NSEI",
    start_date: str = "2019-01-01",
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch historical NSE data using yfinance.

    Args:
        ticker: Market ticker symbol (default: ^NSEI).
        start_date: Start date for historical data (YYYY-MM-DD).
        end_date: Optional end date.

    Returns:
        DataFrame of OHLCV data.
    """
    data = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if data.empty:
        raise ValueError(f"No market data retrieved for {ticker}.")
    return data


__all__ = ["fetch_nse_data"]

