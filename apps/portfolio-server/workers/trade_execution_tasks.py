from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Optional

from celery.utils.log import get_task_logger

from celery_app import celery_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.trade_execution_service import TradeExecutionService  # type: ignore  # noqa: E402

task_logger = get_task_logger(__name__)


async def _execute_trade_job_async(
    trade_id: str, 
    simulate: Optional[bool],
    signal_timestamp: Optional[float] = None
) -> dict[str, Any]:
    """Execute trade and track latency metrics."""
    exec_start = time.time()
    
    service = TradeExecutionService(logger=task_logger)
    task_logger.info("🔄 Processing trade execution for trade_id: %s (simulate=%s)", trade_id, simulate)
    await service.update_status(trade_id, status="in_progress")
    result = await service.execute_trade(trade_id, simulate=simulate)
    
    # Calculate trade_delay (time from signal to execution completion)
    exec_time_ms = int((time.time() - exec_start) * 1000)
    trade_delay_ms = None
    if signal_timestamp:
        trade_delay_ms = int((time.time() - signal_timestamp) * 1000)
    
    # Update trade with delay metrics
    try:
        from db_context import get_db_connection
        async with get_db_connection() as client:
            # Update trade execution log with delay
            await client.tradeexecutionlog.update_many(
                where={"trade_id": trade_id},
                data={"trade_delay": trade_delay_ms or exec_time_ms}
            )
            task_logger.info(
                "✅ Trade %s executed in %dms (total delay: %dms)",
                trade_id[:8], exec_time_ms, trade_delay_ms or exec_time_ms
            )
    except Exception as e:
        task_logger.warning("Failed to update trade_delay: %s", e)
    
    result["exec_time_ms"] = exec_time_ms
    result["trade_delay_ms"] = trade_delay_ms
    
    task_logger.info("✅ Trade execution completed for trade_id: %s | Status: %s", trade_id, result.get("status", "unknown"))
    return result


@celery_app.task(
    bind=True,
    name="trading.execute_trade_job",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=10,  # Max backoff 10 seconds (faster retries)
    retry_kwargs={"max_retries": 3},
    # CRITICAL: No rate limit - trades must execute immediately
    rate_limit=None,
    # High priority for trading tasks
    priority=9,
    # Shorter timeouts - trades should execute fast
    soft_time_limit=60,  # 1 minute soft limit
    time_limit=90,  # 1.5 minutes hard limit
    # Acknowledge late for reliability
    acks_late=True,
)
def execute_trade_job(
    self, 
    trade_id: str, 
    simulate: Optional[bool] = None,
    signal_timestamp: Optional[float] = None
) -> dict[str, Any]:
    """
    Celery task that executes a persisted trade job.
    
    Args:
        trade_id: The ID of the trade to execute
        simulate: Whether to simulate the trade (paper trading)
        signal_timestamp: Unix timestamp when the signal was generated (for latency tracking)
    
    Returns:
        dict with execution result including trade_delay_ms
    """
    task_logger.info("🚀 Trade execution task started for %s (priority=9)", trade_id[:8])
    
    try:
        return asyncio.run(_execute_trade_job_async(trade_id, simulate, signal_timestamp))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_execute_trade_job_async(trade_id, simulate, signal_timestamp))
        finally:
            asyncio.set_event_loop(None)
            loop.close()

