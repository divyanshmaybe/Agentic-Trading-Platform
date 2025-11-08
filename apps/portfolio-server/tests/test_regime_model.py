import os
import sys
from typing import List

import numpy as np
import pandas as pd
import pytest

# Ensure the services package is on sys.path when running tests from repo root
CURRENT_DIR = os.path.dirname(__file__)
APP_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from services.regime_model import (
    MarketRegimeClassifier,
    get_scaled_features,
    predict_forward_bias,
    predict_no_forward_bias,
    train_classifier,
    update_sensitivity,
)


@pytest.fixture(scope="module")
def synthetic_market_data() -> pd.DataFrame:
    """Generate deterministic synthetic OHLCV data for tests."""
    rng = np.random.default_rng(seed=42)
    periods = 420
    index = pd.date_range("2020-01-01", periods=periods, freq="D")

    base_price = 100 + rng.normal(0, 0.5, size=periods).cumsum()
    high = base_price + rng.uniform(0.1, 1.5, size=periods)
    low = base_price - rng.uniform(0.1, 1.5, size=periods)
    open_ = base_price + rng.normal(0, 0.3, size=periods)
    close = base_price + rng.normal(0, 0.2, size=periods)
    volume = rng.integers(1_000_000, 5_000_000, size=periods)

    data = pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Adj Close": close,
            "Volume": volume,
        },
        index=index,
    )
    return data


def test_prepare_features_returns_expected_columns(synthetic_market_data: pd.DataFrame) -> None:
    classifier = MarketRegimeClassifier(n_regimes=4, random_state=0)
    features = classifier.prepare_features(synthetic_market_data)

    assert not features.empty, "Prepared features should not be empty"
    expected_columns = {
        "returns",
        "log_returns",
        "volatility_5d",
        "volatility_20d",
        "vol_ratio",
        "returns_ma5",
        "returns_ma20",
        "trend_strength",
        "rsi",
        "atr",
        "atr_normalized",
        "bb_width",
        "volume_ratio",
        "volume_trend",
        "price_range",
        "up_down_ratio",
        "macd",
        "roc",
    }
    assert set(features.columns) == expected_columns
    assert features.isna().sum().sum() == 0, "Features should not contain NaNs"


def test_fit_creates_regime_names(synthetic_market_data: pd.DataFrame) -> None:
    classifier = train_classifier(synthetic_market_data, n_regimes=4, random_state=1)

    assert classifier.is_trained is True
    assert classifier.regime_names is not None
    assert len(classifier.regime_names) == classifier.n_regimes

    predictions = predict_forward_bias(classifier, synthetic_market_data)
    assert len(predictions) == len(classifier.features)
    unique_regimes = set(predictions)
    assert unique_regimes.issubset(set(classifier.regime_names.values()))


def test_update_sensitivity_increases_diagonal_probability(synthetic_market_data: pd.DataFrame) -> None:
    classifier = train_classifier(synthetic_market_data, n_regimes=4, random_state=2)
    prev_transmat = classifier.model.transmat_.copy()

    updated = update_sensitivity(classifier, alpha_diag=10.0)
    new_transmat = updated.model.transmat_

    assert np.allclose(new_transmat.sum(axis=1), 1.0)
    diag_increase = new_transmat.diagonal() >= prev_transmat.diagonal() - 1e-9
    assert diag_increase.all(), "Diagonal probabilities should not decrease after update"


def test_predict_no_forward_bias_matches_prefix(synthetic_market_data: pd.DataFrame) -> None:
    classifier = train_classifier(synthetic_market_data, n_regimes=3, random_state=3)
    scaled_features = get_scaled_features(classifier, synthetic_market_data)

    forward_predictions = predict_forward_bias(classifier, synthetic_market_data)
    no_forward_predictions = predict_no_forward_bias(classifier, scaled_features)

    assert len(no_forward_predictions) == scaled_features.shape[0]
    assert isinstance(no_forward_predictions[-1], str)

    prefix_length = 50
    assert forward_predictions[:prefix_length] == no_forward_predictions[:prefix_length]


@pytest.mark.parametrize("n_regimes", [2, 3, 4])
def test_classifier_handles_variable_regime_counts(synthetic_market_data: pd.DataFrame, n_regimes: int) -> None:
    classifier = train_classifier(synthetic_market_data, n_regimes=n_regimes, random_state=5)
    assert classifier.is_trained
    assert len(classifier.regime_names) == n_regimes

    predictions = predict_forward_bias(classifier, synthetic_market_data)
    assert len(predictions) == len(classifier.features)
    assert set(predictions).issubset(set(classifier.regime_names.values()))
