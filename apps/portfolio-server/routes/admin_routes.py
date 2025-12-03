"""Admin dashboard routes for organization-wide metrics and analytics."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from prisma import Prisma

from controllers.admin_controller import AdminController
from db import prisma_client
from utils.auth import get_authenticated_user


router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])


def get_admin_controller(prisma: Prisma = Depends(prisma_client)) -> AdminController:
    return AdminController(prisma)


def _require_admin(user: dict) -> str:
    """Validate user is admin and return organization_id."""
    role = (user.get("role") or "").lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization ID not found in user context",
        )
    
    return org_id


@router.get("/dashboard")
async def get_admin_dashboard(
    controller: AdminController = Depends(get_admin_controller),
    user: dict = Depends(get_authenticated_user),
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
    org_id = _require_admin(user)
    return await controller.get_dashboard(org_id)


@router.get("/summary")
async def get_admin_summary(
    controller: AdminController = Depends(get_admin_controller),
    user: dict = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """
    Get lightweight dashboard summary for frequent polling.
    
    Use this for:
    - Header stats that need frequent updates
    - Alert badges (portfolios in loss, agents with errors)
    - Quick health check of organization
    
    Poll every 5-10 seconds for near real-time stats.
    """
    org_id = _require_admin(user)
    return await controller.get_summary(org_id)


# =============================================================================
# JSON Response Structure Documentation
# =============================================================================
"""
ADMIN DASHBOARD RESPONSE STRUCTURE:
===================================

{
    "generated_at": "2025-12-03T10:30:00Z",
    "organization_id": "org-uuid",
    "data_freshness": "real-time",
    
    // ORGANIZATION OVERVIEW
    "organization_summary": {
        "organization_id": "org-uuid",
        "total_portfolios": 50,
        "active_portfolios": 45,
        "total_users": 100,
        "active_users": 80,
        "total_aum": 5000000.00,           // Total Assets Under Management
        "total_available_cash": 1000000.00,
        "total_invested": 4000000.00
    },
    
    // FINANCIAL METRICS
    "financial_metrics": {
        "total_realized_pnl": 150000.00,
        "total_unrealized_pnl": 0,          // FRONTEND: Calculate live with market prices
        "total_pnl": 150000.00,
        "overall_roi_percentage": 3.75,
        "best_performing_portfolio_id": "portfolio-uuid",
        "best_performing_portfolio_pnl": 25000.00,
        "worst_performing_portfolio_id": "portfolio-uuid",
        "worst_performing_portfolio_pnl": -5000.00
    },
    
    // MONTHLY P&L TIME SERIES - Line Chart
    "monthly_pnl_series": [
        {"month": "2025-01", "realized_pnl": 10000.00, "cumulative_pnl": 10000.00, "trade_count": 150},
        {"month": "2025-02", "realized_pnl": 15000.00, "cumulative_pnl": 25000.00, "trade_count": 200},
        // ... last 12 months
    ],
    
    // DAILY P&L - Recent Trend Line Chart
    "daily_pnl_series": [
        {"date": "2025-11-03", "realized_pnl": 500.00, "trade_count": 25},
        {"date": "2025-11-04", "realized_pnl": -200.00, "trade_count": 18},
        // ... last 30 days
    ],
    
    // TRADING METRICS
    "trading_metrics": {
        "total_trades": 5000,
        "trades_today": 45,
        "trades_this_week": 250,
        "trades_this_month": 1000,
        "total_volume": 25000000.00,        // Sum of all trade amounts
        "successful_trades": 4500,
        "failed_trades": 100,
        "pending_trades": 400,
        "success_rate_percentage": 90.00,
        "avg_trade_size": 5000.00,
        "total_fees": 50000.00,
        "total_taxes": 25000.00
    },
    
    // TRADES BY STATUS - Pie Chart
    "trades_by_status": {
        "executed": 4500,
        "pending": 200,
        "pending_tp": 100,                  // Pending Take Profit
        "pending_sl": 100,                  // Pending Stop Loss
        "cancelled": 50,
        "failed": 50
    },
    
    // TRADES BY SIDE - Pie Chart
    "trades_by_side": {
        "buy": 2500,
        "sell": 2300,
        "short_sell": 100,
        "cover": 100
    },
    
    // HOURLY DISTRIBUTION - Heatmap
    "hourly_trade_distribution": [
        {"hour": 0, "trade_count": 5, "volume": 25000.00},
        {"hour": 9, "trade_count": 150, "volume": 750000.00},   // Market open
        {"hour": 10, "trade_count": 200, "volume": 1000000.00},
        // ... 24 hours
    ],
    
    // TRADE VOLUME TIME SERIES - Bar Chart
    "trade_volume_series": [
        {"date": "2025-11-03", "trade_count": 45, "buy_count": 25, "sell_count": 20, "total_volume": 225000.00},
        // ... last 30 days
    ],
    
    // AGENT METRICS BY TYPE - Bar Chart Comparison
    "agent_metrics_by_type": [
        {
            "agent_type": "nse_signal",
            "agent_count": 20,
            "active_agents": 18,
            "error_agents": 2,
            "total_realized_pnl": 75000.00,
            "total_trades": 1500,
            "successful_trades": 1400,
            "win_rate_percentage": 93.33,
            "avg_pnl_per_trade": 50.00,
            "total_positions": 100,
            "open_positions": 45
        },
        {
            "agent_type": "low_risk",
            "agent_count": 15,
            "active_agents": 15,
            "error_agents": 0,
            "total_realized_pnl": 50000.00,
            // ...
        },
        // alpha, liquid, high_risk
    ],
    
    // TOP AGENTS - Leaderboard
    "top_agents": [
        {
            "agent_id": "agent-uuid",
            "agent_name": "NSE Signal Agent #1",
            "agent_type": "nse_signal",
            "portfolio_id": "portfolio-uuid",
            "realized_pnl": 15000.00,
            "trade_count": 150,
            "win_rate": 85.00,
            "status": "active"
        },
        // ... top 10
    ],
    
    // BOTTOM AGENTS - Needs Attention
    "bottom_agents": [
        // ... bottom 10 by P&L
    ],
    
    // AGENT P&L TIME SERIES - Multi-line Chart by Agent Type
    "agent_pnl_series": [
        {"snapshot_at": "2025-11-01T00:00:00Z", "agent_type": "nse_signal", "realized_pnl": 50000.00, "current_value": 200000.00},
        // ... historical snapshots
    ],
    
    // USER/PORTFOLIO METRICS - Table with sorting
    "user_portfolio_metrics": [
        {
            "user_id": "user-uuid",
            "portfolio_id": "portfolio-uuid",
            "portfolio_name": "John's Portfolio",
            "investment_amount": 100000.00,
            "current_value": 100000.00,     // FRONTEND: Update with live position values
            "available_cash": 20000.00,
            "realized_pnl": 5000.00,
            "roi_percentage": 5.00,
            "total_trades": 50,
            "open_positions": 5,
            "status": "profit",             // "profit" | "loss" | "breakeven"
            "last_trade_at": "2025-12-03T09:30:00Z",
            "created_at": "2025-01-15T10:00:00Z"
        },
        // ... all users
    ],
    
    // USER P&L DISTRIBUTION - Histogram
    "user_pnl_distribution": [
        {"range_label": "< -50k", "range_min": -100000, "range_max": -50000, "user_count": 2, "total_pnl": -120000.00},
        {"range_label": "-50k to -20k", "range_min": -50000, "range_max": -20000, "user_count": 5, "total_pnl": -150000.00},
        {"range_label": "-20k to -10k", "range_min": -20000, "range_max": -10000, "user_count": 8, "total_pnl": -120000.00},
        {"range_label": "-10k to -5k", "range_min": -10000, "range_max": -5000, "user_count": 10, "total_pnl": -75000.00},
        {"range_label": "-5k to 0", "range_min": -5000, "range_max": 0, "user_count": 15, "total_pnl": -37500.00},
        {"range_label": "0 to 5k", "range_min": 0, "range_max": 5000, "user_count": 20, "total_pnl": 50000.00},
        {"range_label": "5k to 10k", "range_min": 5000, "range_max": 10000, "user_count": 18, "total_pnl": 135000.00},
        {"range_label": "10k to 20k", "range_min": 10000, "range_max": 20000, "user_count": 12, "total_pnl": 180000.00},
        {"range_label": "20k to 50k", "range_min": 20000, "range_max": 50000, "user_count": 7, "total_pnl": 245000.00},
        {"range_label": "> 50k", "range_min": 50000, "range_max": 100000, "user_count": 3, "total_pnl": 200000.00}
    ],
    
    // TOP & BOTTOM USERS - Quick Reference
    "top_bottom_users": {
        "top_users": [/* top 10 from user_portfolio_metrics by realized_pnl */],
        "bottom_users": [/* bottom 10 */]
    },
    
    // POSITION METRICS
    "position_metrics": {
        "total_positions": 500,
        "open_positions": 350,
        "closed_positions": 150,
        "long_positions": 300,
        "short_positions": 50,
        "total_invested_in_positions": 3500000.00
    },
    
    // SYMBOL CONCENTRATION - Treemap / Pie Chart for Risk
    "symbol_concentration": [
        {"symbol": "RELIANCE", "total_quantity": 1000, "total_value": 250000.00, "position_count": 25, "percentage_of_total": 7.14},
        {"symbol": "TCS", "total_quantity": 500, "total_value": 200000.00, "position_count": 20, "percentage_of_total": 5.71},
        {"symbol": "INFY", "total_quantity": 800, "total_value": 180000.00, "position_count": 18, "percentage_of_total": 5.14},
        // ... top 20 symbols
    ],
    
    // PENDING ORDERS
    "pending_orders": {
        "pending_limit_orders": 50,
        "pending_stop_loss": 100,
        "pending_take_profit": 100,
        "pending_auto_sell": 50,
        "total_pending_value": 500000.00
    },
    
    // PIPELINE METRICS - Signal Processing Performance
    "pipeline_metrics": {
        "signals_today": 25,
        "signals_this_week": 150,
        "avg_llm_delay_ms": 2500.50,        // LLM processing time
        "avg_trade_delay_ms": 150.25,       // Order execution time
        "min_llm_delay_ms": 1500.00,
        "max_llm_delay_ms": 5000.00,
        "min_trade_delay_ms": 50.00,
        "max_trade_delay_ms": 500.00
    },
    
    // EXECUTION METRICS
    "execution_metrics": {
        "total_executions": 5000,
        "successful_executions": 4800,
        "failed_executions": 100,
        "pending_executions": 100,
        "avg_execution_time_ms": 125.50
    },
    
    // PORTFOLIO VALUE TIME SERIES - Area Chart
    "portfolio_value_series": [
        {"snapshot_at": "2025-09-05", "total_value": 4500000.00, "realized_pnl": 100000.00, "unrealized_pnl": 50000.00},
        {"snapshot_at": "2025-09-06", "total_value": 4550000.00, "realized_pnl": 105000.00, "unrealized_pnl": 45000.00},
        // ... last 90 days
    ],
    
    // ALPHA COPILOT METRICS (if using alpha features)
    "alpha_metrics": {
        "total_runs": 25,
        "completed_runs": 20,
        "running_runs": 3,
        "failed_runs": 2,
        "live_alphas_count": 15,
        "running_alphas": 12,
        "total_alpha_signals": 500,
        "executed_signals": 450,
        "pending_signals": 50
    }
}

FRONTEND CALCULATION NOTES:
===========================

1. UNREALIZED P&L (calculate live):
   - For each position in user_portfolio_metrics:
     unrealized_pnl = (current_market_price - average_buy_price) * quantity
   - Sum all for total_unrealized_pnl in financial_metrics

2. CURRENT VALUE (calculate live):
   - current_value = available_cash + sum(position_quantity * current_market_price)

3. LIVE POSITION VALUE:
   - Update symbol_concentration values with live prices
   - Recalculate percentage_of_total

4. REAL-TIME ALERTS:
   - high_concentration_symbols from /admin/summary (symbols > 20%)
   - agents_with_errors count
   - portfolios_in_loss count

5. POLLING STRATEGY:
   - /admin/dashboard: Every 30-60 seconds (heavy query)
   - /admin/summary: Every 5-10 seconds (lightweight)
   - Market prices: WebSocket or every 1-2 seconds

6. CHARTS RECOMMENDATIONS:
   - Use recharts or chart.js
   - monthly_pnl_series: Area chart with cumulative line
   - daily_pnl_series: Bar chart (green positive, red negative)
   - trades_by_status: Donut chart
   - hourly_trade_distribution: Heatmap (hours x days)
   - user_pnl_distribution: Histogram with colored bars
   - symbol_concentration: Treemap for visual risk
   - agent_metrics_by_type: Grouped bar chart
"""
