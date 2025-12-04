"""Pydantic schemas for request/response validation."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    """Request schema for creating a new run."""
    hypothesis: str = Field(..., description="Market hypothesis to test")
    custom_factors: Optional[List[str]] = Field(None, description="Optional custom factor expressions")
    model_type: Optional[str] = Field("LightGBM", description="ML model type (LightGBM, XGBoost, RandomForest, or None)")
    data_path: Optional[str] = Field(None, description="Path to market data CSV")
    symbol_col: str = Field("symbol", description="Column name for symbols")
    timestamp_col: str = Field("timestamp", description="Column name for timestamps")
    symbols_file: Optional[str] = Field(".data/nifty500.txt", description="Path to file with symbols to filter (default: .data/nifty500.txt)")
    max_symbols: Optional[int] = Field(None, description="Maximum number of symbols to use")
    train_start_date: Optional[str] = Field(None, description="Training period start date (YYYY-MM-DD)")
    train_end_date: Optional[str] = Field(None, description="Training period end date (YYYY-MM-DD)")
    test_start_date: Optional[str] = Field(None, description="Testing period start date (YYYY-MM-DD)")
    test_end_date: Optional[str] = Field(None, description="Testing period end date (YYYY-MM-DD)")
    validation_start_date: Optional[str] = Field(None, description="Validation period start date (YYYY-MM-DD)")
    validation_end_date: Optional[str] = Field(None, description="Validation period end date (YYYY-MM-DD)")
    max_iterations: int = Field(3, ge=1, description="Maximum number of iterations per run")
    num_runs: int = Field(1, ge=1, description="Number of independent runs to execute")
    strategy_type: str = Field("TopkDropout", description="Strategy type")
    strategy_method: str = Field("equal", description="Strategy method")
    topk: int = Field(30, ge=1, description="Number of top stocks")
    n_drop: int = Field(5, ge=0, description="Stocks to drop per rebalance")
    initial_capital: float = Field(1_000_000, gt=0, description="Initial capital")
    commission: float = Field(0.001, ge=0, description="Commission rate")
    slippage: float = Field(0.001, ge=0, description="Slippage rate")
    rebalance_frequency: int = Field(1, ge=1, description="Rebalance frequency")


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
    completed_at: datetime

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

