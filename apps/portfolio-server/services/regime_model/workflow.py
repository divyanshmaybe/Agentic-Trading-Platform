"""
High-level training and inference helpers for the regime classifier.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from .classifier import MarketRegimeClassifier


def train_classifier(
    data: pd.DataFrame, n_regimes: int = 4, random_state: int = 42
) -> MarketRegimeClassifier:
    """
    Train a MarketRegimeClassifier on historical data.
    """
    classifier = MarketRegimeClassifier(n_regimes=n_regimes, random_state=random_state)
    classifier.fit(data)
    return classifier


def get_scaled_features(
    classifier: MarketRegimeClassifier, data: pd.DataFrame
) -> np.ndarray:
    """
    Return scaled features for inference without forward bias.
    """
    features = classifier.prepare_features(data)
    return classifier.scaler.transform(features)


def predict_forward_bias(
    classifier: MarketRegimeClassifier, data: pd.DataFrame
) -> List[str]:
    """
    Predict regimes with the classifier using forward-looking features.
    """
    return classifier.predict(data)


def predict_no_forward_bias(
    classifier: MarketRegimeClassifier, scaled_features: np.ndarray
) -> List[Optional[str]]:
    """
    Predict regimes sequentially to avoid forward bias.
    """
    predictions: List[Optional[str]] = [None] * scaled_features.shape[0]
    for idx in range(scaled_features.shape[0]):
        partial = scaled_features[: idx + 1]
        regime = classifier.inference(partial)[-1]
        predictions[idx] = regime
    return predictions


__all__ = [
    "train_classifier",
    "get_scaled_features",
    "predict_forward_bias",
    "predict_no_forward_bias",
]

