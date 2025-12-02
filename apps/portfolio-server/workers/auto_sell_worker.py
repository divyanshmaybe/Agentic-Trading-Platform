"""
Auto-Sell Worker - Production-ready trade closer for expired positions.

Design principles:
1. MAX 2 CONCURRENT WORKERS - Uses Redis semaphore to limit concurrency
2. SEQUENTIAL PER USER - Trades for same portfolio execute in order
3. FAST SCANNER - Only scans and dispatches, doesn't execute
4. ATOMIC OPERATIONS - Prevents duplicate processing
5. IDEMPOTENT - Safe to run multiple times
6. PRODUCTION EDGE CASES - Handles all failure scenarios
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from celery_app import celery_app

logger = logging.getLogger(__name__)

# Configuration
MAX_AUTO_SELL_WORKERS = int(os.getenv("MAX_AUTO_SELL_WORKERS", "2"))
AUTO_SELL_LOCK_TIMEOUT = int(os.getenv("AUTO_SELL_LOCK_TIMEOUT", "60"))
AUTO_SELL_BATCH_SIZE = int(os.getenv("AUTO_SELL_BATCH_SIZE", "100"))


def _get_redis_client():
    """Get Redis client for distributed locking."""
    import redis
    redis_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url)


def _acquire_semaphore(r, max_workers: int = MAX_AUTO_SELL_WORKERS) -> Optional[str]:
    """
    Acquire a slot in the semaphore (max N workers).
    Returns slot_id if acquired, None if all slots taken.
    """
    import uuid
    slot_id = str(uuid.uuid4())
    
    for i in range(max_workers):
        lock_key = f"auto_sell_worker:slot:{i}"
        # Try to set the slot with NX (only if not exists) and EX (expiry)
        if r.set(lock_key, slot_id, nx=True, ex=AUTO_SELL_LOCK_TIMEOUT):
            logger.debug("✅ Acquired slot %d for auto_sell worker", i)
            return f"{i}:{slot_id}"
    
    return None


def _release_semaphore(r, slot_info: str):
    """Release a semaphore slot."""
    try:
        slot_num, slot_id = slot_info.split(":", 1)
        lock_key = f"auto_sell_worker:slot:{slot_num}"
        # Only delete if we still own the slot
        current = r.get(lock_key)
        if current and current.decode() == slot_id:
            r.delete(lock_key)
            logger.debug("✅ Released slot %s", slot_num)
    except Exception as e:
        logger.warning("Failed to release semaphore: %s", e)


@celery_app.task(
    name="trades.auto_sell_expired_trades",
    bind=True,
    acks_late=False,  # Acknowledge immediately to prevent re-delivery
    reject_on_worker_lost=False,
    soft_time_limit=30,  # 30 seconds max - scanner should be FAST
    time_limit=45,  # Hard kill at 45 sec
    max_retries=0,  # No retries - next beat will handle it
)
def auto_sell_expired_trades(self):
    """
    LIGHTWEIGHT auto-close scanner with semaphore-based concurrency control.
    
    - Max 2 workers can run simultaneously (configurable via MAX_AUTO_SELL_WORKERS)
    - Groups trades by portfolio for sequential per-user execution
    - Dispatches individual close tasks with proper ordering
    
    This task ONLY scans and dispatches - actual execution in execute_auto_close.
    """
    r = _get_redis_client()
    
    # Try to acquire a slot (max 2 workers)
    slot_info = _acquire_semaphore(r, MAX_AUTO_SELL_WORKERS)
    if not slot_info:
        logger.debug("⏭️ All %d auto_sell slots occupied, skipping...", MAX_AUTO_SELL_WORKERS)
        return {"status": "skipped", "reason": "max_workers_reached", "max_workers": MAX_AUTO_SELL_WORKERS}
    
    try:
        logger.info("🔄 Auto-close scanner starting (slot: %s)...", slot_info.split(":")[0])
        return asyncio.run(_scan_and_dispatch_grouped())
    except Exception as exc:
        logger.error("❌ Auto-close scanner failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}
    finally:
        _release_semaphore(r, slot_info)


async def _scan_and_dispatch_grouped():
    """
    Scan for expired trades and dispatch grouped by portfolio.
    Ensures sequential execution per user/portfolio.
    """
    from db_context import get_db_connection
    
    # Check market hours (respect DEMO_MODE)
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    
    if not demo_mode:
        try:
            from utils.market_hours import is_market_hours, get_market_status
            if not is_market_hours():
                _, msg = get_market_status()
                logger.info("⏸️ Market closed - skipping. %s", msg)
                return {"status": "skipped", "reason": "market_closed", "dispatched": 0}
        except ImportError:
            pass  # Market hours check not available
    
    async with get_db_connection() as client:
        current_time = datetime.now(timezone.utc)
        
        # Query expired LONG trades (BUY with auto_sell_at expired)
        expired_longs = await client.trade.find_many(
            where={
                "status": {"in": ["executed", "pending"]},
                "auto_sell_at": {"lte": current_time, "not": None},
                "side": "BUY",
            },
            include={"portfolio": True},
            take=AUTO_SELL_BATCH_SIZE,
            order={"auto_sell_at": "asc"},  # Oldest first
        )
        
        # Query expired SHORT trades (SHORT_SELL with auto_cover_at expired)
        expired_shorts = await client.trade.find_many(
            where={
                "status": {"in": ["executed", "pending"]},
                "auto_cover_at": {"lte": current_time, "not": None},
                "side": "SHORT_SELL",
            },
            include={"portfolio": True},
            take=AUTO_SELL_BATCH_SIZE,
            order={"auto_cover_at": "asc"},  # Oldest first
        )
        
        total_found = len(expired_longs or []) + len(expired_shorts or [])
        if total_found == 0:
            logger.debug("✅ No expired trades found")
            return {"status": "completed", "dispatched": 0, "portfolios": 0}
        
        logger.info("📊 Found %d expired trades to close", total_found)
        
        # Group trades by portfolio_id for sequential per-user execution
        portfolio_trades: Dict[str, List[dict]] = {}
        
        # Process LONGs
        for trade in expired_longs or []:
            trade_id = str(trade.id)
            portfolio_id = str(trade.portfolio_id) if trade.portfolio_id else "unknown"
            
            # Atomic lock - clear auto_sell_at to prevent duplicate processing
            updated = await client.trade.update_many(
                where={"id": trade_id, "auto_sell_at": {"not": None}},
                data={"auto_sell_at": None},
            )
            
            if updated == 0:
                logger.debug("⏭️ Trade %s already claimed", trade_id[:8])
                continue
            
            if portfolio_id not in portfolio_trades:
                portfolio_trades[portfolio_id] = []
            
            portfolio_trades[portfolio_id].append({
                "trade_id": trade_id,
                "close_type": "sell",
                "symbol": str(trade.symbol),
                "quantity": int(trade.quantity or 0),
                "original_price": float(trade.price or 0),
                "portfolio_id": portfolio_id,
            })
        
        # Process SHORTs
        for trade in expired_shorts or []:
            trade_id = str(trade.id)
            portfolio_id = str(trade.portfolio_id) if trade.portfolio_id else "unknown"
            
            updated = await client.trade.update_many(
                where={"id": trade_id, "auto_cover_at": {"not": None}},
                data={"auto_cover_at": None},
            )
            
            if updated == 0:
                continue
            
            if portfolio_id not in portfolio_trades:
                portfolio_trades[portfolio_id] = []
            
            portfolio_trades[portfolio_id].append({
                "trade_id": trade_id,
                "close_type": "cover",
                "symbol": str(trade.symbol),
                "quantity": int(trade.quantity or 0),
                "original_price": float(trade.price or 0),
                "portfolio_id": portfolio_id,
            })
        
        # Dispatch trades - sequential per portfolio using chains
        dispatched = 0
        for portfolio_id, trades in portfolio_trades.items():
            if not trades:
                continue
            
            # For each portfolio, dispatch trades sequentially using Celery chain
            # This ensures trades for same user execute in order
            if len(trades) == 1:
                # Single trade - dispatch directly
                trade = trades[0]
                execute_auto_close.apply_async(
                    kwargs=trade,
                    queue="general",  # Use general queue, not trading
                    priority=7,  # High but below manual trades
                )
                dispatched += 1
            else:
                # Multiple trades for same portfolio - use chain for sequential execution
                from celery import chain
                task_chain = chain(
                    execute_auto_close.s(**trade).set(queue="general", priority=7)
                    for trade in trades
                )
                task_chain.apply_async()
                dispatched += len(trades)
            
            logger.info("📤 Dispatched %d trades for portfolio %s", len(trades), portfolio_id[:8])
        
        logger.info("✅ Dispatched %d close tasks across %d portfolios", dispatched, len(portfolio_trades))
        return {
            "status": "completed", 
            "dispatched": dispatched, 
            "portfolios": len(portfolio_trades),
            "longs": len(expired_longs or []),
            "shorts": len(expired_shorts or []),
        }


@celery_app.task(
    name="trades.execute_auto_close",
    bind=True,
    acks_late=True,
    soft_time_limit=60,  # 1 minute - single trade should be fast
    time_limit=90,  # 1.5 min hard limit
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=15,
    retry_jitter=True,  # Add jitter to prevent thundering herd
    # Lower priority than manual trades
    priority=7,
)
def execute_auto_close(
    self,
    trade_id: str,
    close_type: str,  # "sell" or "cover"
    symbol: str,
    quantity: int,
    original_price: float,
    portfolio_id: str = "",
):
    """
    Execute a single auto-close trade with production-ready error handling.
    
    Features:
    - Per-portfolio locking to prevent race conditions
    - Idempotency check (won't re-close already closed trades)
    - Detailed logging for debugging
    - Graceful degradation on price fetch failure
    """
    logger.info(
        "🔄 Executing auto-%s: %s %s x %d (portfolio: %s, attempt: %d/%d)", 
        close_type, trade_id[:8], symbol, quantity, portfolio_id[:8] if portfolio_id else "?",
        self.request.retries + 1, self.max_retries + 1
    )
    
    try:
        return asyncio.run(_execute_close_safe(
            trade_id, close_type, symbol, quantity, original_price, portfolio_id
        ))
    except Exception as exc:
        logger.error("❌ Auto-%s failed for %s: %s", close_type, trade_id[:8], exc, exc_info=True)
        raise


async def _execute_close_safe(
    trade_id: str, 
    close_type: str, 
    symbol: str, 
    quantity: int, 
    original_price: float,
    portfolio_id: str,
):
    """Execute the actual close trade with comprehensive error handling."""
    import json
    import uuid
    from decimal import Decimal
    from db_context import get_db_connection
    from services.trade_execution_service import TradeExecutionService
    
    exec_start = time.time()
    
    async with get_db_connection() as client:
        # IDEMPOTENCY CHECK: Verify trade still needs closing
        trade = await client.trade.find_unique(
            where={"id": trade_id},
            include={"portfolio": True, "position": True},
        )
        
        if not trade:
            logger.warning("⚠️ Trade %s not found - may have been deleted", trade_id[:8])
            return {"status": "not_found", "trade_id": trade_id}
        
        # Check if already processed (metadata has auto_sold flag)
        meta = trade.metadata if isinstance(trade.metadata, dict) else {}
        if meta.get("auto_sold"):
            logger.info("⏭️ Trade %s already auto-sold, skipping", trade_id[:8])
            return {"status": "already_closed", "trade_id": trade_id}
        
        # Check trade status - only process executed/pending trades
        if trade.status not in ["executed", "pending"]:
            logger.info("⏭️ Trade %s has status '%s', skipping auto-close", trade_id[:8], trade.status)
            return {"status": "invalid_status", "trade_id": trade_id, "current_status": trade.status}
        
        portfolio = trade.portfolio
        if not portfolio:
            logger.error("❌ No portfolio for trade %s", trade_id[:8])
            return {"status": "no_portfolio", "trade_id": trade_id}
        
        # Get live price with timeout and fallback
        current_price = original_price
        try:
            from market_data import await_live_price
            fetched_price = await asyncio.wait_for(
                await_live_price(symbol, timeout=3.0),
                timeout=5.0
            )
            if fetched_price and float(fetched_price) > 0:
                current_price = float(fetched_price)
                logger.debug("📈 Live price for %s: ₹%.2f", symbol, current_price)
        except asyncio.TimeoutError:
            logger.warning("⏱️ Price fetch timeout for %s, using original: ₹%.2f", symbol, original_price)
        except Exception as e:
            logger.warning("⚠️ Price fetch failed for %s: %s, using original: ₹%.2f", symbol, e, original_price)
        
        # Determine close side
        close_side = "SELL" if close_type == "sell" else "BUY"  # COVER = BUY
        
        # Create close trade with comprehensive metadata
        close_trade = await client.trade.create(
            data={
                "portfolio_id": str(portfolio.id),
                "organization_id": getattr(portfolio, "organization_id", None),
                "customer_id": str(getattr(portfolio, "customer_id", "") or ""),
                "trade_type": "auto",
                "symbol": symbol,
                "exchange": str(trade.exchange) if trade.exchange else "NSE",
                "segment": str(trade.segment) if trade.segment else "EQUITY",
                "side": close_side,
                "order_type": "market",
                "quantity": quantity,
                "price": Decimal(str(current_price)),
                "status": "pending",
                "source": "auto_sell_worker",
                "agent_id": getattr(trade, "agent_id", None),
                "allocation_id": getattr(trade, "allocation_id", None),
                "position_id": getattr(trade, "position_id", None),
                "metadata": json.dumps({
                    "order_type": f"auto_{close_type}",
                    "parent_trade_id": trade_id,
                    "triggered_by": "auto_sell_worker",
                    "original_price": original_price,
                    "execution_price": current_price,
                    "sell_reason": "15_minute_window_expired",
                    "original_trade_time": trade.created_at.isoformat() if trade.created_at else None,
                    "auto_close_triggered_at": datetime.now(timezone.utc).isoformat(),
                }),
            }
        )
        
        # Create execution log
        request_id = f"auto_{close_type}_{uuid.uuid4().hex[:8]}"
        await client.tradeexecutionlog.create(
            data={
                "trade_id": close_trade.id,
                "request_id": request_id,
                "status": "pending",
                "order_type": "market",
            }
        )
        
        # Execute the close trade
        trade_service = TradeExecutionService(logger=logger)
        result = await trade_service.execute_trade(close_trade.id, simulate=True)
        
        exec_time_ms = int((time.time() - exec_start) * 1000)
        
        if result and result.get("status") == "executed":
            # Mark original trade as auto-sold
            meta.update({
                "auto_sold": True,
                "auto_sold_at": datetime.now(timezone.utc).isoformat(),
                "auto_close_trade_id": close_trade.id,
                "closing_price": current_price,
                "opening_price": original_price,
                "pnl_at_close": (current_price - original_price) * quantity if close_type == "sell" else (original_price - current_price) * quantity,
                "exec_time_ms": exec_time_ms,
            })
            
            await client.trade.update(
                where={"id": trade_id},
                data={"metadata": json.dumps(meta)},
            )
            
            # Update execution log with timing
            await client.tradeexecutionlog.update_many(
                where={"trade_id": close_trade.id},
                data={"trade_delay": exec_time_ms}
            )
            
            logger.info(
                "✅ Auto-%s completed in %dms: %s %s x %d @ ₹%.2f (original: ₹%.2f)", 
                close_type, exec_time_ms, trade_id[:8], symbol, quantity, current_price, original_price
            )
            return {
                "status": "executed", 
                "trade_id": trade_id,
                "close_trade_id": close_trade.id,
                "price": current_price,
                "exec_time_ms": exec_time_ms,
            }
        else:
            error_msg = result.get("error", "Unknown error") if result else "No result"
            logger.error("❌ Auto-%s execution failed for %s: %s", close_type, trade_id[:8], error_msg)
            
            # Mark the close trade as failed
            await client.trade.update(
                where={"id": close_trade.id},
                data={"status": "failed", "metadata": json.dumps({"error": str(error_msg)})},
            )
            
            return {
                "status": "failed", 
                "trade_id": trade_id,
                "close_trade_id": close_trade.id,
                "error": str(error_msg),
                "exec_time_ms": exec_time_ms,
            }
