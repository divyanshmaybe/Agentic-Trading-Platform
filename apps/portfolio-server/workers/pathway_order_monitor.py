"""
Pathway-based order monitor worker - True real-time reactive monitoring.

This is the NEW implementation using Pathway reactive streams:
- Trades published to Redis → Pathway subscribes → Instant reaction
- Zero database polling (only Redis pub/sub)
- Sub-100ms latency from trade execution to TP/SL monitoring
- True reactive architecture matching NSE pipeline design

USAGE:
    python -m workers.pathway_order_monitor
    
    Or via pnpm:
    pnpm pathway:orders

ENVIRONMENT:
    PATHWAY_ORDER_MONITOR_ENABLED - Enable Pathway monitor (default: true)
    REDIS_HOST - Redis host (default: localhost)
    REDIS_PORT - Redis port (default: 6379)
    
REDIS CHANNELS:
    - trades:executed - New executed trades with TP/SL
    - trades:pending - New pending orders (limit/stop)
    - trades:cancelled - Cancelled orders (cleanup)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

# Load environment variables
from dotenv import load_dotenv
env_file = Path(__file__).resolve().parents[1] / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ Loaded environment from {env_file}")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Market data service
sys.path.insert(0, str(PROJECT_ROOT / ".." / ".." / "shared" / "py"))
from market_data import get_market_data_service  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
ENABLED = os.getenv("PATHWAY_ORDER_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

_pathway_thread: Optional[any] = None
_shutdown_event = asyncio.Event()


def run_pathway_monitor():
    """Run Pathway monitor in separate thread"""
    import pathway as pw
    from pipelines.orders.pathway_order_monitor import create_pathway_order_monitor
    
    logger.info("🚀 Starting Pathway order monitor...")
    
    try:
        # Get market data service
        market_service = get_market_data_service()
        
        # Create Pathway pipeline
        tables = create_pathway_order_monitor(
            redis_host=REDIS_HOST,
            redis_port=REDIS_PORT,
            market_data_service=market_service,
        )
        
        logger.info("✅ Pathway pipeline created, starting computation...")
        logger.info(
            f"📊 Monitoring configuration:\n"
            f"   - Redis pub/sub: {REDIS_HOST}:{REDIS_PORT}\n"
            f"   - Channels: trades:executed, trades:pending\n"
            f"   - Real-time reactive: ENABLED\n"
            f"   - Database polling: DISABLED"
        )
        
        # Run Pathway computation (blocking)
        pw.run(monitoring_level=pw.MonitoringLevel.NONE)
        
    except Exception as exc:
        logger.exception(f"❌ Pathway monitor failed: {exc}")
        raise


async def start_monitor():
    """Start the Pathway order monitor"""
    global _pathway_thread
    
    if not ENABLED:
        logger.warning("Pathway order monitor disabled via PATHWAY_ORDER_MONITOR_ENABLED=false")
        return
    
    try:
        # Run Pathway in a separate thread (it's blocking)
        import threading
        _pathway_thread = threading.Thread(target=run_pathway_monitor, daemon=True)
        _pathway_thread.start()
        
        logger.info("✅ Pathway order monitor started in background thread")
        
        # Keep alive
        await _shutdown_event.wait()
        
    except Exception as exc:
        logger.exception(f"❌ Failed to start Pathway monitor: {exc}")
        raise


async def stop_monitor():
    """Stop the Pathway order monitor"""
    global _pathway_thread
    
    if _pathway_thread and _pathway_thread.is_alive():
        logger.info("Stopping Pathway order monitor...")
        # Pathway pw.run() doesn't have a clean stop mechanism
        # It will exit when the thread is terminated
        logger.info("Pathway order monitor stopped")


def handle_shutdown(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    _shutdown_event.set()


async def main():
    """Main entry point"""
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    try:
        await start_monitor()
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as exc:
        logger.exception(f"Fatal error in Pathway monitor: {exc}")
    finally:
        await stop_monitor()
        logger.info("Pathway order monitor exited")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Pathway order monitor terminated")
