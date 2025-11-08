"""Regime Classification Schemas for API Responses"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime


class CurrentRegimeResponse(BaseModel):
    """Response for current regime classification"""
    regime: str = Field(..., description="Current market regime (Bull Market, Bear Market, etc.)")
    timestamp: float = Field(..., description="Unix timestamp of classification")
    state_id: int = Field(..., description="HMM state ID")
    features: Dict[str, float] = Field(..., description="Technical indicators used for classification")
    
    class Config:
        json_schema_extra = {
            "example": {
                "regime": "Bull Market",
                "timestamp": 1699564800.0,
                "state_id": 2,
                "features": {
                    "returns": 0.0125,
                    "volatility_20d": 0.015,
                    "rsi": 65.5,
                    "macd": 0.003
                }
            }
        }


class RegimeDataPoint(BaseModel):
    """Single regime classification data point"""
    timestamp: float = Field(..., description="Unix timestamp")
    regime: str = Field(..., description="Market regime")
    state_id: int = Field(..., description="HMM state ID")


class RegimeHistoryResponse(BaseModel):
    """Response for regime classification history"""
    data: List[RegimeDataPoint] = Field(..., description="List of regime data points")
    count: int = Field(..., description="Number of data points returned")
    
    class Config:
        json_schema_extra = {
            "example": {
                "data": [
                    {"timestamp": 1699564800.0, "regime": "Bull Market", "state_id": 2},
                    {"timestamp": 1699568400.0, "regime": "Bull Market", "state_id": 2},
                    {"timestamp": 1699572000.0, "regime": "Sideways Market", "state_id": 3}
                ],
                "count": 3
            }
        }


class RegimeStatistics(BaseModel):
    """Statistics for each regime"""
    regime: str
    percentage_time: float = Field(..., description="Percentage of time in this regime")
    avg_return: float = Field(..., description="Average return during this regime")
    avg_volatility: float = Field(..., description="Average volatility during this regime")
    count: int = Field(..., description="Number of observations")


class RegimeStatisticsResponse(BaseModel):
    """Response for regime statistics"""
    statistics: List[RegimeStatistics] = Field(..., description="Statistics per regime")
    total_observations: int = Field(..., description="Total number of observations")


class TrainModelRequest(BaseModel):
    """Request to retrain the regime classification model"""
    start_date: Optional[str] = Field(None, description="Start date for training data (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date for training data (YYYY-MM-DD)")
    n_regimes: Optional[int] = Field(4, ge=2, le=6, description="Number of regimes to classify")


class TrainModelResponse(BaseModel):
    """Response after model training"""
    success: bool
    message: str
    regimes: Dict[int, str] = Field(..., description="Mapping of state IDs to regime names")
    training_samples: int = Field(..., description="Number of samples used for training")


class UpdateSensitivityRequest(BaseModel):
    """Request to update regime transition sensitivity"""
    alpha_diag: float = Field(5.0, ge=0.1, le=20.0, description="Diagonal boost for transition matrix (higher = stickier)")


class UpdateSensitivityResponse(BaseModel):
    """Response after sensitivity update"""
    success: bool
    message: str
    alpha_diag: float

