"""LightGBM model implementation for quantitative forecasting."""

from typing import Optional

import pandas as pd
import lightgbm as lgb

from quant_stream.models.base import ForecastModel


class LightGBMModel(ForecastModel):
    """LightGBM gradient boosting model for financial forecasting.

    This model uses LightGBM with parameters tuned for quantitative finance
    applications. It's particularly good for handling large feature sets and
    capturing non-linear relationships.

    Example:
        >>> model = LightGBMModel(
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
        verbose: int = -1,
        **kwargs,
    ):
        """Initialize LightGBM model.

        Args:
            params: LightGBM parameters. If None, uses default financial params.
            num_boost_round: Number of boosting iterations
            early_stopping_rounds: Early stopping rounds (requires validation set)
            verbose: Verbosity level (-1 = silent, 0 = warning, 1+ = info)
            **kwargs: Additional parameters passed to base class
        """
        super().__init__(**kwargs)

        # Default parameters optimized for financial forecasting
        default_params = {
            "objective": "regression",
            "metric": "l2",
            "boosting_type": "gbdt",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 5,
            "min_child_samples": 20,
            "subsample": 0.8,
            "subsample_freq": 1,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "random_state": 42,
            "verbose": -1,
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
        self,
        X: pd.DataFrame,
        y: pd.Series,
        eval_set: tuple = None,
        categorical_features: list = None,
        **kwargs,
    ) -> "LightGBMModel":
        """Fit the LightGBM model.

        Args:
            X: Training features
            y: Training targets
            eval_set: Optional validation set as (X_val, y_val) tuple
            categorical_features: List of categorical feature names
            **kwargs: Additional parameters passed to lgb.train

        Returns:
            Self (for method chaining)

        Example:
            >>> model.fit(X_train, y_train, eval_set=(X_val, y_val))
        """
        # Store feature names
        self.feature_names = list(X.columns)

        # Create LightGBM datasets
        train_data = lgb.Dataset(
            X, label=y, categorical_feature=categorical_features, free_raw_data=False
        )

        valid_sets = [train_data]
        valid_names = ["training"]

        if eval_set is not None:
            X_val, y_val = eval_set
            valid_data = lgb.Dataset(
                X_val,
                label=y_val,
                categorical_feature=categorical_features,
                reference=train_data,
                free_raw_data=False,
            )
            valid_sets.append(valid_data)
            valid_names.append("validation")

        # Train the model
        callbacks = []
        if self.early_stopping_rounds and eval_set is not None:
            callbacks.append(lgb.early_stopping(self.early_stopping_rounds))

        self.model = lgb.train(
            self.params,
            train_data,
            num_boost_round=self.num_boost_round,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=callbacks,
            **kwargs,
        )

        # Warn if model stopped very early (likely not learning)
        if hasattr(self.model, 'best_iteration') and self.model.best_iteration <= 1:
            print(f"[WARN] Model stopped at iteration {self.model.best_iteration}. This may indicate:")
            print(f"  - Regularization too high (reg_alpha: {self.params.get('reg_alpha', 'N/A')}, reg_lambda: {self.params.get('reg_lambda', 'N/A')})")
            print(f"  - Features not informative enough")
            print(f"  - Learning rate too low (current: {self.params.get('learning_rate', 'N/A')})")
            print(f"  - Model may predict constant values (mean of target)")

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

        # Use best_iteration if available, otherwise use all iterations
        num_iteration = getattr(self.model, 'best_iteration', None)
        if num_iteration is not None and num_iteration <= 1:
            # If best_iteration is 1 or less, the model likely didn't learn
            # Use a minimum of 10 iterations or all available
            num_iteration = max(10, min(self.num_boost_round, 100))
            print(f"[WARN] best_iteration was {self.model.best_iteration}, using {num_iteration} iterations instead")
        
        if num_iteration is not None:
            predictions = self.model.predict(X, num_iteration=num_iteration)
        else:
            predictions = self.model.predict(X)
        return pd.Series(predictions, index=X.index)

    def get_feature_importance(self, importance_type: str = "gain") -> pd.Series:
        """Get feature importance scores.

        Args:
            importance_type: Type of importance ('split', 'gain')

        Returns:
            Series with feature importances sorted in descending order

        Example:
            >>> importance = model.get_feature_importance()
            >>> print(importance.head(10))
        """
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted first. Call fit() before getting importance.")

        importance = self.model.feature_importance(importance_type=importance_type)
        feature_importance = pd.Series(importance, index=self.feature_names)
        return feature_importance.sort_values(ascending=False)

    def save(self, path: str):
        """Save the model to disk.

        Args:
            path: File path to save the model

        Example:
            >>> model.save("lightgbm_model.txt")
        """
        if not self.is_fitted:
            raise RuntimeError("Cannot save unfitted model. Call fit() first.")

        # Save as LightGBM text format
        if not path.endswith(".txt"):
            path = path + ".txt"

        self.model.save_model(path)

    @classmethod
    def load(cls, path: str) -> "LightGBMModel":
        """Load a saved model from disk.

        Args:
            path: File path to load the model from

        Returns:
            Loaded LightGBMModel instance

        Example:
            >>> model = LightGBMModel.load("lightgbm_model.txt")
        """
        if not path.endswith(".txt"):
            path = path + ".txt"

        # Create new instance
        model_instance = cls()

        # Load the booster
        model_instance.model = lgb.Booster(model_file=path)
        model_instance.is_fitted = True
        model_instance.feature_names = model_instance.model.feature_name()

        return model_instance

