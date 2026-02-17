"""Machine learning models for quantitative forecasting.

This module provides a framework-agnostic interface for training and predicting
with various ML models, along with built-in implementations.
"""

from quant_stream.models.base import ForecastModel
from quant_stream.models.lightgbm_model import LightGBMModel
from quant_stream.models.linear_model import LinearModel
from quant_stream.models.tree_model import RandomForestModel
from quant_stream.models.xgboost_model import XGBoostModel
from quant_stream.models.lstm_model import LSTMModel
from quant_stream.models.training import create_model, train_and_evaluate

__all__ = [
    "ForecastModel",
    "LightGBMModel",
    "LinearModel",
    "LSTMModel",
    "RandomForestModel",
    "XGBoostModel",
    "create_model",
    "train_and_evaluate",
]

