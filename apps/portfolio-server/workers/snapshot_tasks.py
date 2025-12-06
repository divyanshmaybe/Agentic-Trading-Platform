"""
Celery tasks for capturing trading agent snapshots
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict

# Add server directory to path
server_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(server_dir))

from celery_app import celery_app
from services.snapshot_service import TradingAgentSnapshotService

task_logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="snapshot.capture_agent_snapshots",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    soft_time_limit=None,  # No time limit - quick task but scheduled
    time_limit=None,
)
def capture_trading_agent_snapshots(self) -> Dict[str, Any]:
    """
    Celery task that captures snapshots for all active trading agents.
    
    This task is scheduled to run every 3 hours via Celery Beat.
    It captures portfolio_value and realized_pnl for each active agent.
    
    Returns:
        Dict with summary of capture results
    """
    try:
        task_logger.info("📸 Starting trading agent snapshot capture...")
        
        service = TradingAgentSnapshotService(logger=task_logger)
        
        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(service.capture_all_active_agents())
        finally:
            loop.close()
        
        task_logger.info(
            "✅ Snapshot capture complete: %d/%d agents, %d failed",
            result.get("snapshots_captured", 0),
            result.get("total_agents", 0),
            result.get("failed", 0),
        )
        
        return result
        
    except Exception as exc:
        task_logger.error("❌ Failed to capture trading agent snapshots: %s", exc, exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="snapshot.capture_portfolio_snapshots",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    soft_time_limit=None,  # No time limit - quick task but scheduled
    time_limit=None,
)
def capture_portfolio_snapshots(self) -> Dict[str, Any]:
    """
    Celery task that captures snapshots for ALL portfolios.
    
    This task is scheduled to run every 3 hours via Celery Beat.
    For each portfolio it captures: current_value, total_pnl, timestamp
    
    Returns:
        Dict with summary of capture results
    """
    try:
        task_logger.info("📸 Starting portfolio snapshot capture...")
        
        service = TradingAgentSnapshotService(logger=task_logger)
        
        # Run async function in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(service.capture_all_portfolio_snapshots())
        finally:
            loop.close()
        
        task_logger.info(
            "✅ Portfolio snapshot capture complete: %d/%d portfolios, %d failed",
            result.get("snapshots_captured", 0),
            result.get("total_portfolios", 0),
            result.get("failed", 0),
        )
        
        return result
        
    except Exception as exc:
        task_logger.error("❌ Failed to capture portfolio snapshots: %s", exc, exc_info=True)
        raise
