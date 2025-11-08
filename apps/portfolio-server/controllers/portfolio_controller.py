"""Portfolio controller encapsulating business logic for portfolio routes."""

from __future__ import annotations

import json
import os
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

    def __init__(self, prisma: Prisma) -> None:
        self.prisma = prisma

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
                "expected_return_target": DEFAULT_EXPECTED_RETURN_TARGET,
            }
            portfolio = await self.prisma.portfolio.create(
                data={
                    "organization_id": organization_id,
                    "customer_id": customer_id,
                    "portfolio_name": f"{user.get('name') or user.get('firstName') or 'User'}'s Portfolio"
                    if user.get("name") or user.get("firstName")
                    else DEFAULT_PORTFOLIO_NAME,
                    "investment_amount": defaults["investment_amount"],
                    "current_value": defaults["investment_amount"],
                    "investment_horizon_years": DEFAULT_INVESTMENT_HORIZON_YEARS,
                    "expected_return_target": defaults["expected_return_target"],
                    "risk_tolerance": DEFAULT_RISK_TOLERANCE,
                    "liquidity_needs": DEFAULT_LIQUIDITY_NEEDS,
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
