"""Portfolio routes for retrieving or creating user portfolios."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from prisma import Prisma

from controllers.portfolio_controller import PortfolioController
from db import prisma_client
from schemas import (
    HoldingResponse,
    PortfolioResponse,
    PositionListResponse,
    TradeListResponse,
    TradingAgentListResponse,
    PortfolioAllocationListResponse,
    PortfolioDashboardResponse,
    AgentDashboardResponse,
    SnapshotListResponse,
    AllocationSnapshotListResponse,
)
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
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    sortBy: str = Query("updatedAt", regex="^[A-Za-z]+$"),
    sortOrder: Literal["asc", "desc"] = Query("desc"),
) -> PositionListResponse:
    return await controller.list_positions(
        request_user,
        page=page,
        limit=limit,
        search=search,
        profitability=profitability,
        agent_id=agent_id,
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
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
) -> TradeListResponse:
    return await controller.list_recent_trades(
        request_user,
        page=page,
        limit=limit,
        symbol=symbol,
        side=side,
        order_type=order_type,
        status_filter=status_filter,
        agent_id=agent_id,
    )


@router.get("/trading-agents", response_model=TradingAgentListResponse)
async def get_trading_agents(
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
) -> TradingAgentListResponse:
    """Get all trading agents for the authenticated user's portfolio"""
    return await controller.get_trading_agents(request_user)


@router.get("/allocations", response_model=PortfolioAllocationListResponse)
async def get_portfolio_allocations(
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
) -> PortfolioAllocationListResponse:
    """Get all portfolio allocations for the authenticated user's portfolio"""
    return await controller.get_portfolio_allocations(request_user)


@router.get("/dashboard", response_model=PortfolioDashboardResponse)
async def get_portfolio_dashboard(
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
) -> PortfolioDashboardResponse:
    """Get main portfolio dashboard with aggregated stats, P&L, and allocation summary"""
    return await controller.get_dashboard(request_user)


@router.get("/agents/{agent_type}/dashboard", response_model=AgentDashboardResponse)
async def get_agent_dashboard(
    agent_type: str,
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
) -> AgentDashboardResponse:
    """Get agent-specific dashboard with positions, P&L, and performance metrics"""
    return await controller.get_agent_dashboard(agent_type, request_user)


@router.get("/snapshots", response_model=SnapshotListResponse)
async def get_portfolio_snapshots(
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
    agent_type: Optional[str] = Query(None, description="Filter by specific agent type (alpha, liquid, low_risk, high_risk)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of snapshots to return"),
) -> SnapshotListResponse:
    """
    Get portfolio snapshot history for timeline charts.
    
    If agent_type is provided, returns snapshots for that specific agent.
    Otherwise, returns aggregated snapshots (sum of all agents in portfolio).
    """
    return await controller.get_snapshots(request_user, agent_type=agent_type, limit=limit)


@router.get("/agents/{agent_type}/snapshots", response_model=SnapshotListResponse)
async def get_trading_agent_snapshots(
    agent_type: str,
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of snapshots to return"),
) -> SnapshotListResponse:
    """
    Get trading agent snapshot history for a specific agent type.
    
    Returns portfolio value and realized P&L snapshots over time for the agent.
    """
    return await controller.get_snapshots(request_user, agent_type=agent_type, limit=limit)


@router.get("/allocations/{allocation_id}/snapshots", response_model=AllocationSnapshotListResponse)
async def get_allocation_snapshots(
    allocation_id: str,
    controller: PortfolioController = Depends(get_portfolio_controller),
    request_user: dict = Depends(get_authenticated_user),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of snapshots to return"),
) -> AllocationSnapshotListResponse:
    """
    Get allocation snapshot history for a specific portfolio allocation.
    
    Returns allocation weight and value snapshots over time, typically captured during rebalancing.
    """
    return await controller.get_allocation_snapshots(request_user, allocation_id=allocation_id, limit=limit)
