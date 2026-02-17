"""
Utilities for adjusting HMM regime transition sensitivity.
"""

from __future__ import annotations

import numpy as np
from hmmlearn import hmm

from .classifier import MarketRegimeClassifier


def make_sticky_transmat(transmat: np.ndarray, alpha_diag: float = 5.0) -> np.ndarray:
    """
    Reduce state-switching probability by boosting diagonal elements.
    """
    adjusted = transmat + np.eye(transmat.shape[0]) * alpha_diag
    adjusted = adjusted / adjusted.sum(axis=1, keepdims=True)
    return adjusted


def replace_model(
    classifier: MarketRegimeClassifier, new_model: hmm.GaussianHMM
) -> MarketRegimeClassifier:
    """
    Replace the underlying HMM within the classifier.
    """
    classifier.model = new_model
    return classifier


def update_sensitivity(
    classifier: MarketRegimeClassifier, alpha_diag: float = 5.0
) -> MarketRegimeClassifier:
    """
    Update transition probabilities to make regimes stickier.
    """
    previous = classifier.model

    tuned_model = hmm.GaussianHMM(
        n_components=previous.n_components,
        covariance_type=previous.covariance_type,
        n_iter=5000,
        random_state=classifier.random_state,
    )

    tuned_model.startprob_ = previous.startprob_
    tuned_model.transmat_ = make_sticky_transmat(
        previous.transmat_, alpha_diag=alpha_diag
    )
    tuned_model.means_ = previous.means_
    tuned_model.covars_ = previous.covars_

    return replace_model(classifier, tuned_model)


__all__ = ["make_sticky_transmat", "replace_model", "update_sensitivity"]

