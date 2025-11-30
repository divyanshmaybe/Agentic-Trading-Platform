"""Routes for Live Alpha management."""

from __future__ import annotations

import os
import sys
from typing import List, Optional
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from prisma import Prisma, Json
from pydantic import BaseModel, Field

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
MIDDLEWARE_PATH = os.path.join(PROJECT_ROOT, "middleware/py")
if MIDDLEWARE_PATH not in sys.path:
    sys.path.insert(0, MIDDLEWARE_PATH)

from db import prisma_client
from utils.auth import get_authenticated_user

router = APIRouter(prefix="/alphas", tags=["Alphas"])


# ============================================================================
# Request/Response Schemas
# ============================================================================

class CreateLiveAlphaRequest(BaseModel):
    """Request to create a live alpha from an AlphaCopilot run."""
    name: str = Field(..., description="Name for the live alpha")
    run_id: Optional[str] = Field(None, description="AlphaCopilot run ID to deploy")
    hypothesis: Optional[str] = Field(None, description="Hypothesis (if not from run)")
    workflow_config: dict = Field(..., description="Complete workflow configuration")
    symbols: List[str] = Field(..., description="Symbols to trade")
    allocated_amount: float = Field(..., gt=0, description="Capital to allocate")
    portfolio_id: str = Field(..., description="Portfolio to attach to")
    model_type: Optional[str] = Field(None, description="Model type (LightGBM, etc.)")
    strategy_type: str = Field("TopkDropout", description="Strategy type")


class UpdateLiveAlphaRequest(BaseModel):
    """Request to update a live alpha."""
    name: Optional[str] = None
    allocated_amount: Optional[float] = None
    status: Optional[str] = None
    workflow_config: Optional[dict] = None
    symbols: Optional[List[str]] = None


class LiveAlphaResponse(BaseModel):
    """Response for a live alpha."""
    id: str
    name: str
    hypothesis: Optional[str]
    run_id: Optional[str]
    workflow_config: dict
    symbols: List[str]
    model_type: Optional[str]
    strategy_type: str
    status: str
    allocated_amount: float
    portfolio_id: str
    agent_id: Optional[str]
    last_signal_at: Optional[str]
    total_signals: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class LiveAlphaListResponse(BaseModel):
    """Response for list of live alphas."""
    alphas: List[LiveAlphaResponse]
    total: int


class AllocateCapitalRequest(BaseModel):
    """Request to allocate capital to multiple alphas."""
    allocations: List[dict] = Field(..., description="List of {alpha_id, amount}")
    portfolio_id: str


class AlphaSignalResponse(BaseModel):
    """Response for alpha signal."""
    alpha_id: str
    alpha_name: str
    signal_type: str
    symbol: str
    quantity: int
    confidence: float
    generated_at: str


# ============================================================================
# Helper Functions
# ============================================================================

def _alpha_to_response(alpha) -> LiveAlphaResponse:
    """Convert Prisma LiveAlpha to response model."""
    return LiveAlphaResponse(
        id=alpha.id,
        name=alpha.name,
        hypothesis=alpha.hypothesis,
        run_id=alpha.run_id,
        workflow_config=alpha.workflow_config if isinstance(alpha.workflow_config, dict) else {},
        symbols=alpha.symbols if alpha.symbols else [],
        model_type=alpha.model_type,
        strategy_type=alpha.strategy_type,
        status=alpha.status,
        allocated_amount=float(alpha.allocated_amount),
        portfolio_id=alpha.portfolio_id,
        agent_id=alpha.agent_id,
        last_signal_at=alpha.last_signal_at.isoformat() if alpha.last_signal_at else None,
        total_signals=alpha.total_signals,
        created_at=alpha.created_at.isoformat(),
        updated_at=alpha.updated_at.isoformat(),
    )


# ============================================================================
# Routes
# ============================================================================

@router.post("/live", response_model=LiveAlphaResponse, status_code=201)
async def create_live_alpha(
    payload: CreateLiveAlphaRequest,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Create a new live alpha from workflow configuration.
    
    This endpoint deploys an alpha strategy for live trading.
    The workflow_config should contain the complete quant-stream WorkflowConfig
    including features, model, and strategy configuration.
    """
    # Verify portfolio exists and belongs to user (using customer_id like portfolio_controller)
    portfolio = await prisma.portfolio.find_unique(where={"id": payload.portfolio_id})
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    
    # Check authorization using customer_id (consistent with portfolio_controller)
    user_customer_id = user.get("customer_id") or user.get("id")
    if portfolio.customer_id != user_customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this portfolio")
    
    # Check available cash
    if float(portfolio.available_cash) < payload.allocated_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient available cash. Available: {portfolio.available_cash}, Requested: {payload.allocated_amount}"
        )
    
    # If run_id provided, fetch hypothesis from run
    hypothesis = payload.hypothesis
    if payload.run_id:
        run = await prisma.alphacopilotrun.find_unique(where={"id": payload.run_id})
        if run:
            hypothesis = run.hypothesis
    
    # Create live alpha
    alpha = await prisma.livealpha.create(
        data={
            "name": payload.name,
            "hypothesis": hypothesis,
            "run_id": payload.run_id,
            "workflow_config": Json(payload.workflow_config) if payload.workflow_config else Json({}),
            "symbols": payload.symbols,
            "model_type": payload.model_type,
            "strategy_type": payload.strategy_type,
            "status": "stopped",
            "allocated_amount": Decimal(str(payload.allocated_amount)),
            "portfolio_id": payload.portfolio_id,
        }
    )
    
    return _alpha_to_response(alpha)


@router.get("/live", response_model=LiveAlphaListResponse)
async def list_live_alphas(
    portfolio_id: Optional[str] = Query(None, description="Filter by portfolio"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """List live alphas for the user."""
    # Build where clause
    where_clause = {}
    
    if portfolio_id:
        # Verify portfolio belongs to user
        portfolio = await prisma.portfolio.find_unique(where={"id": portfolio_id})
        if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
            raise HTTPException(status_code=403, detail="Not authorized")
        where_clause["portfolio_id"] = portfolio_id
    else:
        # Get all portfolios for user (using customer_id like portfolio_controller)
        user_customer_id = user.get("customer_id") or user.get("id")
        portfolios = await prisma.portfolio.find_many(
            where={"customer_id": user_customer_id}
        )
        portfolio_ids = [p.id for p in portfolios]
        where_clause["portfolio_id"] = {"in": portfolio_ids}
    
    if status:
        where_clause["status"] = status
    
    # Query
    total = await prisma.livealpha.count(where=where_clause)
    alphas = await prisma.livealpha.find_many(
        where=where_clause,
        order={"created_at": "desc"},
        skip=offset,
        take=limit,
    )
    
    return LiveAlphaListResponse(
        alphas=[_alpha_to_response(a) for a in alphas],
        total=total,
    )


@router.get("/live/{alpha_id}", response_model=LiveAlphaResponse)
async def get_live_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Get a specific live alpha."""
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    # Verify access
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return _alpha_to_response(alpha)


@router.patch("/live/{alpha_id}", response_model=LiveAlphaResponse)
async def update_live_alpha(
    alpha_id: str,
    payload: UpdateLiveAlphaRequest,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Update a live alpha."""
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    # Verify access
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Build update data
    update_data = {}
    if payload.name is not None:
        update_data["name"] = payload.name
    if payload.allocated_amount is not None:
        update_data["allocated_amount"] = Decimal(str(payload.allocated_amount))
    if payload.status is not None:
        if payload.status not in ["running", "stopped", "error"]:
            raise HTTPException(status_code=400, detail="Invalid status")
        update_data["status"] = payload.status
    if payload.workflow_config is not None:
        update_data["workflow_config"] = Json(payload.workflow_config)
    if payload.symbols is not None:
        update_data["symbols"] = payload.symbols
    
    if not update_data:
        return _alpha_to_response(alpha)
    
    updated = await prisma.livealpha.update(
        where={"id": alpha_id},
        data=update_data,
    )
    
    return _alpha_to_response(updated)


@router.delete("/live/{alpha_id}", status_code=204)
async def delete_live_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Delete a live alpha."""
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    # Verify access
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Cannot delete running alpha
    if alpha.status == "running":
        raise HTTPException(status_code=400, detail="Cannot delete running alpha. Stop it first.")
    
    await prisma.livealpha.delete(where={"id": alpha_id})
    return None


@router.post("/live/{alpha_id}/start", response_model=LiveAlphaResponse)
async def start_live_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Start a live alpha for trading."""
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    # Verify access
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if alpha.status == "running":
        raise HTTPException(status_code=400, detail="Alpha is already running")
    
    # Update status
    updated = await prisma.livealpha.update(
        where={"id": alpha_id},
        data={"status": "running"},
    )
    
    return _alpha_to_response(updated)


@router.post("/live/{alpha_id}/stop", response_model=LiveAlphaResponse)
async def stop_live_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Stop a live alpha."""
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    # Verify access
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if alpha.status != "running":
        raise HTTPException(status_code=400, detail="Alpha is not running")
    
    # Update status
    updated = await prisma.livealpha.update(
        where={"id": alpha_id},
        data={"status": "stopped"},
    )
    
    return _alpha_to_response(updated)


@router.post("/allocate", response_model=LiveAlphaListResponse)
async def allocate_capital_to_alphas(
    payload: AllocateCapitalRequest,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Allocate capital to multiple alphas at once."""
    # Verify portfolio
    portfolio = await prisma.portfolio.find_unique(where={"id": payload.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Calculate total allocation
    total_allocation = sum(alloc.get("amount", 0) for alloc in payload.allocations)
    
    if float(portfolio.available_cash) < total_allocation:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient cash. Available: {portfolio.available_cash}, Requested: {total_allocation}"
        )
    
    # Update each alpha
    updated_alphas = []
    for alloc in payload.allocations:
        alpha_id = alloc.get("alpha_id")
        amount = alloc.get("amount", 0)
        
        if not alpha_id or amount <= 0:
            continue
        
        alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
        if not alpha or alpha.portfolio_id != payload.portfolio_id:
            continue
        
        updated = await prisma.livealpha.update(
            where={"id": alpha_id},
            data={"allocated_amount": Decimal(str(amount))},
        )
        updated_alphas.append(updated)
    
    return LiveAlphaListResponse(
        alphas=[_alpha_to_response(a) for a in updated_alphas],
        total=len(updated_alphas),
    )


@router.get("/live/{alpha_id}/signals", response_model=List[AlphaSignalResponse])
async def get_alpha_signals(
    alpha_id: str,
    limit: int = Query(50, ge=1, le=500),
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Get recent signals generated by a live alpha."""
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    # Verify access
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # For now, return empty list - signals will be stored in a separate table
    # or fetched from the alpha_agent trades
    return []



