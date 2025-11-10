"""
Regime Classification Stream Components
Pathway schemas, ConnectorSubject, and AsyncTransformer for candle streaming
"""

import os
os.environ["PATHWAY_DISABLE_PROGRESS"] = "1"
os.environ.setdefault("PATHWAY_PROGRESS_DISABLE", "1")
os.environ.setdefault("PW_DISABLE_PROGRESS", "1")
os.environ["PATHWAY_LOG_LEVEL"] = "warning"

import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import pathway as pw
from pathway.io.python import ConnectorSubject

logger = logging.getLogger(__name__)

try:
    from market_data import AngelOneAdapter, get_market_data_service  # type: ignore
except ImportError:  # pragma: no cover - defensive
    AngelOneAdapter = None  # type: ignore
    get_market_data_service = None  # type: ignore


# ==================== Pathway Schemas ====================

class TriggerSchema(pw.Schema):
    """Schema for triggering candle fetches"""
    trigger_time: float


class CandleSchema(pw.Schema):
    """Schema for OHLCV candle data"""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str


class RegimeFeatureSchema(pw.Schema):
    """Schema for computed technical features"""
    timestamp: float
    symbol: str
    # Basic returns
    returns: float
    log_returns: float
    # Volatility indicators
    volatility_5d: float
    volatility_20d: float
    vol_ratio: float
    # Momentum indicators
    returns_ma5: float
    returns_ma20: float
    # Trend indicators
    trend_strength: float
    rsi: float
    # Volatility measures
    atr: float
    atr_normalized: float
    bb_width: float
    # Volume indicators
    volume_ratio: float
    volume_trend: float
    # Price range
    price_range: float
    # Up/down ratio
    up_down_ratio: float
    # MACD
    macd: float
    # Rate of change
    roc: float


class RegimePredictionSchema(pw.Schema):
    """Schema for regime predictions"""
    timestamp: float
    symbol: str
    regime: str
    state_id: int
    features_json: str


# ==================== ConnectorSubject for Candle Streaming ====================

class CandleStreamSubject(ConnectorSubject):
    """
    Pathway connector subject that emits periodic triggers for candle fetching.
    This is a lightweight trigger mechanism - actual fetching happens in AsyncTransformer.
    """
    
    def __init__(self, interval_seconds: int = 60) -> None:
        super().__init__()
        self.interval_seconds = interval_seconds
        logger.info(f"CandleStreamSubject initialized with {interval_seconds}s interval")
    
    def run(self) -> None:
        """Emit periodic triggers for candle fetching"""
        logger.info("CandleStreamSubject started")
        
        while True:
            try:
                current_time = time.time()
                
                # Emit trigger
                self.next(trigger_time=current_time)
                
                logger.debug(f"Emitted candle fetch trigger at {current_time}")
                
                # Wait for next interval
                time.sleep(self.interval_seconds)
                
            except Exception as exc:
                logger.error(f"Error in CandleStreamSubject: {exc}", exc_info=True)
                time.sleep(self.interval_seconds)


# ==================== AsyncTransformer for Candle Fetching ====================

class CandleFetcherTransformer(pw.AsyncTransformer, output_schema=CandleSchema):
    """
    Async fetch candles from yfinance or market data API.
    Processes each trigger asynchronously and non-blocking.
    """

    def __init__(
        self,
        input_table,
        symbol: str = "^NSEI",
        *,
        provider_symbol: Optional[str] = None,
        interval: str = "ONE_MINUTE",
        **kwargs,
    ):
        super().__init__(input_table=input_table, instance=pw.this.trigger_time, **kwargs)
        self.symbol = symbol
        self.provider_symbol = provider_symbol or symbol
        self.interval = interval
        logger.info(
            "CandleFetcherTransformer initialized for %s (provider=%s, interval=%s)",
            symbol,
            self.provider_symbol,
            interval,
        )
    
    async def invoke(self, trigger_time: float) -> Dict:
        """
        Fetch latest candle asynchronously.
        
        Args:
            trigger_time: Unix timestamp trigger
            
        Returns:
            Dictionary with candle data (timestamp, open, high, low, close, volume, symbol)
            
        Raises:
            ValueError: If no candle data is available
        """
        logger.debug("Fetching candle for %s at trigger %s", self.symbol, trigger_time)

        candle = await self._try_market_service(trigger_time)
        if candle:
            return candle

        # Fallback to yfinance for symbols not supported by the market adapter (e.g. indices)
        return await self._fetch_via_yfinance(trigger_time)

    async def _try_market_service(self, trigger_time: float) -> Optional[Dict[str, Any]]:
        if get_market_data_service is None:
            return None

        try:
            service = get_market_data_service()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Market data service unavailable for regime pipeline: %s", exc)
            return None

        adapter = getattr(service, "adapter", None)
        if adapter is None or not hasattr(adapter, "get_historical_candles"):
            return None

        if AngelOneAdapter is not None and isinstance(adapter, AngelOneAdapter):
            now = datetime.utcnow()
            start = now - timedelta(days=2)
            fromdate = start.strftime("%Y-%m-%d 09:15")
            todate = now.strftime("%Y-%m-%d %H:%M")

            normalized = adapter.normalize_symbol(self.provider_symbol)
            candles = adapter.get_historical_candles(
                symbol=normalized,
                interval=self.interval,
                fromdate=fromdate,
                todate=todate,
                exchange="NSE",
            )

            if not candles:
                return None

            latest = sorted(candles, key=lambda item: item.get("timestamp", ""))[-1]
            candle_timestamp = self._parse_timestamp(latest.get("timestamp"), default=trigger_time)

            result = {
                "timestamp": candle_timestamp,
                "open": float(latest.get("open", 0.0)),
                "high": float(latest.get("high", 0.0)),
                "low": float(latest.get("low", 0.0)),
                "close": float(latest.get("close", 0.0)),
                "volume": float(latest.get("volume", 0.0)),
                "symbol": self.symbol,
            }

            logger.debug(
                "Fetched candle for %s via market service: close=%s volume=%s",
                self.symbol,
                result["close"],
                result["volume"],
            )

            return result

        return None

    async def _fetch_via_yfinance(self, trigger_time: float) -> Dict[str, Any]:
        import yfinance as yf

        loop = asyncio.get_event_loop()

        try:
            data = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    self.symbol,
                    period="2d",
                    interval="1m",
                    progress=False,
                    show_errors=False,
                ),
            )
        except Exception as exc:  # pragma: no cover - network failures
            logger.error("YFinance download failed for %s: %s", self.symbol, exc)
            raise ValueError(f"Failed to fetch candle: {exc}") from exc

        if data.empty:
            raise ValueError(f"No candle data available for {self.symbol}")

        if hasattr(data.columns, "levels"):
            data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]

        latest_idx = len(data) - 1
        latest_timestamp = data.index[latest_idx]
        candle_timestamp = latest_timestamp.timestamp() if hasattr(latest_timestamp, "timestamp") else trigger_time

        result = {
            "timestamp": candle_timestamp,
            "open": float(data["Open"].iloc[latest_idx]),
            "high": float(data["High"].iloc[latest_idx]),
            "low": float(data["Low"].iloc[latest_idx]),
            "close": float(data["Close"].iloc[latest_idx]),
            "volume": float(data["Volume"].iloc[latest_idx]),
            "symbol": self.symbol,
        }

        logger.debug(
            "Fetched candle for %s via yfinance fallback: close=%s volume=%s",
            self.symbol,
            result["close"],
            result["volume"],
        )

        return result

    @staticmethod
    def _parse_timestamp(value: Any, *, default: float) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    return datetime.strptime(value, fmt).timestamp()
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(value).timestamp()
            except ValueError:
                pass
        return default


# Import pandas for MultiIndex handling
import pandas as pd

