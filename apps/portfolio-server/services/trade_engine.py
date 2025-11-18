from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

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

        await self._execute_market_order(payload, price, existing_trade_id=trade.id)
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
            trade = await self.prisma.trade.create(
                data={
                    "organization_id": payload.organization_id,
                    "portfolio_id": payload.portfolio_id,
                    "customer_id": payload.customer_id,
                    "trade_type": payload.trade_type,
                    "symbol": payload.symbol,
                    "exchange": payload.exchange,
                    "segment": payload.segment,
                    "side": payload.side,
                    "order_type": payload.order_type,
                    "quantity": payload.quantity,
                    "limit_price": payload.limit_price,
                    "status": "executed",
                    "price": execution_price,
                    "executed_price": execution_price,
                    "executed_quantity": payload.quantity,
                    "execution_time": datetime.utcnow(),
                    "fees": fees,
                    "taxes": taxes,
                    "net_amount": net_amount,
                    "source": payload.source,
                    "metadata": json.dumps(payload.metadata) if payload.metadata else "{}",
                }
            )

        if payload.side == "BUY":
            await self._apply_buy_execution(payload, execution_price)
        else:
            await self._apply_sell_execution(payload, execution_price)

        # Send email notification asynchronously
        await self._send_execution_email(trade.dict(), payload)

        return trade.dict()

    async def _create_pending_trade(self, payload: TradeCreate) -> Dict:
        import json
        if payload.order_type == "limit" and payload.limit_price is None:
            raise ValueError("limit_price required for limit orders")
        if payload.order_type in {"stop", "stop_loss", "take_profit"} and payload.trigger_price is None:
            raise ValueError("trigger_price required for stop/take-profit orders")

        trade = await self.prisma.trade.create(
            data={
                "organization_id": payload.organization_id,
                "portfolio_id": payload.portfolio_id,
                "customer_id": payload.customer_id,
                "trade_type": payload.trade_type,
                "symbol": payload.symbol,
                "exchange": payload.exchange,
                "segment": payload.segment,
                "side": payload.side,
                "order_type": payload.order_type,
                "quantity": payload.quantity,
                "limit_price": payload.limit_price,
                "price": payload.limit_price,
                "trigger_price": payload.trigger_price,
                "status": "pending",
                "source": payload.source,
                "metadata": json.dumps(payload.metadata) if payload.metadata else "{}",
            }
        )

        self._enqueue_pending_trade(trade.id)
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
                    "current_price": execution_price,
                    "current_value": (execution_price * Decimal(new_quantity)).quantize(FOUR_DP),
                    "status": "open",
                },
            )
        else:
            await self.prisma.position.create(
                data={
                    "portfolio_id": payload.portfolio_id,
                    "agent_id": None,
                    "symbol": payload.symbol,
                    "exchange": payload.exchange,
                    "segment": payload.segment,
                    "quantity": payload.quantity,
                    "average_buy_price": execution_price,
                    "current_price": execution_price,
                    "current_value": total_cost,
                    "position_type": "long",
                    "status": "open",
                }
            )

        await self._recalculate_portfolio_value(payload.portfolio_id)

    async def _apply_sell_execution(self, payload: TradeCreate, execution_price: Decimal) -> None:
        position = await self.prisma.position.find_first(
            where={"portfolio_id": payload.portfolio_id, "symbol": payload.symbol}
        )
        if not position or position.quantity < payload.quantity:
            raise ValueError("Insufficient holdings to execute sell order")

        remaining = position.quantity - payload.quantity
        if remaining == 0:
            await self.prisma.position.delete(where={"id": position.id})
        else:
            await self.prisma.position.update(
                where={"id": position.id},
                data={
                    "quantity": remaining,
                    "current_price": execution_price,
                    "current_value": (execution_price * Decimal(remaining)).quantize(FOUR_DP),
                    "status": "open",
                },
            )

        await self._recalculate_portfolio_value(payload.portfolio_id)

    async def _recalculate_portfolio_value(self, portfolio_id: str) -> None:
        positions = await self.prisma.position.find_many(where={"portfolio_id": portfolio_id})
        total = Decimal(0)

        for position in positions:
            self.market_data.register_symbol(position.symbol)
            price = self.market_data.get_latest_price(position.symbol)
            if price is None:
                price = await await_live_price(position.symbol, timeout=5.0)

            current_value = (price * Decimal(position.quantity)).quantize(FOUR_DP)
            total += current_value

            await self.prisma.position.update(
                where={"id": position.id},
                data={
                    "current_price": price,
                    "current_value": current_value,
                },
            )

        await self.prisma.portfolio.update(
            where={"id": portfolio_id},
            data={"current_value": total.quantize(FOUR_DP)},
        )

    async def _build_portfolio_snapshot(self, portfolio_id: str) -> Dict:
        portfolio = await self.prisma.portfolio.find_unique_or_raise(where={"id": portfolio_id})
        return {
            "id": portfolio.id,
            "current_value": portfolio.current_value,
            "updated_at": portfolio.updated_at,
        }

    async def _ensure_portfolio(self, portfolio_id: str) -> None:
        portfolio = await self.prisma.portfolio.find_unique(where={"id": portfolio_id})
        if not portfolio:
            raise ValueError(f"Portfolio {portfolio_id} not found")

    def _enqueue_pending_trade(self, trade_id: str) -> None:
        try:
            from workers.trade_tasks import process_pending_trade

            process_pending_trade.delay(trade_id)
        except Exception:  # pragma: no cover - defensive logging
            import logging

            logging.getLogger(__name__).exception("Failed to enqueue pending trade %s", trade_id)

    async def _send_execution_email(self, trade_dict: Dict, payload: TradeCreate) -> None:
        """Send email notification for trade execution."""
        try:
            # Get user email from auth service (customer_id is user_id in this system)
            # Skip email for now - would need to call auth service to get user email
            # This is a non-critical feature, so we'll skip it silently
                import logging
                logging.getLogger(__name__).debug(
                f"Trade execution email skipped (customer_id: {payload.customer_id})"
                )
                return
            
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to send trade execution email: {e}"
            )
