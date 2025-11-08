"""Portfolio routes for retrieving or creating user portfolios."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from prisma import Prisma

from controllers.portfolio_controller import PortfolioController
from db import prisma_client
from schemas import HoldingResponse, PortfolioResponse, PositionListResponse, TradeListResponse
from utils.auth import get_authenticated_user


router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


def get_portfolio_controller(prisma: Prisma = Depends(prisma_client)) -> PortfolioController:
    return PortfolioController(prisma)


@router.get("/", response_model=PortfolioResponse)
async def get_or_create_portfolio_for_user(
    controller: PortfolioController = Depends(get_portfolio_controller),
    user: dict = Depends(get_authenticated_user),
) -> PortfolioResponse:
    return await controller.get_or_create_portfolio(user)


@router.get("/holding/{symbol}", response_model=HoldingResponse)
async def get_user_holding(
    symbol: str,
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
) -> HoldingResponse:
    return await controller.get_holding(request_user, symbol)


@router.get("/positions", response_model=PositionListResponse)
async def list_user_positions(
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search term for symbol"),
    profitability: Optional[str] = Query(
        None, description="Filter by profitability: profitable, loss-making, breakeven"
    ),
    sortBy: str = Query("updatedAt", regex="^[A-Za-z]+$"),
    sortOrder: Literal["asc", "desc"] = Query("desc"),
) -> PositionListResponse:
    return await controller.list_positions(
        request_user,
        page=page,
        limit=limit,
        search=search,
        profitability=profitability,
        sort_by=sortBy,
        sort_order=sortOrder,
    )


@router.get("/recent-trades", response_model=TradeListResponse)
async def get_recent_trades(
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    symbol: Optional[str] = Query(None),
    side: Optional[str] = Query(None, description="buy or sell"),
    order_type: Optional[str] = Query(None, alias="orderType"),
    status_filter: Optional[str] = Query(None, alias="status"),
) -> TradeListResponse:
    return await controller.list_recent_trades(
        request_user,
        page=page,
        limit=limit,
        symbol=symbol,
        side=side,
        order_type=order_type,
        status_filter=status_filter,
    )
