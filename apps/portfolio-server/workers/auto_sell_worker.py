"""Auto-Sell Worker - Sells trades that have reached their auto_sell_at timestamp."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from celery_app import celery_app  # type: ignore
from dbManager import DBManager
from market_data import get_live_price  # type: ignore
from services.trade_execution_service import TradeExecutionService  # type: ignore

logger = logging.getLogger(__name__)


@celery_app.task(name="trades.auto_sell_expired_trades", bind=True)
def auto_sell_expired_trades(self):
    """Auto-sell trades that have reached their auto_sell_at timestamp."""
    logger.info("🔄 Starting auto-sell worker...")
    try:
        return asyncio.run(_run_auto_sell())
    except Exception as exc:
        logger.error("❌ Auto-sell worker failed: %s", exc, exc_info=True)
        raise


async def _run_auto_sell():
    """Run auto-sell logic for expired trades."""
    db_manager = DBManager.get_instance()
    await db_manager.connect()
    client = db_manager.get_client()
    
    current_time = datetime.now(timezone.utc)
    
    # Only check Trade records (auto_sell_at field only exists on Trade model)
    trades_to_sell = await client.trade.find_many(
        where={
            "status": {"in": ["executed", "simulated_executed"]},
            "auto_sell_at": {"lte": current_time, "not": None},  # Must have auto_sell_at set
            "side": "BUY",
        },
        include={"portfolio": True, "agent": True},
    )
    
    logger.info(
        "📊 Found %d Trade records to auto-sell (15-minute window expired)",
        len(trades_to_sell) if trades_to_sell else 0,
    )
    
    trade_service = TradeExecutionService(logger=logger)
    sold_count = 0
    error_count = 0
    skipped_count = 0
    
    for trade in trades_to_sell or []:
        try:
            # Atomic check: Try to clear auto_sell_at for this trade
            # If auto_sell_at is already None, another worker processed it
            update_result = await client.trade.update_many(
                where={
                    "id": trade.id,
                    "auto_sell_at": {"not": None},  # Only update if still set
                },
                data={"auto_sell_at": None},  # Clear to prevent duplicate processing
            )
            
            # If no rows were updated, another worker already claimed this trade
            if update_result == 0:
                logger.debug("⏭️ Skipping Trade %s: already processed by another worker", trade.id)
                skipped_count += 1
                continue
            
            # We successfully claimed this trade, now sell it
            await _sell_trade(trade, trade_service, client, logger)
            sold_count += 1
        except Exception as exc:
            logger.error("❌ Failed to auto-sell Trade %s: %s", trade.id, exc, exc_info=True)
            error_count += 1
    
    logger.info(
        "✅ Auto-sell worker completed: %d sold, %d errors, %d skipped (already processed)",
        sold_count, error_count, skipped_count,
    )
    
    return {
        "status": "completed",
        "sold_count": sold_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
    }


async def _sell_trade(trade, trade_service: TradeExecutionService, client, logger):
    """Sell a Trade record."""
    symbol = str(getattr(trade, "symbol", ""))
    portfolio_id = str(getattr(trade, "portfolio_id", ""))
    executed_quantity = int(getattr(trade, "executed_quantity", 0))
    executed_price = float(getattr(trade, "executed_price", 0))
    
    if not symbol or not portfolio_id or executed_quantity == 0:
        logger.warning("⚠️ Skipping Trade %s: missing required fields", trade.id)
        return
    
    logger.info(
        "🔄 Auto-selling Trade %s (15-min window expired): SELL %s x %d (original buy @ ₹%.2f)",
        trade.id, symbol, executed_quantity, executed_price,
    )
    
    # Use executed_price as reference (live price not needed for simulated trades)
    reference_price = executed_price
    
    portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
    if not portfolio:
        logger.error("❌ Portfolio %s not found for Trade %s", portfolio_id, trade.id)
        return
    
    user_id = str(getattr(portfolio, "customer_id", ""))
    if not user_id:
        logger.error("❌ No user_id found for Portfolio %s", portfolio_id)
        return
    
    agent_type = None
    if hasattr(trade, "agent") and trade.agent:
        agent_type = getattr(trade.agent, "agent_type", None)
    
    # Create Trade record first for auto-sell
    trade_data = {
        "portfolio_id": portfolio_id,
        "organization_id": getattr(portfolio, "organization_id", None),
        "customer_id": user_id,
        "trade_type": "auto",
        "symbol": symbol,
        "exchange": "NSE",
        "segment": "EQUITY",
        "side": "SELL",
        "order_type": "market",
        "quantity": executed_quantity,
        "price": Decimal(str(reference_price)),
        "status": "pending",
        "source": "auto_sell_worker",
        "agent_id": getattr(trade, "agent_id", None),
        "metadata": json.dumps({
            "order_type": "auto_sell",
            "parent_trade_id": str(trade.id),
            "triggered_by": "auto_sell_worker",
            "original_buy_price": executed_price,
            "original_buy_time": str(getattr(trade, "execution_time", "")),
            "sell_reason": "15_minute_window_expired",
        }),
    }

    sell_trade = await client.trade.create(data=trade_data)

    # Create TradeExecutionLog record
    sell_log = await client.tradeexecutionlog.create(
        data={
            "trade_id": sell_trade.id,
            "request_id": f"auto_sell_{uuid.uuid4().hex[:12]}",
            "status": "pending",
            "order_type": "market",
            "metadata": json.dumps({
                "order_type": "auto_sell",
                "parent_trade_id": str(trade.id),
                "triggered_by": "auto_sell_worker",
                "original_buy_price": executed_price,
                "original_buy_time": str(getattr(trade, "execution_time", "")),
                "sell_reason": "15_minute_window_expired",
            }),
        },
    )
    
    # Execute the sell trade (pass Trade ID, not TradeExecutionLog ID)
    result = await trade_service.execute_trade(sell_trade.id, simulate=True)
    
    if result.get("status") in ["simulated_executed", "executed"]:
        logger.info(
            "✅ Auto-sold Trade %s (15-min window): SELL %s x %d @ ₹%.2f",
            trade.id, symbol, executed_quantity, result.get("executed_price", reference_price),
        )
        
        trade_metadata = _parse_metadata(getattr(trade, "metadata", None))
        trade_metadata.update({
            "auto_sold": True,
            "auto_sold_at": datetime.now(timezone.utc).isoformat(),
            "auto_sell_trade_log_id": str(sell_log.id),
            "sell_reason": "15_minute_window_expired",
        })
        
        # Update metadata to mark as auto-sold
        await client.trade.update(
            where={"id": trade.id},
            data={"metadata": json.dumps(trade_metadata)},
        )
    else:
        logger.error("❌ Failed to execute auto-sell for Trade %s: %s", trade.id, result)


def _parse_metadata(metadata):
    """Parse metadata from string or dict."""
    if not metadata:
        return {}
    if isinstance(metadata, str):
        try:
            return json.loads(metadata)
        except:
            return {}
    return dict(metadata) if isinstance(metadata, dict) else {}
