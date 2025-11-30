"""
Low Risk Pipeline Routes

Provides REST API endpoints for triggering and monitoring the low-risk
stock selection pipeline with proper authentication and status tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging

from utils.auth import get_authenticated_user
from workers.low_risk_tasks import run_low_risk_pipeline, get_low_risk_pipeline_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/low-risk", tags=["low-risk-pipeline"])


class PipelineTriggerRequest(BaseModel):
    """Request model for triggering low-risk pipeline"""
    fund_allocated: float = Field(
        default=100000.0,
        gt=0,
        description="Total fund amount to allocate (must be positive)"
    )


class PipelineTriggerResponse(BaseModel):
    """Response model for pipeline trigger"""
    success: bool
    message: str
    task_id: Optional[str] = None
    user_id: str
    fund_allocated: float


class PipelineStatusResponse(BaseModel):
    """Response model for pipeline status"""
    running: bool
    status: str
    start_time: Optional[str] = None
    elapsed_minutes: Optional[int] = None
    error: Optional[str] = None
    timestamp: Optional[str] = None


@router.post("/trigger", response_model=PipelineTriggerResponse)
async def trigger_low_risk_pipeline(
    request: PipelineTriggerRequest,
    user: dict = Depends(get_authenticated_user)
) -> PipelineTriggerResponse:
    """
    Trigger the low-risk stock selection pipeline.
    
    **Authentication Required**
    
    This endpoint triggers the complete low-risk pipeline which:
    1. Computes industry indicators from market data
    2. Selects optimal industries based on economic regime
    3. Selects stocks within each industry using AI agents
    4. Generates trade recommendations with position sizing
    
    The pipeline runs asynchronously via Celery and publishes real-time
    progress updates to Kafka that can be consumed by the frontend.
    
    **Concurrency Control:**
    - Only one pipeline instance can run per user at a time
    - If pipeline is already running, returns error with elapsed time
    - Lock automatically expires after 30 minutes for safety
    
    **Request Parameters:**
    - `fund_allocated`: Total amount to allocate across selected stocks (default: ₹100,000)
    
    **Returns:**
    - `success`: Whether pipeline was successfully triggered
    - `message`: Human-readable status message
    - `task_id`: Celery task ID for tracking (if successful)
    - `user_id`: User ID for which pipeline is running
    - `fund_allocated`: Fund amount allocated
    
    **Example Request:**
    ```json
    {
        "fund_allocated": 500000.0
    }
    ```
    
    **Example Success Response:**
    ```json
    {
        "success": true,
        "message": "Low-risk pipeline started successfully. Selecting stocks...",
        "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "user_id": "user123",
        "fund_allocated": 500000.0
    }
    ```
    
    **Example Error Response (Already Running):**
    ```json
    {
        "success": false,
        "message": "Pipeline already running. Selecting stocks... (running for 5 minutes)",
        "task_id": null,
        "user_id": "user123",
        "fund_allocated": 500000.0
    }
    ```
    """
    user_id = user.get("user_id") or user.get("id")
    
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")
    
    logger.info(f"📨 Low-risk pipeline trigger request from user {user_id} with fund: ₹{request.fund_allocated:,.2f}")
    
    # Check current status first
    try:
        status = get_low_risk_pipeline_status.delay(user_id).get(timeout=5)
        
        if status.get("running"):
            elapsed = status.get("elapsed_minutes", 0)
            message = f"Pipeline already running. Selecting stocks... (running for {elapsed} minutes)"
            logger.warning(f"⚠️ Pipeline already running for user {user_id} ({elapsed} minutes)")
            
            return PipelineTriggerResponse(
                success=False,
                message=message,
                task_id=None,
                user_id=user_id,
                fund_allocated=request.fund_allocated
            )
    except Exception as e:
        logger.warning(f"Failed to check pipeline status: {e}. Proceeding with trigger...")
    
    # Trigger pipeline asynchronously
    try:
        result = run_low_risk_pipeline.delay(
            user_id=user_id,
            fund_allocated=request.fund_allocated
        )
        
        logger.info(f"✅ Low-risk pipeline triggered for user {user_id}, task_id: {result.id}")
        
        return PipelineTriggerResponse(
            success=True,
            message="Low-risk pipeline started successfully. Selecting stocks...",
            task_id=result.id,
            user_id=user_id,
            fund_allocated=request.fund_allocated
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to trigger low-risk pipeline for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger pipeline: {str(e)}"
        )


@router.get("/status", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    user: dict = Depends(get_authenticated_user)
) -> PipelineStatusResponse:
    """
    Get current status of the low-risk pipeline for authenticated user.
    
    **Authentication Required**
    
    Returns real-time status information about the low-risk pipeline execution:
    - Whether pipeline is currently running
    - How long it has been running (if active)
    - Last completion/failure status (if not running)
    - Error details (if failed)
    
    **Returns:**
    - `running`: Boolean indicating if pipeline is currently executing
    - `status`: Current status ("running", "completed", "failed", "not_started")
    - `start_time`: ISO timestamp when pipeline started (if running)
    - `elapsed_minutes`: How long pipeline has been running (if running)
    - `error`: Error message (if failed)
    - `timestamp`: Error timestamp (if failed)
    
    **Example Response (Running):**
    ```json
    {
        "running": true,
        "status": "running",
        "start_time": "2025-11-30T10:30:00Z",
        "elapsed_minutes": 3,
        "error": null,
        "timestamp": null
    }
    ```
    
    **Example Response (Completed):**
    ```json
    {
        "running": false,
        "status": "completed",
        "start_time": null,
        "elapsed_minutes": null,
        "error": null,
        "timestamp": null
    }
    ```
    
    **Example Response (Failed):**
    ```json
    {
        "running": false,
        "status": "failed",
        "start_time": null,
        "elapsed_minutes": null,
        "error": "GEMINI_API_KEY not found",
        "timestamp": "2025-11-30T10:35:00Z"
    }
    ```
    """
    user_id = user.get("user_id") or user.get("id")
    
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")
    
    logger.debug(f"📊 Status check for user {user_id}")
    
    try:
        # Get status from Celery task (runs quickly)
        status = get_low_risk_pipeline_status.delay(user_id).get(timeout=5)
        
        return PipelineStatusResponse(
            running=status.get("running", False),
            status=status.get("status", "unknown"),
            start_time=status.get("start_time"),
            elapsed_minutes=status.get("elapsed_minutes"),
            error=status.get("error"),
            timestamp=status.get("timestamp")
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to get pipeline status for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get pipeline status: {str(e)}"
        )


__all__ = ["router"]
