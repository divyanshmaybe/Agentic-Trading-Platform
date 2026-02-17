"""
Regime Feature Computation and Prediction
Using Pathway's native streaming operations for feature computation
"""

import os
os.environ["PATHWAY_DISABLE_PROGRESS"] = "1"

import asyncio
import json
import logging
from typing import Dict, List, Any
from collections import deque
import numpy as np
import pandas as pd
import pathway as pw

from services.regime_stream import RegimeFeatureSchema, RegimePredictionSchema

logger = logging.getLogger(__name__)


# ==================== Feature Computation Functions ====================

def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """Calculate Relative Strength Index"""
    try:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        if loss.iloc[-1] == 0:
            return 100.0
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        value = rsi.iloc[-1]
        
        return float(value) if pd.notna(value) else 50.0
    except Exception:
        return 50.0


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate Average True Range"""
    try:
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 0.0
    except Exception:
        return 0.0


def calculate_bb_width(prices: pd.Series, period: int = 20, num_std: int = 2) -> float:
    """Calculate Bollinger Band Width"""
    try:
        ma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper = ma + (num_std * std)
        lower = ma - (num_std * std)
        bb_width = (upper - lower) / ma
        
        return float(bb_width.iloc[-1]) if pd.notna(bb_width.iloc[-1]) else 0.0
    except Exception:
        return 0.0


def calculate_macd(prices: pd.Series) -> float:
    """Calculate MACD"""
    try:
        ema_12 = prices.ewm(span=12, adjust=False).mean()
        ema_26 = prices.ewm(span=26, adjust=False).mean()
        macd = (ema_12 - ema_26) / prices
        
        return float(macd.iloc[-1]) if pd.notna(macd.iloc[-1]) else 0.0
    except Exception:
        return 0.0


async def compute_all_features(candles: List[Dict]) -> Dict[str, float]:
    """
    Compute all technical indicators asynchronously.
    This function can be cached with UDF_CACHING for performance.
    
    Args:
        candles: List of candle dictionaries
        
    Returns:
        Dictionary of computed features
    """
    try:
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        df['Close'] = df['close']
        df['High'] = df['high']
        df['Low'] = df['low']
        df['Volume'] = df['volume']
        df['Open'] = df['open']
        
        # Calculate returns
        returns = df['Close'].pct_change()
        df['returns'] = returns
        
        # Feature 1 & 2: Returns
        current_return = float(returns.iloc[-1]) if pd.notna(returns.iloc[-1]) else 0.0
        log_return = float(np.log(df['Close'].iloc[-1] / df['Close'].iloc[-2])) if len(df) >= 2 else 0.0
        
        # Feature 3 & 4: Short and Long-term Volatility
        vol_5d = float(returns.rolling(window=5).std().iloc[-1]) if len(df) >= 5 else 0.0
        vol_20d = float(returns.rolling(window=20).std().iloc[-1]) if len(df) >= 20 else 0.0
        
        # Feature 5: Volatility Ratio
        vol_ratio = vol_5d / vol_20d if vol_20d > 0 else 1.0
        
        # Feature 6: Returns Momentum
        returns_ma5 = float(returns.rolling(window=5).mean().iloc[-1]) if len(df) >= 5 else 0.0
        returns_ma20 = float(returns.rolling(window=20).mean().iloc[-1]) if len(df) >= 20 else 0.0
        
        # Feature 7: Trend Strength
        if len(df) >= 200:
            ma_50 = df['Close'].rolling(window=50).mean()
            ma_200 = df['Close'].rolling(window=200).mean()
            trend_strength = float((ma_50.iloc[-1] - ma_200.iloc[-1]) / ma_200.iloc[-1])
        else:
            trend_strength = 0.0
        
        # Feature 8: RSI
        rsi = calculate_rsi(df['Close'], period=14)
        
        # Feature 9 & 10: ATR
        atr = calculate_atr(df, period=14)
        atr_normalized = atr / df['Close'].iloc[-1] if df['Close'].iloc[-1] > 0 else 0.0
        
        # Feature 11: Bollinger Band Width
        bb_width = calculate_bb_width(df['Close'], period=20)
        
        # Feature 12 & 13: Volume indicators
        volume_ma20 = df['Volume'].rolling(window=20).mean()
        volume_ratio = float(df['Volume'].iloc[-1] / volume_ma20.iloc[-1]) if len(df) >= 20 and volume_ma20.iloc[-1] > 0 else 1.0
        
        volume_ma5 = df['Volume'].rolling(window=5).mean()
        volume_trend = float(volume_ma5.iloc[-1] / volume_ma20.iloc[-1]) if len(df) >= 20 and volume_ma20.iloc[-1] > 0 else 1.0
        
        # Feature 14: Price Range
        price_range = float((df['High'].iloc[-1] - df['Low'].iloc[-1]) / df['Close'].iloc[-1]) if df['Close'].iloc[-1] > 0 else 0.0
        
        # Feature 15: Up/Down days ratio
        if len(df) >= 20:
            up_days = (df['returns'] > 0).rolling(window=20).sum()
            up_down_ratio = float(up_days.iloc[-1] / 20)
        else:
            up_down_ratio = 0.5
        
        # Feature 16: MACD
        macd = calculate_macd(df['Close'])
        
        # Feature 17: Rate of Change
        if len(df) >= 11:
            roc = float((df['Close'].iloc[-1] - df['Close'].iloc[-11]) / df['Close'].iloc[-11])
        else:
            roc = 0.0
        
        features = {
            'returns': current_return,
            'log_returns': log_return,
            'volatility_5d': vol_5d,
            'volatility_20d': vol_20d,
            'vol_ratio': vol_ratio,
            'returns_ma5': returns_ma5,
            'returns_ma20': returns_ma20,
            'trend_strength': trend_strength,
            'rsi': rsi,
            'atr': atr,
            'atr_normalized': atr_normalized,
            'bb_width': bb_width,
            'volume_ratio': volume_ratio,
            'volume_trend': volume_trend,
            'price_range': price_range,
            'up_down_ratio': up_down_ratio,
            'macd': macd,
            'roc': roc,
        }
        
        return features
        
    except Exception as exc:
        logger.error(f"Error computing features: {exc}", exc_info=True)
        # Return zero features on error
        return {
            'returns': 0.0, 'log_returns': 0.0, 'volatility_5d': 0.0, 'volatility_20d': 0.01,
            'vol_ratio': 1.0, 'returns_ma5': 0.0, 'returns_ma20': 0.0, 'trend_strength': 0.0,
            'rsi': 50.0, 'atr': 0.0, 'atr_normalized': 0.0, 'bb_width': 0.0,
            'volume_ratio': 1.0, 'volume_trend': 1.0, 'price_range': 0.0,
            'up_down_ratio': 0.5, 'macd': 0.0, 'roc': 0.0,
        }


# ==================== AsyncTransformer for Feature Computation ====================

class FeatureComputeTransformer(pw.AsyncTransformer, output_schema=RegimeFeatureSchema):
    """
    Async compute 15+ technical indicators using stateful feature computer.
    Maintains rolling window buffer using numpy operations (more efficient than pandas).
    """

    def __init__(self, input_table, window_size: int = 250, **kwargs):
        super().__init__(input_table=input_table, instance=pw.this.timestamp, **kwargs)
        self.window_size = window_size
        self.candle_buffer: deque[Dict[str, float]] = deque(maxlen=window_size)
        logger.info(f"FeatureComputeTransformer initialized with window_size={window_size}")
    
    async def invoke(self, timestamp: float, open: float, high: float, 
                    low: float, close: float, volume: float, symbol: str) -> Dict:
        """
        Compute features from candle window asynchronously.
        
        Args:
            timestamp: Candle timestamp
            open, high, low, close, volume: OHLCV data
            symbol: Stock symbol
            
        Returns:
            Dictionary with timestamp, symbol, and all computed features
            
        Raises:
            ValueError: If insufficient data for feature computation
        """
        # Add to buffer
        candle = {
            'timestamp': timestamp,
            'open': open,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        }
        self.candle_buffer.append(candle)
        
        logger.debug(f"Buffer size: {len(self.candle_buffer)}/{self.window_size}")
        
        # Need minimum data for features (at least 200 candles for all indicators)
        if len(self.candle_buffer) < 200:
            raise ValueError(f"Insufficient data for feature computation: {len(self.candle_buffer)}/200")
        
        # Async compute features (non-blocking)
        features = await compute_all_features(list(self.candle_buffer))
        
        # Add metadata
        features['timestamp'] = timestamp
        features['symbol'] = symbol
        
        logger.info(
            f"✨ Computed features: RSI={features['rsi']:.2f}, "
            f"Vol20d={features['volatility_20d']:.4f}, "
            f"Returns={features['returns']:.4f}"
        )
        
        return features


# ==================== AsyncTransformer for Regime Prediction ====================

class RegimePredictorTransformer(pw.AsyncTransformer, output_schema=RegimePredictionSchema):
    """
    Async HMM inference for regime classification.
    Predicts market regime from computed features.
    """

    def __init__(self, input_table, classifier, **kwargs):
        super().__init__(input_table=input_table, instance=pw.this.timestamp, **kwargs)
        self.classifier = classifier
        self.scaler = classifier.scaler
        self.model = classifier.model
        self.regime_names = classifier.regime_names
        self.feature_names = classifier.feature_names
        logger.info(f"RegimePredictorTransformer initialized with {len(self.regime_names)} regimes")
    
    async def invoke(self, timestamp: float, symbol: str, **features) -> Dict:
        """
        Predict regime from features asynchronously.
        
        Args:
            timestamp: Feature timestamp
            symbol: Stock symbol
            **features: All computed features
            
        Returns:
            Dictionary with timestamp, symbol, regime, state_id, and features_json
        """
        try:
            # Extract features in correct order
            feature_array = [[features.get(k, 0.0) for k in self.feature_names]]
            
            # Scale features
            scaled = self.scaler.transform(feature_array)
            
            # Async model inference (non-blocking)
            loop = asyncio.get_event_loop()
            state_id = await loop.run_in_executor(
                None,
                lambda: int(self.model.predict(scaled)[0])
            )
            
            # Get regime name
            regime = self.regime_names[state_id]
            
            # Prepare features for JSON serialization
            features_dict = {k: float(features.get(k, 0.0)) for k in self.feature_names}
            
            logger.info(f"🎯 Predicted regime: {regime} (state {state_id})")
            
            return {
                "timestamp": timestamp,
                "symbol": symbol,
                "regime": regime,
                "state_id": state_id,
                "features_json": json.dumps(features_dict)
            }
            
        except Exception as exc:
            logger.error(f"Error predicting regime: {exc}", exc_info=True)
            raise ValueError(f"Regime prediction failed: {exc}")

