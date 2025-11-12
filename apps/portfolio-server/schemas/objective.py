from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from typing_extensions import Literal

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
    investment_horizon_label: Optional[str] = Field(
        default=None,
        description="Canonical horizon label derived from intake (short/medium/long)",
    )
    target_return: Optional[Decimal] = Field(
        default=None,
        description="Target annualised return percentage (0-100)",
    )
    risk_tolerance: Optional[str] = Field(
        default=None,
        description="User risk appetite (low/medium/high or custom labels)",
    )
    risk_aversion_lambda: Optional[Decimal] = Field(
        default=None,
        description="Risk aversion score when provided by intake",
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
    preferences: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Preference metadata captured during intake",
    )
    generic_notes: Optional[List[str]] = Field(
        default=None,
        description="Free-form notes extracted from transcript",
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
    raw: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    structured_payload: Optional[Dict[str, Any]] = None
    investable_amount: Optional[Decimal] = None
    investment_horizon_years: Optional[int] = None
    investment_horizon_label: Optional[str] = None
    target_return: Optional[Decimal] = None
    risk_tolerance: Optional[str] = None
    risk_aversion_lambda: Optional[Decimal] = None
    liquidity_needs: Optional[str]
    rebalancing_frequency: Optional[str]
    constraints: Optional[Dict[str, Any]] = None
    target_returns: Optional[List[Any]] = None
    preferences: Optional[Dict[str, Any]] = None
    generic_notes: Optional[List[Any]] = None
    missing_fields: Optional[List[str]] = None
    completion_status: str
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


class ObjectiveIntakeRequest(BaseModel):
    """Interactive intake payload supporting transcripts and partial JSON."""

    objective_id: Optional[str] = Field(
        default=None, description="Pass objective id to continue an intake session"
    )
    name: Optional[str] = Field(default=None, description="Optional label for the objective")
    transcript: Optional[str] = Field(
        default=None,
        description="Conversation transcript used for extraction. Lines should be prefixed with 'User:'",
    )
    structured_payload: Optional[Dict[str, Any]] = Field(
        default=None, description="Partial or complete InvestmentParameters JSON"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata to persist during intake"
    )
    source: Optional[str] = Field(
        default=None,
        description="Source tag for this intake (e.g. chatbot, advisor_form)",
    )

    @validator("transcript")
    def _strip_transcript(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @validator("structured_payload")
    def _ensure_not_empty(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        return value or None


class ObjectiveIntakeResponse(BaseModel):
    """Response payload for the interactive intake endpoint."""

    objective_id: str
    status: Literal["pending", "complete"]
    missing_fields: List[str] = Field(default_factory=list)
    structured_payload: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    message: Optional[str] = None
    created: bool = False
    completion_timestamp: Optional[datetime] = None
    allocation: Optional[AllocationResultSummary] = None

