"""Admin dashboard routes for organization-wide metrics and analytics."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from prisma import Prisma

from controllers.admin_controller import AdminController
from db import prisma_client
from auth_middleware import require_admin_or_staff  # type: ignore


router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])


def get_admin_controller(prisma: Prisma = Depends(prisma_client)) -> AdminController:
    return AdminController(prisma)


@router.get("/dashboard")
async def get_admin_dashboard(
    controller: AdminController = Depends(get_admin_controller),
    user: dict = Depends(require_admin_or_staff),
) -> Dict[str, Any]:
    """
    Get comprehensive admin dashboard data for the organization.
    
    Returns all metrics, charts data, and analytics for:
    - Organization overview (AUM, users, portfolios)
    - Financial performance (P&L, ROI, time series)
    - Trading activity (volumes, success rates, distributions)
    - Agent performance (by type, rankings)
    - User analysis (top/bottom performers, P&L distribution)
    - Position & risk metrics (concentration, pending orders)
    - Pipeline metrics (signal delays, execution times)
    - Alpha copilot metrics (if applicable)
    
    **Frontend Notes:**
    - Poll this endpoint every 30-60 seconds for updates
    - Use /admin/summary for more frequent lightweight polling (5-10s)
    - Calculate unrealized P&L live using current market prices
    - current_value in user_portfolio_metrics needs live price calculation
    
    **Charts to render:**
    - Line chart: monthly_pnl_series (cumulative P&L over time)
    - Line chart: daily_pnl_series (recent 30-day trend)
    - Bar chart: trade_volume_series (daily trading activity)
    - Pie chart: trades_by_status (execution success breakdown)
    - Pie chart: trades_by_side (buy/sell distribution)
    - Heatmap: hourly_trade_distribution (trading hours activity)
    - Bar chart: agent_metrics_by_type (agent comparison)
    - Area chart: portfolio_value_series (org value over time)
    - Histogram: user_pnl_distribution (user performance spread)
    - Treemap: symbol_concentration (position risk analysis)
    """
    org_id = user["organization_id"]
    return await controller.get_dashboard(org_id)


@router.get("/summary")
async def get_admin_summary(
    controller: AdminController = Depends(get_admin_controller),
    user: dict = Depends(require_admin_or_staff),
) -> Dict[str, Any]:
    """
    Get lightweight dashboard summary for frequent polling.
    
    Use this for:
    - Header stats that need frequent updates
    - Alert badges (portfolios in loss, agents with errors)
    - Quick health check of organization
    
    Poll every 5-10 seconds for near real-time stats.
    """
    org_id = user["organization_id"]
    return await controller.get_summary(org_id)