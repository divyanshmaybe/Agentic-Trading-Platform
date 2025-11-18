"""Auto-Sell Worker - Sells trades that have reached their auto_sell_at timestamp."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from celery_app import celery_app  # type: ignore
from db import get_db_manager  # type: ignore
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
    db_manager = get_db_manager()
    if not db_manager.is_connected():
        await db_manager.connect()
    
    client = db_manager.get_client()
    current_time = datetime.now(timezone.utc)
    
    trades_to_sell = client.trade.find_many(
        where={
            "status": {"in": ["executed", "simulated_executed"]},
            "auto_sell_at": {"lte": current_time},
            "side": "BUY",
        },
        include={"portfolio": True, "agent": True},
    )
    
    trade_logs_to_sell = client.tradeexecutionlog.find_many(
        where={
            "status": {"in": ["executed", "simulated_executed"]},
            "auto_sell_at": {"lte": current_time},
            "side": "BUY",
        },
    )
    
    logger.info(
        "📊 Found %d Trade records and %d TradeExecutionLog records to auto-sell",
        len(trades_to_sell) if trades_to_sell else 0,
        len(trade_logs_to_sell) if trade_logs_to_sell else 0,
    )
    
    trade_service = TradeExecutionService(logger=logger)
    sold_count = 0
    error_count = 0
    
    for trade in trades_to_sell or []:
        try:
            await _sell_trade(trade, trade_service, client, logger)
            sold_count += 1
        except Exception as exc:
            logger.error("❌ Failed to auto-sell Trade %s: %s", trade.id, exc, exc_info=True)
            error_count += 1
    
    for trade_log in trade_logs_to_sell or []:
        try:
            await _sell_trade_log(trade_log, trade_service, client, logger)
            sold_count += 1
        except Exception as exc:
            logger.error("❌ Failed to auto-sell TradeExecutionLog %s: %s", trade_log.id, exc, exc_info=True)
            error_count += 1
    
    logger.info("✅ Auto-sell worker completed: %d sold, %d errors", sold_count, error_count)
    
    return {"status": "completed", "sold_count": sold_count, "error_count": error_count}


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
        "🔄 Auto-selling Trade %s: SELL %s x %d (original buy @ ₹%.2f)",
        trade.id, symbol, executed_quantity, executed_price,
    )
    
    try:
        reference_price = float(get_live_price(symbol))
    except Exception:
        reference_price = executed_price
    
    portfolio = client.portfolio.find_unique(where={"id": portfolio_id})
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
    
    sell_log = client.tradeexecutionlog.create(
        data={
            "request_id": f"auto_sell_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "side": "SELL",
            "quantity": executed_quantity,
            "reference_price": Decimal(str(reference_price)),
            "status": "pending",
            "agent_id": getattr(trade, "agent_id", None),
            "agent_type": agent_type,
            "metadata": json.dumps({
                "order_type": "auto_sell",
                "parent_trade_id": str(trade.id),
                "triggered_by": "auto_sell_worker",
                "original_buy_price": executed_price,
                "original_buy_time": str(getattr(trade, "execution_time", "")),
            }),
        },
    )
    
    result = await trade_service.execute_trade(sell_log.id, simulate=True)
    
    if result.get("status") in ["simulated_executed", "executed"]:
        logger.info(
            "✅ Auto-sold Trade %s: SELL %s x %d @ ₹%.2f",
            trade.id, symbol, executed_quantity, result.get("executed_price", reference_price),
        )
        
        trade_metadata = _parse_metadata(getattr(trade, "metadata", None))
        trade_metadata.update({
            "auto_sold": True,
            "auto_sold_at": datetime.now(timezone.utc).isoformat(),
            "auto_sell_trade_log_id": str(sell_log.id),
        })
        
        client.trade.update(
            where={"id": trade.id},
            data={"metadata": json.dumps(trade_metadata)},
        )
    else:
        logger.error("❌ Failed to execute auto-sell for Trade %s: %s", trade.id, result)


async def _sell_trade_log(trade_log, trade_service: TradeExecutionService, client, logger):
    """Sell a TradeExecutionLog record."""
    symbol = str(getattr(trade_log, "symbol", ""))
    portfolio_id = str(getattr(trade_log, "portfolio_id", ""))
    executed_quantity = int(getattr(trade_log, "executed_quantity", 0))
    executed_price = float(getattr(trade_log, "executed_price", 0))
    
    if not symbol or not portfolio_id or executed_quantity == 0:
        logger.warning("⚠️ Skipping TradeExecutionLog %s: missing required fields", trade_log.id)
        return
    
    logger.info(
        "🔄 Auto-selling TradeExecutionLog %s: SELL %s x %d (original buy @ ₹%.2f)",
        trade_log.id, symbol, executed_quantity, executed_price,
    )
    
    try:
        reference_price = float(get_live_price(symbol))
    except Exception:
        reference_price = executed_price
    
    portfolio = client.portfolio.find_unique(where={"id": portfolio_id})
    if not portfolio:
        logger.error("❌ Portfolio %s not found for TradeExecutionLog %s", portfolio_id, trade_log.id)
        return
    
    user_id = str(getattr(portfolio, "customer_id", ""))
    if not user_id:
        logger.error("❌ No user_id found for Portfolio %s", portfolio_id)
        return
    
    sell_log = client.tradeexecutionlog.create(
        data={
            "request_id": f"auto_sell_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "portfolio_id": portfolio_id,
            "symbol": symbol,
            "side": "SELL",
            "quantity": executed_quantity,
            "reference_price": Decimal(str(reference_price)),
            "status": "pending",
            "agent_id": getattr(trade_log, "agent_id", None),
            "agent_type": getattr(trade_log, "agent_type", None),
            "metadata": json.dumps({
                "order_type": "auto_sell",
                "parent_trade_log_id": str(trade_log.id),
                "triggered_by": "auto_sell_worker",
                "original_buy_price": executed_price,
                "original_buy_time": str(getattr(trade_log, "created_at", "")),
            }),
        },
    )
    
    result = await trade_service.execute_trade(sell_log.id, simulate=True)
    
    if result.get("status") in ["simulated_executed", "executed"]:
        logger.info(
            "✅ Auto-sold TradeExecutionLog %s: SELL %s x %d @ ₹%.2f",
            trade_log.id, symbol, executed_quantity, result.get("executed_price", reference_price),
        )
        
        trade_log_metadata = _parse_metadata(getattr(trade_log, "metadata", None))
        trade_log_metadata.update({
            "auto_sold": True,
            "auto_sold_at": datetime.now(timezone.utc).isoformat(),
            "auto_sell_trade_log_id": str(sell_log.id),
        })
        
        client.tradeexecutionlog.update(
            where={"id": trade_log.id},
            data={"metadata": json.dumps(trade_log_metadata)},
        )
    else:
        logger.error("❌ Failed to execute auto-sell for TradeExecutionLog %s: %s", trade_log.id, result)


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

