"""
Regime Controller
Business logic layer for regime classification API
"""

import logging
from typing import Dict, Optional
from fastapi import HTTPException

from services.regime_service import RegimeService
from schemas.regime import (
    CurrentRegimeResponse,
    RegimeHistoryResponse,
    RegimeDataPoint,
    RegimeStatisticsResponse,
    RegimeStatistics,
    TrainModelRequest,
    TrainModelResponse,
    UpdateSensitivityRequest,
    UpdateSensitivityResponse,
)

logger = logging.getLogger(__name__)


class RegimeController:
    """Controller for regime classification endpoints"""
    
    def __init__(self):
        """Initialize controller with regime service"""
        self.service = RegimeService.get_instance()
    
    async def get_current_regime(self) -> CurrentRegimeResponse:
        """
        Get current market regime classification.
        
        Returns:
            CurrentRegimeResponse with regime, timestamp, state_id, and features
            
        Raises:
            HTTPException: If no regime prediction is available yet
        """
        try:
            regime_data = self.service.get_current_regime()
            
            if regime_data is None:
                raise HTTPException(
                    status_code=503,
                    detail="No regime prediction available yet. Please wait for the first prediction cycle."
                )
            
            return CurrentRegimeResponse(
                regime=regime_data["regime"],
                timestamp=regime_data["timestamp"],
                state_id=regime_data["state_id"],
                features=regime_data["features"]
            )
            
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Error getting current regime: {exc}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get current regime: {str(exc)}"
            )
    
    async def get_regime_history(self, limit: int = 100) -> RegimeHistoryResponse:
        """
        Get regime classification history.
        
        Args:
            limit: Maximum number of historical points to return
            
        Returns:
            RegimeHistoryResponse with historical regime data
            
        Raises:
            HTTPException: If query fails
        """
        try:
            history = self.service.get_regime_history(limit=limit)
            
            # Convert to data points
            data_points = [
                RegimeDataPoint(
                    timestamp=item["timestamp"],
                    regime=item["regime"],
                    state_id=item["state_id"]
                )
                for item in history
            ]
            
            return RegimeHistoryResponse(
                data=data_points,
                count=len(data_points)
            )
            
        except Exception as exc:
            logger.error(f"Error getting regime history: {exc}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get regime history: {str(exc)}"
            )
    
    async def get_regime_statistics(self) -> RegimeStatisticsResponse:
        """
        Get statistics for each regime.
        
        Returns:
            RegimeStatisticsResponse with statistics per regime
            
        Raises:
            HTTPException: If query fails
        """
        try:
            stats_data = self.service.get_regime_statistics()
            
            # Convert to response model
            statistics = [
                RegimeStatistics(
                    regime=stat["regime"],
                    percentage_time=stat["percentage_time"],
                    avg_return=stat["avg_return"],
                    avg_volatility=stat["avg_volatility"],
                    count=stat["count"]
                )
                for stat in stats_data["statistics"]
            ]
            
            return RegimeStatisticsResponse(
                statistics=statistics,
                total_observations=stats_data["total_observations"]
            )
            
        except Exception as exc:
            logger.error(f"Error getting regime statistics: {exc}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get regime statistics: {str(exc)}"
            )
    
    async def train_model(self, request: TrainModelRequest) -> TrainModelResponse:
        """
        Retrain the regime classification model.
        
        Args:
            request: Training parameters
            
        Returns:
            TrainModelResponse with training results
            
        Raises:
            HTTPException: If training fails
        """
        try:
            result = self.service.retrain_model(
                start_date=request.start_date or "2020-01-01",
                end_date=request.end_date,
                n_regimes=request.n_regimes or 4
            )
            
            if not result["success"]:
                raise HTTPException(
                    status_code=500,
                    detail=result["message"]
                )
            
            return TrainModelResponse(
                success=result["success"],
                message=result["message"],
                regimes=result["regimes"],
                training_samples=result["training_samples"]
            )
            
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Error training model: {exc}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to train model: {str(exc)}"
            )
    
    async def update_sensitivity(self, request: UpdateSensitivityRequest) -> UpdateSensitivityResponse:
        """
        Update regime transition sensitivity.
        
        Args:
            request: Sensitivity parameters
            
        Returns:
            UpdateSensitivityResponse with update results
            
        Raises:
            HTTPException: If update fails
        """
        try:
            result = self.service.update_sensitivity(alpha_diag=request.alpha_diag)
            
            if not result["success"]:
                raise HTTPException(
                    status_code=500,
                    detail=result["message"]
                )
            
            return UpdateSensitivityResponse(
                success=result["success"],
                message=result["message"],
                alpha_diag=result["alpha_diag"]
            )
            
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Error updating sensitivity: {exc}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update sensitivity: {str(exc)}"
            )

