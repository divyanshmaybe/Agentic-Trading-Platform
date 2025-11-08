"""
Technical indicator utilities for the market regime classifier.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI).

    Args:
        prices: Series of closing prices.
        period: Lookback period for RSI calculation.

    Returns:
        RSI values as a pandas Series.
    """
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()

    rs = gain / loss
    rsi_values = 100 - (100 / (1 + rs))
    return rsi_values


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR).

    Args:
        df: DataFrame with columns `High`, `Low`, `Close`.
        period: Lookback period for ATR.

    Returns:
        ATR values as a pandas Series.
    """
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_values = true_range.rolling(window=period).mean()
    return atr_values


def bollinger_band_width(
    prices: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.Series:
    """
    Calculate Bollinger Band Width.

    Args:
        prices: Series of closing prices.
        period: Lookback period for moving average.
        num_std: Number of standard deviations for the bands.

    Returns:
        Bollinger Band width as a pandas Series.
    """
    ma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = ma + (num_std * std)
    lower = ma - (num_std * std)

    width = (upper - lower) / ma
    return width


__all__ = ["rsi", "atr", "bollinger_band_width"]

