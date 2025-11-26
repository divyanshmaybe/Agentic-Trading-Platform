"""Auto-Sell Worker - Sells trades that have reached their auto_sell_at timestamp."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from celery_app import celery_app  # type: ignore
from db_context import get_db_connection
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
    async with get_db_connection() as client:
        current_time = datetime.now(timezone.utc)
        
        # Debug: Check all BUY trades with auto_sell_at (query all fields - no select)
        all_auto_sell_trades = await client.trade.find_many(
            where={
                "auto_sell_at": {"not": None},
                "side": "BUY",
            },
        )
        
        logger.info(
            "🔍 DEBUG: Found %d total BUY trades with auto_sell_at set. Current time: %s",
            len(all_auto_sell_trades) if all_auto_sell_trades else 0,
            current_time.isoformat(),
        )
    
        for trade in all_auto_sell_trades or []:
            logger.info(
                "🔍 Trade %s: symbol=%s, status=%s, auto_sell_at=%s, expired=%s",
                trade.id[:8],
                trade.symbol,
                trade.status,
                trade.auto_sell_at,
                trade.auto_sell_at <= current_time if trade.auto_sell_at else "N/A",
            )
        
        # Only check Trade records (auto_sell_at field only exists on Trade model)
        # Auto-sell applies to both executed and pending BUY trades that have expired
        trades_to_sell = await client.trade.find_many(
            where={
                "status": {"in": ["executed", "pending"]},
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
    executed_quantity = int(getattr(trade, "executed_quantity", 0) or 0)
    executed_price_raw = getattr(trade, "executed_price", None)
    executed_price = float(executed_price_raw) if executed_price_raw is not None else 0.0
    
    if not symbol or not portfolio_id or executed_quantity == 0:
        logger.warning("⚠️ Skipping Trade %s: missing required fields (symbol=%s, portfolio=%s, qty=%s)", 
                      trade.id, symbol, portfolio_id, executed_quantity)
        return
    
    logger.info(
        "🔄 Auto-selling Trade %s (15-min window expired): SELL %s x %d (original buy @ ₹%.2f)",
        trade.id, symbol, executed_quantity, executed_price,
    )
    
    # Fetch live market price from Angel One for realistic P&L
    try:
        from services.angel_one_service import AngelOneService
        angel_service = AngelOneService()
        await angel_service.initialize()
        
        # Get current market price
        market_data = await angel_service.get_market_price(symbol, "NSE")
        if market_data and market_data.get("ltp"):
            reference_price = float(market_data["ltp"])
            logger.info("📈 Using live market price for %s: ₹%.2f (buy was ₹%.2f)", symbol, reference_price, executed_price)
        else:
            reference_price = executed_price
            logger.warning("⚠️ No live price available for %s, using buy price ₹%.2f", symbol, executed_price)
    except Exception as e:
        logger.warning("⚠️ Failed to fetch live price for %s: %s, using buy price ₹%.2f", symbol, e, executed_price)
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
    
    if result.get("status") in ["executed", "executed"]:
        closing_price = result.get("executed_price", reference_price)
        logger.info(
            "✅ Auto-sold Trade %s (15-min window): SELL %s x %d @ ₹%.2f",
            trade.id, symbol, executed_quantity, closing_price,
        )
        
        trade_metadata = _parse_metadata(getattr(trade, "metadata", None))
        trade_metadata.update({
            "auto_sold": True,
            "auto_sold_at": datetime.now(timezone.utc).isoformat(),
            "auto_sell_trade_log_id": str(sell_log.id),
            "sell_reason": "15_minute_window_expired",
            "closing_price": float(closing_price),
            "opening_price": executed_price,
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
