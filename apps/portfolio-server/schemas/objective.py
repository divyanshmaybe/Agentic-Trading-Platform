from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class ObjectiveCreateRequest(BaseModel):
    """Payload for creating or updating a user's investment objective."""

    name: Optional[str] = Field(default=None, description="Friendly label for the objective")
    investable_amount: Decimal = Field(..., gt=Decimal("0"), description="Total capital available for allocation")
    investment_horizon_years: int = Field(..., ge=1, description="Investment horizon expressed in years")
    expected_return_target: Optional[Decimal] = Field(
        default=None,
        description="Annualised return target (e.g. 0.12 = 12%)",
    )
    risk_tolerance: Optional[str] = Field(
        default=None,
        description="User risk appetite (low/medium/high or custom labels)",
    )
    liquidity_needs: Optional[str] = Field(
        default=None,
        description="Liquidity preference (e.g. standard, high, low)",
    )
    rebalancing_frequency: Optional[Any] = Field(
        default=None,
        description="Preferred rebalancing cadence (string or structured payload)",
    )
    constraints: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Allocation constraints or guard-rails",
    )
    target_returns: Optional[List[Any]] = Field(
        default=None,
        description="Structured milestones or return targets",
    )
    raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Unstructured payload captured from onboarding questionnaire",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata to persist alongside the objective",
    )

    @validator("risk_tolerance")
    def _normalise_risk(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip().lower()


class ObjectiveResponse(BaseModel):
    """API response representation of an investment objective."""

    id: str
    user_id: str
    name: Optional[str]
    raw: Dict[str, Any] = Field(default_factory=dict)
    investable_amount: Decimal
    investment_horizon_years: int
    liquidity_needs: Optional[str]
    rebalancing_frequency: Optional[str]
    constraints: Optional[Dict[str, Any]] = None
    target_returns: Optional[List[Any]] = None
    status: str
    created_at: datetime
    updated_at: datetime


class AllocationResultSummary(BaseModel):
    """Compact summary of an allocation pipeline execution."""

    weights: Dict[str, float]
    expected_return: Optional[float] = None
    expected_risk: Optional[float] = None
    objective_value: Optional[float] = None
    message: Optional[str] = None
    regime: Optional[str] = None
    progress_ratio: Optional[float] = None


class ObjectiveCreateResponse(BaseModel):
    """Response payload returned after creating an objective and allocating the portfolio."""

    objective: ObjectiveResponse
    portfolio_id: str
    allocation: Optional[AllocationResultSummary] = None
    last_rebalanced_at: Optional[datetime] = None
    next_rebalance_at: Optional[datetime] = None

