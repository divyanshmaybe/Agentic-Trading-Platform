"""Portfolio routes for retrieving or creating user portfolios."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from prisma import Prisma

from auth_middleware import protect_route  # type: ignore
from db import prisma_client
from schemas import PortfolioResponse


router = APIRouter(prefix="/portfolio", tags=["Portfolio"])


def _decimal_from_env(env_key: str, default: str) -> Decimal:
    value = os.getenv(env_key)
    if value is None:
        return Decimal(default)
    try:
        return Decimal(value)
    except Exception:
        return Decimal(default)


DEFAULT_PORTFOLIO_NAME = os.getenv("DEFAULT_PORTFOLIO_NAME", "Managed Portfolio")
DEFAULT_INVESTMENT_AMOUNT = _decimal_from_env("DEFAULT_PORTFOLIO_INVESTMENT_AMOUNT", "0")
DEFAULT_EXPECTED_RETURN_TARGET = _decimal_from_env("DEFAULT_PORTFOLIO_EXPECTED_RETURN_TARGET", "0.0800")
DEFAULT_INVESTMENT_HORIZON_YEARS = int(os.getenv("DEFAULT_PORTFOLIO_HORIZON_YEARS", "3"))
DEFAULT_RISK_TOLERANCE = os.getenv("DEFAULT_PORTFOLIO_RISK_TOLERANCE", "moderate")
DEFAULT_LIQUIDITY_NEEDS = os.getenv("DEFAULT_PORTFOLIO_LIQUIDITY_NEEDS", "standard")


def _normalize_user(user: dict) -> dict:
    normalized = {
        "id": user.get("id") or user.get("_id"),
        "organization_id": user.get("organization_id") or user.get("organizationId"),
        "customer_id": user.get("customer_id") or user.get("customerId"),
        "role": user.get("role"),
        "email": user.get("email"),
        "raw": user,
    }
    return normalized


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


@router.get("/", response_model=PortfolioResponse)
async def get_or_create_portfolio_for_user(
    request: Request,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
) -> PortfolioResponse:
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

    portfolio = await prisma.portfolio.find_first(
        where={
            "organization_id": organization_id,
            "customer_id": customer_id,
        },
        order={"created_at": "asc"},
    )

    if portfolio is None:
        defaults: Dict[str, Optional[Decimal]] = {
            "investment_amount": DEFAULT_INVESTMENT_AMOUNT,
            "expected_return_target": DEFAULT_EXPECTED_RETURN_TARGET,
        }
        portfolio = await prisma.portfolio.create(
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
                "metadata": json.dumps({
                    "auto_created": True,
                    "created_for_user": str(user_id),
                }),
            }
        )

    return PortfolioResponse.model_validate(portfolio)
