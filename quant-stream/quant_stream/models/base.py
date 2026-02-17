"""Base class for forecast models.

Defines the abstract interface that all forecast models must implement.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import pandas as pd


class ForecastModel(ABC):
    """Abstract base class for forecast models.

    All forecast models should inherit from this class and implement
    the abstract methods for fitting and prediction.

    Example:
        >>> class MyModel(ForecastModel):
        ...     def fit(self, X, y, **kwargs):
        ...         self.model = train_model(X, y)
        ...     def predict(self, X):
        ...         return self.model.predict(X)
    """

    def __init__(self, **kwargs):
        """Initialize the model.

        Args:
            **kwargs: Model-specific parameters
        """
        self.model = None
        self.is_fitted = False
        self.feature_names = None
        self.params = kwargs

    @abstractmethod
    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> "ForecastModel":
        """Fit the model to training data.

        Args:
            X: Feature matrix (n_samples, n_features)
            y: Target values (n_samples,)
            **kwargs: Additional fitting parameters

        Returns:
            Self (for method chaining)

        Example:
            >>> model.fit(X_train, y_train)
        """
        pass

    @abstractmethod
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Generate predictions for new data.

        Args:
            X: Feature matrix (n_samples, n_features)

        Returns:
            Predictions (n_samples,)

        Example:
            >>> predictions = model.predict(X_test)
        """
        pass

    def fit_predict(
        self, X_train: pd.DataFrame, y_train: pd.Series, X_test: pd.DataFrame
    ) -> pd.Series:
        """Fit the model and generate predictions in one call.

        Args:
            X_train: Training features
            y_train: Training targets
            X_test: Test features

        Returns:
            Predictions for X_test

        Example:
            >>> predictions = model.fit_predict(X_train, y_train, X_test)
        """
        self.fit(X_train, y_train)
        return self.predict(X_test)

    def save(self, path: str):
        """Save the model to disk.

        Args:
            path: File path to save the model

        Example:
            >>> model.save("my_model.pkl")
        """
        import pickle

        if not self.is_fitted:
            raise RuntimeError("Cannot save unfitted model. Call fit() first.")

        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str) -> "ForecastModel":
        """Load a saved model from disk.

        Args:
            path: File path to load the model from

        Returns:
            Loaded model instance

        Example:
            >>> model = ForecastModel.load("my_model.pkl")
        """
        import pickle

        with open(path, "rb") as f:
            model = pickle.load(f)

        if not isinstance(model, cls):
            raise TypeError(
                f"Loaded object is not an instance of {cls.__name__}: {type(model)}"
            )

        return model

    def get_feature_importance(self) -> Optional[pd.Series]:
        """Get feature importance scores.

        Returns:
            Series with feature names as index and importance as values,
            or None if the model doesn't support feature importance

        Example:
            >>> importance = model.get_feature_importance()
            >>> print(importance.sort_values(ascending=False).head(10))
        """
        return None

    def get_params(self) -> Dict[str, Any]:
        """Get model parameters.

        Returns:
            Dictionary of model parameters
        """
        return self.params.copy()

    def set_params(self, **params):
        """Set model parameters.

        Args:
            **params: Parameters to update

        Example:
            >>> model.set_params(learning_rate=0.1, max_depth=5)
        """
        self.params.update(params)

    def __repr__(self) -> str:
        """String representation of the model."""
        fitted_str = "fitted" if self.is_fitted else "not fitted"
        return f"{self.__class__.__name__}({fitted_str})"

