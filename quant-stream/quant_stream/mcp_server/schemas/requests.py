"""Request schemas for MCP tools."""

from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field, model_validator


class DataConfig(BaseModel):
    """Data loading configuration."""

    path: Optional[str] = Field(None, description="Path to market data CSV file")
    symbol_col: str = Field("symbol", description="Column name for symbol/ticker")
    timestamp_col: str = Field("timestamp", description="Column name for timestamp")


class FeatureConfig(BaseModel):
    """Feature configuration."""
    
    name: str = Field(description="Feature name")
    expression: str = Field(description="Feature expression (e.g., 'DELTA($close, 1)')")


class TrainTestSplitConfig(BaseModel):
    """Train/test split configuration for model training."""

    train_start: str = Field(description="Training start date (YYYY-MM-DD)")
    train_end: str = Field(description="Training end date (YYYY-MM-DD)")
    test_start: str = Field(description="Test start date (YYYY-MM-DD)")
    test_end: str = Field(description="Test end date (YYYY-MM-DD)")
    validation_start: Optional[str] = Field(
        None, description="Validation start date (optional, YYYY-MM-DD)"
    )
    validation_end: Optional[str] = Field(
        None, description="Validation end date (optional, YYYY-MM-DD)"
    )


class ModelConfig(BaseModel):
    """ML model configuration."""
    
    type: Literal["LightGBM", "Linear", "XGBoost", "RandomForest", "LSTM"] = Field(
        "LightGBM", description="Model type"
    )
    features: Optional[List[str]] = Field(
        None,
        description="Explicit list of feature names or expressions to use. "
        "Can reference existing computed factors by name, OHLCV columns, or specify inline expressions. "
        "If None, uses all computed factors (backward compatible)."
    )
    include_ohlcv: bool = Field(
        True,
        description="Whether to include OHLCV columns as features when features=None"
    )
    params: Dict[str, Any] = Field(default_factory=dict, description="Model hyperparameters (all params passed directly to model)")
    target: str = Field("forward_return_1d", description="Target variable name")
    train_test_split: Optional[TrainTestSplitConfig] = Field(
        None, description="Train/test split configuration for model training"
    )

    @model_validator(mode="after")
    def _disallow_train_test_split(self):
        if self.train_test_split is not None:
            raise ValueError(
                "model.train_test_split is no longer supported. "
                "Provide train/validation/test windows via backtest.segments."
            )
        return self


class SegmentsConfig(BaseModel):
    """Time segments for backtesting."""
    
    train: Optional[List[str]] = Field(
        None, 
        description="Train segment: [start_date, end_date]"
    )
    test: Optional[List[str]] = Field(
        None,
        description="Test segment: [start_date, end_date]"
    )
    validation: Optional[List[str]] = Field(
        None,
        description="Validation segment: [start_date, end_date]"
    )


class BacktestConfig(BaseModel):
    """Backtest configuration."""
    
    segments: Optional[SegmentsConfig] = Field(
        None,
        description="Time segments for train/test split"
    )
    initial_capital: float = Field(1_000_000, description="Initial capital")
    commission: float = Field(0.001, description="Commission rate")
    slippage: float = Field(0.001, description="Slippage rate")
    min_commission: float = Field(0.0, description="Minimum commission per trade")
    rebalance_frequency: int = Field(1, description="Rebalance every N periods")


class StrategyConfig(BaseModel):
    """Strategy configuration."""
    
    type: Literal["TopkDropout", "Weight"] = Field("TopkDropout", description="Strategy type")
    params: Dict[str, Any] = Field(default_factory=dict, description="Strategy parameters")


class ExperimentConfig(BaseModel):
    """Experiment tracking configuration."""
    
    name: str = Field("mcp_experiment", description="Experiment name")
    tracking_uri: str = Field("sqlite:///mlruns.db", description="MLflow tracking URI")
    run_name: Optional[str] = Field(None, description="Run name")
    tags: Dict[str, str] = Field(default_factory=dict, description="Experiment tags")


class CalculateFactorRequest(BaseModel):
    """Request schema for calculate_factor tool."""
    
    expression: str = Field(description="Factor expression (e.g., 'DELTA($close, 1)')")
    data_config: Optional[DataConfig] = Field(
        None, 
        description="Data configuration (path, start_date, end_date, etc.)"
    )
    factor_name: str = Field("alpha", description="Name for the output factor")


class RunWorkflowRequest(BaseModel):
    """Request schema for run_workflow tool."""
    
    # Either provide YAML path or full config
    config_path: Optional[str] = Field(None, description="Path to YAML config file")
    config_dict: Optional[Dict[str, Any]] = Field(None, description="Configuration dictionary")
    
    # Or provide structured configuration
    data: Optional[DataConfig] = Field(None, description="Data configuration")
    features: Optional[List[FeatureConfig]] = Field(None, description="Feature configurations")
    model: Optional[ModelConfig] = Field(None, description="Model configuration")
    strategy: Optional[StrategyConfig] = Field(None, description="Strategy configuration")
    backtest: Optional[BacktestConfig] = Field(None, description="Backtest configuration")
    experiment: Optional[ExperimentConfig] = Field(None, description="Experiment configuration")
    
    output_path: Optional[str] = Field(None, description="Path to save results CSV")

