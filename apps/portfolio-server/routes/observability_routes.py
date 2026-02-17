"""
NSE Observability Logs Routes

REST API endpoints for accessing NSE observability analysis logs.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from prisma import Prisma

from db import prisma_client
from utils.auth import get_authenticated_user
from controllers.observability_controller import ObservabilityController
from schemas.observability_schemas import (
    ObservabilityLogResponse,
    ObservabilityLogListResponse,
    ObservabilityStatsResponse,
)

router = APIRouter(prefix="/observability", tags=["observability"])


def get_controller(prisma: Prisma = Depends(prisma_client)) -> ObservabilityController:
    """Dependency to get observability controller."""
    return ObservabilityController(prisma)


@router.get("/logs", response_model=ObservabilityLogListResponse)
async def list_observability_logs(
    # Pagination
    limit: int = Query(20, ge=1, le=100, description="Number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    # Filters
    analysis_type: Optional[str] = Query(None, description="Filter by analysis type"),
    symbol: Optional[str] = Query(None, description="Filter by stock symbol"),
    status: Optional[str] = Query(None, description="Filter by status (completed, failed, pending)"),
    sentiment: Optional[str] = Query(None, description="Filter by sentiment"),
    triggered_by: Optional[str] = Query(None, description="Filter by trigger type"),
    model_name: Optional[str] = Query(None, description="Filter by LLM model name"),
    # Date filters
    start_date: Optional[datetime] = Query(None, description="Filter logs after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter logs before this date"),
    # Sorting
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort order: 'asc' or 'desc'"),
    # Dependencies
    controller: ObservabilityController = Depends(get_controller),
    _: dict = Depends(get_authenticated_user),
) -> ObservabilityLogListResponse:
    """List NSE observability analysis logs with filtering and pagination."""
    return await controller.list_logs(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        analysis_type=analysis_type,
        symbol=symbol,
        status=status,
        sentiment=sentiment,
        triggered_by=triggered_by,
        model_name=model_name,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/logs/{log_id}", response_model=ObservabilityLogResponse)
async def get_observability_log(
    log_id: str,
    controller: ObservabilityController = Depends(get_controller),
    _: dict = Depends(get_authenticated_user),
) -> ObservabilityLogResponse:
    """Get a specific observability analysis log by ID."""
    result = await controller.get_log(log_id)
    if not result:
        raise HTTPException(status_code=404, detail="Observability log not found")
    return result


@router.get("/stats", response_model=ObservabilityStatsResponse)
async def get_observability_stats(
    days: int = Query(7, ge=1, le=90, description="Number of days for stats"),
    controller: ObservabilityController = Depends(get_controller),
    _: dict = Depends(get_authenticated_user),
) -> ObservabilityStatsResponse:
    """Get aggregate statistics for observability logs."""
    return await controller.get_stats(days)


@router.get("/symbols", response_model=List[str])
async def list_analyzed_symbols(
    controller: ObservabilityController = Depends(get_controller),
    _: dict = Depends(get_authenticated_user),
) -> List[str]:
    """Get list of unique symbols that have been analyzed."""
    return await controller.list_symbols()


@router.get("/triggers", response_model=List[str])
async def list_trigger_types(
    controller: ObservabilityController = Depends(get_controller),
    _: dict = Depends(get_authenticated_user),
) -> List[str]:
    """Get list of unique trigger types."""
    return await controller.list_triggers()
