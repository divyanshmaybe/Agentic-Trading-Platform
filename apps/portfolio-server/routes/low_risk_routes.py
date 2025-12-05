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
from shared.py.dbManager import DBManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/low-risk", tags=["low-risk-pipeline"])


class PipelineTriggerRequest(BaseModel):
    """Request model for triggering low-risk pipeline"""
    pass  # No fund_allocated needed - will be fetched from allocation


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

    logger.info(f"📨 Low-risk pipeline trigger request from user {user_id}")

    # Initialize DB connection
    db_manager = DBManager()
    await db_manager.connect()

    try:
        db = db_manager.get_client()

        # 1. Fetch user's portfolio
        portfolio = await db.portfolio.find_first(
            where={"customer_id": user_id},
            include={"allocations": {"include": {"tradingAgent": True}}}
        )

        if not portfolio:
            raise HTTPException(status_code=404, detail="Portfolio not found for user")

        # 2. Find low_risk allocation
        low_risk_allocation = None
        for allocation in portfolio.allocations:
            if allocation.allocation_type == "low_risk":
                low_risk_allocation = allocation
                break

        if not low_risk_allocation:
            raise HTTPException(
                status_code=404,
                detail="Low-risk allocation not found. Please set up portfolio allocations first."
            )

        # 3. Check trading agent exists and is active
        trading_agent = low_risk_allocation.tradingAgent

        if not trading_agent:
            raise HTTPException(
                status_code=404,
                detail="Trading agent not found for low_risk allocation"
            )

        agent_status = str(trading_agent.status).lower()
        if agent_status == "paused":
            raise HTTPException(
                status_code=400,
                detail=f"Trading agent is paused. Please activate the agent before running pipeline."
            )

        if agent_status not in ["active", "running"]:
            raise HTTPException(
                status_code=400,
                detail=f"Trading agent status is '{agent_status}'. Expected 'active' or 'running'."
            )

        # 4. Get allocated cash from low_risk allocation
        allocated_cash = float(low_risk_allocation.allocated_amount or 0)
        available_cash = float(low_risk_allocation.available_cash or 0)

        if allocated_cash <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"No cash allocated to low_risk strategy. Allocated: ₹{allocated_cash:,.2f}"
            )

        logger.info(
            f"✅ Low-risk agent validated | User: {user_id} | Agent: {trading_agent.id} | "
            f"Status: {agent_status} | Allocated: ₹{allocated_cash:,.2f} | Available: ₹{available_cash:,.2f}"
        )

    finally:
        await db_manager.disconnect()

    # Check current pipeline status
    # Check current pipeline status
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
                fund_allocated=allocated_cash
            )
    except Exception as e:
        logger.warning(f"Failed to check pipeline status: {e}. Proceeding with trigger...")

    # Trigger pipeline asynchronously with allocated cash
    try:
        result = run_low_risk_pipeline.delay(
            user_id=user_id,
            fund_allocated=allocated_cash
        )

        logger.info(f"✅ Low-risk pipeline triggered for user {user_id}, task_id: {result.id}")

        return PipelineTriggerResponse(
            success=True,
            message="Low-risk pipeline started successfully. Selecting stocks...",
            task_id=result.id,
            user_id=user_id,
            fund_allocated=allocated_cash
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
