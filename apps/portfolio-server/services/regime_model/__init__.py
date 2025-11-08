"""
Regime model package exposing classifier, data utilities, and sensitivity tuning.
"""

from .classifier import MarketRegimeClassifier
from .data import fetch_nse_data
from .sensitivity import make_sticky_transmat, replace_model, update_sensitivity
from .workflow import (
    get_scaled_features,
    predict_forward_bias,
    predict_no_forward_bias,
    train_classifier,
)

__all__ = [
    "MarketRegimeClassifier",
    "fetch_nse_data",
    "make_sticky_transmat",
    "replace_model",
    "update_sensitivity",
    "train_classifier",
    "get_scaled_features",
    "predict_forward_bias",
    "predict_no_forward_bias",
]

