"""
Streaming order monitor worker - Real-time order execution with sub-second response.

⚠️  LEGACY VERSION - Uses PostgreSQL polling (10s refresh interval)
    For true real-time reactive monitoring, use pathway_order_monitor.py instead.

This worker runs continuously in the background, monitoring all pending orders
via WebSocket price feeds and executing orders instantly when conditions are met.

Architecture:
- Uses MarketDataService singleton with WebSocket connection pooling
- Subscribes to symbols from pending orders automatically
- Checks order conditions in real-time (every 0.5s against cached prices)
- Executes orders immediately via TradeEngine
- Handles connection failures, stale orders, and execution retries

Performance:
- Sub-second response time (price update → order execution)
- Database polling every 10s (can miss events, use Pathway version for true real-time)
- Efficient batch symbol subscription
- Connection pooling and automatic retry logic

USAGE:
    python -m workers.streaming_order_monitor
    
    Or via pnpm:
    pnpm streaming:orders

ENVIRONMENT:
    STREAMING_ORDER_MONITOR_ENABLED - Enable streaming monitor (default: true)
    ORDER_MONITOR_REFRESH_INTERVAL - Refresh orders from DB every N seconds (default: 10)
    ORDER_MONITOR_CHECK_INTERVAL - Check conditions every N seconds (default: 0.5)
    
MIGRATION:
    To use Pathway-based reactive monitoring (recommended):
    - Set STREAMING_ORDER_MONITOR_ENABLED=false
    - Set PATHWAY_ORDER_MONITOR_ENABLED=true
    - Run: pnpm pathway:orders
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

# Load environment variables from .env file
from dotenv import load_dotenv
env_file = Path(__file__).resolve().parents[1] / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ Loaded environment from {env_file}")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipelines.orders.streaming_order_monitor_pipeline import PathwayOrderMonitor

# Market data service and DB manager come from shared/py
sys.path.insert(0, str(PROJECT_ROOT / ".." / ".." / "shared" / "py"))
from market_data import get_market_data_service  # type: ignore
from dbManager import DBManager  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
ENABLED = os.getenv("STREAMING_ORDER_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
REFRESH_INTERVAL = float(os.getenv("ORDER_MONITOR_REFRESH_INTERVAL", "10"))  # Refresh orders every 10s
CHECK_INTERVAL = float(os.getenv("ORDER_MONITOR_CHECK_INTERVAL", "0.1"))  # Check conditions every 0.1s (100ms for sub-second response)

# Global monitor instance
_monitor: Optional[PathwayOrderMonitor] = None
_shutdown_event = asyncio.Event()


async def start_monitor():
    """Start the streaming order monitor."""
    global _monitor
    
    if not ENABLED:
        logger.warning("Streaming order monitor disabled via STREAMING_ORDER_MONITOR_ENABLED=false")
        return
    
    logger.info(
        f"🚀 Starting streaming order monitor "
        f"(refresh: {REFRESH_INTERVAL}s, check: {CHECK_INTERVAL}s)"
    )
    
    try:
        # Get market data service with WebSocket feeds (synchronous singleton)
        market_service = get_market_data_service()
        
        # Ensure WebSocket is initialized
        await market_service._ensure_init()
        logger.info("✅ Connected to MarketDataService")
        
        # Get database client (Prisma) - keep connection alive for long-running monitor
        db_manager = DBManager.get_instance()
        await db_manager.connect()
        db = db_manager.get_client()  # Get Prisma client
        logger.info("✅ Connected to database")
        
        # Initialize streaming order monitor
        _monitor = PathwayOrderMonitor(
            market_data_service=market_service,
            db_client=db,
            execution_callback=None,  # Use default execution
            refresh_interval=REFRESH_INTERVAL,
            check_interval=CHECK_INTERVAL,
        )
        
        # Start monitoring
        _monitor.start()
        
        logger.info("✅ Streaming order monitor started successfully")
        logger.info(
            "📊 Monitoring configuration:\n"
            f"   - Order refresh interval: {REFRESH_INTERVAL}s\n"
            f"   - Condition check interval: {CHECK_INTERVAL}s\n"
            f"   - WebSocket-based price feeds: ENABLED\n"
            f"   - Real-time execution: ENABLED"
        )
        
        # Keep monitor running
        await _shutdown_event.wait()
        
    except Exception as exc:
        logger.exception(f"❌ Failed to start streaming order monitor: {exc}")
        raise


async def stop_monitor():
    """Stop the streaming order monitor gracefully."""
    global _monitor
    
    if _monitor and _monitor.is_running:
        logger.info("Stopping streaming order monitor...")
        _monitor.stop()
        logger.info("Streaming order monitor stopped")
    
    # Force disconnect database on shutdown
    try:
        db_manager = DBManager.get_instance()
        await db_manager.disconnect(force=True)
    except Exception as exc:
        logger.debug(f"Database disconnect error: {exc}")


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
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as exc:
        logger.exception(f"Fatal error in streaming order monitor: {exc}")
    finally:
        await stop_monitor()
        logger.info("Streaming order monitor exited")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Streaming order monitor terminated")
