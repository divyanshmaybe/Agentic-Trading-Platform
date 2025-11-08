"""
Regime Feature Computation using Pathway Native Operations
Streaming technical indicators computed with Pathway's window operations
"""

import os
os.environ["PATHWAY_DISABLE_PROGRESS"] = "1"

import asyncio
import json
import logging
from typing import Dict, Any
import numpy as np
import pathway as pw

from services.regime_stream import CandleSchema, RegimeFeatureSchema, RegimePredictionSchema

logger = logging.getLogger(__name__)


# ==================== Pathway UDFs for Technical Indicators ====================

@pw.udf
def calculate_returns(close: float, prev_close: float) -> float:
    """Calculate simple returns"""
    if prev_close == 0 or prev_close is None:
        return 0.0
    return (close - prev_close) / prev_close


@pw.udf
def calculate_log_returns(close: float, prev_close: float) -> float:
    """Calculate log returns"""
    if prev_close <= 0 or close <= 0:
        return 0.0
    return float(np.log(close / prev_close))


@pw.udf
def calculate_volatility(returns_window: list) -> float:
    """Calculate volatility (standard deviation of returns)"""
    if not returns_window or len(returns_window) < 2:
        return 0.0
    try:
        return float(np.std(returns_window, ddof=1))
    except:
        return 0.0


@pw.udf
def calculate_mean(values: list) -> float:
    """Calculate mean of values"""
    if not values:
        return 0.0
    return float(np.mean(values))


@pw.udf
def calculate_rsi_from_returns(returns_window: list, period: int = 14) -> float:
    """Calculate RSI from returns window"""
    if not returns_window or len(returns_window) < period:
        return 50.0
    
    try:
        gains = [r if r > 0 else 0 for r in returns_window[-period:]]
        losses = [-r if r < 0 else 0 for r in returns_window[-period:]]
        
        avg_gain = np.mean(gains) if gains else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)
    except:
        return 50.0


@pw.udf
def calculate_atr_from_candles(high_window: list, low_window: list, close_window: list, period: int = 14) -> float:
    """Calculate ATR from candle windows"""
    if not high_window or len(high_window) < period + 1:
        return 0.0
    
    try:
        true_ranges = []
        for i in range(1, len(high_window)):
            high_low = high_window[i] - low_window[i]
            high_close = abs(high_window[i] - close_window[i-1])
            low_close = abs(low_window[i] - close_window[i-1])
            tr = max(high_low, high_close, low_close)
            true_ranges.append(tr)
        
        if not true_ranges:
            return 0.0
        
        atr = np.mean(true_ranges[-period:]) if len(true_ranges) >= period else np.mean(true_ranges)
        return float(atr)
    except:
        return 0.0


@pw.udf
def calculate_bb_width(close_window: list, period: int = 20, num_std: float = 2.0) -> float:
    """Calculate Bollinger Band Width"""
    if not close_window or len(close_window) < period:
        return 0.0
    
    try:
        prices = close_window[-period:]
        mean_price = np.mean(prices)
        std_price = np.std(prices, ddof=1)
        
        if mean_price == 0:
            return 0.0
        
        upper = mean_price + (num_std * std_price)
        lower = mean_price - (num_std * std_price)
        bb_width = (upper - lower) / mean_price
        
        return float(bb_width)
    except:
        return 0.0


@pw.udf
def calculate_macd(close_window: list) -> float:
    """Calculate MACD (normalized)"""
    if not close_window or len(close_window) < 26:
        return 0.0
    
    try:
        closes = np.array(close_window)
        
        # Simple EMA calculation
        def ema(data, span):
            alpha = 2 / (span + 1)
            ema_values = [data[0]]
            for price in data[1:]:
                ema_values.append(alpha * price + (1 - alpha) * ema_values[-1])
            return ema_values[-1]
        
        ema_12 = ema(closes, 12)
        ema_26 = ema(closes, 26)
        current_price = closes[-1]
        
        if current_price == 0:
            return 0.0
        
        macd = (ema_12 - ema_26) / current_price
        return float(macd)
    except:
        return 0.0


@pw.udf
def calculate_trend_strength(close_window: list) -> float:
    """Calculate trend strength from MA difference"""
    if not close_window or len(close_window) < 200:
        return 0.0
    
    try:
        ma_50 = np.mean(close_window[-50:])
        ma_200 = np.mean(close_window[-200:])
        
        if ma_200 == 0:
            return 0.0
        
        trend = (ma_50 - ma_200) / ma_200
        return float(trend)
    except:
        return 0.0


@pw.udf
def calculate_up_down_ratio(returns_window: list, period: int = 20) -> float:
    """Calculate ratio of up days"""
    if not returns_window or len(returns_window) < period:
        return 0.5
    
    try:
        recent_returns = returns_window[-period:]
        up_days = sum(1 for r in recent_returns if r > 0)
        return float(up_days / period)
    except:
        return 0.5


@pw.udf
def calculate_price_range(high: float, low: float, close: float) -> float:
    """Calculate normalized price range"""
    if close == 0:
        return 0.0
    return (high - low) / close


# ==================== Feature Pipeline using Pathway Operations ====================

def build_feature_pipeline(candles_table: pw.Table) -> pw.Table:
    """
    Build complete feature computation pipeline using Pathway operations.
    
    Args:
        candles_table: Pathway table with CandleSchema
        
    Returns:
        Pathway table with RegimeFeatureSchema (all computed features)
    """
    
    # Sort by timestamp to ensure proper ordering
    sorted_candles = candles_table.sort(key=pw.this.timestamp)
    
    # Calculate basic returns using Pathway's prev() for previous row
    with_returns = sorted_candles.select(
        *pw.this,
        prev_close=pw.this.close.prev(default=pw.this.close),
    ).select(
        *pw.this,
        returns=calculate_returns(pw.this.close, pw.this.prev_close),
        log_returns=calculate_log_returns(pw.this.close, pw.this.prev_close),
    )
    
    # Use temporal context for window operations
    # Create windows of different sizes using windowby with temporal context
    
    # For rolling windows, we'll use reducers with temporal windows
    # Window by time with sliding windows for different periods
    
    # Calculate features using window_sliding for temporal aggregations
    features = with_returns.select(
        timestamp=pw.this.timestamp,
        symbol=pw.this.symbol,
        returns=pw.this.returns,
        log_returns=pw.this.log_returns,
        
        # Store full candle data for window operations
        close=pw.this.close,
        high=pw.this.high,
        low=pw.this.low,
        volume=pw.this.volume,
    )
    
    # Note: For complex window operations requiring historical context,
    # we'll use a UDF that maintains state across calls
    # This is where AsyncTransformer pattern becomes useful
    
    return features


# ==================== Stateful Feature Computer for Historical Windows ====================

class StatefulFeatureComputer:
    """
    Maintains historical candle buffer for feature computation.
    Used within Pathway pipeline to compute features with full historical context.
    """
    
    def __init__(self, window_size: int = 250):
        self.window_size = window_size
        self.candle_buffer = {
            'timestamp': [],
            'open': [],
            'high': [],
            'low': [],
            'close': [],
            'volume': [],
            'returns': []
        }
    
    def add_candle(self, timestamp: float, open: float, high: float, low: float, 
                   close: float, volume: float, returns: float):
        """Add candle to buffer"""
        for key, value in [('timestamp', timestamp), ('open', open), ('high', high),
                           ('low', low), ('close', close), ('volume', volume), 
                           ('returns', returns)]:
            self.candle_buffer[key].append(value)
            if len(self.candle_buffer[key]) > self.window_size:
                self.candle_buffer[key].pop(0)
    
    def compute_features(self) -> Dict[str, float]:
        """Compute all features from buffer using numpy"""
        if len(self.candle_buffer['close']) < 200:
            # Not enough data yet - return default features
            return self._default_features()
        
        try:
            # Extract arrays
            closes = np.array(self.candle_buffer['close'])
            highs = np.array(self.candle_buffer['high'])
            lows = np.array(self.candle_buffer['low'])
            volumes = np.array(self.candle_buffer['volume'])
            returns = np.array(self.candle_buffer['returns'])
            
            # Compute all features using numpy
            features = {
                'returns': float(returns[-1]) if len(returns) > 0 else 0.0,
                'log_returns': float(np.log(closes[-1] / closes[-2])) if len(closes) >= 2 and closes[-2] > 0 else 0.0,
                
                # Volatility
                'volatility_5d': float(np.std(returns[-5:], ddof=1)) if len(returns) >= 5 else 0.0,
                'volatility_20d': float(np.std(returns[-20:], ddof=1)) if len(returns) >= 20 else 0.0,
                
                # Volatility ratio
                'vol_ratio': 0.0,
                
                # Returns momentum
                'returns_ma5': float(np.mean(returns[-5:])) if len(returns) >= 5 else 0.0,
                'returns_ma20': float(np.mean(returns[-20:])) if len(returns) >= 20 else 0.0,
                
                # Trend strength
                'trend_strength': 0.0,
                
                # RSI
                'rsi': calculate_rsi_from_returns(returns.tolist(), 14),
                
                # ATR
                'atr': calculate_atr_from_candles(highs.tolist(), lows.tolist(), closes.tolist(), 14),
                'atr_normalized': 0.0,
                
                # Bollinger Band Width
                'bb_width': calculate_bb_width(closes.tolist(), 20),
                
                # Volume indicators
                'volume_ratio': 0.0,
                'volume_trend': 0.0,
                
                # Price range
                'price_range': calculate_price_range(highs[-1], lows[-1], closes[-1]),
                
                # Up/down ratio
                'up_down_ratio': calculate_up_down_ratio(returns.tolist(), 20),
                
                # MACD
                'macd': calculate_macd(closes.tolist()),
                
                # Rate of change
                'roc': float((closes[-1] - closes[-11]) / closes[-11]) if len(closes) >= 11 and closes[-11] > 0 else 0.0,
            }
            
            # Calculate derived features
            if features['volatility_20d'] > 0:
                features['vol_ratio'] = features['volatility_5d'] / features['volatility_20d']
            
            if len(closes) >= 200:
                ma_50 = float(np.mean(closes[-50:]))
                ma_200 = float(np.mean(closes[-200:]))
                if ma_200 > 0:
                    features['trend_strength'] = (ma_50 - ma_200) / ma_200
            
            if closes[-1] > 0:
                features['atr_normalized'] = features['atr'] / closes[-1]
            
            if len(volumes) >= 20:
                vol_ma20 = float(np.mean(volumes[-20:]))
                if vol_ma20 > 0:
                    features['volume_ratio'] = volumes[-1] / vol_ma20
                    
                    vol_ma5 = float(np.mean(volumes[-5:]))
                    features['volume_trend'] = vol_ma5 / vol_ma20
            
            return features
            
        except Exception as exc:
            logger.error(f"Error computing features: {exc}", exc_info=True)
            return self._default_features()
    
    def _default_features(self) -> Dict[str, float]:
        """Return default zero features"""
        return {
            'returns': 0.0, 'log_returns': 0.0, 'volatility_5d': 0.0, 'volatility_20d': 0.01,
            'vol_ratio': 1.0, 'returns_ma5': 0.0, 'returns_ma20': 0.0, 'trend_strength': 0.0,
            'rsi': 50.0, 'atr': 0.0, 'atr_normalized': 0.0, 'bb_width': 0.0,
            'volume_ratio': 1.0, 'volume_trend': 1.0, 'price_range': 0.0,
            'up_down_ratio': 0.5, 'macd': 0.0, 'roc': 0.0,
        }


# ==================== AsyncTransformer with Stateful Computer ====================

class FeatureComputeTransformer(pw.AsyncTransformer, output_schema=RegimeFeatureSchema):
    """
    Async compute 15+ technical indicators using stateful feature computer.
    Maintains rolling window buffer using numpy operations (more efficient than pandas).
    """
    
    def __init__(self, input_table, window_size: int = 250, **kwargs):
        super().__init__(input_table=input_table, **kwargs)
        self.window_size = window_size
        self.feature_computer = StatefulFeatureComputer(window_size=window_size)
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
        # Calculate returns for this candle
        prev_closes = self.feature_computer.candle_buffer['close']
        returns = (close - prev_closes[-1]) / prev_closes[-1] if prev_closes and prev_closes[-1] > 0 else 0.0
        
        # Add to buffer
        self.feature_computer.add_candle(timestamp, open, high, low, close, volume, returns)
        
        buffer_size = len(self.feature_computer.candle_buffer['close'])
        logger.debug(f"Buffer size: {buffer_size}/{self.window_size}")
        
        # Need minimum data for features
        if buffer_size < 200:
            raise ValueError(f"Insufficient data for feature computation: {buffer_size}/200")
        
        # Async compute features (non-blocking using numpy)
        loop = asyncio.get_event_loop()
        features = await loop.run_in_executor(None, self.feature_computer.compute_features)
        
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
        super().__init__(input_table=input_table, **kwargs)
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

