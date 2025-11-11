"""
Data access helpers for fetching market data.

IMPORTANT: yfinance is ONLY used here for regime model training to avoid
Angel One rate limits. All other market data should use the shared market_data service.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
import time
from typing import List, Optional

import pandas as pd
import requests
YFINANCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


try:
    from market_data import AngelOneAdapter, get_market_data_service  # type: ignore
except ImportError:  # pragma: no cover - defensive in case shared modules unavailable
    AngelOneAdapter = None  # type: ignore
    get_market_data_service = None  # type: ignore

logger = logging.getLogger(__name__)


def fetch_nse_data(
    ticker: str,
    start_date,
    end_date: Optional[datetime] = None,
    provider_symbol: Optional[str] = None,
    interval: str = "1D",
    use_yfinance: bool = False,
) -> pd.DataFrame:
    """
    Fetch NSE market data for a given ticker and date range.

    Args:
        ticker: Stock ticker symbol (e.g., 'SBIN', 'RELIANCE', 'NIFTY 50')
        start_date: Start date for data retrieval
        end_date: End date for data retrieval
        provider_symbol: Provider-specific symbol mapping (optional)
        interval: Data interval (default: '1D')
        use_yfinance: If True, use yfinance instead of Angel One.
                     ONLY set this to True for regime model training!
                     Default: False (uses shared market_data service)

    Returns:
        DataFrame indexed by timestamp with columns: Open, High, Low, Close, Volume

    Raises:
        ValueError: If data cannot be retrieved from any source
    """
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date is None:
        end_date = datetime.utcnow()
    elif isinstance(end_date, str):
        end_date = datetime.strptime(end_date, "%Y-%m-%d")

    if use_yfinance:
        # Route to yfinance for regime training ONLY
        logger.info(
            f"Using yfinance for {ticker} (regime training mode)"
        )
        return _fetch_with_yfinance(
            symbol=ticker,
            provider_symbol=provider_symbol,
            start_date=start_date,
            end_date=end_date,
        )
    
    # Default path: use shared market_data service (Angel One)
    return _fetch_via_market_service(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        provider_symbol=provider_symbol,
        interval=interval,
    )


def _fetch_via_market_service(
    *,
    ticker: str,
    provider_symbol: Optional[str],
    start_date: datetime,
    end_date: datetime,
    interval: str = "1D",
) -> Optional[pd.DataFrame]:
    """Best-effort retrieval using the shared market data service adapter."""

    if get_market_data_service is None:
        return None

    try:
        service = get_market_data_service()
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"Market data service unavailable: {exc}"
        ) from exc

    adapter = getattr(service, "adapter", None)
    if not adapter or not hasattr(adapter, "get_historical_candles"):
        logger.debug("Active market adapter does not support historical candles")
        return None

    if AngelOneAdapter is not None and isinstance(adapter, AngelOneAdapter):
        symbol = provider_symbol or ticker
        return _fetch_with_angelone(
            adapter=adapter,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            interval=interval,
        )

    raise RuntimeError(
        f"Market adapter {getattr(adapter, 'name', 'unknown')} does not support historical candles."
    )


def _fetch_with_angelone(
    adapter: "AngelOneAdapter",
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    interval: str,
) -> pd.DataFrame:
    """
    Fetch data using the AngelOne adapter.

    Args:
        adapter: Instance of AngelOneAdapter
        symbol: Stock symbol
        start_date: Start date for data
        end_date: End date for data

    Returns:
        DataFrame indexed by timestamp with columns: Open, High, Low, Close, Volume
    """
    normalized_symbol = adapter.normalize_symbol(symbol)

    interval_map = {
        "1D": "ONE_DAY",
        "1d": "ONE_DAY",
        "D": "ONE_DAY",
        "1m": "ONE_MINUTE",
        "5m": "FIVE_MINUTE",
        "15m": "FIFTEEN_MINUTE",
        "30m": "THIRTY_MINUTE",
        "60m": "ONE_HOUR",
    }
    angel_interval = interval_map.get(interval, "ONE_DAY")

    fromdate = start_date.strftime("%Y-%m-%d 09:15")
    todate = end_date.strftime("%Y-%m-%d 15:30")

    candles = adapter.get_historical_candles(
        symbol=normalized_symbol,
        interval=angel_interval,
        fromdate=fromdate,
        todate=todate,
        exchange="NSE",
    )

    if not candles:
        logger.error(
            "Angel One returned no candles for %s between %s and %s",
            normalized_symbol,
            fromdate,
            todate,
        )
        return pd.DataFrame()

    frame = pd.DataFrame(candles)
    if frame.empty:
        return frame

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


def _fetch_with_yfinance(
    symbol: str,
    start_date: datetime,
    end_date: datetime,
    provider_symbol: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch historical data using yfinance.
    
    IMPORTANT: This function should ONLY be called during regime model training
    to avoid Angel One rate limits. Do not use yfinance elsewhere in the codebase.

    Args:
        symbol: NSE stock symbol (e.g., 'NIFTY 50', 'SBIN')
        start_date: Start date for historical data
        end_date: End date for historical data

    Returns:
        DataFrame indexed by timestamp with columns: Open, High, Low, Close, Volume
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error(
            "yfinance not installed. Install with: pip install yfinance"
        )
        raise

    try:
        tickers = _map_to_yfinance_tickers(symbol, provider_symbol)
        last_error: Optional[Exception] = None

        period1 = int(start_date.timestamp())
        period2 = int((end_date + timedelta(days=1)).timestamp())
        params = {
            "interval": "1d",
            "period1": str(period1),
            "period2": str(period2),
            "includePrePost": "false",
            "events": "div,splits",
        }

        for yf_symbol in tickers:
            attempt = 0
            backoff = 1.0

            while attempt < 4:
                try:
                    logger.info(
                        "Fetching %s (yfinance: %s) from %s to %s (attempt %s)",
                        symbol,
                        yf_symbol,
                        start_date.date(),
                        end_date.date(),
                        attempt + 1,
                    )

                    response = requests.get(
                        YAHOO_CHART_URL.format(ticker=yf_symbol),
                        params=params,
                        headers=YFINANCE_HEADERS,
                        timeout=30,
                    )

                    if response.status_code == 429:
                        logger.warning(
                            "yfinance rate limit hit for %s (%s); sleeping %.1fs",
                            symbol,
                            yf_symbol,
                            backoff,
                        )
                        time.sleep(backoff)
                        attempt += 1
                        backoff *= 2
                        continue

                    if response.status_code != 200:
                        logger.warning(
                            "yfinance returned status %s for %s (%s): %s",
                            response.status_code,
                            symbol,
                            yf_symbol,
                            response.text[:200],
                        )
                        break

                    payload = response.json()
                    chart = payload.get("chart", {})
                    result = (chart.get("result") or [None])[0]
                    if not result:
                        logger.warning(
                            "yfinance chart response missing result for %s (%s)",
                            symbol,
                            yf_symbol,
                        )
                        break

                    timestamps = result.get("timestamp") or []
                    if not timestamps:
                        logger.warning(
                            "yfinance returned no timestamps for %s (%s)",
                            symbol,
                            yf_symbol,
                        )
                        break

                    quote_entries = (
                        result.get("indicators", {}).get("quote") or [{}]
                    )[0]
                    if not quote_entries:
                        logger.warning(
                            "yfinance returned no quote data for %s (%s)",
                            symbol,
                            yf_symbol,
                        )
                        break

                    frame = pd.DataFrame(
                        {
                            "Open": quote_entries.get("open"),
                            "High": quote_entries.get("high"),
                            "Low": quote_entries.get("low"),
                            "Close": quote_entries.get("close"),
                            "Volume": quote_entries.get("volume"),
                        }
                    )

                    frame.index = pd.to_datetime(timestamps, unit="s")
                    frame = frame.dropna(subset=["Open", "High", "Low", "Close"])

                    if frame.empty:
                        logger.warning(
                            "yfinance returned empty OHLC data for %s (%s)",
                            symbol,
                            yf_symbol,
                        )
                        break

                    frame.sort_index(inplace=True)

                    logger.info(
                        "Successfully fetched %s candles for %s via yfinance (%s)",
                        len(frame),
                        symbol,
                        yf_symbol,
                    )
                    return frame

                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "yfinance fetch exception for %s (%s): %s",
                        symbol,
                        yf_symbol,
                        exc,
                    )
                    attempt += 1
                    time.sleep(backoff)
                    backoff *= 2
                    continue

            # Move to next candidate ticker
            continue

        if last_error:
            raise last_error
        raise RuntimeError(
            f"yfinance returned no data for {symbol}. Tried tickers: {', '.join(tickers)}"
        )
    except Exception as e:
        logger.error(f"Failed to fetch data from yfinance for {symbol}: {e}")
        raise


def _map_to_yfinance_tickers(
    nse_symbol: str,
    provider_symbol: Optional[str] = None,
) -> List[str]:
    """
    Map NSE symbols to a prioritized list of yfinance tickers.

    The list allows fallbacks (e.g., ^CRSLDX) if the primary ticker (^NSEI) is rate limited
    or temporarily unavailable.
    """

    def _normalize(value: str) -> str:
        return value.strip().upper().replace("_", "").replace("-", "").replace(" ", "")

    index_map: dict[str, List[str]] = {
        "NIFTY50": ["^NSEI", "^CRSLDX"],
        "NIFTY 50": ["^NSEI", "^CRSLDX"],
        "NIFTY": ["^NSEI", "^CRSLDX"],
        "NSEI": ["^NSEI", "^CRSLDX"],
        "^NSEI": ["^NSEI", "^CRSLDX"],
        "NIFTY500": ["^CRSLDX"],
        "NIFTY 500": ["^CRSLDX"],
        "^CRSLDX": ["^CRSLDX"],
        "BANKNIFTY": ["^NSEBANK"],
        "NIFTYBANK": ["^NSEBANK"],
        "NIFTY BANK": ["^NSEBANK"],
        "NSEBANK": ["^NSEBANK"],
        "^NSEBANK": ["^NSEBANK"],
    }

    seen: List[str] = []
    candidates: List[Optional[str]] = [provider_symbol, nse_symbol]

    for candidate in candidates:
        if not candidate:
            continue
        candidate_clean = candidate.strip()
        if candidate_clean.startswith("^"):
            value = candidate_clean.upper()
            if value not in seen:
                seen.append(value)

    for candidate in candidates:
        if not candidate:
            continue
        normalized = _normalize(candidate)
        if normalized in index_map:
            for ticker in index_map[normalized]:
                if ticker not in seen:
                    seen.append(ticker)

    for candidate in candidates:
        if not candidate:
            continue
        normalized = _normalize(candidate)
        fallback = f"{normalized}.NS"
        if fallback not in seen:
            seen.append(fallback)

    if not seen:
        seen.append(f"{_normalize(nse_symbol)}.NS")

    return seen


__all__ = ["fetch_nse_data"]

