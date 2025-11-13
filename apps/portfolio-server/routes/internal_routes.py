from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Set

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from prisma import Prisma

from db import prisma_client
from workers.allocation_tasks import _ensure_trading_agent  # type: ignore
from middleware.py.internal_auth_middleware import internal_auth


router = APIRouter(
    prefix="/internal/trading-agents",
    tags=["Internal Trading Agents"],
)


class AgentSubscriptionSyncRequest(BaseModel):
    user_id: str = Field(..., alias="user_id")
    subscriptions: List[str] = Field(default_factory=list)


@router.post(
    "/sync",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(internal_auth)],
)
async def sync_trading_agents_for_user(
    payload: AgentSubscriptionSyncRequest,
    prisma: Prisma = Depends(prisma_client),
) -> Dict[str, int]:
    user_id = payload.user_id
    subscription_set: Set[str] = {sub.lower() for sub in payload.subscriptions}

    portfolios = await prisma.portfolio.find_many(
        where={
            "OR": [
                {"user_id": user_id},
                {"customer_id": user_id},
            ],
            "status": "active",
        },
        include={"allocations": True},
    )

    if not portfolios:
        return {"portfolios_evaluated": 0, "agents_updated": 0}

    agents_updated = 0
    timestamp = datetime.utcnow().isoformat()

    for portfolio in portfolios:
        allocations = getattr(portfolio, "allocations", []) or []
        for allocation in allocations:
            context = {
                "request_id": f"subscription_sync_{portfolio.id}_{allocation.id}_{timestamp}",
                "trigger": "subscription_sync",
                "timestamp": timestamp,
            }
            updated = await _ensure_trading_agent(
                prisma,
                portfolio_id=str(getattr(portfolio, "id")),
                allocation=allocation,
                allocation_type=str(getattr(allocation, "allocation_type")),
                request_context=context,
                objective_id=getattr(portfolio, "objective_id", None),
                user_subscriptions=subscription_set,
            )
            if updated is not None:
                agents_updated += 1

    return {
        "portfolios_evaluated": len(portfolios),
        "agents_updated": agents_updated,
    }

