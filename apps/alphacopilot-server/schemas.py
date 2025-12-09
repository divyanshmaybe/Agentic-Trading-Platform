"""Pydantic schemas for request/response validation."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class RunStatus(str, Enum):
    """Status of a run."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunCreateRequest(BaseModel):
    """Request schema for creating a new run."""
    hypothesis: str = Field(..., description="Market hypothesis to test")
    custom_factors: Optional[List[str]] = Field(None, description="Optional custom factor expressions")
    model_type: Optional[str] = Field("LightGBM", description="ML model type (LightGBM, XGBoost, RandomForest, or None)")
    
    # Data configuration
    data_path: Optional[str] = Field(None, description="Path to market data CSV")
    symbol_col: str = Field("symbol", description="Column name for symbols")
    timestamp_col: str = Field("timestamp", description="Column name for timestamps")
    symbols_file: Optional[str] = Field(None, description="Path to file with symbols to filter (defaults to quant-stream/.data/nifty500.txt)")
    max_symbols: Optional[int] = Field(None, description="Maximum number of symbols to use")
    
    # Date ranges
    train_start_date: Optional[str] = Field(None, description="Training period start date (YYYY-MM-DD)")
    train_end_date: Optional[str] = Field(None, description="Training period end date (YYYY-MM-DD)")
    test_start_date: Optional[str] = Field(None, description="Testing period start date (YYYY-MM-DD)")
    test_end_date: Optional[str] = Field(None, description="Testing period end date (YYYY-MM-DD)")
    validation_start_date: Optional[str] = Field(None, description="Validation period start date (YYYY-MM-DD)")
    validation_end_date: Optional[str] = Field(None, description="Validation period end date (YYYY-MM-DD)")
    
    # Iteration control
    max_iterations: int = Field(3, ge=1, description="Maximum number of iterations per run")
    num_runs: int = Field(1, ge=1, description="Number of independent runs to execute")
    
    # Strategy configuration
    strategy_type: str = Field("TopkDropout", description="Strategy type")
    strategy_method: str = Field("equal", description="Strategy method")
    topk: int = Field(30, ge=1, description="Number of top stocks")
    n_drop: int = Field(5, ge=0, description="Stocks to drop per rebalance")
    
    # Backtest configuration
    initial_capital: float = Field(1_000_000, gt=0, description="Initial capital")
    commission: float = Field(0.001, ge=0, description="Commission rate")
    slippage: float = Field(0.001, ge=0, description="Slippage rate")
    rebalance_frequency: int = Field(1, ge=1, description="Rebalance frequency")
    
    # LightGBM/Model parameters (optional)
    model_params: Optional[Dict[str, Any]] = Field(None, description="Model hyperparameters")


class FactorInfo(BaseModel):
    """Information about a factor."""
    name: str
    expression: str
    description: Optional[str] = None


class IterationResponse(BaseModel):
    """Response schema for iteration results."""
    id: str
    run_id: str
    iteration_num: int
    factors: Optional[List[Dict[str, Any]]] = None
    metrics: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RunResponse(BaseModel):
    """Response schema for run details."""
    id: str
    hypothesis: str
    status: str
    config: Dict[str, Any]
    num_iterations: int
    current_iteration: int
    created_at: datetime
    updated_at: datetime
    error_message: Optional[str] = None
    # Final results (if run is completed)
    generated_factors: Optional[List[Dict[str, Any]]] = None
    workflow_config: Optional[Dict[str, Any]] = None
    best_factors: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


class RunListResponse(BaseModel):
    """Response schema for listing runs."""
    runs: List[RunResponse]
    total: int


class ResultsResponse(BaseModel):
    """Response schema for run results."""
    run_id: str
    status: str
    final_metrics: Optional[Dict[str, Any]] = None
    all_factors: Optional[List[Dict[str, Any]]] = None
    best_factors: Optional[List[Dict[str, Any]]] = None
    iterations: Optional[List[IterationResponse]] = None
    
    # Workflow config for deployment
    workflow_config: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class StatusResponse(BaseModel):
    """Response schema for run status."""
    run_id: str
    status: str
    current_iteration: int
    num_iterations: int
    progress_percent: float = Field(..., description="Progress as percentage (0-100)")
    error_message: Optional[str] = None
    iterations: Optional[List[IterationResponse]] = Field(None, description="All iterations for this run")


class LogEntry(BaseModel):
    """Log entry for a run."""
    id: str
    run_id: str
    level: str
    message: str
    timestamp: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Live Alpha Schemas
# ============================================================================

class DeployAlphaRequest(BaseModel):
    """Request to deploy an alpha from a completed run."""
    run_id: str = Field(..., description="ID of the completed run to deploy")
    name: str = Field(..., description="Name for the live alpha")
    portfolio_id: str = Field(..., description="Portfolio to attach this alpha to")
    allocated_amount: float = Field(..., gt=0, description="Capital to allocate")
    symbols: Optional[List[str]] = Field(None, description="Override symbols (uses run config if not provided)")
    auto_trade: bool = Field(True, description="Enable automatic trading")


class LiveAlphaResponse(BaseModel):
    """Response for a live alpha."""
    id: str
    name: str
    hypothesis: Optional[str]
    run_id: Optional[str]
    workflow_config: Dict[str, Any]
    symbols: List[str]
    model_type: Optional[str]
    strategy_type: str
    status: str
    allocated_amount: float
    portfolio_id: str
    agent_id: Optional[str]
    last_signal_at: Optional[datetime]
    total_signals: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True



