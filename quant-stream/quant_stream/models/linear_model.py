"""Linear model implementations for quantitative forecasting."""

import pandas as pd
from sklearn.linear_model import Ridge, Lasso, ElasticNet

from quant_stream.models.base import ForecastModel


class LinearModel(ForecastModel):
    """Linear regression model with regularization.

    Supports Ridge (L2), Lasso (L1), and ElasticNet regularization.
    Good baseline model and interpretable for factor analysis.

    Example:
        >>> model = LinearModel(alpha=1.0, method="ridge")
        >>> model.fit(X_train, y_train)
        >>> predictions = model.predict(X_test)
    """

    def __init__(
        self,
        alpha: float = 1.0,
        method: str = "ridge",
        fit_intercept: bool = True,
        normalize: bool = False,
        l1_ratio: float = 0.5,
        **kwargs,
    ):
        """Initialize linear model.

        Args:
            alpha: Regularization strength (higher = more regularization)
            method: Regularization method ('ridge', 'lasso', or 'elasticnet')
            fit_intercept: Whether to fit intercept term
            normalize: Whether to normalize features before fitting
            l1_ratio: ElasticNet mixing parameter (only used if method='elasticnet')
            **kwargs: Additional parameters passed to base class
        """
        super().__init__(**kwargs)

        self.alpha = alpha
        self.method = method
        self.fit_intercept = fit_intercept
        self.normalize = normalize
        self.l1_ratio = l1_ratio

        # Create the appropriate model
        if method == "ridge":
            self.model = Ridge(
                alpha=alpha,
                fit_intercept=fit_intercept,
                random_state=42,
            )
        elif method == "lasso":
            self.model = Lasso(
                alpha=alpha,
                fit_intercept=fit_intercept,
                random_state=42,
            )
        elif method == "elasticnet":
            self.model = ElasticNet(
                alpha=alpha,
                l1_ratio=l1_ratio,
                fit_intercept=fit_intercept,
                random_state=42,
            )
        else:
            raise ValueError(f"Unknown method: {method}. Use 'ridge', 'lasso', or 'elasticnet'.")

    def fit(self, X: pd.DataFrame, y: pd.Series, **kwargs) -> "LinearModel":
        """Fit the linear model.

        Args:
            X: Training features
            y: Training targets
            **kwargs: Additional parameters (ignored for linear models)

        Returns:
            Self (for method chaining)

        Example:
            >>> model.fit(X_train, y_train)
        """
        self.feature_names = list(X.columns)
        self.model.fit(X, y)
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
        """Get feature coefficients (weights).

        For linear models, coefficients represent feature importance.
        Returns absolute values sorted in descending order.

        Returns:
            Series with feature coefficients

        Example:
            >>> importance = model.get_feature_importance()
            >>> print(importance.head(10))
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted first. Call fit() before getting importance.")

        coefficients = pd.Series(self.model.coef_, index=self.feature_names)
        # Return absolute values for importance ranking
        return coefficients.abs().sort_values(ascending=False)

    def get_coefficients(self) -> pd.Series:
        """Get raw feature coefficients (with signs).

        Returns:
            Series with feature coefficients including signs

        Example:
            >>> coef = model.get_coefficients()
            >>> positive_factors = coef[coef > 0]
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted first. Call fit() before getting coefficients.")

        return pd.Series(self.model.coef_, index=self.feature_names)

    def get_intercept(self) -> float:
        """Get the intercept term.

        Returns:
            Intercept value

        Example:
            >>> intercept = model.get_intercept()
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted first. Call fit() before getting intercept.")

        return float(self.model.intercept_)

