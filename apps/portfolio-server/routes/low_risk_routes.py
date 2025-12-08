"""
Low Risk Pipeline Routes

Provides REST API endpoints for triggering and monitoring the low-risk
stock selection pipeline with proper authentication and status tracking.
"""

import os
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import logging
from prisma import Prisma
from redis import Redis

from utils.auth import get_authenticated_user
from workers.low_risk_tasks import get_low_risk_pipeline_status, PipelineStatus
from db import prisma_client, DBManager
from celery_app import BROKER_URL

logger = logging.getLogger(__name__)

# Auth DB URL for fetching LowRiskUserSummaries
AUTH_DATABASE_URL = os.getenv("AUTH_DATABASE_URL", "postgresql://prisma_user:strongpassword@localhost:5432/prisma_db")

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

    # Get DB client with auto-reconnection (singleton - do NOT disconnect)
    db = await prisma_client()

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

    # Check if summary already exists within last 180 days (prevent duplicate runs)
    from datetime import datetime, timezone, timedelta
    auth_db = Prisma(datasource={"url": AUTH_DATABASE_URL})
    try:
        await auth_db.connect()
        cooldown_start = datetime.now(timezone.utc) - timedelta(days=180)
        
        summaries_recent = await auth_db.query_raw(
            '''
            SELECT id, "createdAt"
            FROM low_risk_user_summaries
            WHERE "userId" = $1 AND "createdAt" >= $2::timestamp
            ORDER BY "createdAt" DESC
            LIMIT 1
            ''',
            user_id,
            cooldown_start.isoformat()
        )
        
        if summaries_recent and len(summaries_recent) > 0:
            last_run = summaries_recent[0].get("createdAt")
            if last_run:
                if isinstance(last_run, str):
                    from dateutil import parser
                    last_run = parser.parse(last_run)
                if last_run.tzinfo is None:
                    last_run = last_run.replace(tzinfo=timezone.utc)
                
                days_elapsed = (datetime.now(timezone.utc) - last_run).days
                days_remaining = 180 - days_elapsed
                
                logger.warning(f"🚫 Summary already exists for user {user_id} within last 180 days ({days_elapsed} days ago)")
                await auth_db.disconnect()
                return PipelineTriggerResponse(
                    success=False,
                    message=f"Pipeline was already run {days_elapsed} days ago. Please wait {days_remaining} more days before running again (180-day cooldown).",
                    task_id=None,
                    user_id=user_id,
                    fund_allocated=allocated_cash
                )
        
        logger.info(f"✅ No summary found within last 180 days - proceeding with pipeline")
    except Exception as e:
        logger.error(f"⚠️ Failed to check existing summaries: {e}", exc_info=True)
        await auth_db.disconnect()
        return PipelineTriggerResponse(
            success=False,
            message=f"Unable to verify cooldown period due to database error. Please try again or contact support.",
            task_id=None,
            user_id=user_id,
            fund_allocated=allocated_cash
        )
    finally:
        try:
            await auth_db.disconnect()
        except:
            pass

    # Initialize Redis and pipeline status BEFORE checking
    redis_client = Redis.from_url(BROKER_URL)
    pipeline_status = PipelineStatus(redis_client, user_id)

    # Check if pipeline already running (check lock directly)
    is_running, start_time = pipeline_status.is_running()
    if is_running:
        import time
        elapsed = int((time.time() - start_time) / 60) if start_time else 0
        message = f"Pipeline already running. Selecting stocks... (running for {elapsed} minutes)"
        logger.warning(f"⚠️ Pipeline already running for user {user_id} ({elapsed} minutes)")

        return PipelineTriggerResponse(
            success=False,
            message=message,
            task_id=None,
            user_id=user_id,
            fund_allocated=allocated_cash
        )

    # Acquire lock BEFORE queuing task to prevent race condition
    if not pipeline_status.acquire_lock(ttl=7200):  # 2 hour lock
        logger.warning(f"⚠️ Failed to acquire lock for user {user_id}")
        return PipelineTriggerResponse(
            success=False,
            message="Pipeline lock already acquired. Please wait...",
            task_id=None,
            user_id=user_id,
            fund_allocated=allocated_cash
        )

    # Trigger pipeline asynchronously with allocated cash
    try:
        from celery_app import celery_app
        
        result = celery_app.send_task(
            "pipeline.low_risk.run",
            args=[user_id],
            kwargs={
                "fund_allocated": allocated_cash,
                "_skip_lock": True,  # Lock already acquired in route
            },
            queue="low_risk_pipeline",
            routing_key="low_risk_pipeline"
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
        # Release lock if task queueing failed
        pipeline_status.release_lock()
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
        # Check Redis directly instead of queuing Celery task
        redis_client = Redis.from_url(BROKER_URL)
        pipeline_status = PipelineStatus(redis_client, user_id)
        status = pipeline_status.get_status()

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


class RebalanceTriggerResponse(BaseModel):
    """Response model for rebalance trigger"""
    success: bool
    message: str
    task_id: Optional[str] = None
    user_id: str
    fund_allocated: float
    summaries_count: int = 0


@router.post("/rebalance", response_model=RebalanceTriggerResponse)
async def trigger_low_risk_rebalance(
    user: dict = Depends(get_authenticated_user)
) -> RebalanceTriggerResponse:
    """
    Trigger low-risk pipeline rebalance for authenticated user.

    **Authentication Required**

    This endpoint triggers a rebalance of the low-risk portfolio which:
    1. Checks that no pipeline is currently running
    2. Verifies that there are NO open positions for low_risk allocation
    3. Fetches previous summaries from LowRiskUserSummaries
    4. Triggers the pipeline with rebalance=True and previous summaries

    **Pre-conditions:**
    - No low-risk pipeline currently running for this user
    - No open positions in low_risk allocation (all positions must be closed)
    - Trading agent must be active

    **Returns:**
    - `success`: Whether rebalance was successfully triggered
    - `message`: Human-readable status message
    - `task_id`: Celery task ID for tracking (if successful)
    - `user_id`: User ID for which rebalance is running
    - `fund_allocated`: Fund amount allocated
    - `summaries_count`: Number of previous summaries used

    **Example Success Response:**
    ```json
    {
        "success": true,
        "message": "Low-risk rebalance started with 3 previous summaries",
        "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "user_id": "user123",
        "fund_allocated": 500000.0,
        "summaries_count": 3
    }
    ```

    **Example Error Response (Open Positions):**
    ```json
    {
        "success": false,
        "message": "Cannot rebalance: 5 open positions exist. Close all positions first.",
        "task_id": null,
        "user_id": "user123",
        "fund_allocated": 500000.0,
        "summaries_count": 0
    }
    ```
    """
    user_id = user.get("user_id") or user.get("id")

    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")

    logger.info(f"📨 Low-risk rebalance request from user {user_id}")

    # Get portfolio DB client (with auto-reconnection)
    db = await prisma_client()

    # 1. Fetch user's portfolio with allocations FIRST (needed for allocated cash)
    portfolio = await db.portfolio.find_first(
        where={"customer_id": user_id},
        include={
            "allocations": {
                "include": {
                    "tradingAgent": True,
                    "positions": {
                        "where": {"status": "open"}
                    }
                }
            }
        }
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

    # Get allocated cash early (needed for error messages)
    allocated_cash = float(low_risk_allocation.available_cash or low_risk_allocation.allocated_amount or 0)

    # 3. Check 6-month cooldown FIRST (highest priority business rule)
    prev_summaries = []
    to_send_summary = {}
    auth_db = Prisma(datasource={"url": AUTH_DATABASE_URL})
    
    # This is a critical business rule check, so we handle it carefully
    cooldown_check_failed = False
    try:
        await auth_db.connect()
        logger.info(f"🔍 Checking 6-month cooldown for user {user_id}")

        # Use raw SQL query since LowRiskUserSummaries is not in portfolio schema
        summaries = await auth_db.query_raw(
            '''
            SELECT id, "userId", type, "jsonContent", "createdAt"
            FROM low_risk_user_summaries
            WHERE "userId" = $1
            ORDER BY "createdAt" DESC
            ''',
            user_id
        )

        # Convert to list of dicts for the pipeline
        from datetime import datetime, timezone, timedelta
        for summary in summaries:
            created_at = summary.get("createdAt")
            # Handle both datetime objects and strings
            if isinstance(created_at, str):
                created_at_str = created_at
            elif hasattr(created_at, 'isoformat'):
                created_at_str = created_at.isoformat()
            else:
                created_at_str = None
                
            summary_data = {
                "id": summary.get("id"),
                "type": summary.get("type"),
                "content": summary.get("jsonContent"),
                "created_at": created_at_str,
                "created_at_obj": created_at
            }
            prev_summaries.append(summary_data)

        logger.info(f"📋 Found {len(prev_summaries)} previous summaries for user {user_id}")
        
        # Check if latest summary is less than 6 months old
        if prev_summaries:
            latest_summary = prev_summaries[0]  # Already sorted DESC
            latest_created = latest_summary.get("created_at_obj")
            
            logger.info(f"⏰ Latest summary created at: {latest_created}")
            
            if latest_created:
                # Convert to datetime if needed
                if isinstance(latest_created, str):
                    from dateutil import parser
                    latest_created = parser.parse(latest_created)
                
                # Make timezone-aware if needed
                if latest_created.tzinfo is None:
                    latest_created = latest_created.replace(tzinfo=timezone.utc)
                
                now = datetime.now(timezone.utc)
                time_diff = now - latest_created
                
                # Check: 180-day cooldown for rebalancing
                cooldown_period = timedelta(days=180)
                
                logger.info(f"⏱️ Time since last run: {time_diff.days} days (cooldown: 180 days)")
                
                if time_diff < cooldown_period:
                    days_remaining = (cooldown_period - time_diff).days
                    logger.warning(f"🚫 COOLDOWN ACTIVE: {time_diff.days} days elapsed, {days_remaining} days remaining")
                    await auth_db.disconnect()
                    return RebalanceTriggerResponse(
                        success=False,
                        message=f"Low-risk pipeline cannot be re-triggered before 180 days. Last run was {time_diff.days} days ago. Please wait {days_remaining} more days.",
                        task_id=None,
                        user_id=user_id,
                        fund_allocated=allocated_cash,
                        summaries_count=len(prev_summaries)
                    )
                else:
                    logger.info(f"✅ Cooldown period passed ({time_diff.days} days > 180 days)")
            
            # Prepare summary data for pipeline
            to_send_summary = {
                "industry_list": prev_summaries[0]["content"]["industry_list"], 
                "final_portfolio": prev_summaries[0]["content"]["final_portfolio"]
            }
        else:
            logger.info(f"ℹ️ No previous summaries found - first run for user {user_id}")

    except Exception as e:
        logger.error(f"❌ Failed to check 6-month cooldown: {e}", exc_info=True)
        cooldown_check_failed = True
    finally:
        await auth_db.disconnect()
    
    # If cooldown check failed due to database error, we should not proceed
    if cooldown_check_failed:
        raise HTTPException(
            status_code=500,
            detail="Failed to verify 6-month cooldown period. Please try again."
        )
   
    # 4. Check if pipeline is already running (after cooldown check)
    redis_client = Redis.from_url(BROKER_URL)
    pipeline_status = PipelineStatus(redis_client, user_id)
    
    is_running, start_time = pipeline_status.is_running()
    if is_running:
        import time
        elapsed = int((time.time() - start_time) / 60) if start_time else 0
        
        # Check queue length to show position
        queue_length = redis_client.llen("low_risk_pipeline")
        queue_msg = f" ({queue_length} tasks queued)" if queue_length > 0 else ""
        
        return RebalanceTriggerResponse(
            success=False,
            message=f"Pipeline already running (for {elapsed} minutes){queue_msg}. Wait for completion.",
            task_id=None,
            user_id=user_id,
            fund_allocated=allocated_cash,
            summaries_count=len(prev_summaries)
        )
   
    # 5. Check for open positions - must be ZERO for rebalance
    open_positions = getattr(low_risk_allocation, "positions", []) or []
    if len(open_positions) > 0:
        return RebalanceTriggerResponse(
            success=False,
            message=f"Cannot rebalance: {len(open_positions)} open positions exist. Close all positions first.",
            task_id=None,
            user_id=user_id,
            fund_allocated=float(low_risk_allocation.allocated_amount or 0),
            summaries_count=0
        )

    # 6. Check trading agent exists and is active
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
            detail="Trading agent is paused. Please activate the agent before rebalancing."
        )

    if agent_status not in ["active", "running"]:
        raise HTTPException(
            status_code=400,
            detail=f"Trading agent status is '{agent_status}'. Expected 'active' or 'running'."
        )

    # 7. Validate allocated cash (already fetched earlier)
    if allocated_cash <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"No cash available for rebalancing. Available: ₹{allocated_cash:,.2f}"
        )

    logger.info(
        f"✅ Rebalance pre-checks passed | User: {user_id} | Agent: {trading_agent.id} | "
        f"Available Cash: ₹{allocated_cash:,.2f} | Open Positions: 0"
    )

    # 8. Acquire lock BEFORE queuing rebalance task
    if not pipeline_status.acquire_lock(ttl=7200):  # 2 hour lock
        logger.warning(f"⚠️ Failed to acquire rebalance lock for user {user_id}")
        return RebalanceTriggerResponse(
            success=False,
            message="Pipeline lock already acquired. Please wait...",
            task_id=None,
            user_id=user_id,
            fund_allocated=allocated_cash,
            summaries_count=len(prev_summaries)
        )

    # 9. Trigger pipeline with rebalance=True
    try:
        # Extract the actual summary content from the latest summary
        latest_summary_content = {}
        if prev_summaries:
            latest_summary_content = prev_summaries[-1].get("content", {})
            logger.info(f"📋 Using latest summary with keys: {list(latest_summary_content.keys())}")
        
        from celery_app import celery_app
        
        result = celery_app.send_task(
            "pipeline.low_risk.run",
            args=[user_id],
            kwargs={
                "fund_allocated": allocated_cash,
                "rebalance": True,
                "prev_summary": to_send_summary,
                "_skip_lock": True,  # Lock already acquired above
            },
            queue="low_risk_pipeline",
            routing_key="low_risk_pipeline"
        )

        # Check queue length after queuing to inform user
        queue_length = redis_client.llen("low_risk_pipeline")
        
        logger.info(
            f"✅ Low-risk rebalance triggered for user {user_id}, task_id: {result.id}, "
            f"queue_position: {queue_length}, summaries: {len(prev_summaries)}"
        )
        
        # Build status message based on queue
        if queue_length > 1:
            status_msg = f"Rebalance queued (position {queue_length} in queue). Will start when current task completes."
        elif queue_length == 1:
            status_msg = f"Rebalance starting now with {len(prev_summaries)} previous summaries."
        else:
            status_msg = f"Rebalance started with {len(prev_summaries)} previous summaries."

        return RebalanceTriggerResponse(
            success=True,
            message=status_msg,
            task_id=result.id,
            user_id=user_id,
            fund_allocated=allocated_cash,
            summaries_count=len(prev_summaries)
        )

    except Exception as e:
        # Release lock if task queueing failed
        pipeline_status.release_lock()
        logger.error(f"❌ Failed to trigger rebalance for user {user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger rebalance: {str(e)}"
        )


__all__ = ["router"]
