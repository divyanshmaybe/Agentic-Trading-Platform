"""Model training utilities."""

from typing import Any, Dict, Optional, Tuple
import pandas as pd

from quant_stream.models import LSTMModel, LightGBMModel, XGBoostModel, RandomForestModel, LinearModel
from quant_stream.models.utils import calculate_ic


def create_model(model_type: str, model_params: Dict[str, Any]) -> Any:
    """Create model instance from type and parameters.
    
    Args:
        model_type: Model type (LightGBM, XGBoost, RandomForest, Linear)
        model_params: Model parameters
        
    Returns:
        Initialized model instance
        
    Example:
        >>> model = create_model("LightGBM", {
        ...     "learning_rate": 0.05,
        ...     "max_depth": 5,
        ...     "num_boost_round": 100
        ... })
    """
    # For LightGBM and XGBoost, separate boost params from hyperparameters
    if model_type in ["LightGBM", "XGBoost"]:
        # Extract boost-specific parameters
        boost_params = {}
        if "num_boost_round" in model_params:
            boost_params["num_boost_round"] = model_params["num_boost_round"]
        if "early_stopping_rounds" in model_params:
            boost_params["early_stopping_rounds"] = model_params["early_stopping_rounds"]
        if "verbose" in model_params:
            boost_params["verbose"] = model_params["verbose"]
        
        # Remaining parameters go into params dict
        hyperparams = {
            k: v for k, v in model_params.items() 
            if k not in boost_params
        }
        
        if model_type == "LightGBM":
            return LightGBMModel(params=hyperparams, **boost_params)
        else:  # XGBoost
            return XGBoostModel(params=hyperparams, **boost_params)
    
    # For RandomForest and Linear, pass params directly as kwargs
    elif model_type == "RandomForest":
        return RandomForestModel(**model_params)
    elif model_type == "Linear":
        return LinearModel(**model_params)
    elif model_type == "LSTM":
        return LSTMModel(**model_params)
    else:
        raise ValueError(f"Unknown model type: {model_type}")


def train_and_evaluate(
    model: Any,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    X_val: Optional[pd.DataFrame] = None,
    y_val: Optional[pd.Series] = None,
) -> Tuple[Any, Dict[str, float], Dict[str, float], Optional[Dict[str, float]]]:
    """Train model and calculate IC metrics.
    
    Args:
        model: Model instance
        X_train: Training features
        y_train: Training target
        X_test: Test features
        y_test: Test target
        
    Returns:
        Tuple of (trained model, train_ic_metrics, test_ic_metrics, validation_ic_metrics)
        
    Example:
        >>> model, train_ic, test_ic, val_ic = train_and_evaluate(
        ...     model, X_train, y_train, X_test, y_test
        ... )
        >>> assert val_ic is None or "IC" in val_ic
        >>> print(f"Test IC: {test_ic['IC']:.4f}")
    """
    # Train model
    use_eval_set = None
    if X_val is not None and y_val is not None and len(X_val) > 0:
        use_eval_set = (X_val, y_val)
    else:
        use_eval_set = (X_test, y_test)

    if hasattr(model, "fit") and "eval_set" in model.fit.__code__.co_varnames:
        model.fit(X_train, y_train, eval_set=use_eval_set)
    else:
        model.fit(X_train, y_train)
    
    # Generate predictions
    train_pred = model.predict(X_train)
    test_pred = model.predict(X_test)
    
    # Debug: Check prediction statistics
    print(f"[DEBUG] Train predictions - mean: {train_pred.mean():.6f}, std: {train_pred.std():.6f}, min: {train_pred.min():.6f}, max: {train_pred.max():.6f}")
    print(f"[DEBUG] Train labels - mean: {y_train.mean():.6f}, std: {y_train.std():.6f}, min: {y_train.min():.6f}, max: {y_train.max():.6f}")
    print(f"[DEBUG] Test predictions - mean: {test_pred.mean():.6f}, std: {test_pred.std():.6f}, min: {test_pred.min():.6f}, max: {test_pred.max():.6f}")
    print(f"[DEBUG] Test labels - mean: {y_test.mean():.6f}, std: {y_test.std():.6f}, min: {y_test.min():.6f}, max: {y_test.max():.6f}")
    
    validation_ic = None
    if X_val is not None and y_val is not None and len(X_val) > 0:
        val_pred = model.predict(X_val)
        validation_ic = calculate_ic(val_pred, y_val)
    
    # Calculate IC metrics
    train_ic = calculate_ic(train_pred, y_train)
    test_ic = calculate_ic(test_pred, y_test)
    
    print(f"[DEBUG] Train IC: {train_ic['IC']:.6f}, Rank IC: {train_ic['Rank_IC']:.6f}")
    print(f"[DEBUG] Test IC: {test_ic['IC']:.6f}, Rank IC: {test_ic['Rank_IC']:.6f}")
    
    return model, train_ic, test_ic, validation_ic

