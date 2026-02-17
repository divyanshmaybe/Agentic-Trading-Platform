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
import threading
from pathlib import Path
from typing import Any, Coroutine, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipelines.risk.risk_monitor_pipeline import (
    RiskMonitorRequest,
    StreamingRiskMonitor,
)
from db_context import get_db_connection
from market_data import get_market_data_service
from utils.risk_monitor import prepare_risk_monitor_requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress verbose HTTP and network logging
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("hpack").setLevel(logging.ERROR)
logging.getLogger("anyio").setLevel(logging.ERROR)

# Configuration
ENABLED = os.getenv("STREAMING_RISK_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
POLL_INTERVAL = float(os.getenv("RISK_MONITOR_POLL_INTERVAL", "0.5"))
REFRESH_INTERVAL = int(os.getenv("RISK_MONITOR_REFRESH_POSITIONS", "30"))

# Global monitor instance
_monitor: Optional[StreamingRiskMonitor] = None
_shutdown_event = asyncio.Event()


# Dedicated event loop for DB lookups invoked from sync callbacks
_positions_loop = asyncio.new_event_loop()


def _start_positions_loop() -> None:
    asyncio.set_event_loop(_positions_loop)
    _positions_loop.run_forever()


_positions_thread = threading.Thread(
    target=_start_positions_loop,
    name="risk-monitor-db-loop",
    daemon=True,
)
_positions_thread.start()


def _run_on_positions_loop(
    coro: Coroutine[Any, Any, List[RiskMonitorRequest]],
) -> List[RiskMonitorRequest]:
    future = asyncio.run_coroutine_threadsafe(coro, _positions_loop)
    return future.result()


async def get_active_positions() -> List[RiskMonitorRequest]:
    """
    Fetch all active positions from database that need risk monitoring.
    
    This is called periodically to refresh the position set being monitored.
    Uses context manager to ensure connection is always cleaned up.
    """
    try:
        # Use context manager to guarantee cleanup
        async with get_db_connection() as client:
            positions = await client.position.find_many(
                where={"status": "open"},
                include={"portfolio": True},
            )

            if not positions:
                # Only log "no positions" every 30 seconds to reduce noise
                global _last_no_pos_log
                try:
                    _last_no_pos_log
                except NameError:
                    _last_no_pos_log = 0
                import time
                if time.time() - _last_no_pos_log >= 30:
                    logger.info("Position refresh: no open positions found")
                    _last_no_pos_log = time.time()
                return []

            try:
                market_service = get_market_data_service()
            except Exception as market_exc:
                logger.warning("Market data service unavailable: %s", market_exc)
                market_service = None

            requests = prepare_risk_monitor_requests(
            positions,
            market_data_service=market_service,
            logger=logger,
        )

        unique_symbols = {req.symbol for req in requests if req.symbol}
        # Only log position refresh every 60 seconds to reduce noise
        global _last_pos_refresh_log
        try:
            _last_pos_refresh_log
        except NameError:
            _last_pos_refresh_log = 0
        import time
        if time.time() - _last_pos_refresh_log >= 60:
            logger.info(
                "Position refresh: %s positions across %s symbols",
                len(requests),
                len(unique_symbols),
            )
            _last_pos_refresh_log = time.time()

        return requests

    except Exception as exc:
        # Only log errors every 30 seconds to avoid spam
        global _last_error_log
        try:
            _last_error_log
        except NameError:
            _last_error_log = 0
        import time
        if time.time() - _last_error_log >= 30:
            logger.error(f"Failed to refresh positions: {exc}")
            _last_error_log = time.time()
        return []


def get_positions_sync() -> List[RiskMonitorRequest]:
    """Synchronous wrapper for position callback."""
    try:
        return _run_on_positions_loop(get_active_positions())
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
