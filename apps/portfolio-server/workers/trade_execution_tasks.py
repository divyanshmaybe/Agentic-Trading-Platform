from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

from celery.utils.log import get_task_logger

from celery_app import celery_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.trade_execution_service import TradeExecutionService  # type: ignore  # noqa: E402

task_logger = get_task_logger(__name__)


async def _execute_trade_job_async(trade_id: str, simulate: Optional[bool]) -> dict[str, Any]:
    service = TradeExecutionService(logger=task_logger)
    task_logger.info("🔄 Processing trade execution for trade_id: %s (simulate=%s)", trade_id, simulate)
    await service.update_status(trade_id, status="in_progress")
    result = await service.execute_trade(trade_id, simulate=simulate)
    task_logger.info("✅ Trade execution completed for trade_id: %s | Status: %s", trade_id, result.get("status", "unknown"))
    return result


@celery_app.task(
    bind=True,
    name="trading.execute_trade_job",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,  # Max backoff 30 seconds
    retry_kwargs={"max_retries": 3},
    # CRITICAL: No rate limit - trades must execute immediately
    rate_limit=None,
    # High priority for trading tasks
    priority=9,
    # Reasonable timeouts for trade execution
    soft_time_limit=120,
    time_limit=180,
)
def execute_trade_job(self, trade_id: str, simulate: Optional[bool] = None) -> dict[str, Any]:
    """Celery task that executes a persisted trade job."""

    try:
        return asyncio.run(_execute_trade_job_async(trade_id, simulate))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_execute_trade_job_async(trade_id, simulate))
        finally:
            asyncio.set_event_loop(None)
            loop.close()

