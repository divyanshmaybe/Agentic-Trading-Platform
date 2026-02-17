"""Default configuration values."""

from typing import Dict, Any


def get_default_config() -> Dict[str, Any]:
    """Get default workflow configuration.
    
    Note: The 'model' key is OPTIONAL. If you want to run without a model
    (using raw factor values as signals), simply omit the 'model' key from
    your configuration or set it to null.
    
    Returns:
        Default configuration dictionary
    """
    return {
        "data": {
            "path": ".data/indian_stock_market_nifty500.csv",
            "symbol_col": "symbol",
            "timestamp_col": "timestamp",
        },
        "features": [
            {
                "name": "momentum_1d",
                "expression": "DELTA($close, 1)",
            }
        ],
        "model": {
            "type": "LightGBM",
            "params": {
                "learning_rate": 0.05,
                "max_depth": 5,
                "num_boost_round": 100,
            },
            "target": "forward_return_1d",
        },
        "strategy": {
            "type": "TopkDropout",
            "params": {
                "topk": 30,
                "n_drop": 5,
                "method": "equal",
            },
        },
        "backtest": {
            "segments": None,  # No segments by default - uses all data
            "initial_capital": 1_000_000,
            "commission": 0.001,
            "slippage": 0.001,
            "min_commission": 0.0,
            "rebalance_frequency": 1,
        },
        "experiment": {
            "name": "quant_experiment",
            "tracking_uri": "sqlite:///mlruns.db",
            "run_name": None,
            "tags": {},
        },
    }


def get_default_data_config() -> Dict[str, Any]:
    """Get default data configuration."""
    return get_default_config()["data"]


def get_default_backtest_config() -> Dict[str, Any]:
    """Get default backtest configuration."""
    return get_default_config()["backtest"]


def get_default_strategy_config() -> Dict[str, Any]:
    """Get default strategy configuration."""
    return get_default_config()["strategy"]
