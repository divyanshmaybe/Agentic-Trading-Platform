"""Portfolio controller encapsulating business logic for portfolio routes."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Dict, Literal, Optional

from fastapi import HTTPException, status
from prisma import Prisma

from schemas import (
    HoldingResponse,
    PortfolioResponse,
    PositionListResponse,
    PositionSummary,
    TradeListResponse,
    TradingAgentListResponse,
    TradingAgentSummary,
    PortfolioAllocationListResponse,
    PortfolioAllocationSummary,
    SnapshotListResponse,
    SnapshotResponse,
    AllocationDashboardSummary,
    RecentTradeSummary,
    PortfolioDashboardResponse,
    AgentDashboardResponse,
)
from schemas.portfolio import TradeSummary as PortfolioTradeSummary


def _decimal_from_env(env_key: str, default: str) -> Decimal:
    value = os.getenv(env_key)
    if value is None:
        return Decimal(default)
    try:
        return Decimal(value)
    except Exception:
        return Decimal(default)


DEFAULT_PORTFOLIO_NAME = os.getenv("DEFAULT_PORTFOLIO_NAME", "Managed Portfolio")
DEFAULT_PORTFOLIO_CASH = _decimal_from_env("DEFAULT_PORTFOLIO_CASH", "100000")
DEFAULT_EXPECTED_RETURN_TARGET = _decimal_from_env("DEFAULT_PORTFOLIO_EXPECTED_RETURN_TARGET", "0.0800")
DEFAULT_INVESTMENT_HORIZON_YEARS = int(os.getenv("DEFAULT_PORTFOLIO_HORIZON_YEARS", "3"))
DEFAULT_RISK_TOLERANCE = os.getenv("DEFAULT_PORTFOLIO_RISK_TOLERANCE", "moderate")
DEFAULT_LIQUIDITY_NEEDS = os.getenv("DEFAULT_PORTFOLIO_LIQUIDITY_NEEDS", "standard")
MAX_TRADE_VALUE = _decimal_from_env("MAX_TRADE_VALUE", "50000")
MAX_POSITION_VALUE = _decimal_from_env("MAX_POSITION_VALUE", "100000")


class PortfolioController:
    """Encapsulates portfolio-related queries and transformations."""

    def __init__(self, prisma: Prisma, *, logger: Optional[logging.Logger] = None) -> None:
        self.prisma = prisma
        self.logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Authorization & helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _authorize_user(request_user: dict, target_user_id: str) -> None:
        if not target_user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        requester_id = str(request_user.get("id")) if request_user.get("id") else None
        if requester_id and requester_id == str(target_user_id):
            return

        # SECURITY: Only accept validated roles from auth system (admin, staff, viewer)
        # Removed unvalidated roles: superadmin, portfolio_admin, portfolio_manager
        role = (request_user.get("role") or "").lower()
        if role == "admin":
            return

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this user")

    @staticmethod
    def _parse_metadata(payload: Optional[object]) -> Optional[dict]:
        if payload is None:
            return None
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return None
        return None

    async def _get_portfolio_for_user(
        self,
        user_id: str,
        organization_id: Optional[str],
    ):
        filters: Dict[str, object] = {"customer_id": user_id}
        if organization_id:
            filters["organization_id"] = organization_id

        return await self.prisma.portfolio.find_first(
            where=filters,
            order={"created_at": "asc"},
        )

    # ------------------------------------------------------------------
    # Public controller methods
    # ------------------------------------------------------------------
    async def get_or_create_portfolio(self, user: dict) -> PortfolioResponse:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        organization_id = user.get("organization_id")
        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated user is not linked to an organization",
            )

        customer_id = user.get("customer_id") or user_id
        if not customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to resolve customer for user",
            )

        portfolio = await self.prisma.portfolio.find_first(
            where={
                "organization_id": organization_id,
                "customer_id": customer_id,
            },
            order={"created_at": "asc"},
        )

        if portfolio is None:
            defaults = {
                "investment_amount": DEFAULT_PORTFOLIO_CASH,
                "initial_investment": DEFAULT_PORTFOLIO_CASH,
                "expected_return_target": DEFAULT_EXPECTED_RETURN_TARGET,
            }
            
            # Create portfolio with pending allocation status
            portfolio = await self.prisma.portfolio.create(
                data={
                    "user_id": user_id,  # Set the authenticated user ID
                    "organization_id": organization_id,
                    "customer_id": customer_id,
                    "portfolio_name": f"{user.get('name') or user.get('firstName') or 'User'}'s Portfolio"
                    if user.get("name") or user.get("firstName")
                    else DEFAULT_PORTFOLIO_NAME,
                    "initial_investment": defaults["initial_investment"],
                    "investment_amount": defaults["investment_amount"],
                    "current_value": defaults["investment_amount"],
                    "investment_horizon_years": DEFAULT_INVESTMENT_HORIZON_YEARS,
                    "expected_return_target": defaults["expected_return_target"],
                    "risk_tolerance": DEFAULT_RISK_TOLERANCE,
                    "liquidity_needs": DEFAULT_LIQUIDITY_NEEDS,
                    "allocation_status": "pending",  # Will be updated by allocation task
                    "metadata": json.dumps(
                        {
                            "auto_created": True,
                            "created_for_user": str(user_id),
                            "max_trade_value": str(MAX_TRADE_VALUE),
                            "max_position_value": str(MAX_POSITION_VALUE),
                        }
                    ),
                }
            )
            
            # Trigger portfolio allocation via Celery
            try:
                from workers.allocation_tasks import allocate_new_portfolio_task
                
                user_inputs = {
                    "risk_tolerance": portfolio.risk_tolerance,
                    "investment_horizon_years": portfolio.investment_horizon_years,
                    "liquidity_needs": portfolio.liquidity_needs or "medium",
                    "expected_return_target": float(portfolio.expected_return_target),
                    "rebalancing_frequency": "quarterly",  # Default frequency
                }
                
                task = allocate_new_portfolio_task.delay(
                    portfolio_id=portfolio.id,
                    user_id=str(user_id),
                    organization_id=organization_id,
                    user_inputs=user_inputs,
                    initial_value=float(portfolio.investment_amount),
                )
                
                self.logger.info(
                    f"✅ Portfolio allocation task dispatched for {portfolio.id} (task_id={task.id})"
                )
            except Exception as exc:
                self.logger.error(
                    f"❌ Failed to dispatch allocation task for portfolio {portfolio.id}: {exc}",
                    exc_info=True
                )

        return PortfolioResponse.model_validate(portfolio)

    async def get_holding(
        self,
        request_user: dict,
        symbol: str,
        *,
        target_user_id: Optional[str] = None,
    ) -> HoldingResponse:
        user_id = target_user_id or request_user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        self._authorize_user(request_user, user_id)

        portfolio = await self._get_portfolio_for_user(user_id, request_user.get("organization_id"))
        if portfolio is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found for user")

        position = await self.prisma.position.find_first(
            where={
                "portfolio_id": portfolio.id,
                "symbol": {"equals": symbol, "mode": "insensitive"},
            }
        )

        if position is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found for symbol")

        return HoldingResponse(
            portfolio_id=portfolio.id,
            position_id=position.id,
            symbol=position.symbol,
            exchange=position.exchange,
            segment=position.segment,
            quantity=position.quantity,
            average_buy_price=position.average_buy_price,
            current_price=position.current_price,
            current_value=position.current_value,
            pnl=position.pnl,
            pnl_percentage=position.pnl_percentage,
            position_type=position.position_type,
            status=position.status,
            metadata=self._parse_metadata(position.metadata),
            last_updated=position.updated_at,
        )

    async def list_positions(
        self,
        request_user: dict,
        *,
        page: int,
        limit: int,
        search: Optional[str],
        profitability: Optional[str],
        sort_by: str,
        sort_order: Literal["asc", "desc"],
        target_user_id: Optional[str] = None,
    ) -> PositionListResponse:
        user_id = target_user_id or request_user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        self._authorize_user(request_user, user_id)

        portfolio = await self._get_portfolio_for_user(user_id, request_user.get("organization_id"))
        if portfolio is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found for user")

        where: Dict[str, object] = {"portfolio_id": portfolio.id}

        if search:
            where["symbol"] = {"contains": search, "mode": "insensitive"}

        if profitability:
            normalized = profitability.lower()
            if normalized in {"profitable", "profit"}:
                where["pnl"] = {"gt": Decimal("0")}
            elif normalized in {"loss", "loss-making", "losing"}:
                where["pnl"] = {"lt": Decimal("0")}
            elif normalized in {"breakeven", "neutral"}:
                where["pnl"] = {"equals": Decimal("0")}

        sort_field_map = {
            "symbol": "symbol",
            "quantity": "quantity",
            "currentValue": "current_value",
            "current_price": "current_price",
            "pnl": "pnl",
            "unrealizedPnL": "pnl",
            "pnlPercentage": "pnl_percentage",
            "positionType": "position_type",
            "status": "status",
            "updatedAt": "updated_at",
        }
        sort_field = sort_field_map.get(sort_by, "updated_at")

        total = await self.prisma.position.count(where=where)
        records = await self.prisma.position.find_many(
            where=where,
            skip=(page - 1) * limit,
            take=limit,
            order={sort_field: sort_order},
        )

        summaries = [
            PositionSummary(
                id=record.id,
                portfolio_id=record.portfolio_id,
                symbol=record.symbol,
                exchange=record.exchange,
                segment=record.segment,
                quantity=record.quantity,
                average_buy_price=record.average_buy_price,
                current_price=record.current_price,
                current_value=record.current_value,
                pnl=record.pnl,
                pnl_percentage=record.pnl_percentage,
                position_type=record.position_type,
                status=record.status,
                updated_at=record.updated_at,
            )
            for record in records
        ]

        return PositionListResponse(items=summaries, page=page, limit=limit, total=total)

    async def list_recent_trades(
        self,
        request_user: dict,
        *,
        page: int,
        limit: int,
        symbol: Optional[str],
        side: Optional[str],
        order_type: Optional[str],
        status_filter: Optional[str],
        target_user_id: Optional[str] = None,
    ) -> TradeListResponse:
        user_id = target_user_id or request_user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        self._authorize_user(request_user, user_id)

        portfolio = await self._get_portfolio_for_user(user_id, request_user.get("organization_id"))
        if portfolio is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found for user")

        where: Dict[str, object] = {"portfolio_id": portfolio.id}

        if symbol:
            where["symbol"] = {"equals": symbol, "mode": "insensitive"}
        if side:
            normalized_side = side.strip().upper()
            side_aliases = {
                "BUY": "BUY",
                "LONG": "BUY",
                "SELL": "SELL",
                "SHORT": "SELL",
            }
            resolved_side = side_aliases.get(normalized_side)
            if resolved_side:
                where["side"] = {"equals": resolved_side}
        if order_type:
            normalized_order_type = order_type.strip().lower()
            order_aliases = {
                "market": "market",
                "limit": "limit",
                "stop": "stop",
                "stop_loss": "stop_loss",
                "stoploss": "stop_loss",
                "take_profit": "take_profit",
                "takeprofit": "take_profit",
            }
            resolved_order_type = order_aliases.get(normalized_order_type)
            if resolved_order_type:
                where["order_type"] = {"equals": resolved_order_type}
        if status_filter:
            normalized_status = status_filter.strip().lower()
            status_aliases = {
                "executed": "executed",
                "filled": "executed",
                "partial": "partially_executed",
                "partially_filled": "partially_executed",
                "pending": "pending",
                "open": "pending",
                "rejected": "rejected",
                "cancelled": "cancelled",
                "canceled": "cancelled",
            }
            resolved_status = status_aliases.get(normalized_status)
            if resolved_status:
                where["status"] = {"equals": resolved_status}

        total = await self.prisma.trade.count(where=where)
        trades = await self.prisma.trade.find_many(
            where=where,
            skip=(page - 1) * limit,
            take=limit,
            order={"created_at": "desc"},
        )

        summaries = [
            PortfolioTradeSummary(
                id=trade.id,
                portfolio_id=trade.portfolio_id,
                symbol=trade.symbol,
                side=trade.side,
                order_type=trade.order_type,
                quantity=trade.quantity,
                executed_quantity=trade.executed_quantity,
                executed_price=trade.executed_price,
                status=trade.status,
                net_amount=trade.net_amount,
                trade_type=trade.trade_type,
                created_at=trade.created_at,
                execution_time=trade.execution_time,
            )
            for trade in trades
        ]

        return TradeListResponse(items=summaries, page=page, limit=limit, total=total)

    async def get_trading_agents(
        self,
        request_user: dict,
        *,
        target_user_id: Optional[str] = None,
    ) -> TradingAgentListResponse:
        """Get all trading agents for the user's portfolio"""
        user_id = target_user_id or request_user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        self._authorize_user(request_user, user_id)

        portfolio = await self._get_portfolio_for_user(user_id, request_user.get("organization_id"))
        if portfolio is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found for user")

        agents = await self.prisma.tradingagent.find_many(
            where={"portfolio_id": portfolio.id},
            order={"created_at": "desc"},
        )

        summaries = [
            TradingAgentSummary(
                id=agent.id,
                portfolio_id=agent.portfolio_id,
                portfolio_allocation_id=agent.portfolio_allocation_id,
                agent_type=agent.agent_type,
                agent_name=agent.agent_name,
                status=agent.status,
                strategy_config=self._parse_metadata(agent.strategy_config),
                performance_metrics=self._parse_metadata(agent.performance_metrics),
                last_executed_at=agent.last_executed_at,
                error_count=agent.error_count,
                last_error_message=agent.last_error_message,
                metadata=self._parse_metadata(agent.metadata),
                created_at=agent.created_at,
                updated_at=agent.updated_at,
            )
            for agent in agents
        ]

        return TradingAgentListResponse(items=summaries, total=len(summaries))

    async def get_portfolio_allocations(
        self,
        request_user: dict,
        *,
        target_user_id: Optional[str] = None,
    ) -> PortfolioAllocationListResponse:
        """Get all portfolio allocations for the user's portfolio"""
        user_id = target_user_id or request_user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        self._authorize_user(request_user, user_id)

        portfolio = await self._get_portfolio_for_user(user_id, request_user.get("organization_id"))
        if portfolio is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found for user")

        allocations = await self.prisma.portfolioallocation.find_many(
            where={"portfolio_id": portfolio.id},
            include={"tradingAgent": True},
            order={"created_at": "asc"},
        )

        summaries = []
        for allocation in allocations:
            trading_agent = None
            if allocation.tradingAgent:
                agent = allocation.tradingAgent
                trading_agent = TradingAgentSummary(
                    id=agent.id,
                    portfolio_id=agent.portfolio_id,
                    portfolio_allocation_id=agent.portfolio_allocation_id,
                    agent_type=agent.agent_type,
                    agent_name=agent.agent_name,
                    status=agent.status,
                    strategy_config=self._parse_metadata(agent.strategy_config),
                    performance_metrics=self._parse_metadata(agent.performance_metrics),
                    last_executed_at=agent.last_executed_at,
                    error_count=agent.error_count,
                    last_error_message=agent.last_error_message,
                    metadata=self._parse_metadata(agent.metadata),
                    created_at=agent.created_at,
                    updated_at=agent.updated_at,
                )

            summaries.append(
                PortfolioAllocationSummary(
                    id=allocation.id,
                    portfolio_id=allocation.portfolio_id,
                    allocation_type=allocation.allocation_type,
                    target_weight=allocation.target_weight,
                    current_weight=allocation.current_weight,
                    allocated_amount=allocation.allocated_amount,
                    current_value=allocation.current_value,
                    expected_return=allocation.expected_return,
                    expected_risk=allocation.expected_risk,
                    regime=allocation.regime,
                    pnl=allocation.pnl,
                    pnl_percentage=allocation.pnl_percentage,
                    drift_percentage=allocation.drift_percentage,
                    requires_rebalancing=allocation.requires_rebalancing,
                    metadata=self._parse_metadata(allocation.metadata),
                    created_at=allocation.created_at,
                    updated_at=allocation.updated_at,
                    trading_agent=trading_agent,
                )
            )

        return PortfolioAllocationListResponse(items=summaries, total=len(summaries))

    async def get_dashboard(
        self,
        request_user: dict,
        *,
        target_user_id: Optional[str] = None,
    ) -> PortfolioDashboardResponse:
        """Get aggregated portfolio dashboard data"""
        user_id = target_user_id or request_user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        self._authorize_user(request_user, user_id)

        portfolio = await self._get_portfolio_for_user(user_id, request_user.get("organization_id"))
        if portfolio is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found for user")

        # Get portfolio statistics
        positions = await self.prisma.position.find_many(
            where={"portfolio_id": portfolio.id, "status": "open"},
        )
        
        agents = await self.prisma.tradingagent.find_many(
            where={"portfolio_id": portfolio.id, "status": "active"},
        )
        
        allocations = await self.prisma.portfolioallocation.find_many(
            where={"portfolio_id": portfolio.id},
        )
        
        # Get recent trades (last 10)
        recent_trades = await self.prisma.trade.find_many(
            where={"portfolio_id": portfolio.id},
            order={"created_at": "desc"},
            take=10,
        )
        
        # Calculate cash balance (look for cashAvailable allocation or use investment_amount - current_value)
        cash_allocation = next(
            (a for a in allocations if a.allocation_type == "cashAvailable"),
            None
        )
        cash_balance = cash_allocation.current_value if cash_allocation else (
            portfolio.investment_amount - portfolio.current_value
        )
        
        # Build allocation summaries
        allocation_summaries = [
            AllocationDashboardSummary(
                allocation_type=alloc.allocation_type,
                target_weight=alloc.target_weight,
                allocated_amount=alloc.allocated_amount,
                current_value=alloc.current_value,
                realized_pnl=getattr(alloc, "realized_pnl", Decimal("0")) or Decimal("0"),
                pnl_percentage=alloc.pnl_percentage,
            )
            for alloc in allocations
            if alloc.allocation_type != "cashAvailable"  # Exclude cash from dashboard allocations
        ]
        
        # Build recent trade summaries
        recent_trade_summaries = [
            RecentTradeSummary(
                id=trade.id,
                symbol=trade.symbol,
                side=trade.side,
                quantity=trade.quantity,
                executed_price=trade.executed_price,
                executed_at=trade.execution_time,
                realized_pnl=getattr(trade, "realized_pnl", None),
            )
            for trade in recent_trades
        ]
        
        return PortfolioDashboardResponse(
            portfolio_id=portfolio.id,
            portfolio_name=portfolio.portfolio_name,
            investment_amount=portfolio.investment_amount,
            current_value=portfolio.current_value,
            realized_pnl=getattr(portfolio, "realized_pnl", Decimal("0")) or Decimal("0"),
            total_positions=len(positions),
            active_agents=len(agents),
            cash_balance=cash_balance,
            allocations=allocation_summaries,
            recent_trades=recent_trade_summaries,
        )

    async def get_agent_dashboard(
        self,
        agent_id: str,
        request_user: dict,
    ) -> AgentDashboardResponse:
        """Get agent-specific dashboard data"""
        # Get agent with related data
        agent = await self.prisma.tradingagent.find_unique(
            where={"id": agent_id},
            include={
                "portfolio": True,
                "allocation": True,
                "positions": {
                    "where": {"status": "open"},
                },
                "trades": {
                    "order_by": {"created_at": "desc"},
                    "take": 10,
                },
            },
        )
        
        if not agent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        
        # Authorize user has access to portfolio
        portfolio = agent.portfolio
        if portfolio:
            user_id = portfolio.customer_id
            self._authorize_user(request_user, user_id)
        
        # Calculate portfolio value from positions
        positions = getattr(agent, "positions", []) or []
        portfolio_value = sum(
            (getattr(p, "current_price", Decimal("0")) or Decimal("0")) * Decimal(str(getattr(p, "quantity", 0)))
            for p in positions
        )
        
        # Get realized P&L from agent
        realized_pnl = getattr(agent, "realized_pnl", Decimal("0")) or Decimal("0")
        
        # Build position summaries
        position_summaries = [
            PositionSummary(
                id=pos.id,
                portfolio_id=pos.portfolio_id,
                symbol=pos.symbol,
                exchange=pos.exchange,
                segment=pos.segment,
                quantity=pos.quantity,
                average_buy_price=pos.average_buy_price,
                current_price=pos.current_price,
                current_value=pos.current_value,
                pnl=pos.pnl,
                pnl_percentage=pos.pnl_percentage,
                position_type=pos.position_type,
                status=pos.status,
                updated_at=pos.updated_at,
            )
            for pos in positions
        ]
        
        # Build allocation summary if exists
        allocation_summary = None
        if agent.allocation:
            alloc = agent.allocation
            allocation_summary = PortfolioAllocationSummary(
                id=alloc.id,
                portfolio_id=alloc.portfolio_id,
                allocation_type=alloc.allocation_type,
                target_weight=alloc.target_weight,
                current_weight=alloc.current_weight,
                allocated_amount=alloc.allocated_amount,
                current_value=alloc.current_value,
                expected_return=alloc.expected_return,
                expected_risk=alloc.expected_risk,
                regime=alloc.regime,
                pnl=alloc.pnl,
                pnl_percentage=alloc.pnl_percentage,
                drift_percentage=alloc.drift_percentage,
                requires_rebalancing=alloc.requires_rebalancing,
                metadata=self._parse_metadata(alloc.metadata),
                created_at=alloc.created_at,
                updated_at=alloc.updated_at,
                trading_agent=None,  # Don't nest recursively
            )
        
        # Build trade summaries
        trades = getattr(agent, "trades", []) or []
        trade_summaries = [
            PortfolioTradeSummary(
                id=trade.id,
                portfolio_id=trade.portfolio_id,
                symbol=trade.symbol,
                side=trade.side,
                order_type=trade.order_type,
                quantity=trade.quantity,
                executed_quantity=trade.executed_quantity,
                executed_price=trade.executed_price,
                status=trade.status,
                net_amount=trade.net_amount,
                trade_type=trade.trade_type,
                created_at=trade.created_at,
                execution_time=trade.execution_time,
            )
            for trade in trades
        ]
        
        return AgentDashboardResponse(
            agent_id=agent.id,
            agent_name=agent.agent_name,
            agent_type=agent.agent_type,
            portfolio_id=agent.portfolio_id or "",
            status=agent.status,
            portfolio_value=portfolio_value,
            realized_pnl=realized_pnl,
            positions_count=len(positions),
            positions=position_summaries,
            allocation=allocation_summary,
            performance_metrics=self._parse_metadata(agent.performance_metrics),
            recent_trades=trade_summaries,
        )

    async def get_snapshots(
        self,
        request_user: dict,
        *,
        agent_id: Optional[str] = None,
        limit: int = 100,
        target_user_id: Optional[str] = None,
    ) -> SnapshotListResponse:
        """Get snapshot history for agent or portfolio"""
        from services.snapshot_service import TradingAgentSnapshotService
        
        user_id = target_user_id or request_user.get("id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User id is required")

        self._authorize_user(request_user, user_id)

        portfolio = await self._get_portfolio_for_user(user_id, request_user.get("organization_id"))
        if portfolio is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found for user")

        service = TradingAgentSnapshotService(logger=self.logger)
        
        if agent_id:
            # Get agent-specific snapshots
            # Verify agent belongs to user's portfolio
            agent = await self.prisma.tradingagent.find_unique(
                where={"id": agent_id},
            )
            if not agent or agent.portfolio_id != portfolio.id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
            
            snapshot_data = await service.get_agent_snapshot_history(agent_id, limit=limit)
        else:
            # Get aggregated portfolio snapshots
            snapshot_data = await service.get_portfolio_snapshot_history(portfolio.id, limit=limit)
        
        snapshots = []
        for item in snapshot_data:
            # Parse snapshot_at - handle both datetime objects and ISO strings
            snapshot_at_str = item["snapshot_at"]
            if isinstance(snapshot_at_str, datetime):
                snapshot_at = snapshot_at_str
            else:
                # Handle ISO string
                snapshot_at_str = snapshot_at_str.replace("Z", "+00:00")
                snapshot_at = datetime.fromisoformat(snapshot_at_str)
            
            snapshots.append(
                SnapshotResponse(
                    snapshot_at=snapshot_at,
                    portfolio_value=Decimal(str(item["portfolio_value"])),
                    realized_pnl=Decimal(str(item["realized_pnl"])),
                    positions_count=item["positions_count"],
                    agents_count=item.get("agents_count"),
                )
            )
        
        return SnapshotListResponse(items=snapshots, total=len(snapshots))
