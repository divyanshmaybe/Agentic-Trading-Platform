"""
Streaming risk monitor worker - Real-time position monitoring with sub-second alerts.

This worker runs continuously in the background, monitoring all active positions
via WebSocket price feeds and emitting alerts instantly when thresholds are breached.

USAGE:
    python -m workers.streaming_risk_monitor

ENVIRONMENT:
    STREAMING_RISK_MONITOR_ENABLED - Enable streaming monitor (default: true)
    RISK_MONITOR_POLL_INTERVAL - Polling interval in seconds (default: 0.5)
    RISK_MONITOR_REFRESH_POSITIONS - Auto-refresh positions every N seconds (default: 30)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipelines.risk.risk_monitor_pipeline import (
    RiskMonitorRequest,
    StreamingRiskMonitor,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
ENABLED = os.getenv("STREAMING_RISK_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
POLL_INTERVAL = float(os.getenv("RISK_MONITOR_POLL_INTERVAL", "0.5"))
REFRESH_INTERVAL = int(os.getenv("RISK_MONITOR_REFRESH_POSITIONS", "30"))

# Global monitor instance
_monitor: Optional[StreamingRiskMonitor] = None
_shutdown_event = asyncio.Event()


async def get_active_positions() -> List[RiskMonitorRequest]:
    """
    Fetch all active positions from database that need risk monitoring.
    
    This is called periodically to refresh the position set being monitored.
    """
    try:
        from db import get_db_client
        from utils.symbol_based_risk_monitor import collect_risk_monitor_requests
        from market_data import get_market_data_service
        
        db = get_db_client()
        market_service = get_market_data_service()
        
        # Use existing helper to collect positions
        requests, metadata = await collect_risk_monitor_requests(
            db,
            market_service,
            logger=logger,
        )
        
        logger.info(
            f"Position refresh: {len(requests)} positions across "
            f"{metadata.get('unique_symbols', 0)} symbols"
        )
        
        return requests
        
    except Exception as exc:
        logger.exception(f"Failed to refresh positions: {exc}")
        return []


def get_positions_sync() -> List[RiskMonitorRequest]:
    """Synchronous wrapper for position callback."""
    try:
        return asyncio.run(get_active_positions())
    except Exception as exc:
        logger.exception(f"Position callback failed: {exc}")
        return []


async def start_monitor():
    """Start the streaming risk monitor."""
    global _monitor
    
    if not ENABLED:
        logger.warning("Streaming risk monitor disabled via STREAMING_RISK_MONITOR_ENABLED=false")
        return
    
    logger.info(
        f"Starting streaming risk monitor (poll: {POLL_INTERVAL}s, refresh: {REFRESH_INTERVAL}s)"
    )
    
    # Initialize monitor with position refresh callback
    _monitor = StreamingRiskMonitor(
        name="production_risk_monitor",
        poll_interval_sec=POLL_INTERVAL,
        get_positions_callback=get_positions_sync,
        alert_callback=None,  # Use default Kafka publishing
    )
    
    # Load initial positions
    initial_positions = await get_active_positions()
    logger.info(f"Loaded {len(initial_positions)} initial positions")
    
    # Start streaming
    _monitor.start(initial_positions=initial_positions)
    
    # Keep monitor running in background
    logger.info("Streaming risk monitor started successfully")
    
    # Periodic position refresh loop
    while not _shutdown_event.is_set():
        try:
            await asyncio.sleep(REFRESH_INTERVAL)
            
            if _monitor and _monitor.is_running:
                fresh_positions = await get_active_positions()
                _monitor.update_positions(fresh_positions)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception(f"Position refresh loop error: {exc}")
            await asyncio.sleep(5)  # Back off on error


async def stop_monitor():
    """Stop the streaming risk monitor gracefully."""
    global _monitor
    
    if _monitor and _monitor.is_running:
        logger.info("Stopping streaming risk monitor...")
        _monitor.stop()
        logger.info("Streaming risk monitor stopped")


def handle_shutdown(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_event.set()


async def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        await start_monitor()
        
        # Wait for shutdown signal
        await _shutdown_event.wait()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as exc:
        logger.exception(f"Fatal error in streaming risk monitor: {exc}")
    finally:
        await stop_monitor()
        logger.info("Streaming risk monitor exited")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Streaming risk monitor terminated")
