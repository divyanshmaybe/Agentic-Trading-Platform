"""
Auto-Sell Worker - LIGHTWEIGHT trade closer for expired positions.

Design principles:
1. FAST - single query, batch processing
2. ATOMIC - clear auto_sell_at before processing to prevent duplicates
3. NON-BLOCKING - dispatch individual trades as separate tasks
4. IDEMPOTENT - safe to run multiple times
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="trades.auto_sell_expired_trades",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=30,  # 30 seconds max - this should be FAST
    time_limit=45,  # Hard kill at 45s
    max_retries=1,
)
def auto_sell_expired_trades(self):
    """
    LIGHTWEIGHT auto-close scanner.
    
    This task ONLY:
    1. Queries for expired trades
    2. Clears their auto_sell_at (atomic lock)
    3. Dispatches individual close tasks
    
    Actual trade execution happens in separate tasks for parallelism.
    """
    logger.info("🔄 Auto-close scanner starting...")
    try:
        return asyncio.run(_scan_and_dispatch())
    except Exception as exc:
        logger.error("❌ Auto-close scanner failed: %s", exc)
        raise


async def _scan_and_dispatch():
    """Scan for expired trades and dispatch close tasks."""
    from db_context import get_db_connection
    
    # Check market hours (respect DEMO_MODE)
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    
    if not demo_mode:
        from utils.market_hours import is_market_hours, get_market_status
        if not is_market_hours():
            _, msg = get_market_status()
            logger.info("⏸️ Market closed - skipping. %s", msg)
            return {"status": "skipped", "reason": "market_closed", "dispatched": 0}
    
    async with get_db_connection() as client:
        current_time = datetime.now(timezone.utc)
        
        # SINGLE efficient query - only get IDs and minimal data
        expired_longs = await client.trade.find_many(
            where={
                "status": {"in": ["executed", "pending"]},
                "auto_sell_at": {"lte": current_time, "not": None},
                "side": "BUY",
            },
            take=50,  # Batch size limit
        )
        
        expired_shorts = await client.trade.find_many(
            where={
                "status": {"in": ["executed", "pending"]},
                "auto_cover_at": {"lte": current_time, "not": None},
                "side": "SHORT_SELL",
            },
            take=50,
        )
        
        total_found = len(expired_longs or []) + len(expired_shorts or [])
        if total_found == 0:
            logger.debug("✅ No expired trades found")
            return {"status": "completed", "dispatched": 0}
        
        logger.info("📊 Found %d expired trades to close", total_found)
        
        dispatched = 0
        
        # Process LONGs - atomically clear auto_sell_at and dispatch
        for trade in expired_longs or []:
            trade_id = str(trade.id)
            
            # Atomic lock - clear auto_sell_at to prevent duplicate processing
            updated = await client.trade.update_many(
                where={"id": trade_id, "auto_sell_at": {"not": None}},
                data={"auto_sell_at": None},
            )
            
            if updated == 0:
                logger.debug("⏭️ Trade %s already claimed", trade_id[:8])
                continue
            
            # Dispatch close task (non-blocking)
            execute_auto_close.delay(
                trade_id=trade_id,
                close_type="sell",
                symbol=str(trade.symbol),
                quantity=int(trade.quantity or 0),
                original_price=float(trade.price or 0),
            )
            dispatched += 1
        
        # Process SHORTs
        for trade in expired_shorts or []:
            trade_id = str(trade.id)
            
            updated = await client.trade.update_many(
                where={"id": trade_id, "auto_cover_at": {"not": None}},
                data={"auto_cover_at": None},
            )
            
            if updated == 0:
                continue
            
            execute_auto_close.delay(
                trade_id=trade_id,
                close_type="cover",
                symbol=str(trade.symbol),
                quantity=int(trade.quantity or 0),
                original_price=float(trade.price or 0),
            )
            dispatched += 1
        
        logger.info("✅ Dispatched %d close tasks", dispatched)
        return {"status": "completed", "dispatched": dispatched}


@celery_app.task(
    name="trades.execute_auto_close",
    bind=True,
    acks_late=True,
    soft_time_limit=30,
    time_limit=45,
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
)
def execute_auto_close(
    self,
    trade_id: str,
    close_type: str,  # "sell" or "cover"
    symbol: str,
    quantity: int,
    original_price: float,
):
    """
    Execute a single auto-close trade.
    
    Runs in parallel with other close tasks for fast execution.
    """
    logger.info("🔄 Executing auto-%s: %s %s x %d", close_type, trade_id[:8], symbol, quantity)
    
    try:
        return asyncio.run(_execute_close(trade_id, close_type, symbol, quantity, original_price))
    except Exception as exc:
        logger.error("❌ Auto-%s failed for %s: %s", close_type, trade_id[:8], exc)
        raise


async def _execute_close(trade_id: str, close_type: str, symbol: str, quantity: int, original_price: float):
    """Execute the actual close trade."""
    import json
    import uuid
    from decimal import Decimal
    from db_context import get_db_connection
    from services.trade_execution_service import TradeExecutionService
    
    async with get_db_connection() as client:
        # Get original trade with portfolio info
        trade = await client.trade.find_unique(
            where={"id": trade_id},
            include={"portfolio": True},
        )
        
        if not trade:
            logger.warning("⚠️ Trade %s not found", trade_id[:8])
            return {"status": "not_found"}
        
        portfolio = trade.portfolio
        if not portfolio:
            logger.warning("⚠️ No portfolio for trade %s", trade_id[:8])
            return {"status": "no_portfolio"}
        
        # Get live price (with timeout)
        try:
            from market_data import await_live_price
            current_price = float(await await_live_price(symbol, timeout=3.0))
        except Exception:
            current_price = original_price  # Fallback
        
        # Determine side for close trade
        close_side = "SELL" if close_type == "sell" else "BUY"
        
        # Create close trade
        close_trade = await client.trade.create(
            data={
                "portfolio_id": str(portfolio.id),
                "organization_id": getattr(portfolio, "organization_id", None),
                "customer_id": str(getattr(portfolio, "customer_id", "")),
                "trade_type": "auto",
                "symbol": symbol,
                "exchange": "NSE",
                "segment": "EQUITY",
                "side": close_side,
                "order_type": "market",
                "quantity": quantity,
                "price": Decimal(str(current_price)),
                "status": "pending",
                "source": "auto_sell_worker",
                "agent_id": getattr(trade, "agent_id", None),
                "metadata": json.dumps({
                    "order_type": f"auto_{close_type}",
                    "parent_trade_id": trade_id,
                    "triggered_by": "auto_sell_worker",
                    "original_price": original_price,
                    "sell_reason": "15_minute_window_expired",
                }),
            }
        )
        
        # Create execution log
        await client.tradeexecutionlog.create(
            data={
                "trade_id": close_trade.id,
                "request_id": f"auto_{close_type}_{uuid.uuid4().hex[:8]}",
                "status": "pending",
                "order_type": "market",
            }
        )
        
        # Execute
        trade_service = TradeExecutionService(logger=logger)
        result = await trade_service.execute_trade(close_trade.id, simulate=True)
        
        if result and result.get("status") == "executed":
            # Update original trade metadata
            meta = trade.metadata if isinstance(trade.metadata, dict) else {}
            meta.update({
                "auto_sold": True,
                "auto_sold_at": datetime.now(timezone.utc).isoformat(),
                "closing_price": current_price,
                "opening_price": original_price,
            })
            
            await client.trade.update(
                where={"id": trade_id},
                data={"metadata": json.dumps(meta)},
            )
            
            logger.info("✅ Auto-%s completed: %s %s x %d @ ₹%.2f", close_type, trade_id[:8], symbol, quantity, current_price)
            return {"status": "executed", "price": current_price}
        else:
            logger.error("❌ Auto-%s execution failed: %s", close_type, result)
            return {"status": "failed", "error": str(result)}
