"""
Celery task for streaming risk monitor - runs continuously in background.

This task starts the real-time risk monitoring pipeline that provides
sub-second alert latency via WebSocket price feeds and Pathway streaming.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from celery_app import celery_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


@celery_app.task(
    name="risk.streaming_monitor.start",
    bind=True,
    time_limit=None,
    soft_time_limit=None,
    acks_late=False,  # Ack immediately - don't redeliver on restart
    max_retries=0,    # Don't retry - this is a long-running monitor
    ignore_result=True,
)
def start_streaming_risk_monitor_task(self):
    """
    Start the streaming risk monitor (long-running background task).
    
    This task runs indefinitely, continuously monitoring positions and
    emitting sub-second risk alerts via Kafka.
    
    Returns:
        Status dict with monitor state
    """
    try:
        logger.info("🚀 Starting streaming risk monitor task...")
        
        # Import here to avoid circular dependencies
        from workers.streaming_risk_monitor import main as monitor_main
        
        # Run the monitor (blocks until stopped)
        asyncio.run(monitor_main())
        
        return {
            "status": "stopped",
            "message": "Streaming risk monitor stopped gracefully"
        }
        
    except Exception as exc:
        logger.exception(f"❌ Streaming risk monitor task failed: {exc}")
        raise


__all__ = ["start_streaming_risk_monitor_task"]
