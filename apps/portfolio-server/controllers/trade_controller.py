from __future__ import annotations

from typing import Dict, List

from fastapi import HTTPException, Request, status
from prisma import Prisma

from schemas import (
    PortfolioSnapshot,
    TradeCreate,
    TradeRequest,
    TradeResponse,
    TradeSummary,
)
from services.trade_engine import TradeEngine


class TradeController:
    """Coordinates trade submission flow and integrates with the trade engine."""

    def __init__(self, prisma: Prisma) -> None:
        self.prisma = prisma
        self.engine = TradeEngine(prisma)

    async def submit_trade(self, payload: TradeRequest, request: Request, user: Dict) -> TradeResponse:
        organization_id = user.get("organization_id")
        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated user is not linked to an organization",
            )

        portfolio = await self.prisma.portfolio.find_unique(where={"id": payload.portfolio_id})
        if not portfolio:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

        if portfolio.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Portfolio access denied")

        resolved_customer = self._resolve_customer(payload, portfolio, user)
        role = (user.get("role") or "").lower()
        if role not in {"admin", "staff"} and resolved_customer not in {user.get("id"), user.get("customer_id")}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not permitted to trade on behalf of this customer",
            )

        trade_input = self._build_trade_create(payload, request, user, organization_id, resolved_customer)

        try:
            result = await self.engine.handle_trade(trade_input)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        summaries = self._summaries_from_result(result.trades)
        portfolio_snapshot = PortfolioSnapshot(**result.portfolio)

        message = (
            "Trade executed" if any(summary.status == "executed" for summary in summaries) else "Order accepted"
        )

        return TradeResponse(
            success=True,
            message=message,
            trades=summaries,
            pending_orders=result.pending_orders,
            portfolio=portfolio_snapshot,
        )

    @staticmethod
    def _resolve_customer(payload: TradeRequest, portfolio, user: Dict) -> str:
        resolved = (
            payload.customer_id
            or getattr(portfolio, "customer_id", None)
            or user.get("customer_id")
            or user.get("id")
        )
        if not resolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to resolve customer for trade",
            )
        return resolved

    @staticmethod
    def _build_trade_create(
        payload: TradeRequest,
        request: Request,
        user: Dict,
        organization_id: str,
        customer_id: str,
    ) -> TradeCreate:
        metadata: Dict = {
            **(payload.metadata or {}),
            "requested_by": user.get("id"),
            "requested_role": user.get("role"),
            "ip": request.client.host if request.client else None,
        }

        return TradeCreate(
            organization_id=organization_id,
            portfolio_id=payload.portfolio_id,
            customer_id=customer_id,
            trade_type=payload.trade_type,
            symbol=payload.symbol,
            exchange=payload.exchange,
            segment=payload.segment,
            side=payload.side,
            order_type=payload.order_type,
            quantity=payload.quantity,
            limit_price=payload.limit_price,
            trigger_price=payload.trigger_price,
            source=payload.source or "user",
            metadata=metadata,
            auto_sell_after=payload.auto_sell_after,
        )

    @staticmethod
    def _summaries_from_result(trades: List[Dict]) -> List[TradeSummary]:
        return [
            TradeSummary(
                id=trade_dict["id"],
                symbol=trade_dict["symbol"],
                side=trade_dict["side"],
                order_type=trade_dict["order_type"],
                status=trade_dict["status"],
                quantity=trade_dict["quantity"],
                price=trade_dict.get("price"),
                execution_time=trade_dict.get("execution_time"),
            )
            for trade_dict in trades
        ]
