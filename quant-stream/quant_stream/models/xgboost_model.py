"""XGBoost model implementation for quantitative forecasting."""

from typing import Optional

import pandas as pd
import xgboost as xgb

from quant_stream.models.base import ForecastModel


class XGBoostModel(ForecastModel):
    """XGBoost gradient boosting model for financial forecasting.

    XGBoost is a highly optimized gradient boosting implementation
    that often provides state-of-the-art performance on structured data.

    Example:
        >>> model = XGBoostModel(
        ...     num_boost_round=100,
        ...     params={"learning_rate": 0.05, "max_depth": 5}
        ... )
        >>> model.fit(X_train, y_train)
        >>> predictions = model.predict(X_test)
    """

    def __init__(
        self,
        params: dict = None,
        num_boost_round: int = 100,
        early_stopping_rounds: int = None,
        verbose: bool = False,
        **kwargs,
    ):
        """Initialize XGBoost model.

        Args:
            params: XGBoost parameters. If None, uses default financial params.
            num_boost_round: Number of boosting iterations
            early_stopping_rounds: Early stopping rounds (requires validation set)
            verbose: Whether to print training progress
            **kwargs: Additional parameters passed to base class
        """
        super().__init__(**kwargs)

        # Default parameters optimized for financial forecasting
        default_params = {
            "objective": "reg:squarederror",
            "eval_metric": "rmse",
            "booster": "gbtree",
            "learning_rate": 0.05,
            "max_depth": 5,
            "min_child_weight": 1,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "n_jobs": -1,
        }

        # Update with user-provided params
        if params:
            default_params.update(params)

        self.params.update(default_params)
        self.num_boost_round = num_boost_round
        self.early_stopping_rounds = early_stopping_rounds
        self.verbose = verbose
        self.model = None

    def fit(
        self, X: pd.DataFrame, y: pd.Series, eval_set: tuple = None, **kwargs
    ) -> "XGBoostModel":
        """Fit the XGBoost model.

        Args:
            X: Training features
            y: Training targets
            eval_set: Optional validation set as (X_val, y_val) tuple
            **kwargs: Additional parameters passed to xgb.train

        Returns:
            Self (for method chaining)

        Example:
            >>> model.fit(X_train, y_train, eval_set=(X_val, y_val))
        """
        # Store feature names
        self.feature_names = list(X.columns)

        # Create DMatrix
        dtrain = xgb.DMatrix(X, label=y, feature_names=self.feature_names)

        evals = [(dtrain, "train")]
        if eval_set is not None:
            X_val, y_val = eval_set
            dval = xgb.DMatrix(X_val, label=y_val, feature_names=self.feature_names)
            evals.append((dval, "validation"))

        # Train the model
        evals_result = {}
        self.model = xgb.train(
            self.params,
            dtrain,
            num_boost_round=self.num_boost_round,
            evals=evals,
            early_stopping_rounds=self.early_stopping_rounds,
            evals_result=evals_result,
            verbose_eval=self.verbose,
            **kwargs,
        )

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

        dmatrix = xgb.DMatrix(X, feature_names=self.feature_names)
        predictions = self.model.predict(dmatrix)
        return pd.Series(predictions, index=X.index)

    def get_feature_importance(
        self, importance_type: str = "weight"
    ) -> pd.Series:
        """Get feature importance scores.

        Args:
            importance_type: Type of importance ('weight', 'gain', 'cover', 'total_gain', 'total_cover')

        Returns:
            Series with feature importances sorted in descending order

        Example:
            >>> importance = model.get_feature_importance(importance_type="gain")
            >>> print(importance.head(10))
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted first. Call fit() before getting importance.")

        importance_dict = self.model.get_score(importance_type=importance_type)

        # Create series with all features (missing features get 0 importance)
        importance = pd.Series(0.0, index=self.feature_names)
        for feat, score in importance_dict.items():
            if feat in importance.index:
                importance[feat] = score

        return importance.sort_values(ascending=False)

    def save(self, path: str):
        """Save the model to disk.

        Args:
            path: File path to save the model

        Example:
            >>> model.save("xgboost_model.json")
        """
        if not self.is_fitted:
            raise RuntimeError("Cannot save unfitted model. Call fit() first.")

        # Save as JSON format (recommended)
        if not path.endswith(".json"):
            path = path + ".json"

        self.model.save_model(path)

    @classmethod
    def load(cls, path: str) -> "XGBoostModel":
        """Load a saved model from disk.

        Args:
            path: File path to load the model from

        Returns:
            Loaded XGBoostModel instance

        Example:
            >>> model = XGBoostModel.load("xgboost_model.json")
        """
        if not path.endswith(".json"):
            path = path + ".json"

        # Create new instance
        model_instance = cls()

        # Load the booster
        model_instance.model = xgb.Booster()
        model_instance.model.load_model(path)
        model_instance.is_fitted = True
        model_instance.feature_names = model_instance.model.feature_names

        return model_instance

