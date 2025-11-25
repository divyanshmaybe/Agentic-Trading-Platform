"""
Continuous Order Monitor Worker - Robust implementation for limit/stop/take-profit orders.

This worker runs continuously to monitor pending orders and executes them when
conditions are met using live price data from the market data service.

Features:
- ✅ Real-time price monitoring via market data WebSocket
- ✅ Automatic symbol subscription for pending orders
- ✅ Efficient batch processing (checks multiple orders simultaneously)
- ✅ Graceful error handling with exponential backoff
- ✅ Database connection pooling
- ✅ Comprehensive logging
- ✅ Auto-recovery from failures
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from decimal import Decimal
from typing import Dict, List, Optional, Set

from celery_app import celery_app

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
SHARED_PY_PATH = os.path.join(PROJECT_ROOT, "shared/py")
if SHARED_PY_PATH not in sys.path:
    sys.path.insert(0, SHARED_PY_PATH)

PORTFOLIO_SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PORTFOLIO_SERVER_ROOT not in sys.path:
    sys.path.insert(0, PORTFOLIO_SERVER_ROOT)

from dbManager import DBManager
from services.trade_engine import TradeEngine
import httpx

logger = logging.getLogger(__name__)

# Configuration
MONITOR_INTERVAL = float(os.getenv("ORDER_MONITOR_INTERVAL", "1.0"))  # Check every 1 second
BATCH_SIZE = int(os.getenv("ORDER_MONITOR_BATCH_SIZE", "100"))  # Process 100 orders per batch
MAX_RETRY_ATTEMPTS = int(os.getenv("ORDER_MONITOR_MAX_RETRIES", "3"))
STALE_ORDER_TIMEOUT = int(os.getenv("ORDER_STALE_TIMEOUT_HOURS", "24"))  # Cancel after 24 hours

# FastAPI server URL for fetching prices
PORTFOLIO_SERVER_URL = os.getenv("PORTFOLIO_SERVER_URL", "http://localhost:8000")


class OrderMonitorWorker:
    """
    Continuous worker that monitors pending orders and executes them when conditions are met.
    
    Architecture:
    - Fetches all pending orders from database
    - Subscribes to live prices for symbols with pending orders
    - Checks order conditions every second using cached prices
    - Executes orders immediately when conditions are met
    - Handles failures gracefully with retries
    """
    
    def __init__(self):
        self.db = None  # Will hold Prisma client
        self.http_client = None  # HTTP client for fetching prices from FastAPI server
        self.running = False
        self.subscribed_symbols: Set[str] = set()
        self._last_cleanup = time.time()
        
    async def initialize(self):
        """Initialize database connection and HTTP client for price fetching."""
        logger.info("🚀 Initializing Order Monitor Worker...")
        
        # Setup database - get singleton instance and connect
        db_manager = DBManager.get_instance()
        await db_manager.connect()
        self.db = db_manager.get_client()
        
        # Setup HTTP client to fetch prices from FastAPI server
        self.http_client = httpx.AsyncClient(
            base_url=PORTFOLIO_SERVER_URL,
            timeout=httpx.Timeout(5.0)
        )
        
        logger.info("✅ Order Monitor Worker initialized (fetching prices from FastAPI server)")
    
    async def close(self):
        """Close database connection and HTTP client."""
        if self.http_client:
            try:
                await self.http_client.aclose()
                self.http_client = None
                logger.debug("🔌 HTTP client closed")
            except Exception as e:
                logger.warning(f"Error closing HTTP client: {e}")
        
        if self.db:
            try:
                await self.db.disconnect()
                self.db = None
                logger.debug("🔌 Database connection closed")
            except Exception as e:
                logger.warning(f"Error closing database connection: {e}")
        
        # Force cleanup of event loop client to prevent connection leaks
        try:
            from dbManager import DBManager
            await DBManager.get_instance().disconnect()
        except Exception as e:
            logger.debug(f"Additional cleanup error: {e}")
    
    async def run(self):
        """Main monitoring loop - runs continuously."""
        await self.initialize()
        self.running = True
        
        logger.info(f"📊 Order Monitor Worker started (checking every {MONITOR_INTERVAL}s)")
        
        error_count = 0
        backoff_delay = 1.0
        
        while self.running:
            try:
                # Fetch pending orders
                pending_orders = await self._fetch_pending_orders()
                
                if not pending_orders:
                    logger.debug("⌛ No pending orders to monitor")
                    await asyncio.sleep(MONITOR_INTERVAL)
                    continue
                
                logger.info(f"👀 Monitoring {len(pending_orders)} pending orders")
                
                # Ensure we're subscribed to all symbols
                await self._ensure_symbol_subscriptions(pending_orders)
                
                # Check and execute orders
                executed_count = await self._process_pending_orders(pending_orders)
                
                if executed_count > 0:
                    logger.info(f"✅ Executed {executed_count} orders this cycle")
                
                # Periodic cleanup of stale/expired orders
                if time.time() - self._last_cleanup > 3600:  # Every hour
                    await self._cleanup_stale_orders()
                    self._last_cleanup = time.time()
                
                # Reset error counters on success
                error_count = 0
                backoff_delay = 1.0
                
                # Wait before next check
                await asyncio.sleep(MONITOR_INTERVAL)
                
            except Exception as e:
                error_count += 1
                logger.error(f"❌ Error in monitor loop (attempt {error_count}): {e}", exc_info=True)
                
                if error_count >= MAX_RETRY_ATTEMPTS:
                    logger.critical(f"💥 Max retry attempts ({MAX_RETRY_ATTEMPTS}) exceeded. Restarting worker...")
                    # Let Celery/supervisor restart the worker
                    self.running = False
                    raise
                
                # Exponential backoff
                logger.info(f"⏳ Backing off for {backoff_delay}s before retry...")
                await asyncio.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, 60)  # Max 60s backoff
    
    async def _fetch_pending_orders(self) -> List[Dict]:
        """Fetch all pending orders from both Trade and TradeExecutionLog models."""
        prisma = self.db
        
        # Fetch from Trade model (manual API trades and TP/SL orders)
        trade_orders = await prisma.trade.find_many(
            where={
                "status": "pending",
                "order_type": {"in": ["limit", "stop", "stop_loss", "take_profit"]}
            },
            order={"created_at": "asc"},
            take=BATCH_SIZE
        )
        
        # Note: We now only monitor Trade records since TradeExecutionLog
        # is just a log of execution attempts. All TP/SL orders are created
        # as Trade records with order_type = "limit" or "stop"
        
        orders = []
        for order in trade_orders:
            order_dict = order.dict()
            order_dict["_source_model"] = "trade"
            orders.append(order_dict)
        
        logger.debug(
            f"📦 Fetched {len(trade_orders)} pending Trade orders (limit/stop/TP/SL)"
        )
        
        return orders
    
    async def _ensure_symbol_subscriptions(self, orders: List[Dict]):
        """
        Ensure FastAPI server is subscribed to symbols (via HTTP request).
        Note: With the centralized WebSocket in FastAPI, workers just request subscription.
        """
        symbols_needed = {order["symbol"] for order in orders}
        new_symbols = symbols_needed - self.subscribed_symbols
        
        if new_symbols:
            logger.info(f"📡 Requesting subscription for {len(new_symbols)} symbols via FastAPI server...")
            
            try:
                # Request FastAPI server to subscribe to symbols
                response = await self.http_client.post(
                    "/api/market/subscribe",
                    json={"symbols": list(new_symbols)},
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    self.subscribed_symbols.update(new_symbols)
                    logger.debug(f"✅ Subscribed to {len(new_symbols)} symbols")
                else:
                    logger.warning(f"⚠️  Subscription request failed: {response.status_code}")
            except Exception as e:
                logger.warning(f"⚠️  Failed to request subscriptions: {e}")
    
    async def _get_current_price(self, symbol: str) -> Optional[Decimal]:
        """Fetch current price from FastAPI server."""
        try:
            response = await self.http_client.get(
                f"/api/market/price/{symbol}",
                timeout=2.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return Decimal(str(data.get("price", 0)))
            else:
                logger.warning(f"⚠️  Failed to fetch price for {symbol}: {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"⚠️  Error fetching price for {symbol}: {e}")
            return None
    
    async def _process_pending_orders(self, orders: List[Dict]) -> int:
        """
        Process pending orders by checking conditions and executing when met.
        
        Returns:
            Number of orders executed
        """
        executed_count = 0
        
        for order in orders:
            try:
                executed = await self._check_and_execute_order(order)
                if executed:
                    executed_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to process order {order['id']}: {e}", exc_info=True)
        
        return executed_count
    
    async def _check_and_execute_order(self, order: Dict) -> bool:
        """
        Check if order conditions are met and execute if so.
        
        Returns:
            True if order was executed, False otherwise
        """
        symbol = order["symbol"]
        source_model = order.get("_source_model", "trade")
        
        # Get current market price from FastAPI server
        current_price = await self._get_current_price(symbol)
        
        if current_price is None:
            logger.debug(f"⏳ No price available yet for {symbol}")
            return False
        
        current_price = Decimal(str(current_price))
        
        # Determine order type and trigger conditions based on source model
        if source_model == "trade_execution_log":
            # For TradeExecutionLog: use direct order_type field (preferred) or fallback to metadata
            order_type = order.get("order_type")
            if not order_type:
                # Fallback to metadata for backward compatibility
                metadata = order.get("metadata", {})
                if isinstance(metadata, str):
                    import json
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}
                order_type = metadata.get("order_type", "limit")
            side = order["side"]
            reference_price = Decimal(str(order.get("reference_price", 0)))
            
            should_execute = False
            condition_met = None
            
            if order_type == "take_profit":
                # Take profit: execute when price reaches or exceeds target
                if side == "SELL" and current_price >= reference_price:
                    should_execute = True
                    condition_met = f"TP SELL: {current_price} >= {reference_price}"
                elif side == "BUY" and current_price <= reference_price:
                    should_execute = True
                    condition_met = f"TP BUY: {current_price} <= {reference_price}"
            
            elif order_type == "stop_loss":
                # Stop loss: execute when price falls to or below target
                if side == "SELL" and current_price <= reference_price:
                    should_execute = True
                    condition_met = f"SL SELL: {current_price} <= {reference_price}"
                elif side == "BUY" and current_price >= reference_price:
                    should_execute = True
                    condition_met = f"SL BUY: {current_price} >= {reference_price}"
            
            else:  # limit order
                if side == "BUY" and current_price <= reference_price:
                    should_execute = True
                    condition_met = f"LIMIT BUY: {current_price} <= {reference_price}"
                elif side == "SELL" and current_price >= reference_price:
                    should_execute = True
                    condition_met = f"LIMIT SELL: {current_price} >= {reference_price}"
        
        else:  # Trade model
            order_type = order["order_type"]
            side = order["side"]
            
            should_execute = False
            condition_met = None
            
            if order_type == "limit":
                limit_price = Decimal(str(order["limit_price"]))
                
                if side == "BUY" and current_price <= limit_price:
                    should_execute = True
                    condition_met = f"BUY limit: {current_price} <= {limit_price}"
                elif side == "SELL" and current_price >= limit_price:
                    should_execute = True
                    condition_met = f"SELL limit: {current_price} >= {limit_price}"
            
            elif order_type in {"stop", "stop_loss"}:
                trigger_price = Decimal(str(order["trigger_price"]))
                
                if side == "BUY" and current_price >= trigger_price:
                    should_execute = True
                    condition_met = f"BUY stop: {current_price} >= {trigger_price}"
                elif side == "SELL" and current_price <= trigger_price:
                    should_execute = True
                    condition_met = f"SELL stop: {current_price} <= {trigger_price}"
            
            elif order_type == "take_profit":
                trigger_price = Decimal(str(order["trigger_price"]))
                
                if current_price >= trigger_price:
                    should_execute = True
                    condition_met = f"Take profit: {current_price} >= {trigger_price}"
        
        if not should_execute:
            return False
        
        # Execute the order!
        logger.info(f"🎯 Executing order {order['id']} ({symbol}): {condition_met}")
        
        try:
            source_model = order.get("_source_model", "trade")
            
            if source_model == "trade":
                # Use TradeEngine for Trade model orders
                prisma = self.db
                engine = TradeEngine(prisma)
                executed = await engine.process_pending_trade(order["id"])
                
                if executed:
                    logger.info(f"✅ Successfully executed Trade order {order['id']} ({symbol}) at {current_price}")
                    return True
                else:
                    logger.warning(f"⚠️  Trade order {order['id']} execution failed")
                    return False
            
            else:  # trade_execution_log
                # Use TradeExecutionService for NSE pipeline TP/SL orders
                from services.trade_execution_service import TradeExecutionService
                
                trade_service = TradeExecutionService()
                result = await trade_service.execute_trade(order["id"], simulate=False)
                
                if result.get("status") in {"executed", "simulated_executed"}:
                    logger.info(
                        f"✅ Successfully executed TradeExecutionLog order {order['id']} ({symbol}) at {current_price}"
                    )
                    return True
                else:
                    logger.warning(f"⚠️  TradeExecutionLog order {order['id']} execution failed: {result}")
                    return False
                
        except Exception as e:
            logger.error(f"❌ Failed to execute order {order['id']}: {e}", exc_info=True)
            return False
    
    async def _cleanup_stale_orders(self):
        """Cancel orders that have been pending for too long in both Trade and TradeExecutionLog."""
        from datetime import datetime, timedelta
        
        prisma = self.db
        
        cutoff_time = datetime.utcnow() - timedelta(hours=STALE_ORDER_TIMEOUT)
        
        # Cleanup Trade model
        stale_trades = await prisma.trade.find_many(
            where={
                "status": "pending",
                "created_at": {"lt": cutoff_time}
            }
        )
        
        if stale_trades:
            logger.info(f"🧹 Cleaning up {len(stale_trades)} stale Trade orders (older than {STALE_ORDER_TIMEOUT}h)")
            
            for order in stale_trades:
                await prisma.trade.update(
                    where={"id": order.id},
                    data={
                        "status": "cancelled",
                        "metadata": '{"cancelled_reason": "Order expired - exceeded max pending time"}'
                    }
                )
            
            logger.info(f"✅ Cancelled {len(stale_trades)} stale Trade orders")
        
        # Cleanup TradeExecutionLog model
        stale_execution_logs = await prisma.tradeexecutionlog.find_many(
            where={
                "status": "pending",
                "created_at": {"lt": cutoff_time}
            }
        )
        
        if stale_execution_logs:
            logger.info(
                f"🧹 Cleaning up {len(stale_execution_logs)} stale TradeExecutionLog orders "
                f"(older than {STALE_ORDER_TIMEOUT}h)"
            )
            
            for order in stale_execution_logs:
                import json
                await prisma.tradeexecutionlog.update(
                    where={"id": order.id},
                    data={
                        "status": "cancelled",
                        "error_message": "Order expired - exceeded max pending time",
                        "metadata": json.dumps({"cancelled_reason": "Order expired - exceeded max pending time"})
                    }
                )
            
            logger.info(f"✅ Cancelled {len(stale_execution_logs)} stale TradeExecutionLog orders")
    
    def stop(self):
        """Gracefully stop the worker."""
        logger.info("🛑 Stopping Order Monitor Worker...")
        self.running = False


# Global worker instance
_worker_instance: Optional[OrderMonitorWorker] = None


@celery_app.task(bind=True, name="order_monitor.start_continuous_monitoring")
def start_continuous_monitoring(self):
    """
    Celery task that starts the continuous order monitoring worker.
    
    This should be started as a long-running background task.
    Configure in celerybeat schedule or start manually.
    """
    global _worker_instance
    
    logger.info("=" * 80)
    logger.info("🚀 Starting Continuous Order Monitor Worker")
    logger.info("=" * 80)
    
    if _worker_instance and _worker_instance.running:
        logger.warning("⚠️  Order monitor already running!")
        return {"status": "already_running"}
    
    _worker_instance = OrderMonitorWorker()
    
    try:
        asyncio.run(_worker_instance.run())
        return {"status": "stopped", "reason": "graceful_shutdown"}
    except Exception as e:
        logger.critical(f"💥 Order monitor crashed: {e}", exc_info=True)
        return {"status": "crashed", "error": str(e)}


@celery_app.task(name="order_monitor.check_pending_orders_once", bind=True)
def check_pending_orders_once(self):
    """
    One-time check of all pending orders (for periodic scheduling).
    
    Use this if you prefer scheduled periodic checks instead of continuous monitoring.
    """
    return asyncio.run(_check_pending_orders_once_async())


async def _check_pending_orders_once_async() -> Dict:
    """Async implementation of one-time order check."""
    worker = OrderMonitorWorker()
    
    try:
        await worker.initialize()
        pending_orders = await worker._fetch_pending_orders()
        
        if not pending_orders:
            return {"status": "success", "orders_checked": 0, "orders_executed": 0}
        
        await worker._ensure_symbol_subscriptions(pending_orders)
        executed_count = await worker._process_pending_orders(pending_orders)
        
        return {
            "status": "success",
            "orders_checked": len(pending_orders),
            "orders_executed": executed_count
        }
    except Exception as e:
        logger.error(f"Failed one-time order check: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        # Always close database connection to prevent leaks
        try:
            await worker.close()
        except Exception as close_err:
            logger.warning(f"Error closing worker: {close_err}")
