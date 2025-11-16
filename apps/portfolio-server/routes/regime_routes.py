"""
Regime Classification API Routes
REST endpoints for market regime classification
"""

from fastapi import APIRouter, Depends, Query, Body
from typing import Annotated

from controllers.regime_controller import RegimeController
from schemas.regime import (
    CurrentRegimeResponse,
    RegimeHistoryResponse,
    RegimeStatisticsResponse,
    TrainModelRequest,
    TrainModelResponse,
    UpdateSensitivityRequest,
    UpdateSensitivityResponse,
)
from utils.auth import get_authenticated_user

router = APIRouter(prefix="/regime", tags=["Regime Classification"])


def get_regime_controller() -> RegimeController:
    """Dependency: Get regime controller instance"""
    return RegimeController()


@router.get(
    "/current",
    response_model=CurrentRegimeResponse,
    summary="Get Current Regime",
    description="Get the current market regime classification with technical indicators"
)
async def get_current_regime(
    _: Annotated[dict, Depends(get_authenticated_user)],
    controller: Annotated[RegimeController, Depends(get_regime_controller)]
) -> CurrentRegimeResponse:
    """
    Get current market regime classification.
    
    Returns the most recent regime prediction including:
    - Regime name (Bull Market, Bear Market, High Volatility, Sideways Market)
    - Timestamp of classification
    - HMM state ID
    - Technical indicators used for classification
    """
    return await controller.get_current_regime()


@router.get(
    "/history",
    response_model=RegimeHistoryResponse,
    summary="Get Regime History",
    description="Get historical regime classifications for time-series analysis"
)
async def get_regime_history(
    _: Annotated[dict, Depends(get_authenticated_user)],
    controller: Annotated[RegimeController, Depends(get_regime_controller)],
    limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of historical points")] = 100,
) -> RegimeHistoryResponse:
    """
    Get regime classification history.
    
    Returns historical regime predictions that can be used for:
    - Time-series visualization
    - Regime transition analysis
    - Backtesting strategies
    
    Args:
        limit: Maximum number of data points to return (1-1000)
        
    Returns:
        List of regime data points with timestamps, regime names, and state IDs
    """
    return await controller.get_regime_history(limit=limit)


@router.get(
    "/statistics",
    response_model=RegimeStatisticsResponse,
    summary="Get Regime Statistics",
    description="Get statistical analysis of market regimes"
)
async def get_regime_statistics(
    _: Annotated[dict, Depends(get_authenticated_user)],
    controller: Annotated[RegimeController, Depends(get_regime_controller)]
) -> RegimeStatisticsResponse:
    """
    Get statistics for each identified regime.
    
    Returns statistical analysis including:
    - Percentage of time spent in each regime
    - Average return during each regime
    - Average volatility during each regime
    - Number of observations per regime
    
    Useful for:
    - Understanding market behavior patterns
    - Risk assessment
    - Strategy optimization
    """
    return await controller.get_regime_statistics()


@router.post(
    "/train",
    response_model=TrainModelResponse,
    summary="Retrain Model",
    description="Retrain the HMM regime classification model with new parameters"
)
async def train_model(
    request: Annotated[TrainModelRequest, Body()],
    _: Annotated[dict, Depends(get_authenticated_user)],
    controller: Annotated[RegimeController, Depends(get_regime_controller)]
) -> TrainModelResponse:
    """
    Retrain the regime classification model.
    
    Allows retraining with different parameters:
    - Date range for training data
    - Number of regimes to classify (2-6)
    
    Note: Service restart required for Pathway pipeline to use new model.
    
    Args:
        request: Training parameters (start_date, end_date, n_regimes)
        
    Returns:
        Training results including regime mappings and sample count
    """
    return await controller.train_model(request)


@router.post(
    "/sensitivity",
    response_model=UpdateSensitivityResponse,
    summary="Update Sensitivity",
    description="Update regime transition sensitivity (stickiness)"
)
async def update_sensitivity(
    request: Annotated[UpdateSensitivityRequest, Body()],
    _: Annotated[dict, Depends(get_authenticated_user)],
    controller: Annotated[RegimeController, Depends(get_regime_controller)]
) -> UpdateSensitivityResponse:
    """
    Update regime transition sensitivity.
    
    Controls how "sticky" regimes are (how easily the model switches between regimes):
    - Lower alpha_diag (0.1-2): More sensitive, switches regimes more frequently
    - Higher alpha_diag (5-20): Less sensitive, maintains regimes longer
    
    Note: Service restart required for Pathway pipeline to use new settings.
    
    Args:
        request: Sensitivity parameter (alpha_diag)
        
    Returns:
        Update confirmation with applied alpha_diag value
    """
    return await controller.update_sensitivity(request)


@router.get(
    "/health",
    summary="Regime Service Health",
    description="Check if regime classification service is operational"
)
async def health_check(
    controller: Annotated[RegimeController, Depends(get_regime_controller)]
):
    """
    Health check endpoint for regime classification service.
    
    Returns service status including:
    - Whether predictions are available
    - Number of historical predictions
    - Current regime (if available)
    """
    regime_data = controller.service.get_current_regime()
    history_count = len(controller.service.get_regime_history(limit=1000))
    
    return {
        "status": "healthy" if regime_data else "initializing",
        "predictions_available": regime_data is not None,
        "history_count": history_count,
        "current_regime": regime_data["regime"] if regime_data else None,
        "message": "Regime classification service is operational" if regime_data 
                  else "Waiting for first prediction cycle (may take 1-2 minutes)"
    }

