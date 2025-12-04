"""Pydantic models for workflow configuration validation."""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator, ConfigDict, model_validator


class DataConfig(BaseModel):
    """Data loading configuration."""
    
    path: str = Field(description="Path to market data CSV file")
    symbols: Optional[List[str]] = Field(None, description="List of symbols to filter (optional)")
    symbols_file: Optional[str] = Field(None, description="Path to file with symbols (optional, one per line)")
    max_symbols: Optional[int] = Field(None, description="Max number of symbols to use (optional)")
    symbol_col: str = Field("symbol", description="Column name for symbol/ticker")
    timestamp_col: str = Field("timestamp", description="Column name for timestamp")
    
    @field_validator("max_symbols")
    @classmethod
    def validate_max_symbols(cls, v):
        """Validate max_symbols is positive."""
        if v is not None and v <= 0:
            raise ValueError(f"max_symbols must be positive, got: {v}")
        return v


class FeatureConfig(BaseModel):
    """Feature engineering configuration."""
    
    model_config = ConfigDict(extra="forbid")
    
    name: str = Field(description="Feature name")
    expression: str = Field(description="Feature expression (e.g., 'DELTA($close, 1)')")


class TrainTestSplitConfig(BaseModel):
    """Train/test split configuration using explicit date ranges."""

    train_start: str = Field(..., description="Training start date (YYYY-MM-DD)")
    train_end: str = Field(..., description="Training end date (YYYY-MM-DD)")
    test_start: str = Field(..., description="Test start date (YYYY-MM-DD)")
    test_end: str = Field(..., description="Test end date (YYYY-MM-DD)")
    validation_start: Optional[str] = Field(
        None, description="Validation start date (optional, YYYY-MM-DD)"
    )
    validation_end: Optional[str] = Field(
        None, description="Validation end date (optional, YYYY-MM-DD)"
    )

    @field_validator(
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "validation_start",
        "validation_end",
    )
    @classmethod
    def validate_date_format(cls, v):
        """Validate date format."""
        if v is None:
            return v
        import re

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"Date must be in YYYY-MM-DD format, got: {v}")
        return v

    @model_validator(mode="after")
    def validate_validation_configuration(self):
        """Ensure validation configuration is consistent."""
        if (self.validation_start is None) != (self.validation_end is None):
            raise ValueError(
                "Both validation_start and validation_end must be provided when configuring validation splits."
            )
        return self


class ModelConfig(BaseModel):
    """Model configuration."""
    
    model_config = ConfigDict(extra="allow")  # Allow extra params for flexibility
    
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
        None, description="Train/test split configuration (optional, falls back to backtest.segments)"
    )

    @model_validator(mode="after")
    def _disallow_train_test_split(self):
        """Forbid defining train/test dates on the model config."""
        if self.train_test_split is not None:
            raise ValueError(
                "model.train_test_split is no longer supported. "
                "Define train/validation/test windows under backtest.segments instead."
            )
        return self


class StrategyConfig(BaseModel):
    """Strategy configuration."""
    
    model_config = ConfigDict(extra="allow")
    
    type: Literal["TopkDropout", "Weight", "BetaNeutral", "DollarNeutral", "IntradayMomentum"] = Field(
        "TopkDropout", description="Strategy type"
    )
    params: Dict[str, Any] = Field(default_factory=dict, description="Strategy parameters")


class SegmentsConfig(BaseModel):
    """Time segments for backtesting."""

    train: Optional[List[str]] = Field(
        None,
        description="Train segment as [start_date, end_date]",
    )
    test: Optional[List[str]] = Field(
        None,
        description="Test segment as [start_date, end_date]",
    )
    validation: Optional[List[str]] = Field(
        None,
        description="Validation segment as [start_date, end_date]",
    )

    @field_validator("train", "test", "validation")
    @classmethod
    def validate_segment(cls, v):
        """Validate segment is an inclusive date range."""
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError(f"Segment must be provided as [start, end] date range, got type: {type(v).__name__}")
        if len(v) != 2:
            raise ValueError(f"Date range must have 2 elements [start, end], got: {v}")
        import re

        for date in v:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                raise ValueError(f"Date must be YYYY-MM-DD format, got: {date}")
        return v


class BacktestConfig(BaseModel):
    """Backtesting configuration."""
    
    segments: Optional[SegmentsConfig] = Field(
        None,
        description="Time segments for train/validation/test split"
    )
    initial_capital: float = Field(1_000_000, description="Initial capital")
    commission: float = Field(0.001, description="Commission rate (fraction)")
    slippage: float = Field(0.001, description="Slippage rate (fraction)")
    min_commission: float = Field(0.0, description="Minimum commission per trade")
    rebalance_frequency: int = Field(1, description="Rebalance every N periods")
    allow_short: bool = Field(False, description="Allow short positions")
    intraday_short_only: bool = Field(True, description="Square off shorts at end of day (Indian market)")
    short_funding_rate: float = Field(0.0002, description="Daily funding rate for shorts")
    
    @field_validator("commission", "slippage")
    @classmethod
    def validate_rate(cls, v):
        """Validate rates are non-negative."""
        if v < 0:
            raise ValueError(f"Rate must be non-negative, got: {v}")
        return v
    
    @field_validator("initial_capital")
    @classmethod
    def validate_capital(cls, v):
        """Validate capital is positive."""
        if v <= 0:
            raise ValueError(f"Initial capital must be positive, got: {v}")
        return v


class ExperimentConfig(BaseModel):
    """Experiment tracking configuration."""
    
    model_config = ConfigDict(extra="allow")
    
    name: str = Field("quant_experiment", description="Experiment name")
    tracking_uri: str = Field("sqlite:///mlruns.db", description="MLflow tracking URI")
    run_name: Optional[str] = Field(None, description="Run name")
    tags: Dict[str, str] = Field(default_factory=dict, description="Experiment tags")


class WorkflowConfig(BaseModel):
    """Complete workflow configuration."""
    
    model_config = ConfigDict(extra="forbid")
    
    data: DataConfig = Field(description="Data configuration")
    features: List[FeatureConfig] = Field(default_factory=list, description="Feature configurations (named factors)")
    model: Optional[ModelConfig] = Field(None, description="Model configuration (optional)")
    strategy: StrategyConfig = Field(description="Strategy configuration")
    backtest: BacktestConfig = Field(default_factory=BacktestConfig, description="Backtest configuration")
    experiment: ExperimentConfig = Field(
        default_factory=ExperimentConfig, description="Experiment tracking configuration"
    )
    
    def model_dump_safe(self) -> Dict[str, Any]:
        """Dump model to dict, handling nested models."""
        return self.model_dump()
    
    def get_all_factor_expressions(self) -> List[Dict[str, str]]:
        """Get all factor expressions defined in the workflow.
        
        Returns:
            List of dicts with 'name' and 'expression' keys
        """
        return [{"name": f.name, "expression": f.expression} for f in self.features]
