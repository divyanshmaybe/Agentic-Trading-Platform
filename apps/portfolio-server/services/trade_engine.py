from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
import json
import logging

from prisma import Prisma

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PORTFOLIO_SERVER_ROOT = Path(__file__).resolve().parents[1]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))
if str(PORTFOLIO_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_ROOT))

from market_data import await_live_price, get_market_data_service  # type: ignore  # noqa: E402
from schemas import TradeCreate
from services.trade_email_service import send_trade_execution_email  # noqa: E402

logger = logging.getLogger(__name__)

FEE_RATE = Decimal(os.getenv("TRADE_FEE_RATE", "0.0003"))
TAX_RATE = Decimal(os.getenv("TRADE_TAX_RATE", "0"))
FOUR_DP = Decimal("0.0001")


@dataclass
class TradeExecutionResult:
    trades: List[Dict]
    pending_orders: int
    portfolio: Dict


class TradeEngine:
    """Core trading engine that executes trades and coordinates pending orders."""

    def __init__(self, prisma: Prisma) -> None:
        self.prisma = prisma
        self.market_data = get_market_data_service()
        self._redis_manager: Optional[any] = None

    async def _get_redis(self) -> Optional[any]:
        """Get Redis manager for publishing trade events (lazy init)"""
        if self._redis_manager is None:
            try:
                from redisManager import RedisManager
                self._redis_manager = RedisManager()
                await self._redis_manager.connect()
                logger.debug("✅ Redis connected for trade event publishing")
            except Exception as e:
                logger.warning(f"Redis not available for trade events: {e}")
                return None
        return self._redis_manager

    async def _publish_trade_event(self, channel: str, trade_data: dict):
        """Publish trade event to Redis for Pathway monitoring (non-blocking)"""
        try:
            redis = await self._get_redis()
            if redis:
                await redis.publish(channel, json.dumps(trade_data))
                logger.debug(f"📤 Published to {channel}: {trade_data.get('trade_id', 'N/A')[:8]}")
        except Exception as e:
            # Don't fail trade execution if Redis publish fails
            logger.warning(f"Failed to publish trade event: {e}")

    async def handle_trade(self, payload: TradeCreate) -> TradeExecutionResult:
        await self._ensure_portfolio(payload.portfolio_id)

        if payload.order_type == "market":
            # NO FALLBACK - Fail fast if price not available
            try:
                execution_price = await await_live_price(payload.symbol, timeout=10.0)
            except RuntimeError as price_error:
                import logging
                logging.getLogger(__name__).error(
                    f"❌ Price unavailable for {payload.symbol}: {price_error}. "
                    f"Trade will be rejected - no fallback pricing."
                )
                raise RuntimeError(
                    f"Cannot execute trade for {payload.symbol}: Price data unavailable. "
                    f"Check if symbol is valid in Angel One token map."
                ) from price_error
            
            trade = await self._execute_market_order(payload, execution_price)
            trades = [trade]
            pending = 0
        else:
            trade = await self._create_pending_trade(payload)
            trades = [trade]
            pending = 1

        portfolio_snapshot = await self._build_portfolio_snapshot(payload.portfolio_id)
        return TradeExecutionResult(trades=trades, pending_orders=pending, portfolio=portfolio_snapshot)

    async def process_pending_trade(self, trade_id: str) -> bool:
        import time
        start_time = time.time()
        
        trade = await self.prisma.trade.find_unique(where={"id": trade_id})
        # Include pending_tp and pending_sl statuses for TP/SL order execution
        if not trade or trade.status not in ["pending", "pending_tp", "pending_sl"]:
            return False

        # Use shorter timeout for TP/SL orders (should have cached price from WebSocket)
        price_start = time.time()
        try:
            price = await await_live_price(trade.symbol, timeout=3.0)
            price_time = (time.time() - price_start) * 1000
            print(f"[PERF] Price fetch for {trade.symbol} took {price_time:.1f}ms")
        except RuntimeError as price_error:
            price_time = (time.time() - price_start) * 1000
            print(
                f"⚠️  [SKIP] TP/SL order {trade_id} for {trade.symbol} skipped - "
                f"price unavailable after {price_time:.1f}ms: {price_error}"
            )
            return False  # Skip this order, will be retried in next monitoring cycle

        should_execute = False
        if trade.order_type == "limit" and trade.limit_price:
            if trade.side == "BUY" and price <= trade.limit_price:
                should_execute = True
            if trade.side == "SELL" and price >= trade.limit_price:
                should_execute = True
        elif trade.order_type in {"stop", "stop_loss"} and trade.trigger_price:
            if trade.side == "BUY" and price >= trade.trigger_price:
                should_execute = True
            if trade.side == "SELL" and price <= trade.trigger_price:
                should_execute = True
        elif trade.order_type == "take_profit" and trade.trigger_price:
            if price >= trade.trigger_price:
                should_execute = True

        if not should_execute:
            return False

        payload = TradeCreate(
            organization_id=trade.organization_id,
            portfolio_id=trade.portfolio_id,
            customer_id=trade.customer_id,
            trade_type=trade.trade_type,
            symbol=trade.symbol,
            exchange=trade.exchange,
            segment=trade.segment,
            side=trade.side,
            order_type="market",
            quantity=trade.quantity,
            limit_price=None,
            trigger_price=None,
            source=trade.source,
            metadata=trade.metadata,
        )

        # Recalculate auto_sell_at based on actual execution time if auto_sell_after was specified
        execution_time = datetime.utcnow()
        if payload.auto_sell_after and trade.side == "BUY":
            auto_sell_at = self._calculate_auto_sell_at(payload, execution_time)
            if auto_sell_at:
                # Update the trade with the recalculated auto_sell_at
                # The streaming_order_monitor will pick this up and auto-sell when time expires
                await self.prisma.trade.update(
                    where={"id": trade.id},
                    data={"auto_sell_at": auto_sell_at}
                )
                import logging
                logging.getLogger(__name__).info(
                    "🕒 Auto-sell scheduled for trade %s at %s (streaming monitor will handle)",
                    trade.id, auto_sell_at
                )
        
        # Create payload for execution (will create/update TradeExecutionLog)
        exec_start = time.time()
        updated_trade = await self._execute_market_order(payload, price, existing_trade_id=trade.id)
        exec_time = (time.time() - exec_start) * 1000
        print(f"[PERF] Market order execution for {trade.symbol} took {exec_time:.1f}ms")
        
        # CRITICAL: If this was a TP/SL order, cancel the counterpart
        # e.g., if TP executed, cancel any pending SL orders for same symbol
        if trade.status in ["pending_tp", "pending_sl"]:
            await self._cancel_counterpart_tp_sl_orders(
                trade.portfolio_id, 
                trade.symbol, 
                executed_order_id=trade.id
            )
        
        portfolio_start = time.time()
        portfolio_snapshot = await self._build_portfolio_snapshot(trade.portfolio_id)
        portfolio_time = (time.time() - portfolio_start) * 1000
        print(f"[PERF] Portfolio snapshot for TP/SL order took {portfolio_time:.1f}ms")
        
        total_time = (time.time() - start_time) * 1000
        print(f"[PERF] Total TP/SL order processing for {trade.symbol} took {total_time:.1f}ms")

        return True

    async def _execute_market_order(
        self,
        payload: TradeCreate,
        execution_price: Decimal,
        existing_trade_id: Optional[str] = None,
    ) -> Dict:
        gross_value = execution_price * Decimal(str(payload.quantity))
        fees = (gross_value * FEE_RATE).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
        taxes = (gross_value * TAX_RATE).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
        if payload.side == "BUY":
            net_amount = (gross_value + fees + taxes) * Decimal(-1)
        else:
            net_amount = gross_value - fees - taxes

        if existing_trade_id:
            trade = await self.prisma.trade.update(
                where={"id": existing_trade_id},
                data={
                    "status": "executed",
                    "price": execution_price,
                    "executed_price": execution_price,
                    "executed_quantity": payload.quantity,
                    "execution_time": datetime.utcnow(),
                    "fees": fees,
                    "taxes": taxes,
                    "net_amount": net_amount,
                },
            )
        else:
            import json
            # Provide defaults for required fields if not specified
            exchange = payload.exchange or "NSE"
            segment = payload.segment or "EQUITY"
            
            execution_time = datetime.utcnow()
            auto_sell_at = self._calculate_auto_sell_at(payload, execution_time)
            
            trade_data = {
                "organization_id": payload.organization_id,
                "portfolio_id": payload.portfolio_id,
                "customer_id": payload.customer_id,
                "trade_type": payload.trade_type,
                "symbol": payload.symbol,
                "exchange": exchange,
                "segment": segment,
                "side": payload.side,
                "order_type": payload.order_type,
                "quantity": payload.quantity,
                "limit_price": payload.limit_price,
                "status": "executed",
                "price": execution_price,
                "executed_price": execution_price,
                "executed_quantity": payload.quantity,
                "execution_time": execution_time,
                "fees": fees,
                "taxes": taxes,
                "net_amount": net_amount,
                "source": payload.source,
                "metadata": json.dumps(payload.metadata) if payload.metadata else "{}",
            }
            
            if auto_sell_at:
                trade_data["auto_sell_at"] = auto_sell_at
            
            trade = await self.prisma.trade.create(data=trade_data)
            
            # Log auto-sell scheduling (streaming_order_monitor will handle execution)
            if auto_sell_at and payload.side == "BUY":
                import logging
                logging.getLogger(__name__).info(
                    "🕒 Auto-sell scheduled for trade %s at %s (streaming monitor will handle)",
                    trade.id, auto_sell_at
                )

        if payload.side == "BUY":
            await self._apply_buy_execution(payload, execution_price)
        elif payload.side == "SHORT_SELL":
            # SHORT_SELL is handled by trade_execution_service
            # No realized P&L for opening short position
            pass
        else:  # SELL
            realized_pnl = await self._apply_sell_execution(payload, execution_price)
            # Update trade with realized_pnl
            if realized_pnl is not None:
                await self.prisma.trade.update(
                    where={"id": trade.id},
                    data={"realized_pnl": realized_pnl}
                )

        await self._create_trade_execution_log(trade, payload)

        await self._send_execution_email(trade.dict(), payload)
        
        # Capture post-trade snapshot for the trading agent
        await self._capture_post_trade_snapshot(payload)

        # Publish to Redis for Pathway monitoring (if TP/SL set)
        trade_dict = trade.dict()
        if trade_dict.get("take_profit_price") or trade_dict.get("stop_loss_price"):
            exec_time = trade_dict.get("execution_time")
            if exec_time:
                exec_time_str = exec_time.isoformat() if hasattr(exec_time, 'isoformat') else str(exec_time)
            else:
                exec_time_str = datetime.utcnow().isoformat()
            
            await self._publish_trade_event("trades:executed", {
                "trade_id": trade_dict["id"],
                "symbol": trade_dict["symbol"],
                "side": trade_dict["side"],
                "quantity": trade_dict["quantity"],
                "entry_price": float(trade_dict["executed_price"] or trade_dict["price"]),
                "take_profit_price": float(trade_dict["take_profit_price"]) if trade_dict.get("take_profit_price") else None,
                "stop_loss_price": float(trade_dict["stop_loss_price"]) if trade_dict.get("stop_loss_price") else None,
                "portfolio_id": trade_dict["portfolio_id"],
                "customer_id": trade_dict["customer_id"],
                "execution_time": exec_time_str,
            })

        return trade.dict()

    async def _create_pending_trade(self, payload: TradeCreate) -> Dict:
        import json
        if payload.order_type == "limit" and payload.limit_price is None:
            raise ValueError("limit_price required for limit orders")
        if payload.order_type in {"stop", "stop_loss", "take_profit"} and payload.trigger_price is None:
            raise ValueError("trigger_price required for stop/take-profit orders")

        # Provide defaults for required fields if not specified
        exchange = payload.exchange or "NSE"
        segment = payload.segment or "EQUITY"

        # For pending orders, don't set price to limit_price - it should be None or current market price
        # The price will be set when the order is executed
        trade_price = None
        if payload.order_type == "limit" and payload.limit_price:
            # For limit orders, we can optionally set price to limit_price for reference
            # but it won't cause immediate execution
            trade_price = payload.limit_price
        elif payload.order_type in {"stop", "stop_loss", "take_profit"} and payload.trigger_price:
            # For stop/take-profit, price should be None until triggered
            trade_price = None
        
        # Store auto_sell_after in metadata for pending orders so we can recalculate when executed
        if payload.auto_sell_after and payload.side == "BUY":
            if payload.metadata is None:
                payload.metadata = {}
            payload.metadata["auto_sell_after"] = payload.auto_sell_after
        
        # For pending orders, we don't set auto_sell_at yet - it will be calculated when executed
        # But we can pre-calculate it for reference (will be recalculated on execution)
        auto_sell_at = None
        if payload.auto_sell_after and payload.side == "BUY":
            # For pending orders, calculate auto_sell_at assuming execution happens now
            # The actual auto_sell_at will be recalculated when the order executes
            current_time = datetime.utcnow()
            auto_sell_at = self._calculate_auto_sell_at(payload, current_time)
        
        trade_data = {
            "organization_id": payload.organization_id,
            "portfolio_id": payload.portfolio_id,
            "customer_id": payload.customer_id,
            "trade_type": payload.trade_type,
            "symbol": payload.symbol,
            "exchange": exchange,
            "segment": segment,
            "side": payload.side,
            "order_type": payload.order_type,
            "quantity": payload.quantity,
            "limit_price": payload.limit_price,
            "price": trade_price,  # None for stop/take-profit, limit_price for limit (reference only)
            "trigger_price": payload.trigger_price,
            "status": "pending",  # Always pending for non-market orders
            "source": payload.source,
            "metadata": json.dumps(payload.metadata) if payload.metadata else "{}",
        }
        
        if auto_sell_at:
            trade_data["auto_sell_at"] = auto_sell_at
        
        trade = await self.prisma.trade.create(data=trade_data)

        # Create TradeExecutionLog for pending manual trades
        await self._create_trade_execution_log(trade, payload, status="pending")

        # DO NOT enqueue pending trades immediately - let the order monitoring service handle them
        # The order monitoring service will check and execute when conditions are met
        # self._enqueue_pending_trade(trade.id)  # REMOVED - let order monitor handle it
        
        # Publish to Redis for Pathway monitoring
        trade_dict = trade.dict()
        await self._publish_trade_event("trades:pending", {
            "order_id": trade_dict["id"],
            "symbol": trade_dict["symbol"],
            "side": trade_dict["side"],
            "order_type": trade_dict["order_type"],
            "quantity": trade_dict["quantity"],
            "limit_price": float(trade_dict["limit_price"]) if trade_dict.get("limit_price") else None,
            "trigger_price": float(trade_dict["trigger_price"]) if trade_dict.get("trigger_price") else None,
            "portfolio_id": trade_dict["portfolio_id"],
            "customer_id": trade_dict["customer_id"],
            "parent_trade_id": payload.metadata.get("parent_trade_id") if payload.metadata else None,
            "status": trade_dict["status"],
        })
        
        return trade.dict()

    async def _apply_buy_execution(self, payload: TradeCreate, execution_price: Decimal) -> None:
        """Apply buy execution - update position atomically."""
        position = await self.prisma.position.find_first(
            where={"portfolio_id": payload.portfolio_id, "symbol": payload.symbol}
        )

        quantity_decimal = Decimal(payload.quantity)
        total_cost = (execution_price * quantity_decimal).quantize(FOUR_DP)

        if position:
            new_quantity = position.quantity + payload.quantity
            # Use Decimal consistently for precision
            previous_value = Decimal(str(position.average_buy_price)) * Decimal(str(position.quantity))
            new_average = (previous_value + total_cost) / Decimal(str(new_quantity))
            new_average = new_average.quantize(FOUR_DP, rounding=ROUND_HALF_UP)
            
            # Use transaction for atomic position update
            async with self.prisma.tx() as tx:
                await tx.position.update(
                    where={"id": position.id},
                    data={
                        "quantity": new_quantity,
                        "average_buy_price": new_average,
                        "status": "open",
                    },
                )
        else:
            # NOTE: Legacy position creation path - deprecated
            # Position creation now requires agent_id and allocation_id (NOT NULL)
            # Use trade_execution_service.py for proper position management
            return

        await self._recalculate_portfolio_value(payload.portfolio_id)

    async def _apply_sell_execution(self, payload: TradeCreate, execution_price: Decimal) -> Decimal:
        """
        Apply sell execution - update position and calculate realized PnL.
        Uses Prisma transaction for atomic writes to ensure data consistency.
        
        Returns:
            Decimal: The realized PnL from this sale
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # For test compatibility, avoid using 'include' parameter which isn't supported by in-memory Prisma
        position = await self.prisma.position.find_first(
            where={"portfolio_id": payload.portfolio_id, "symbol": payload.symbol}
        )
        if not position or position.quantity < payload.quantity:
            raise ValueError("Insufficient holdings to execute sell order")

        # Fetch agent and allocation separately for test compatibility
        agent = None
        allocation = None
        if position.agent_id:
            agent = await self.prisma.tradingagent.find_unique(
                where={"id": position.agent_id}
            )
            if agent and agent.portfolio_allocation_id:
                allocation = await self.prisma.portfolioallocation.find_unique(
                    where={"id": agent.portfolio_allocation_id}
                )

        # Calculate realized PnL: (sell_price - average_buy_price) * quantity_sold
        quantity_sold = Decimal(str(payload.quantity))
        average_buy_price = Decimal(str(position.average_buy_price))
        realized_pnl = (execution_price - average_buy_price) * quantity_sold
        realized_pnl = realized_pnl.quantize(FOUR_DP, rounding=ROUND_HALF_UP)

        # Get current realized_pnl (default to 0 if None)
        current_realized_pnl = Decimal(str(position.realized_pnl)) if position.realized_pnl else Decimal(0)
        new_realized_pnl = current_realized_pnl + realized_pnl

        remaining = position.quantity - payload.quantity
        
        # Fetch portfolio for atomic update
        portfolio = await self.prisma.portfolio.find_unique(where={"id": payload.portfolio_id})
        
        # Calculate all values before the transaction
        portfolio_new_realized_pnl = None
        if portfolio:
            portfolio_current_realized_pnl = Decimal(str(portfolio.total_realized_pnl)) if portfolio.total_realized_pnl else Decimal(0)
            portfolio_new_realized_pnl = portfolio_current_realized_pnl + realized_pnl
        
        agent_new_pnl = None
        agent_current_pnl = None
        if agent:
            agent_current_pnl = Decimal(str(agent.realized_pnl)) if agent.realized_pnl else Decimal(0)
            agent_new_pnl = agent_current_pnl + realized_pnl
        
        alloc_new_pnl = None
        alloc_new_cash = None
        alloc_current_pnl = None
        alloc_current_cash = None
        sale_proceeds = None
        if allocation:
            alloc_current_pnl = Decimal(str(allocation.realized_pnl)) if allocation.realized_pnl else Decimal(0)
            alloc_new_pnl = alloc_current_pnl + realized_pnl
            
            # Calculate sale proceeds to return to allocation (net of fees)
            gross_value = execution_price * quantity_sold
            fees = (gross_value * FEE_RATE).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
            taxes = (gross_value * TAX_RATE).quantize(FOUR_DP, rounding=ROUND_HALF_UP)
            sale_proceeds = gross_value - fees - taxes
            
            alloc_current_cash = Decimal(str(allocation.available_cash)) if allocation.available_cash else Decimal(0)
            alloc_new_cash = alloc_current_cash + sale_proceeds

        # Use Prisma transaction for atomic writes
        # All updates succeed or all fail together
        async with self.prisma.tx() as tx:
            # 1. Update portfolio's total_realized_pnl
            if portfolio and portfolio_new_realized_pnl is not None:
                await tx.portfolio.update(
                    where={"id": payload.portfolio_id},
                    data={"total_realized_pnl": portfolio_new_realized_pnl},
                )

            # 2. Update agent realized_pnl
            if agent and agent_new_pnl is not None:
                await tx.tradingagent.update(
                    where={"id": agent.id},
                    data={"realized_pnl": agent_new_pnl},
                )
                
            # 3. Update allocation realized_pnl and available_cash
            if allocation and alloc_new_pnl is not None and alloc_new_cash is not None:
                await tx.portfolioallocation.update(
                    where={"id": allocation.id},
                    data={
                        "realized_pnl": alloc_new_pnl,
                        "available_cash": alloc_new_cash,
                    },
                )

            # 4. Update position (close or reduce quantity)
            if remaining == 0:
                # Mark position as closed instead of deleting
                await tx.position.update(
                    where={"id": position.id},
                    data={
                        "quantity": 0,
                        "realized_pnl": new_realized_pnl,
                        "status": "closed",
                        "closed_at": datetime.utcnow(),
                    },
                )
            else:
                # Keep position open, update quantity and realized_pnl
                await tx.position.update(
                    where={"id": position.id},
                    data={
                        "quantity": remaining,
                        "realized_pnl": new_realized_pnl,
                        "status": "open",
                    },
                )

        # Log updates after successful transaction
        if agent and agent_new_pnl is not None:
            logger.info(
                "💰 Updated agent %s realized_pnl: ₹%.2f → ₹%.2f (+₹%.2f)",
                agent.agent_name, float(agent_current_pnl), float(agent_new_pnl), float(realized_pnl)
            )
            
        if allocation and alloc_new_pnl is not None and sale_proceeds is not None:
            logger.info(
                "💰 Updated allocation %s: realized_pnl ₹%.2f → ₹%.2f (+₹%.2f), cash ₹%.2f → ₹%.2f (+₹%.2f)",
                allocation.allocation_type, 
                float(alloc_current_pnl), float(alloc_new_pnl), float(realized_pnl),
                float(alloc_current_cash), float(alloc_new_cash), float(sale_proceeds)
            )

        await self._recalculate_portfolio_value(payload.portfolio_id)
        
        # Return the realized PnL for this specific sale
        return realized_pnl

    async def _recalculate_portfolio_value(self, portfolio_id: str) -> None:
        """
        DEPRECATED: Portfolio value is no longer stored as a field.
        Position no longer has current_price/current_value fields.
        Portfolio no longer has current_value field.
        Value is calculated on-demand via SnapshotService using live prices.
        """
        # No-op: This method is deprecated but kept for compatibility
        pass

    async def _cancel_counterpart_tp_sl_orders(
        self,
        portfolio_id: str,
        symbol: str,
        executed_order_id: str,
    ) -> int:
        """
        Cancel any remaining pending TP/SL orders for the same symbol after one executes.
        
        When a TP order executes, we need to cancel the corresponding SL order (and vice versa).
        This prevents the orphaned counterpart order from executing later.
        
        Args:
            portfolio_id: Portfolio ID
            symbol: Symbol of the executed order
            executed_order_id: ID of the order that just executed (to exclude)
            
        Returns:
            Number of orders cancelled
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Find all pending TP/SL orders for this symbol (excluding the one we just executed)
            pending_orders = await self.prisma.trade.find_many(
                where={
                    "portfolio_id": portfolio_id,
                    "symbol": symbol,
                    "status": {"in": ["pending_tp", "pending_sl"]},
                    "id": {"not": executed_order_id},
                }
            )
            
            if not pending_orders:
                return 0
            
            # Cancel each pending order
            cancelled_count = 0
            import json
            for order in pending_orders:
                # Parse existing metadata
                existing_meta = order.metadata if isinstance(order.metadata, dict) else {}
                if isinstance(order.metadata, str):
                    try:
                        existing_meta = json.loads(order.metadata)
                    except:
                        existing_meta = {}
                
                updated_meta = {
                    **existing_meta,
                    "cancelled_reason": "counterpart_executed",
                    "cancelled_by_order": executed_order_id,
                    "cancelled_at": datetime.utcnow().isoformat(),
                }
                
                await self.prisma.trade.update(
                    where={"id": order.id},
                    data={
                        "status": "cancelled",
                        "metadata": json.dumps(updated_meta),
                    },
                )
                cancelled_count += 1
                logger.info(
                    "✅ Cancelled counterpart %s order %s for %s (triggered by %s)",
                    order.status.replace("pending_", "").upper(),
                    order.id[:8],
                    symbol,
                    executed_order_id[:8],
                )
            
            return cancelled_count
            
        except Exception as exc:
            logger.exception(
                "Failed to cancel counterpart TP/SL orders for %s: %s",
                symbol, exc
            )
            return 0

    async def _build_portfolio_snapshot(self, portfolio_id: str) -> Dict:
        """
        Build portfolio snapshot with current_value calculation.
        current_value = available_cash + sum(position values)
        """
        # For test compatibility, avoid using 'include' parameter which isn't supported by in-memory Prisma
        portfolio = await self.prisma.portfolio.find_unique_or_raise(
            where={"id": portfolio_id}
        )

        # Get positions separately for test compatibility
        positions = await self.prisma.position.find_many(
            where={"portfolio_id": portfolio_id, "status": "open"}
        )
        
        # Calculate current_value: available_cash + positions value
        current_value = Decimal(str(portfolio.available_cash))
        
        # Add value of all open positions
        for position in positions:
            try:
                # Use latest price from market data
                price = self.market_data.get_latest_price(position.symbol)
                if price is None:
                    # Fallback to average price if live price unavailable
                    price = position.average_buy_price
                position_value = Decimal(str(price)) * Decimal(str(position.quantity))
                current_value += position_value
            except Exception as exc:
                # Log error but continue with other positions
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to calculate position value for {position.symbol}: {exc}"
                )
        
        return {
            "id": portfolio.id,
            "available_cash": portfolio.available_cash,
            "current_value": current_value,
            "updated_at": portfolio.updated_at,
        }

    async def _ensure_portfolio(self, portfolio_id: str) -> None:
        portfolio = await self.prisma.portfolio.find_unique(where={"id": portfolio_id})
        if not portfolio:
            raise ValueError(f"Portfolio {portfolio_id} not found")

    def _calculate_auto_sell_at(self, payload: TradeCreate, execution_time: datetime) -> Optional[datetime]:
        """Calculate auto_sell_at timestamp from auto_sell_after parameter.
        
        Args:
            payload: TradeCreate payload with optional auto_sell_after (in seconds)
            execution_time: When the trade was/will be executed
            
        Returns:
            datetime if auto_sell_at should be set, None otherwise
        """
        # Only apply to BUY orders
        if payload.side != "BUY":
            return None
        
        # Check if auto_sell_after is specified
        if not payload.auto_sell_after or payload.auto_sell_after <= 0:
            return None
        
        # Calculate auto_sell_at = execution_time + auto_sell_after seconds
        auto_sell_at = execution_time + timedelta(seconds=payload.auto_sell_after)
        
        # Check if auto_sell_at would be after market close (15:30 IST)
        try:
            ist = ZoneInfo("Asia/Kolkata")
            # Ensure auto_sell_at is timezone-aware
            if auto_sell_at.tzinfo is None:
                from datetime import timezone
                auto_sell_at = auto_sell_at.replace(tzinfo=timezone.utc)
            local_auto_sell = auto_sell_at.astimezone(ist)
        except Exception as tz_error:
            # CRITICAL: If timezone conversion fails, reject auto-sell to prevent errors
            import logging
            logger = logging.getLogger(__name__)
            logger.error(
                "❌ Timezone conversion failed for auto-sell: %s. Rejecting auto-sell to prevent errors.",
                tz_error
            )
            return None
        
        # Market closes at 15:30 IST (3:30 PM)
        if local_auto_sell.hour > 15 or (local_auto_sell.hour == 15 and local_auto_sell.minute > 30):
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "⚠️ Auto-sell time %s (local %s) would be after market close (>15:30 IST), skipping auto-sell",
                auto_sell_at, local_auto_sell
            )
            return None
        
        return auto_sell_at

    def _enqueue_pending_trade(self, trade_id: str) -> None:
        try:
            from celery_app import celery_app

            celery_app.send_task(
                "trading.process_pending_trade",
                args=[trade_id],
                queue="trading",
                routing_key="trading"
            )
        except Exception:  # pragma: no cover - defensive logging
            import logging

            logging.getLogger(__name__).exception("Failed to enqueue pending trade %s", trade_id)

    async def _create_trade_execution_log(
        self, 
        trade, 
        payload: TradeCreate, 
        status: Optional[str] = None
    ) -> None:
        """Create trade execution log for manual trades.
        
        Args:
            trade: Trade record (dict or Prisma model)
            payload: TradeCreate payload
            status: Optional status override (defaults to trade.status)
        """
        import uuid
        import json
        from decimal import Decimal

        try:
            # Handle both dict and Prisma model objects
            if isinstance(trade, dict):
                trade_id = trade.get("id")
                trade_status = status or trade.get("status", "executed")
            else:
                # Prisma model object - use attribute access
                trade_id = getattr(trade, "id", None)
                trade_status = status or getattr(trade, "status", "executed")
            
            # Check if log already exists for this trade
            existing_log = await self.prisma.tradeexecutionlog.find_first(
                where={"trade_id": trade_id}
            )
            
            if existing_log:
                # Update existing log (e.g., when pending trade is executed)
                await self.prisma.tradeexecutionlog.update(
                    where={"id": existing_log.id},
                    data={
                        "status": trade_status,
                        "execution_time": datetime.utcnow() if trade_status == "executed" else None,
                    }
                )
            else:
                # Create new log entry
                await self.prisma.tradeexecutionlog.create(
                    data={
                        "trade_id": trade_id,  # Reference to the Trade record
                        "request_id": f"manual_{uuid.uuid4().hex[:12]}",
                        "status": trade_status,
                        "order_type": payload.order_type,
                        "metadata": json.dumps({
                            "source": payload.source or "manual",
                            "order_type": payload.order_type,
                        }),
                    },
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to create trade execution log: {e}")

    async def _send_execution_email(self, trade_dict: Dict, payload: TradeCreate) -> None:
        """Send email notification for trade execution."""
        try:
            import logging
            logging.getLogger(__name__).debug(
                f"Trade execution email skipped (customer_id: {payload.customer_id})"
            )
            return
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to send trade execution email: {e}")

    async def _capture_post_trade_snapshot(self, payload: TradeCreate) -> None:
        """
        Capture snapshot for the trading agent after a trade is executed.
        
        This ensures we have accurate point-in-time snapshots that reflect
        the portfolio state immediately after each trade.
        
        Args:
            payload: TradeCreate payload containing allocation_id or portfolio_id
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Skip snapshot in test mode (when prisma is mocked)
        if hasattr(self.prisma, '_mock_name') or str(type(self.prisma).__name__) in ('AsyncMock', 'MagicMock'):
            logger.debug("Skipping snapshot capture in test mode")
            return
        
        try:
            from services.snapshot_service import TradingAgentSnapshotService
            snapshot_service = TradingAgentSnapshotService(logger=logger)
            
            agent_id = None
            
            # Try to get agent_id from allocation
            if payload.allocation_id:
                allocation = await self.prisma.portfolioallocation.find_unique(
                    where={"id": payload.allocation_id},
                    include={"tradingAgent": True}
                )
                if allocation and allocation.tradingAgent:
                    agent_id = allocation.tradingAgent.id
            
            # Fallback: find the agent from portfolio_id that owns this position
            if not agent_id and payload.portfolio_id:
                # Find any active agent for this portfolio (prefer liquid for manual trades)
                agents = await self.prisma.tradingagent.find_many(
                    where={
                        "portfolio_id": payload.portfolio_id,
                        "status": "active"
                    },
                    order={"created_at": "desc"}
                )
                if agents:
                    # Prefer liquid agent for manual trades
                    liquid_agents = [a for a in agents if a.agent_type == "liquid"]
                    agent_id = liquid_agents[0].id if liquid_agents else agents[0].id
            
            if agent_id:
                # Capture agent snapshot
                result = await snapshot_service.capture_agent_snapshot(agent_id)
                if result:
                    logger.info(
                        "📸 Post-trade snapshot captured for agent %s: value=₹%.2f",
                        agent_id[:8],
                        result.get("current_value", 0)
                    )
            
            # Also capture portfolio snapshot
            if payload.portfolio_id:
                result = await snapshot_service.capture_portfolio_snapshot(payload.portfolio_id)
                if result:
                    logger.info(
                        "📸 Post-trade portfolio snapshot: value=₹%.2f",
                        result.get("current_value", 0)
                    )
                    
        except Exception as e:
            logger.warning("Failed to capture post-trade snapshot: %s", e)
