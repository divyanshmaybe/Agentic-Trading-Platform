from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

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

FEE_RATE = Decimal(os.getenv("TRADE_FEE_RATE", "0.0005"))
TAX_RATE = Decimal(os.getenv("TRADE_TAX_RATE", "0.00025"))
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

    async def handle_trade(self, payload: TradeCreate) -> TradeExecutionResult:
        await self._ensure_portfolio(payload.portfolio_id)

        if payload.order_type == "market":
            # For manual trades, use longer timeout and fallback to get_or_fetch_price
            try:
                # First try with longer timeout (15 seconds for manual trades)
                execution_price = await await_live_price(payload.symbol, timeout=15.0)
            except RuntimeError:
                # If await_live_price times out, fallback to get_or_fetch_price
                # This handles cases where the symbol isn't subscribed yet or market data is busy
                self.market_data.register_symbol(payload.symbol)
                price = self.market_data.get_latest_price(payload.symbol)
                if price is None:
                    price = self.market_data.get_or_fetch_price(payload.symbol)
                if price is None:
                    raise RuntimeError(f"Unable to fetch price for {payload.symbol} after timeout and fallback attempts")
                execution_price = price
            
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
        trade = await self.prisma.trade.find_unique(where={"id": trade_id})
        if not trade or trade.status != "pending":
            return False

        price = await await_live_price(trade.symbol, timeout=15.0)

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
                await self.prisma.trade.update(
                    where={"id": trade.id},
                    data={"auto_sell_at": auto_sell_at}
                )
        
        # Create payload for execution (will create/update TradeExecutionLog)
        updated_trade = await self._execute_market_order(payload, price, existing_trade_id=trade.id)
        portfolio_snapshot = await self._build_portfolio_snapshot(trade.portfolio_id)

        return True

    async def _execute_market_order(
        self,
        payload: TradeCreate,
        execution_price: Decimal,
        existing_trade_id: Optional[str] = None,
    ) -> Dict:
        gross_value = execution_price * Decimal(payload.quantity)
        fees = (gross_value * FEE_RATE).quantize(FOUR_DP)
        taxes = (gross_value * TAX_RATE).quantize(FOUR_DP)
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

        if payload.side == "BUY":
            await self._apply_buy_execution(payload, execution_price)
        else:
            await self._apply_sell_execution(payload, execution_price)

        await self._create_trade_execution_log(trade, payload)

        await self._send_execution_email(trade.dict(), payload)

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
        
        return trade.dict()

    async def _apply_buy_execution(self, payload: TradeCreate, execution_price: Decimal) -> None:
        position = await self.prisma.position.find_first(
            where={"portfolio_id": payload.portfolio_id, "symbol": payload.symbol}
        )

        quantity_decimal = Decimal(payload.quantity)
        total_cost = (execution_price * quantity_decimal).quantize(FOUR_DP)

        if position:
            new_quantity = position.quantity + payload.quantity
            previous_value = position.average_buy_price * Decimal(position.quantity)
            new_average = (previous_value + total_cost) / Decimal(new_quantity)
            new_average = new_average.quantize(FOUR_DP)
            await self.prisma.position.update(
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

    async def _apply_sell_execution(self, payload: TradeCreate, execution_price: Decimal) -> None:
        position = await self.prisma.position.find_first(
            where={"portfolio_id": payload.portfolio_id, "symbol": payload.symbol}
        )
        if not position or position.quantity < payload.quantity:
            raise ValueError("Insufficient holdings to execute sell order")

        # Calculate realized PnL: (sell_price - average_buy_price) * quantity_sold
        quantity_sold = Decimal(payload.quantity)
        average_buy_price = Decimal(str(position.average_buy_price))
        realized_pnl = (execution_price - average_buy_price) * quantity_sold
        realized_pnl = realized_pnl.quantize(FOUR_DP)

        # Get current realized_pnl (default to 0 if None)
        current_realized_pnl = Decimal(str(position.realized_pnl)) if position.realized_pnl else Decimal(0)
        new_realized_pnl = current_realized_pnl + realized_pnl

        remaining = position.quantity - payload.quantity
        
        # Update portfolio's total_realized_pnl
        portfolio = await self.prisma.portfolio.find_unique(where={"id": payload.portfolio_id})
        if portfolio:
            portfolio_current_realized_pnl = Decimal(str(portfolio.total_realized_pnl)) if portfolio.total_realized_pnl else Decimal(0)
            portfolio_new_realized_pnl = portfolio_current_realized_pnl + realized_pnl
            
            await self.prisma.portfolio.update(
                where={"id": payload.portfolio_id},
                data={"total_realized_pnl": portfolio_new_realized_pnl},
            )

        if remaining == 0:
            # Mark position as closed instead of deleting
            await self.prisma.position.update(
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
            await self.prisma.position.update(
                where={"id": position.id},
                data={
                    "quantity": remaining,
                    "realized_pnl": new_realized_pnl,
                    "status": "open",
                },
            )

        await self._recalculate_portfolio_value(payload.portfolio_id)

    async def _recalculate_portfolio_value(self, portfolio_id: str) -> None:
        """
        DEPRECATED: Portfolio value is no longer stored as a field.
        Position no longer has current_price/current_value fields.
        Portfolio no longer has current_value field.
        Value is calculated on-demand via SnapshotService using live prices.
        """
        # No-op: This method is deprecated but kept for compatibility
        pass

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
            local_auto_sell = auto_sell_at.astimezone(ist)
        except Exception:
            # If timezone conversion fails, use naive comparison
            local_auto_sell = auto_sell_at
        
        # Market closes at 15:30 IST
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
            from workers.trade_tasks import process_pending_trade

            process_pending_trade.delay(trade_id)
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
