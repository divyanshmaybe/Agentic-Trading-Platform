"""
Market Regime Classifier built on Hidden Markov Models.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

# CRITICAL: Disable NumPy/OpenBLAS threading before imports to prevent SIGSEGV
# in multiprocessing contexts (e.g., Celery workers)
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import numpy as np
import pandas as pd
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler

from .indicators import atr, bollinger_band_width, rsi

logger = logging.getLogger(__name__)


class MarketRegimeClassifier:
    """
    Hidden Markov Model based Market Regime Classifier.

    Identifies regimes such as Bull, Bear, High Volatility, and Sideways markets.
    """

    def __init__(self, n_regimes: int = 4, random_state: int = 42) -> None:
        self.n_regimes = n_regimes
        self.random_state = random_state

        self.model = hmm.GaussianHMM(
            n_components=n_regimes,
            covariance_type="full",
            n_iter=2000,
            tol=1e-4,
            random_state=random_state,
            verbose=False,
        )

        self.scaler = StandardScaler()
        self.regime_names: Optional[Dict[int, str]] = None
        self.feature_names: Optional[List[str]] = None
        self.is_trained = False
        self.features: Optional[pd.DataFrame] = None
        self.regime_predictions: Optional[List[str]] = None

    def prepare_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare advanced technical features from market data.
        """
        df = data.copy()

        # Flatten MultiIndex columns if present (e.g., yfinance output)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        features = pd.DataFrame(index=df.index)

        # Returns
        returns = df["Close"].pct_change()
        df["returns"] = returns
        features["returns"] = returns
        features["log_returns"] = np.log(df["Close"] / df["Close"].shift(1))

        # Volatility
        features["volatility_5d"] = returns.rolling(window=5).std()
        features["volatility_20d"] = returns.rolling(window=20).std()
        features["vol_ratio"] = (
            features["volatility_5d"] / features["volatility_20d"]
        )

        # Momentum
        features["returns_ma5"] = returns.rolling(window=5).mean()
        features["returns_ma20"] = returns.rolling(window=20).mean()

        # Trend strength
        ma_50 = df["Close"].rolling(window=50).mean()
        ma_200 = df["Close"].rolling(window=200).mean()
        features["trend_strength"] = (ma_50 - ma_200) / ma_200

        # Indicators
        features["rsi"] = rsi(df["Close"], period=14)
        atr_values = atr(df, period=14)
        features["atr"] = atr_values
        features["atr_normalized"] = atr_values / df["Close"]
        features["bb_width"] = bollinger_band_width(df["Close"], period=20)

        # Volume indicators
        volume_series = pd.to_numeric(df["Volume"], errors="coerce")
        volume_series = volume_series.replace(0, np.nan)
        if volume_series.dropna().empty:
            features["volume_ratio"] = 1.0
            features["volume_trend"] = 1.0
        else:
            volume_mean_20 = volume_series.rolling(window=20, min_periods=1).mean()
            features["volume_ratio"] = volume_series / volume_mean_20
            volume_mean_5 = volume_series.rolling(window=5, min_periods=1).mean()
            features["volume_trend"] = volume_mean_5 / volume_mean_20
            # Fix pandas FutureWarning by using proper DataFrame method
            features["volume_ratio"] = features["volume_ratio"].fillna(1.0)
            features["volume_trend"] = features["volume_trend"].fillna(1.0)

        # Price action
        features["price_range"] = (df["High"] - df["Low"]) / df["Close"]
        up_days = (df["returns"] > 0).rolling(window=20).sum()
        features["up_down_ratio"] = up_days / 20

        # MACD and Rate of Change
        ema_12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema_26 = df["Close"].ewm(span=26, adjust=False).mean()
        features["macd"] = (ema_12 - ema_26) / df["Close"]
        features["roc"] = (df["Close"] - df["Close"].shift(10)) / df["Close"].shift(10)

        features.replace([np.inf, -np.inf], np.nan, inplace=True)
        self.features = features.dropna()
        if self.features.empty:
            raise ValueError("Insufficient clean feature rows for HMM training.")
        self.feature_names = self.features.columns.tolist()
        return self.features

    def fit(self, data: pd.DataFrame) -> "MarketRegimeClassifier":
        """
        Train the HMM model on historical data.
        
        NOTE: This method assumes NumPy/OpenBLAS threading is disabled
        via environment variables to prevent SIGSEGV in multiprocessing contexts.
        """
        logger.info("Preparing technical features for HMM training")
        features = self.prepare_features(data)
        logger.info(
            "Training HMM with %s observations and %s features",
            len(features),
            len(self.feature_names or []),
        )

        # Ensure single-threaded mode for BLAS operations
        # This prevents SIGSEGV in multiprocessing (Celery) contexts
        original_threads = {
            "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS", "1"),
            "MKL_NUM_THREADS": os.environ.get("MKL_NUM_THREADS", "1"),
            "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "1"),
        }
        
        # Force single-threaded mode
        os.environ["OPENBLAS_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"
        os.environ["OMP_NUM_THREADS"] = "1"
        
        try:
            features_scaled = self.scaler.fit_transform(features)
            self.model.fit(features_scaled)
            hidden_states = self.model.predict(features_scaled)
        finally:
            # Restore original thread settings (though we want single-threaded anyway)
            for key, value in original_threads.items():
                if value:
                    os.environ[key] = value

        self.regime_names = self._label_regimes(features, hidden_states)
        self.is_trained = True
        logger.info("HMM training complete. Identified regimes: %s", self.regime_names)
        return self

    def predict(self, data: pd.DataFrame) -> List[str]:
        """
        Predict regimes for the provided data.
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before calling predict().")

        features = self.prepare_features(data)
        features_scaled = self.scaler.transform(features)
        hidden_states = self.model.predict(features_scaled)
        fallback = lambda s: self.regime_names.get(s, f"Regime {int(s)}")  # type: ignore[union-attr]
        self.regime_predictions = [fallback(state) for state in hidden_states]
        return self.regime_predictions

    def predict_current(self, data: pd.DataFrame) -> str:
        """
        Predict the regime for the most recent observation.
        """
        predictions = self.predict(data)
        return predictions[-1]

    def inference(self, features_scaled: np.ndarray) -> List[str]:
        """
        Predict regimes from scaled features (no forward bias).
        """
        hidden_states = self.model.predict(features_scaled)
        return [self.regime_names.get(state, f"Regime {int(state)}") for state in hidden_states]  # type: ignore[union-attr]

    def get_regime_statistics(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Compute statistics for each regime.
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before computing statistics.")

        features = self.prepare_features(data)
        predictions = self.regime_predictions or self.predict(data)
        features = features.copy()
        features["regime"] = predictions

        stats = features.groupby("regime").agg(
            {
                "returns": ["mean", "std", "min", "max"],
                "volatility_20d": ["mean", "std"],
                "rsi": "mean",
                "regime": "count",
            }
        )

        stats.columns = ["_".join(col).strip() for col in stats.columns.values]
        stats = stats.rename(columns={"regime_count": "n_observations"})
        stats["pct_time"] = (stats["n_observations"] / len(features) * 100).round(2)

        return stats.round(4)

    def _label_regimes(
        self, features: pd.DataFrame, hidden_states: np.ndarray
    ) -> Dict[int, str]:
        """
        Label regimes based on return/volatility characteristics.
        """
        regime_stats: Dict[int, Dict[str, float]] = {}

        for state in range(self.n_regimes):
            mask = hidden_states == state
            regime_stats[state] = {
                "mean_return": features.loc[mask, "returns"].mean(),
                "mean_volatility": features.loc[mask, "volatility_20d"].mean(),
                "count": float(mask.sum()),
            }

        def highest_return(states: List[int]) -> int:
            return max(states, key=lambda s: regime_stats[s]["mean_return"])

        def lowest_return(states: List[int]) -> int:
            return min(states, key=lambda s: regime_stats[s]["mean_return"])

        def highest_vol(states: List[int]) -> int:
            return max(states, key=lambda s: regime_stats[s]["mean_volatility"])

        regime_names: Dict[int, str] = {}

        if self.n_regimes == 2:
            bull = highest_return(list(regime_stats.keys()))
            bear = lowest_return(list(regime_stats.keys()))
            regime_names[bull] = "Bull Market"
            regime_names[bear] = "Bear Market"

        elif self.n_regimes == 3:
            high_vol = highest_vol(list(regime_stats.keys()))
            regime_names[high_vol] = "High Volatility"
            remaining = [s for s in regime_stats.keys() if s != high_vol]
            bull = highest_return(remaining)
            bear = lowest_return(remaining)
            regime_names[bull] = "Bull Market"
            regime_names[bear] = "Bear Market"

        else:
            high_vol = highest_vol(list(regime_stats.keys()))
            regime_names[high_vol] = "High Volatility"
            remaining = [s for s in regime_stats.keys() if s != high_vol]
            bull = highest_return(remaining)
            bear = lowest_return(remaining)
            regime_names[bull] = "Bull Market"
            regime_names[bear] = "Bear Market"

            for state in remaining:
                if state not in (bull, bear):
                    regime_names[state] = "Sideways Market"

        default_labels = [
            "Bull Market",
            "Bear Market",
            "High Volatility",
            "Sideways Market",
        ]
        used_labels = set(regime_names.values())
        for state in range(self.n_regimes):
            if state not in regime_names:
                fallback_label = next(
                    (label for label in default_labels if label not in used_labels),
                    f"Regime {state}",
                )
                regime_names[state] = fallback_label
                used_labels.add(fallback_label)

        return regime_names


__all__ = ["MarketRegimeClassifier"]

