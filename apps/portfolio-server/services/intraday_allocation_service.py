"""Immediate, deterministic allocation for intraday-only portfolios."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional


INTRADAY_ALLOCATION_TYPE = "high_risk"


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


async def allocate_full_portfolio_to_intraday(
    db: Any,
    *,
    portfolio_id: str,
    user_id: Optional[str],
    objective_id: Optional[str] = None,
    investable_amount: Optional[float] = None,
    triggered_by: str,
) -> dict[str, Any]:
    """Assign 100% of a portfolio to its high-risk/intraday trading agent.

    This is synchronous and contains no model, regime, Pathway, or Celery
    allocation step. The allocation is ready when this function returns.
    """

    portfolio = await db.portfolio.find_unique(where={"id": portfolio_id})
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    amount = Decimal(
        str(
            investable_amount
            if investable_amount is not None
            else portfolio.investment_amount or portfolio.initial_investment or 0
        )
    )
    now = datetime.utcnow()
    allocation_metadata = {
        "mode": "intraday_only",
        "trigger": triggered_by,
        "objective_id": objective_id,
        "allocated_at": now.isoformat() + "Z",
    }

    existing_allocations = await db.portfolioallocation.find_many(
        where={"portfolio_id": portfolio_id}
    )
    intraday_allocation = None

    for allocation in existing_allocations:
        if allocation.allocation_type == INTRADAY_ALLOCATION_TYPE:
            intraday_allocation = allocation
            continue

        await db.portfolioallocation.update(
            where={"id": allocation.id},
            data={
                "target_weight": Decimal("0"),
                "current_weight": Decimal("0"),
                "allocated_amount": Decimal("0"),
                "available_cash": Decimal("0"),
                "requires_rebalancing": False,
                "metadata": _json(
                    {
                        "mode": "intraday_only",
                        "disabled_at": now.isoformat() + "Z",
                        "disabled_by": triggered_by,
                    }
                ),
            },
        )
        agent = await db.tradingagent.find_first(
            where={"portfolio_allocation_id": allocation.id}
        )
        if agent:
            await db.tradingagent.update(
                where={"id": agent.id},
                data={"status": "paused"},
            )

    allocation_data = {
        "target_weight": Decimal("1"),
        "current_weight": Decimal("1"),
        "allocated_amount": amount,
        "available_cash": amount,
        "requires_rebalancing": False,
        "regime": "intraday_only",
        "metadata": _json(allocation_metadata),
    }
    if intraday_allocation:
        intraday_allocation = await db.portfolioallocation.update(
            where={"id": intraday_allocation.id},
            data=allocation_data,
        )
    else:
        intraday_allocation = await db.portfolioallocation.create(
            data={
                "portfolio_id": portfolio_id,
                "allocation_type": INTRADAY_ALLOCATION_TYPE,
                **allocation_data,
            }
        )

    strategy_config = {
        "allocation_type": INTRADAY_ALLOCATION_TYPE,
        "subscription_key": INTRADAY_ALLOCATION_TYPE,
        "auto_trade": True,
        "capital_weight": 1.0,
        "mode": "intraday_only",
        "synced_at": now.isoformat() + "Z",
    }
    agent_metadata = {
        "portfolio_id": portfolio_id,
        "portfolio_allocation_id": intraday_allocation.id,
        "objective_id": objective_id,
        "user_id": user_id,
        "trigger": triggered_by,
    }
    existing_agent = await db.tradingagent.find_first(
        where={"portfolio_allocation_id": intraday_allocation.id}
    )
    agent_data = {
        "portfolio_id": portfolio_id,
        "agent_type": INTRADAY_ALLOCATION_TYPE,
        "agent_name": "Intraday Trading Agent",
        "status": "active",
        "strategy_config": _json(strategy_config),
        "metadata": _json(agent_metadata),
    }
    if existing_agent:
        await db.tradingagent.update(where={"id": existing_agent.id}, data=agent_data)
    else:
        await db.tradingagent.create(
            data={
                **agent_data,
                "portfolio_allocation_id": intraday_allocation.id,
            }
        )

    portfolio_metadata: dict[str, Any] = {}
    raw_metadata = getattr(portfolio, "metadata", None)
    if isinstance(raw_metadata, dict):
        portfolio_metadata.update(raw_metadata)
    elif isinstance(raw_metadata, str):
        try:
            parsed = json.loads(raw_metadata)
            if isinstance(parsed, dict):
                portfolio_metadata.update(parsed)
        except json.JSONDecodeError:
            pass
    portfolio_metadata["allocation"] = allocation_metadata

    await db.portfolio.update(
        where={"id": portfolio_id},
        data={
            "allocation_status": "ready",
            "allocation_strategy": _json({INTRADAY_ALLOCATION_TYPE: 1.0}),
            "rebalancing_date": None,
            "next_rebalance_at": None,
            "last_rebalanced_at": now,
            "metadata": _json(portfolio_metadata),
        },
    )

    return {
        "processed": True,
        "pending": False,
        "allocation": {
            "weights": {INTRADAY_ALLOCATION_TYPE: 1.0},
            "message": "100% of portfolio capital allocated immediately to intraday trading",
            "regime": "intraday_only",
        },
        "last_rebalanced_at": now,
        "next_rebalance_at": None,
        "allocation_id": intraday_allocation.id,
    }
