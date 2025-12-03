"""Admin dashboard controller - fetches organization-wide metrics directly from DB."""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException, status
from prisma import Prisma

logger = logging.getLogger(__name__)

# Auth service URL for fetching user data
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:3001")
INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "agentinvest-secret")


def _decimal_to_float(val: Any) -> float:
    """Convert Decimal to float for JSON serialization."""
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def _ensure_tz_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware (UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_metadata(payload: Any) -> dict:
    """Parse metadata field which can be dict or JSON string."""
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return {}


class AdminController:
    """Controller for admin dashboard - aggregates organization-wide metrics."""

    def __init__(self, prisma: Prisma, *, logger_instance: Optional[logging.Logger] = None) -> None:
        self.prisma = prisma
        self.logger = logger_instance or logging.getLogger(__name__)

    async def _fetch_auth_users(self, organization_id: str) -> List[Dict[str, Any]]:
        """Fetch users from auth service via internal API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{AUTH_SERVICE_URL}/api/users",
                    params={"organization_id": organization_id, "limit": 1000},
                    headers={
                        "X-Internal-Service": "true",
                        "X-Service-Secret": INTERNAL_SERVICE_SECRET,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("data", {}).get("users", [])
        except Exception as e:
            self.logger.warning(f"Failed to fetch users from auth service: {e}")
        return []

    async def get_dashboard(self, organization_id: str) -> Dict[str, Any]:
        """
        Get complete admin dashboard data for an organization.
        
        Returns a comprehensive dict with all metrics - no schema validation overhead.
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        thirty_days_ago = today_start - timedelta(days=30)
        
        # Fetch all portfolios for this organization
        portfolios = await self.prisma.portfolio.find_many(
            where={"organization_id": organization_id},
            include={
                "positions": True,
                "allocations": True,
                "trades": {"take": 1, "order_by": {"created_at": "desc"}},
            },
        )
        
        if not portfolios:
            return self._empty_dashboard(organization_id, now)
        
        portfolio_ids = [p.id for p in portfolios]
        
        # Fetch all data in parallel-ish manner
        all_trades = await self.prisma.trade.find_many(
            where={"portfolio_id": {"in": portfolio_ids}},
            order={"created_at": "desc"},
        )
        
        all_positions = await self.prisma.position.find_many(
            where={"portfolio_id": {"in": portfolio_ids}},
        )
        
        all_agents = await self.prisma.tradingagent.find_many(
            where={"portfolio_id": {"in": portfolio_ids}},
            include={"trades": True, "positions": True},
        )
        
        all_execution_logs = await self.prisma.tradeexecutionlog.find_many(
            where={"trade": {"portfolio_id": {"in": portfolio_ids}}},
            order={"created_at": "desc"},
            take=1000,
        )
        
        # Portfolio snapshots for time series
        portfolio_snapshots = await self.prisma.portfoliosnapshot.find_many(
            where={"portfolio_id": {"in": portfolio_ids}},
            order={"snapshot_at": "desc"},
            take=500,
        )
        
        # Agent snapshots for time series
        agent_snapshots = await self.prisma.tradingagentsnapshot.find_many(
            where={"portfolio_id": {"in": portfolio_ids}},
            order={"snapshot_at": "desc"},
            take=500,
        )
        
        # Alpha metrics (if applicable)
        alpha_runs = await self.prisma.alphacopilotrun.find_many(take=100)
        live_alphas = await self.prisma.livealpha.find_many(
            where={"portfolio_id": {"in": portfolio_ids}},
        )
        # Get live_alpha_ids to filter alpha_signals
        live_alpha_ids = [alpha.id for alpha in live_alphas] if live_alphas else []
        alpha_signals = []
        if live_alpha_ids:
            try:
                # Try to access alphasignal model - may not exist if Prisma client not regenerated
                alphasignal_model = getattr(self.prisma, 'alphasignal', None)
                if alphasignal_model is not None:
                    alpha_signals = await alphasignal_model.find_many(
                        where={"live_alpha_id": {"in": live_alpha_ids}},
                        take=1000,
                    )
                else:
                    logger.warning("AlphaSignal model not available in Prisma client. Please regenerate Prisma client.")
            except Exception as e:
                logger.warning(f"Error querying AlphaSignal model: {e}, skipping alpha signals")
                alpha_signals = []
        
        # Fetch users from auth service
        auth_users = await self._fetch_auth_users(organization_id)
        
        # Build dashboard
        return {
            "generated_at": now.isoformat(),
            "organization_id": organization_id,
            "data_freshness": "real-time",
            
            # Organization Summary
            "organization_summary": self._build_organization_summary(
                organization_id, portfolios, auth_users, all_positions
            ),
            
            # Financial Metrics
            "financial_metrics": self._build_financial_metrics(portfolios),
            "monthly_pnl_series": self._build_monthly_pnl_series(all_trades),
            "daily_pnl_series": self._build_daily_pnl_series(all_trades, thirty_days_ago),
            
            # Trading Metrics
            "trading_metrics": self._build_trading_metrics(
                all_trades, today_start, week_start, month_start
            ),
            "trades_by_status": self._build_trades_by_status(all_trades),
            "trades_by_side": self._build_trades_by_side(all_trades),
            "hourly_trade_distribution": self._build_hourly_distribution(all_trades),
            "trade_volume_series": self._build_trade_volume_series(all_trades, thirty_days_ago),
            
            # Agent Metrics
            "agent_metrics_by_type": self._build_agent_metrics_by_type(all_agents, all_trades),
            "top_agents": self._build_agent_ranking(all_agents, top=True, limit=10),
            "bottom_agents": self._build_agent_ranking(all_agents, top=False, limit=10),
            "agent_pnl_series": self._build_agent_pnl_series(agent_snapshots),
            
            # User/Portfolio Metrics
            "user_portfolio_metrics": self._build_user_portfolio_metrics(
                portfolios, all_trades, all_positions
            ),
            "user_pnl_distribution": self._build_user_pnl_distribution(portfolios),
            "top_bottom_users": self._build_top_bottom_users(portfolios, all_trades, all_positions),
            
            # Position & Risk Metrics
            "position_metrics": self._build_position_metrics(all_positions),
            "symbol_concentration": self._build_symbol_concentration(all_positions),
            "pending_orders": self._build_pending_orders_metrics(all_trades),
            
            # Pipeline Metrics
            "pipeline_metrics": self._build_pipeline_metrics(all_trades, today_start, week_start),
            "execution_metrics": self._build_execution_metrics(all_execution_logs),
            
            # Time Series
            "portfolio_value_series": self._build_portfolio_value_series(portfolio_snapshots),
            
            # Alpha Metrics
            "alpha_metrics": self._build_alpha_metrics(alpha_runs, live_alphas, alpha_signals),
        }

    def _empty_dashboard(self, organization_id: str, now: datetime) -> Dict[str, Any]:
        """Return empty dashboard structure when no data exists."""
        return {
            "generated_at": now.isoformat(),
            "organization_id": organization_id,
            "data_freshness": "real-time",
            "organization_summary": {
                "organization_id": organization_id,
                "total_portfolios": 0,
                "active_portfolios": 0,
                "total_users": 0,
                "active_users": 0,
                "total_aum": 0,
                "total_available_cash": 0,
                "total_invested": 0,
            },
            "financial_metrics": {
                "total_realized_pnl": 0,
                "total_unrealized_pnl": 0,
                "total_pnl": 0,
                "overall_roi_percentage": 0,
            },
            "monthly_pnl_series": [],
            "daily_pnl_series": [],
            "trading_metrics": {
                "total_trades": 0,
                "trades_today": 0,
                "trades_this_week": 0,
                "trades_this_month": 0,
                "total_volume": 0,
                "successful_trades": 0,
                "failed_trades": 0,
                "pending_trades": 0,
                "success_rate_percentage": 0,
                "avg_trade_size": 0,
                "total_fees": 0,
                "total_taxes": 0,
            },
            "trades_by_status": {"executed": 0, "pending": 0, "pending_tp": 0, "pending_sl": 0, "cancelled": 0, "failed": 0},
            "trades_by_side": {"buy": 0, "sell": 0, "short_sell": 0, "cover": 0},
            "hourly_trade_distribution": [],
            "trade_volume_series": [],
            "agent_metrics_by_type": [],
            "top_agents": [],
            "bottom_agents": [],
            "agent_pnl_series": [],
            "user_portfolio_metrics": [],
            "user_pnl_distribution": [],
            "top_bottom_users": {"top_users": [], "bottom_users": []},
            "position_metrics": {
                "total_positions": 0,
                "open_positions": 0,
                "closed_positions": 0,
                "long_positions": 0,
                "short_positions": 0,
                "total_invested_in_positions": 0,
            },
            "symbol_concentration": [],
            "pending_orders": {
                "pending_limit_orders": 0,
                "pending_stop_loss": 0,
                "pending_take_profit": 0,
                "pending_auto_sell": 0,
                "total_pending_value": 0,
            },
            "pipeline_metrics": {"signals_today": 0, "signals_this_week": 0},
            "execution_metrics": {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "pending_executions": 0,
            },
            "portfolio_value_series": [],
            "alpha_metrics": None,
        }

    def _build_organization_summary(
        self, organization_id: str, portfolios: List, auth_users: List, positions: List
    ) -> Dict[str, Any]:
        """Build organization summary stats."""
        active_portfolios = [p for p in portfolios if p.status == "active"]
        
        total_aum = sum(_decimal_to_float(p.investment_amount) for p in portfolios)
        total_cash = sum(_decimal_to_float(p.available_cash) for p in portfolios)
        total_invested = total_aum - total_cash
        
        # Count active users (those with portfolios or recent activity)
        user_ids_with_portfolios = set(p.user_id or p.customer_id for p in portfolios if p.user_id or p.customer_id)
        active_user_count = len(user_ids_with_portfolios)
        
        return {
            "organization_id": organization_id,
            "total_portfolios": len(portfolios),
            "active_portfolios": len(active_portfolios),
            "total_users": len(auth_users) if auth_users else active_user_count,
            "active_users": active_user_count,
            "total_aum": total_aum,
            "total_available_cash": total_cash,
            "total_invested": total_invested,
        }

    def _build_financial_metrics(self, portfolios: List) -> Dict[str, Any]:
        """Build financial performance metrics."""
        total_realized_pnl = sum(_decimal_to_float(p.total_realized_pnl or 0) for p in portfolios)
        total_investment = sum(_decimal_to_float(p.investment_amount) for p in portfolios)
        
        # Find best and worst performing
        sorted_by_pnl = sorted(portfolios, key=lambda p: _decimal_to_float(p.total_realized_pnl or 0), reverse=True)
        
        best = sorted_by_pnl[0] if sorted_by_pnl else None
        worst = sorted_by_pnl[-1] if sorted_by_pnl else None
        
        roi = (total_realized_pnl / total_investment * 100) if total_investment > 0 else 0
        
        return {
            "total_realized_pnl": total_realized_pnl,
            "total_unrealized_pnl": 0,  # Frontend calculates with live prices
            "total_pnl": total_realized_pnl,
            "overall_roi_percentage": round(roi, 2),
            "best_performing_portfolio_id": best.id if best else None,
            "best_performing_portfolio_pnl": _decimal_to_float(best.total_realized_pnl) if best else None,
            "worst_performing_portfolio_id": worst.id if worst else None,
            "worst_performing_portfolio_pnl": _decimal_to_float(worst.total_realized_pnl) if worst else None,
        }

    def _build_monthly_pnl_series(self, trades: List) -> List[Dict[str, Any]]:
        """Build monthly P&L time series for charts."""
        monthly_data = defaultdict(lambda: {"realized_pnl": 0, "trade_count": 0})
        
        for trade in trades:
            if trade.status == "executed" and trade.realized_pnl:
                month_key = trade.created_at.strftime("%Y-%m")
                monthly_data[month_key]["realized_pnl"] += _decimal_to_float(trade.realized_pnl)
                monthly_data[month_key]["trade_count"] += 1
        
        # Sort by month and calculate cumulative
        sorted_months = sorted(monthly_data.keys())
        cumulative = 0
        result = []
        
        for month in sorted_months:
            data = monthly_data[month]
            cumulative += data["realized_pnl"]
            result.append({
                "month": month,
                "realized_pnl": round(data["realized_pnl"], 2),
                "cumulative_pnl": round(cumulative, 2),
                "trade_count": data["trade_count"],
            })
        
        return result[-12:]  # Last 12 months

    def _build_daily_pnl_series(self, trades: List, since: datetime) -> List[Dict[str, Any]]:
        """Build daily P&L for last 30 days."""
        daily_data = defaultdict(lambda: {"realized_pnl": 0, "trade_count": 0})
        
        for trade in trades:
            trade_dt = _ensure_tz_aware(trade.created_at)
            if trade_dt and trade_dt >= since and trade.status == "executed":
                date_key = trade_dt.strftime("%Y-%m-%d")
                if trade.realized_pnl:
                    daily_data[date_key]["realized_pnl"] += _decimal_to_float(trade.realized_pnl)
                daily_data[date_key]["trade_count"] += 1
        
        sorted_dates = sorted(daily_data.keys())
        return [
            {
                "date": date,
                "realized_pnl": round(daily_data[date]["realized_pnl"], 2),
                "trade_count": daily_data[date]["trade_count"],
            }
            for date in sorted_dates
        ]

    def _build_trading_metrics(
        self, trades: List, today_start: datetime, week_start: datetime, month_start: datetime
    ) -> Dict[str, Any]:
        """Build trading activity metrics."""
        trades_today = [t for t in trades if _ensure_tz_aware(t.created_at) and _ensure_tz_aware(t.created_at) >= today_start]
        trades_week = [t for t in trades if _ensure_tz_aware(t.created_at) and _ensure_tz_aware(t.created_at) >= week_start]
        trades_month = [t for t in trades if _ensure_tz_aware(t.created_at) and _ensure_tz_aware(t.created_at) >= month_start]
        
        executed = [t for t in trades if t.status == "executed"]
        failed = [t for t in trades if t.status in ("failed", "rejected")]
        pending = [t for t in trades if t.status in ("pending", "pending_tp", "pending_sl")]
        
        total_volume = sum(_decimal_to_float(t.net_amount or 0) for t in executed)
        total_fees = sum(_decimal_to_float(t.fees or 0) for t in trades)
        total_taxes = sum(_decimal_to_float(t.taxes or 0) for t in trades)
        
        success_rate = (len(executed) / len(trades) * 100) if trades else 0
        avg_size = (total_volume / len(executed)) if executed else 0
        
        return {
            "total_trades": len(trades),
            "trades_today": len(trades_today),
            "trades_this_week": len(trades_week),
            "trades_this_month": len(trades_month),
            "total_volume": round(total_volume, 2),
            "successful_trades": len(executed),
            "failed_trades": len(failed),
            "pending_trades": len(pending),
            "success_rate_percentage": round(success_rate, 2),
            "avg_trade_size": round(avg_size, 2),
            "total_fees": round(total_fees, 2),
            "total_taxes": round(total_taxes, 2),
        }

    def _build_trades_by_status(self, trades: List) -> Dict[str, int]:
        """Count trades by status for pie chart."""
        status_counts = defaultdict(int)
        for trade in trades:
            status_counts[trade.status] += 1
        
        return {
            "executed": status_counts.get("executed", 0),
            "pending": status_counts.get("pending", 0),
            "pending_tp": status_counts.get("pending_tp", 0),
            "pending_sl": status_counts.get("pending_sl", 0),
            "cancelled": status_counts.get("cancelled", 0),
            "failed": status_counts.get("failed", 0) + status_counts.get("rejected", 0),
        }

    def _build_trades_by_side(self, trades: List) -> Dict[str, int]:
        """Count trades by side."""
        side_counts = defaultdict(int)
        for trade in trades:
            side_counts[trade.side.lower()] += 1
        
        return {
            "buy": side_counts.get("buy", 0),
            "sell": side_counts.get("sell", 0),
            "short_sell": side_counts.get("short_sell", 0),
            "cover": side_counts.get("cover", 0),
        }

    def _build_hourly_distribution(self, trades: List) -> List[Dict[str, Any]]:
        """Build hourly trade distribution for heatmap."""
        hourly = defaultdict(lambda: {"trade_count": 0, "volume": 0})
        
        for trade in trades:
            hour = trade.created_at.hour
            hourly[hour]["trade_count"] += 1
            hourly[hour]["volume"] += _decimal_to_float(trade.net_amount or 0)
        
        return [
            {"hour": h, "trade_count": hourly[h]["trade_count"], "volume": round(hourly[h]["volume"], 2)}
            for h in range(24)
        ]

    def _build_trade_volume_series(self, trades: List, since: datetime) -> List[Dict[str, Any]]:
        """Build daily trade volume series."""
        daily = defaultdict(lambda: {"trade_count": 0, "buy_count": 0, "sell_count": 0, "volume": 0})
        
        for trade in trades:
            trade_dt = _ensure_tz_aware(trade.created_at)
            if trade_dt and trade_dt >= since:
                date_key = trade_dt.strftime("%Y-%m-%d")
                daily[date_key]["trade_count"] += 1
                if trade.side.upper() == "BUY":
                    daily[date_key]["buy_count"] += 1
                elif trade.side.upper() == "SELL":
                    daily[date_key]["sell_count"] += 1
                daily[date_key]["volume"] += _decimal_to_float(trade.net_amount or 0)
        
        sorted_dates = sorted(daily.keys())
        return [
            {
                "date": date,
                "trade_count": daily[date]["trade_count"],
                "buy_count": daily[date]["buy_count"],
                "sell_count": daily[date]["sell_count"],
                "total_volume": round(daily[date]["volume"], 2),
            }
            for date in sorted_dates
        ]

    def _build_agent_metrics_by_type(self, agents: List, trades: List) -> List[Dict[str, Any]]:
        """Build metrics grouped by agent type."""
        agent_types = defaultdict(lambda: {
            "agent_count": 0,
            "active_agents": 0,
            "error_agents": 0,
            "total_realized_pnl": 0,
            "total_trades": 0,
            "successful_trades": 0,
            "total_positions": 0,
            "open_positions": 0,
        })
        
        for agent in agents:
            atype = agent.agent_type
            agent_types[atype]["agent_count"] += 1
            if agent.status == "active":
                agent_types[atype]["active_agents"] += 1
            if agent.error_count > 0:
                agent_types[atype]["error_agents"] += 1
            agent_types[atype]["total_realized_pnl"] += _decimal_to_float(agent.realized_pnl or 0)
            
            # Count trades and positions for this agent
            agent_trades = [t for t in trades if t.agent_id == agent.id]
            agent_types[atype]["total_trades"] += len(agent_trades)
            agent_types[atype]["successful_trades"] += len([t for t in agent_trades if t.status == "executed"])
            
            positions = getattr(agent, "positions", []) or []
            agent_types[atype]["total_positions"] += len(positions)
            agent_types[atype]["open_positions"] += len([p for p in positions if p.status == "open"])
        
        result = []
        for atype, data in agent_types.items():
            win_rate = (data["successful_trades"] / data["total_trades"] * 100) if data["total_trades"] > 0 else 0
            avg_pnl = (data["total_realized_pnl"] / data["total_trades"]) if data["total_trades"] > 0 else 0
            
            result.append({
                "agent_type": atype,
                "agent_count": data["agent_count"],
                "active_agents": data["active_agents"],
                "error_agents": data["error_agents"],
                "total_realized_pnl": round(data["total_realized_pnl"], 2),
                "total_trades": data["total_trades"],
                "successful_trades": data["successful_trades"],
                "win_rate_percentage": round(win_rate, 2),
                "avg_pnl_per_trade": round(avg_pnl, 2),
                "total_positions": data["total_positions"],
                "open_positions": data["open_positions"],
            })
        
        return result

    def _build_agent_ranking(self, agents: List, top: bool = True, limit: int = 10) -> List[Dict[str, Any]]:
        """Build agent ranking by P&L."""
        sorted_agents = sorted(
            agents,
            key=lambda a: _decimal_to_float(a.realized_pnl or 0),
            reverse=top,
        )[:limit]
        
        result = []
        for agent in sorted_agents:
            trades = getattr(agent, "trades", []) or []
            executed = [t for t in trades if t.status == "executed"]
            profitable = [t for t in executed if t.realized_pnl and _decimal_to_float(t.realized_pnl) > 0]
            win_rate = (len(profitable) / len(executed) * 100) if executed else 0
            
            result.append({
                "agent_id": agent.id,
                "agent_name": agent.agent_name,
                "agent_type": agent.agent_type,
                "portfolio_id": agent.portfolio_id,
                "realized_pnl": round(_decimal_to_float(agent.realized_pnl or 0), 2),
                "trade_count": len(trades),
                "win_rate": round(win_rate, 2),
                "status": agent.status,
            })
        
        return result

    def _build_agent_pnl_series(self, snapshots: List) -> List[Dict[str, Any]]:
        """Build agent P&L time series from snapshots."""
        result = []
        for snap in snapshots[:100]:  # Limit for performance
            result.append({
                "snapshot_at": snap.snapshot_at.isoformat(),
                "agent_type": snap.agent_type,
                "realized_pnl": round(_decimal_to_float(snap.realized_pnl), 2),
                "current_value": round(_decimal_to_float(snap.current_value), 2),
            })
        return result

    def _build_user_portfolio_metrics(
        self, portfolios: List, trades: List, positions: List
    ) -> List[Dict[str, Any]]:
        """Build per-user portfolio metrics."""
        result = []
        
        for portfolio in portfolios:
            user_id = portfolio.user_id or portfolio.customer_id
            portfolio_trades = [t for t in trades if t.portfolio_id == portfolio.id]
            portfolio_positions = [p for p in positions if p.portfolio_id == portfolio.id]
            open_positions = [p for p in portfolio_positions if p.status == "open"]
            
            realized_pnl = _decimal_to_float(portfolio.total_realized_pnl or 0)
            investment = _decimal_to_float(portfolio.investment_amount)
            roi = (realized_pnl / investment * 100) if investment > 0 else 0
            
            # Determine profit/loss status
            if realized_pnl > 0:
                status = "profit"
            elif realized_pnl < 0:
                status = "loss"
            else:
                status = "breakeven"
            
            # Get last trade date
            last_trade = portfolio_trades[0] if portfolio_trades else None
            
            result.append({
                "user_id": user_id,
                "portfolio_id": portfolio.id,
                "portfolio_name": portfolio.portfolio_name,
                "investment_amount": investment,
                "current_value": investment,  # Frontend updates with live prices
                "available_cash": _decimal_to_float(portfolio.available_cash),
                "realized_pnl": round(realized_pnl, 2),
                "roi_percentage": round(roi, 2),
                "total_trades": len(portfolio_trades),
                "open_positions": len(open_positions),
                "status": status,
                "last_trade_at": last_trade.created_at.isoformat() if last_trade else None,
                "created_at": portfolio.created_at.isoformat(),
            })
        
        return result

    def _build_user_pnl_distribution(self, portfolios: List) -> List[Dict[str, Any]]:
        """Build P&L distribution histogram for users."""
        # Define ranges
        ranges = [
            (-float("inf"), -50000, "< -50k"),
            (-50000, -20000, "-50k to -20k"),
            (-20000, -10000, "-20k to -10k"),
            (-10000, -5000, "-10k to -5k"),
            (-5000, 0, "-5k to 0"),
            (0, 5000, "0 to 5k"),
            (5000, 10000, "5k to 10k"),
            (10000, 20000, "10k to 20k"),
            (20000, 50000, "20k to 50k"),
            (50000, float("inf"), "> 50k"),
        ]
        
        distribution = []
        for min_val, max_val, label in ranges:
            users_in_range = [
                p for p in portfolios
                if min_val <= _decimal_to_float(p.total_realized_pnl or 0) < max_val
            ]
            total_pnl = sum(_decimal_to_float(p.total_realized_pnl or 0) for p in users_in_range)
            
            distribution.append({
                "range_label": label,
                "range_min": min_val if min_val != -float("inf") else -100000,
                "range_max": max_val if max_val != float("inf") else 100000,
                "user_count": len(users_in_range),
                "total_pnl": round(total_pnl, 2),
            })
        
        return distribution

    def _build_top_bottom_users(
        self, portfolios: List, trades: List, positions: List
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get top and bottom performing users."""
        user_metrics = self._build_user_portfolio_metrics(portfolios, trades, positions)
        
        sorted_by_pnl = sorted(user_metrics, key=lambda x: x["realized_pnl"], reverse=True)
        
        return {
            "top_users": sorted_by_pnl[:10],
            "bottom_users": sorted_by_pnl[-10:][::-1] if len(sorted_by_pnl) > 10 else sorted_by_pnl[::-1],
        }

    def _build_position_metrics(self, positions: List) -> Dict[str, Any]:
        """Build position summary metrics."""
        open_positions = [p for p in positions if p.status == "open"]
        closed_positions = [p for p in positions if p.status == "closed"]
        long_positions = [p for p in positions if p.position_type == "long"]
        short_positions = [p for p in positions if p.position_type == "short"]
        
        total_invested = sum(
            _decimal_to_float(p.average_buy_price) * p.quantity
            for p in open_positions
        )
        
        return {
            "total_positions": len(positions),
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "long_positions": len(long_positions),
            "short_positions": len(short_positions),
            "total_invested_in_positions": round(total_invested, 2),
        }

    def _build_symbol_concentration(self, positions: List) -> List[Dict[str, Any]]:
        """Build symbol concentration for risk analysis."""
        symbol_data = defaultdict(lambda: {"quantity": 0, "value": 0, "count": 0})
        
        for pos in positions:
            if pos.status == "open":
                value = _decimal_to_float(pos.average_buy_price) * pos.quantity
                symbol_data[pos.symbol]["quantity"] += pos.quantity
                symbol_data[pos.symbol]["value"] += value
                symbol_data[pos.symbol]["count"] += 1
        
        total_value = sum(d["value"] for d in symbol_data.values())
        
        result = []
        for symbol, data in symbol_data.items():
            pct = (data["value"] / total_value * 100) if total_value > 0 else 0
            result.append({
                "symbol": symbol,
                "total_quantity": data["quantity"],
                "total_value": round(data["value"], 2),
                "position_count": data["count"],
                "percentage_of_total": round(pct, 2),
            })
        
        # Sort by value descending
        result.sort(key=lambda x: x["total_value"], reverse=True)
        return result[:20]  # Top 20

    def _build_pending_orders_metrics(self, trades: List) -> Dict[str, Any]:
        """Build pending orders summary."""
        pending_limit = len([t for t in trades if t.status == "pending" and t.order_type == "limit"])
        pending_sl = len([t for t in trades if t.status == "pending_sl"])
        pending_tp = len([t for t in trades if t.status == "pending_tp"])
        pending_auto_sell = len([t for t in trades if t.auto_sell_at is not None and t.status in ("executed", "pending")])
        
        pending_value = sum(
            _decimal_to_float(t.quantity * (t.limit_price or t.trigger_price or t.price or 0))
            for t in trades
            if t.status in ("pending", "pending_tp", "pending_sl")
        )
        
        return {
            "pending_limit_orders": pending_limit,
            "pending_stop_loss": pending_sl,
            "pending_take_profit": pending_tp,
            "pending_auto_sell": pending_auto_sell,
            "total_pending_value": round(pending_value, 2),
        }

    def _build_pipeline_metrics(self, trades: List, today_start: datetime, week_start: datetime) -> Dict[str, Any]:
        """Build pipeline/signal metrics from trade metadata."""
        signals_today = 0
        signals_week = 0
        llm_delays = []
        trade_delays = []
        
        for trade in trades:
            metadata = _parse_metadata(trade.metadata)
            
            # Count NSE signals
            if metadata.get("source") == "nse_pipeline" or trade.trade_type == "nse_signal":
                trade_dt = _ensure_tz_aware(trade.created_at)
                if trade_dt and trade_dt >= today_start:
                    signals_today += 1
                if trade_dt and trade_dt >= week_start:
                    signals_week += 1
            
            # Collect delay metrics
            if metadata.get("llm_delay_ms"):
                llm_delays.append(metadata["llm_delay_ms"])
            if metadata.get("trade_delay"):
                trade_delays.append(metadata["trade_delay"])
        
        return {
            "signals_today": signals_today,
            "signals_this_week": signals_week,
            "avg_llm_delay_ms": round(sum(llm_delays) / len(llm_delays), 2) if llm_delays else None,
            "avg_trade_delay_ms": round(sum(trade_delays) / len(trade_delays), 2) if trade_delays else None,
            "min_llm_delay_ms": min(llm_delays) if llm_delays else None,
            "max_llm_delay_ms": max(llm_delays) if llm_delays else None,
            "min_trade_delay_ms": min(trade_delays) if trade_delays else None,
            "max_trade_delay_ms": max(trade_delays) if trade_delays else None,
        }

    def _build_execution_metrics(self, execution_logs: List) -> Dict[str, Any]:
        """Build execution log metrics."""
        successful = [e for e in execution_logs if e.status == "executed"]
        failed = [e for e in execution_logs if e.status in ("failed", "rejected")]
        pending = [e for e in execution_logs if e.status == "pending"]
        
        # Calculate average execution time from trade_delay field
        delays = [e.trade_delay for e in execution_logs if e.trade_delay is not None]
        avg_time = (sum(delays) / len(delays)) if delays else None
        
        return {
            "total_executions": len(execution_logs),
            "successful_executions": len(successful),
            "failed_executions": len(failed),
            "pending_executions": len(pending),
            "avg_execution_time_ms": round(avg_time, 2) if avg_time else None,
        }

    def _build_portfolio_value_series(self, snapshots: List) -> List[Dict[str, Any]]:
        """Build portfolio value time series."""
        # Group by date and aggregate
        daily_snapshots = defaultdict(lambda: {"value": 0, "realized": 0, "unrealized": 0, "count": 0})
        
        for snap in snapshots:
            date_key = snap.snapshot_at.strftime("%Y-%m-%d")
            daily_snapshots[date_key]["value"] += _decimal_to_float(snap.current_value)
            daily_snapshots[date_key]["realized"] += _decimal_to_float(snap.realized_pnl)
            daily_snapshots[date_key]["unrealized"] += _decimal_to_float(snap.unrealized_pnl)
            daily_snapshots[date_key]["count"] += 1
        
        result = []
        for date in sorted(daily_snapshots.keys()):
            data = daily_snapshots[date]
            result.append({
                "snapshot_at": date,
                "total_value": round(data["value"], 2),
                "realized_pnl": round(data["realized"], 2),
                "unrealized_pnl": round(data["unrealized"], 2),
            })
        
        return result[-90:]  # Last 90 days

    def _build_alpha_metrics(
        self, runs: List, live_alphas: List, signals: List
    ) -> Optional[Dict[str, Any]]:
        """Build alpha copilot metrics."""
        if not runs and not live_alphas:
            return None
        
        completed = len([r for r in runs if r.status == "completed"])
        running = len([r for r in runs if r.status == "running"])
        failed = len([r for r in runs if r.status == "failed"])
        
        running_alphas = len([a for a in live_alphas if a.status == "running"])
        
        executed_signals = len([s for s in signals if s.status == "executed"])
        pending_signals = len([s for s in signals if s.status == "pending"])
        
        return {
            "total_runs": len(runs),
            "completed_runs": completed,
            "running_runs": running,
            "failed_runs": failed,
            "live_alphas_count": len(live_alphas),
            "running_alphas": running_alphas,
            "total_alpha_signals": len(signals),
            "executed_signals": executed_signals,
            "pending_signals": pending_signals,
        }

    async def get_summary(self, organization_id: str) -> Dict[str, Any]:
        """
        Get lightweight dashboard summary for frequent polling.
        """
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        portfolios = await self.prisma.portfolio.find_many(
            where={"organization_id": organization_id},
        )
        
        if not portfolios:
            return {
                "generated_at": now.isoformat(),
                "organization_id": organization_id,
                "total_aum": 0,
                "total_realized_pnl": 0,
                "total_trades_today": 0,
                "pending_orders_count": 0,
                "active_agents": 0,
                "error_agents": 0,
                "portfolios_in_loss": 0,
                "agents_with_errors": 0,
                "high_concentration_symbols": [],
            }
        
        portfolio_ids = [p.id for p in portfolios]
        
        # Quick counts
        trades_today = await self.prisma.trade.count(
            where={
                "portfolio_id": {"in": portfolio_ids},
                "created_at": {"gte": today_start},
            }
        )
        
        pending_orders = await self.prisma.trade.count(
            where={
                "portfolio_id": {"in": portfolio_ids},
                "status": {"in": ["pending", "pending_tp", "pending_sl"]},
            }
        )
        
        agents = await self.prisma.tradingagent.find_many(
            where={"portfolio_id": {"in": portfolio_ids}},
        )
        
        active_agents = len([a for a in agents if a.status == "active"])
        error_agents = len([a for a in agents if a.error_count > 0])
        
        total_aum = sum(_decimal_to_float(p.investment_amount) for p in portfolios)
        total_pnl = sum(_decimal_to_float(p.total_realized_pnl or 0) for p in portfolios)
        portfolios_in_loss = len([p for p in portfolios if _decimal_to_float(p.total_realized_pnl or 0) < 0])
        
        # High concentration check
        positions = await self.prisma.position.find_many(
            where={"portfolio_id": {"in": portfolio_ids}, "status": "open"},
        )
        
        symbol_values = defaultdict(float)
        total_position_value = 0
        for pos in positions:
            value = _decimal_to_float(pos.average_buy_price) * pos.quantity
            symbol_values[pos.symbol] += value
            total_position_value += value
        
        high_concentration = [
            sym for sym, val in symbol_values.items()
            if total_position_value > 0 and (val / total_position_value) > 0.2
        ]
        
        return {
            "generated_at": now.isoformat(),
            "organization_id": organization_id,
            "total_aum": round(total_aum, 2),
            "total_realized_pnl": round(total_pnl, 2),
            "total_trades_today": trades_today,
            "pending_orders_count": pending_orders,
            "active_agents": active_agents,
            "error_agents": error_agents,
            "portfolios_in_loss": portfolios_in_loss,
            "agents_with_errors": error_agents,
            "high_concentration_symbols": high_concentration,
        }
