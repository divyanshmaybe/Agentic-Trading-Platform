"""Tree-based model implementations for quantitative forecasting."""

import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from quant_stream.models.base import ForecastModel


class RandomForestModel(ForecastModel):
    """Random Forest model for financial forecasting.

    Ensemble of decision trees that provides good performance with
    minimal hyperparameter tuning. Robust to outliers and provides
    feature importance.

    Example:
        >>> model = RandomForestModel(n_estimators=100, max_depth=5)
        >>> model.fit(X_train, y_train)
        >>> predictions = model.predict(X_test)
    """

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = None,
        min_samples_split: int = 2,
        min_samples_leaf: int = 1,
        max_features: str = "sqrt",
        bootstrap: bool = True,
        n_jobs: int = -1,
        random_state: int = 42,
        **kwargs,
    ):
        """Initialize Random Forest model.

        Args:
            n_estimators: Number of trees in the forest
            max_depth: Maximum depth of trees (None = unlimited)
            min_samples_split: Minimum samples required to split a node
            min_samples_leaf: Minimum samples required at leaf node
            max_features: Number of features to consider for splits
            bootstrap: Whether to use bootstrap samples
            n_jobs: Number of parallel jobs (-1 = use all cores)
            random_state: Random seed for reproducibility
            **kwargs: Additional parameters passed to base class
        """
        super().__init__(**kwargs)

        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.bootstrap = bootstrap
        self.n_jobs = n_jobs
        self.random_state = random_state

        self.model = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            max_features=max_features,
            bootstrap=bootstrap,
            n_jobs=n_jobs,
            random_state=random_state,
        )

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> "RandomForestModel":
        """Fit the Random Forest model.

        Args:
            X: Training features
            y: Training targets
            **kwargs: Additional parameters passed to sklearn's fit method

        Returns:
            Self (for method chaining)

        Example:
            >>> model.fit(X_train, y_train)
        """
        self.feature_names = list(X.columns)
        self.model.fit(X, y, **kwargs)
        self.is_fitted = True
        return self

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Generate predictions.

        Args:
            X: Features to predict on

        Returns:
            Predictions as pandas Series

        Example:
            >>> predictions = model.predict(X_test)
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before prediction. Call fit() first.")

        predictions = self.model.predict(X)
        return pd.Series(predictions, index=X.index)

    def get_feature_importance(self) -> pd.Series:
        """Get feature importance scores based on impurity decrease.

        Returns:
            Series with feature importances sorted in descending order

        Example:
            >>> importance = model.get_feature_importance()
            >>> print(importance.head(10))
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted first. Call fit() before getting importance.")

        importance = pd.Series(
            self.model.feature_importances_, index=self.feature_names
        )
        return importance.sort_values(ascending=False)

    def get_oob_score(self) -> float:
        """Get out-of-bag score (if bootstrap=True).

        Returns:
            OOB R² score

        Example:
            >>> oob = model.get_oob_score()
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted first.")

        if not self.bootstrap:
            raise ValueError("OOB score only available when bootstrap=True")

        # Re-fit with oob_score enabled if needed
        if not hasattr(self.model, "oob_score_"):
            raise ValueError("Model was not fitted with oob_score=True")

        return float(self.model.oob_score_)

