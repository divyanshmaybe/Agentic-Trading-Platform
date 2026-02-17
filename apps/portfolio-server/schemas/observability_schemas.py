"""
Observability Schemas

Pydantic models for observability API requests and responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ObservabilityLogResponse(BaseModel):
    """Response model for a single observability log."""
    
    id: str
    analysis_type: str
    symbol: Optional[str] = None
    analysis_period: Optional[str] = None
    prompt: Optional[str] = None
    response: Optional[str] = None
    model_name: Optional[str] = None
    model_provider: Optional[str] = None
    token_count: Optional[int] = None
    latency_ms: Optional[int] = None
    cost_estimate: Optional[float] = None
    summary: Optional[str] = None
    key_findings: Optional[List[str]] = None
    sentiment: Optional[str] = None
    risk_factors: Optional[List[str]] = None
    recommendations: Optional[List[str]] = None
    confidence_score: Optional[float] = None
    triggered_by: Optional[str] = None
    worker_id: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    context_data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True


class ObservabilityLogListResponse(BaseModel):
    """Response model for paginated list of observability logs."""
    
    logs: List[ObservabilityLogResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class ObservabilityStatsResponse(BaseModel):
    """Response model for observability statistics."""
    
    total_analyses: int
    completed: int
    failed: int
    avg_latency_ms: Optional[float] = None
    sentiment_breakdown: Dict[str, int]
    symbols_analyzed: int
    recent_activity_count: int
