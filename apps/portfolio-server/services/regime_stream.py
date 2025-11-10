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
from typing import Dict, Any
import pathway as pw
from pathway.io.python import ConnectorSubject

logger = logging.getLogger(__name__)


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

    def __init__(self, input_table, symbol: str = "^NSEI", **kwargs):
        super().__init__(input_table=input_table, instance=pw.this.trigger_time, **kwargs)
        self.symbol = symbol
        logger.info(f"CandleFetcherTransformer initialized for {symbol}")
    
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
        import yfinance as yf
        
        logger.debug(f"Fetching candle for {self.symbol} at trigger {trigger_time}")
        
        # Non-blocking fetch using executor
        loop = asyncio.get_event_loop()
        
        try:
            # Fetch last 2 days of 1-minute candles to ensure we have latest data
            data = await loop.run_in_executor(
                None,
                lambda: yf.download(
                    self.symbol, 
                    period="2d", 
                    interval="1m", 
                    progress=False
                )
            )
            
            if data.empty:
                raise ValueError(f"No candle data available for {self.symbol}")
            
            # Flatten MultiIndex columns if present (yfinance sometimes returns MultiIndex)
            if hasattr(data.columns, 'levels'):  # Check for MultiIndex without importing pandas
                # Get column names - yfinance returns ('Open', ticker) for MultiIndex
                data.columns = [col[0] if isinstance(col, tuple) else col for col in data.columns]
            
            # Get the latest candle - use dict to avoid pandas operations
            latest_idx = len(data) - 1
            latest_timestamp = data.index[latest_idx]
            
            # Extract values using column access (works with both pandas and dict-like structures)
            candle_timestamp = latest_timestamp.timestamp() if hasattr(latest_timestamp, 'timestamp') else trigger_time
            
            result = {
                "timestamp": candle_timestamp,
                "open": float(data['Open'].iloc[latest_idx]),
                "high": float(data['High'].iloc[latest_idx]),
                "low": float(data['Low'].iloc[latest_idx]),
                "close": float(data['Close'].iloc[latest_idx]),
                "volume": float(data['Volume'].iloc[latest_idx]),
                "symbol": self.symbol
            }
            
            logger.info(
                f"📊 Fetched candle for {self.symbol}: "
                f"Close={result['close']:.2f}, Volume={result['volume']:.0f}"
            )
            
            return result
            
        except Exception as exc:
            logger.error(f"Error fetching candle for {self.symbol}: {exc}")
            raise ValueError(f"Failed to fetch candle: {exc}")


# Import pandas for MultiIndex handling
import pandas as pd

