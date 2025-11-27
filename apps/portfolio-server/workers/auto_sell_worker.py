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
from utils.market_hours import is_market_hours, get_market_status  # type: ignore

logger = logging.getLogger(__name__)


@celery_app.task(
    name="trades.auto_sell_expired_trades",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    time_limit=50,  # Hard limit - must complete in 50 seconds
    soft_time_limit=45,  # Soft limit at 45 seconds
)
def auto_sell_expired_trades(self):
    """
    Auto-close trades that have reached their auto_sell_at/auto_cover_at timestamp.
    
    PRODUCTION BEHAVIOR:
    - LONG positions (BUY trades): Auto-SELL after 15-minute window (auto_sell_at)
    - SHORT positions (SHORT_SELL trades): Auto-COVER after 15-minute window (auto_cover_at)
    """
    logger.info("🔄 Starting auto-close worker (LONG and SHORT positions)...")
    try:
        return asyncio.run(_run_auto_close())
    except Exception as exc:
        logger.error("❌ Auto-close worker failed: %s", exc, exc_info=True)
        raise


async def _run_auto_close():
    """Run auto-close logic for expired trades (both LONG and SHORT)."""
    # Check market hours before executing auto-close trades (respect DEMO_MODE)
    import os
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    
    if not demo_mode and not is_market_hours():
        market_status, msg = get_market_status()
        logger.info(
            "⏸️ Market closed - skipping auto-close execution. Status: %s - %s",
            market_status,
            msg
        )
        return {
            "status": "skipped",
            "reason": "market_closed",
            "message": msg,
            "sold_count": 0,
            "covered_count": 0,
        }
    
    if demo_mode:
        logger.info("🧪 DEMO_MODE enabled - executing auto-close regardless of market hours")
    
    async with get_db_connection() as client:
        current_time = datetime.now(timezone.utc)
        
        # Find LONG positions to auto-sell (BUY trades with expired auto_sell_at)
        trades_to_sell = await client.trade.find_many(
            where={
                "status": {"in": ["executed", "pending"]},
                "auto_sell_at": {"lte": current_time, "not": None},
                "side": "BUY",
            },
            include={"portfolio": True, "agent": True},
        )
        
        # Find SHORT positions to auto-cover (SHORT_SELL trades with expired auto_cover_at)
        trades_to_cover = await client.trade.find_many(
            where={
                "status": {"in": ["executed", "pending"]},
                "auto_cover_at": {"lte": current_time, "not": None},
                "side": "SHORT_SELL",
            },
            include={"portfolio": True, "agent": True},
        )
        
        logger.info(
            "📊 Found %d LONG trades to auto-sell and %d SHORT trades to auto-cover (15-minute window expired)",
            len(trades_to_sell) if trades_to_sell else 0,
            len(trades_to_cover) if trades_to_cover else 0,
        )
        
        trade_service = TradeExecutionService(logger=logger)
        sold_count = 0
        covered_count = 0
        error_count = 0
        skipped_count = 0
        
        # Process LONG positions (auto-sell)
        for trade in trades_to_sell or []:
            try:
                # Atomic check: Try to clear auto_sell_at for this trade
                update_result = await client.trade.update_many(
                    where={
                        "id": trade.id,
                        "auto_sell_at": {"not": None},
                    },
                    data={"auto_sell_at": None},
                )
                
                if update_result == 0:
                    logger.debug("⏭️ Skipping LONG trade %s: already processed", trade.id)
                    skipped_count += 1
                    continue
                
                # Execute auto-sell
                await _close_long_position(trade, trade_service, client, logger)
                sold_count += 1
            except Exception as exc:
                logger.error("❌ Failed to auto-sell LONG trade %s: %s", trade.id, exc, exc_info=True)
                error_count += 1
        
        # Process SHORT positions (auto-cover)
        for trade in trades_to_cover or []:
            try:
                # Atomic check: Try to clear auto_cover_at for this trade
                update_result = await client.trade.update_many(
                    where={
                        "id": trade.id,
                        "auto_cover_at": {"not": None},
                    },
                    data={"auto_cover_at": None},
                )
                
                if update_result == 0:
                    logger.debug("⏭️ Skipping SHORT trade %s: already processed", trade.id)
                    skipped_count += 1
                    continue
                
                # Execute auto-cover
                await _close_short_position(trade, trade_service, client, logger)
                covered_count += 1
            except Exception as exc:
                logger.error("❌ Failed to auto-cover SHORT trade %s: %s", trade.id, exc, exc_info=True)
                error_count += 1
        
        logger.info(
            "✅ Auto-close worker completed: %d LONG sold, %d SHORT covered, %d errors, %d skipped",
            sold_count, covered_count, error_count, skipped_count,
        )
        
        return {
            "status": "completed",
            "long_sold_count": sold_count,
            "short_covered_count": covered_count,
            "total_closed": sold_count + covered_count,
            "error_count": error_count,
            "skipped_count": skipped_count,
        }


async def _close_long_position(trade, trade_service: TradeExecutionService, client, logger):
    """Close a LONG position (auto-sell after 15-minute window)."""
    symbol = str(getattr(trade, "symbol", ""))
    portfolio_id = str(getattr(trade, "portfolio_id", ""))
    executed_quantity = int(getattr(trade, "executed_quantity", 0) or 0)
    executed_price_raw = getattr(trade, "executed_price", None)
    executed_price = float(executed_price_raw) if executed_price_raw is not None else 0.0
    
    if not symbol or not portfolio_id or executed_quantity == 0:
        logger.warning("⚠️ Skipping LONG trade %s: missing required fields", trade.id)
        return
    
    logger.info(
        "🔄 Auto-selling LONG position %s (15-min window expired): SELL %s x %d (bought @ ₹%.2f)",
        trade.id, symbol, executed_quantity, executed_price,
    )
    
    # Fetch live market price from Angel One for realistic P&L
    try:
        # Import market data service from shared module
        import sys
        import os
        shared_path = os.path.join(os.path.dirname(__file__), "../../../shared/py")
        if shared_path not in sys.path:
            sys.path.insert(0, shared_path)
        
        from market_data import await_live_price
        
        # Get current market price (async)
        reference_price_decimal = await await_live_price(symbol, timeout=5.0)
        reference_price = float(reference_price_decimal)
        
        # Calculate P&L
        pnl = (reference_price - executed_price) * executed_quantity
        pnl_pct = ((reference_price - executed_price) / executed_price) * 100 if executed_price > 0 else 0
        
        logger.info(
            "📈 Using live market price for %s: ₹%.2f (buy: ₹%.2f, P&L: ₹%.2f [%.2f%%])", 
            symbol, reference_price, executed_price, pnl, pnl_pct
        )
    except ImportError as ie:
        logger.error("❌ Failed to import market_data module: %s, using buy price", ie)
        reference_price = executed_price
    except TimeoutError:
        logger.warning("⏱️ Timeout fetching live price for %s, using buy price ₹%.2f", symbol, executed_price)
        reference_price = executed_price
    except (ValueError, TypeError, AttributeError) as ve:
        logger.error("❌ Invalid price data for %s: %s, using buy price", symbol, ve)
        reference_price = executed_price
    except Exception as e:
        logger.error("❌ Unexpected error fetching price for %s: %s, using buy price", symbol, e, exc_info=True)
        reference_price = executed_price
    
    try:
        portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
        if not portfolio:
            logger.error("❌ Portfolio %s not found for Trade %s", portfolio_id, trade.id)
            raise ValueError(f"Portfolio {portfolio_id} not found")
        
        user_id = str(getattr(portfolio, "customer_id", ""))
        if not user_id:
            logger.error("❌ No user_id found for Portfolio %s", portfolio_id)
            raise ValueError(f"No customer_id for portfolio {portfolio_id}")
    except Exception as e:
        logger.error("❌ Failed to retrieve portfolio %s: %s", portfolio_id, e, exc_info=True)
        raise
    
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
    try:
        result = await trade_service.execute_trade(sell_trade.id, simulate=True)
        
        if not result:
            raise RuntimeError("Trade execution returned None")
        
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
            error_msg = result.get("error", "Unknown error")
            logger.error("❌ Failed to execute auto-sell for Trade %s: status=%s, error=%s", 
                        trade.id, result.get("status"), error_msg)
            raise RuntimeError(f"Trade execution failed: {error_msg}")
    except ValueError as ve:
        logger.error("❌ Validation error executing auto-sell for Trade %s: %s", trade.id, ve)
        raise
    except RuntimeError as re:
        logger.error("❌ Runtime error executing auto-sell for Trade %s: %s", trade.id, re)
        raise
    except Exception as e:
        logger.error("❌ Unexpected error executing auto-sell for Trade %s: %s", trade.id, e, exc_info=True)
        raise


async def _close_short_position(trade, trade_service: TradeExecutionService, client, logger):
    """Close a SHORT position (auto-cover after 15-minute window)."""
    symbol = str(getattr(trade, "symbol", ""))
    portfolio_id = str(getattr(trade, "portfolio_id", ""))
    executed_quantity = int(getattr(trade, "executed_quantity", 0) or 0)
    executed_price_raw = getattr(trade, "executed_price", None)
    executed_price = float(executed_price_raw) if executed_price_raw is not None else 0.0
    
    if not symbol or not portfolio_id or executed_quantity == 0:
        logger.warning("⚠️ Skipping SHORT trade %s: missing required fields", trade.id)
        return
    
    logger.info(
        "🔄 Auto-covering SHORT position %s (15-min window expired): COVER %s x %d (shorted @ ₹%.2f)",
        trade.id, symbol, executed_quantity, executed_price,
    )
    
    # Fetch live market price
    try:
        import sys
        import os
        shared_path = os.path.join(os.path.dirname(__file__), "../../../shared/py")
        if shared_path not in sys.path:
            sys.path.insert(0, shared_path)
        
        from market_data import await_live_price
        
        reference_price_decimal = await await_live_price(symbol, timeout=5.0)
        reference_price = float(reference_price_decimal)
        
        # Calculate P&L for SHORT position (profit when price goes down)
        pnl = (executed_price - reference_price) * executed_quantity
        pnl_pct = ((executed_price - reference_price) / executed_price) * 100 if executed_price > 0 else 0
        
        logger.info(
            "📈 Using live price for %s: ₹%.2f (short: ₹%.2f, P&L: ₹%.2f [%.2f%%])", 
            symbol, reference_price, executed_price, pnl, pnl_pct
        )
    except Exception as e:
        logger.warning("⚠️ Failed to fetch live price for %s: %s, using short price ₹%.2f", symbol, e, executed_price)
        reference_price = executed_price
    
    portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
    if not portfolio:
        logger.error("❌ Portfolio %s not found for Trade %s", portfolio_id, trade.id)
        return
    
    user_id = str(getattr(portfolio, "customer_id", ""))
    if not user_id:
        logger.error("❌ No user_id found for Portfolio %s", portfolio_id)
        return
    
    # Create COVER (BUY) trade to close short position
    cover_trade_data = {
        "portfolio_id": portfolio_id,
        "organization_id": getattr(portfolio, "organization_id", None),
        "customer_id": user_id,
        "trade_type": "auto",
        "symbol": symbol,
        "exchange": "NSE",
        "segment": "EQUITY",
        "side": "COVER",  # COVER = BUY to close short
        "order_type": "market",
        "quantity": executed_quantity,
        "price": Decimal(str(reference_price)),
        "status": "pending",
        "source": "auto_cover_worker",
        "agent_id": getattr(trade, "agent_id", None),
        "metadata": json.dumps({
            "order_type": "auto_cover",
            "parent_trade_id": str(trade.id),
            "triggered_by": "auto_cover_worker",
            "original_short_price": executed_price,
            "original_short_time": str(getattr(trade, "execution_time", "")),
            "cover_reason": "15_minute_window_expired",
        }),
    }

    cover_trade = await client.trade.create(data=cover_trade_data)

    # Create TradeExecutionLog record
    cover_log = await client.tradeexecutionlog.create(
        data={
            "trade_id": cover_trade.id,
            "request_id": f"auto_cover_{uuid.uuid4().hex[:12]}",
            "status": "pending",
            "order_type": "market",
            "metadata": json.dumps({
                "order_type": "auto_cover",
                "parent_trade_id": str(trade.id),
                "triggered_by": "auto_cover_worker",
                "original_short_price": executed_price,
                "cover_reason": "15_minute_window_expired",
            }),
        },
    )
    
    # Execute the cover trade
    result = await trade_service.execute_trade(cover_trade.id, simulate=True)
    
    if result.get("status") in ["executed", "executed"]:
        closing_price = result.get("executed_price", reference_price)
        logger.info(
            "✅ Auto-covered SHORT position %s: COVER %s x %d @ ₹%.2f",
            trade.id, symbol, executed_quantity, closing_price,
        )
        
        trade_metadata = _parse_metadata(getattr(trade, "metadata", None))
        trade_metadata.update({
            "auto_covered": True,
            "auto_covered_at": datetime.now(timezone.utc).isoformat(),
            "auto_cover_trade_id": str(cover_trade.id),
            "cover_reason": "15_minute_window_expired",
            "closing_price": float(closing_price),
            "opening_price": executed_price,
        })
        
        await client.trade.update(
            where={"id": trade.id},
            data={"metadata": json.dumps(trade_metadata)},
        )
    else:
        logger.error("❌ Failed to execute auto-cover for Trade %s: %s", trade.id, result)


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
