from __future__ import annotations

import os
import sys
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from prisma import Prisma

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
MIDDLEWARE_PATH = os.path.join(PROJECT_ROOT, "middleware/py")
if MIDDLEWARE_PATH not in sys.path:
    sys.path.insert(0, MIDDLEWARE_PATH)

from auth_middleware import protect_route  # type: ignore

from db import prisma_client
from schemas import (
    PortfolioSnapshot,
    TradeCreate,
    TradeRequest,
    TradeResponse,
    TradeSummary,
)
from services.trade_engine import TradeEngine

router = APIRouter(prefix="/trades", tags=["Trades"])


def _normalize_user(user: dict) -> dict:
    return {
        "id": user.get("id") or user.get("_id"),
        "organization_id": user.get("organization_id") or user.get("organizationId"),
        "customer_id": user.get("customer_id") or user.get("customerId"),
        "role": user.get("role"),
        "email": user.get("email"),
        "raw": user,
    }


async def get_authenticated_user(request: Request) -> dict:
    """Resolve the authenticated user via auth middleware."""
    raw_user = getattr(request.state, "user", None)
    if raw_user:
        normalized = _normalize_user(raw_user)
        request.state.user = normalized
        return normalized
    raw_user = await protect_route(request)
    normalized = _normalize_user(raw_user)
    request.state.user = normalized
    return normalized


@router.post("/", response_model=TradeResponse)
async def create_trade(
    payload: TradeRequest,
    request: Request,
    user: dict = Depends(get_authenticated_user),
    prisma: Prisma = Depends(prisma_client),
) -> TradeResponse:
    engine = TradeEngine(prisma)

    organization_id = user.get("organization_id")
    if not organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user is not linked to an organization",
        )

    portfolio = await prisma.portfolio.find_unique(where={"id": payload.portfolio_id})
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    if portfolio.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Portfolio access denied")

    resolved_customer = (
        payload.customer_id
        or portfolio.customer_id
        or user.get("customer_id")
        or user.get("id")
    )
    if not resolved_customer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to resolve customer for trade",
        )

    role = (user.get("role") or "").lower()
    if role not in {"admin", "staff"} and resolved_customer not in {user.get("id"), user.get("customer_id")}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not permitted to trade on behalf of this customer",
        )

    trade_input = TradeCreate(
        organization_id=organization_id,
        portfolio_id=payload.portfolio_id,
        customer_id=resolved_customer,
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
        metadata={
            **(payload.metadata or {}),
            "requested_by": user.get("id"),
            "requested_role": user.get("role"),
            "ip": request.client.host if request.client else None,
        },
    )

    try:
        result = await engine.handle_trade(trade_input)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    summaries: List[TradeSummary] = [
        TradeSummary(
            id=trade_dict["id"],
            symbol=trade_dict["symbol"],
            side=trade_dict["side"],
            order_type=trade_dict["order_type"],
            status=trade_dict["status"],
            quantity=trade_dict["quantity"],
            price=trade_dict.get("price"),
            executed_quantity=trade_dict.get("executed_quantity"),
            executed_price=trade_dict.get("executed_price"),
            execution_time=trade_dict.get("execution_time"),
        )
        for trade_dict in result.trades
    ]

    portfolio_snapshot = PortfolioSnapshot(**result.portfolio)

    message = (
        "Trade executed" if any(summary.status == "executed" for summary in summaries)
        else "Order accepted"
    )

    return TradeResponse(
        success=True,
        message=message,
        trades=summaries,
        pending_orders=result.pending_orders,
        portfolio=portfolio_snapshot,
    )
