"""Routes for Live Alpha management."""

from __future__ import annotations

import os
import sys
import uuid
from typing import List, Optional
from decimal import Decimal
from datetime import datetime, timedelta, timezone

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
    id: str
    live_alpha_id: str
    batch_id: str
    symbol: str
    signal_type: str
    quantity: int
    predicted_return: float
    confidence: float
    price: float
    allocated_amount: float
    rank: Optional[int] = None
    status: str
    generated_at: str
    executed_at: Optional[str] = None
    expires_at: Optional[str] = None
    trade_id: Optional[str] = None


class SignalBatch(BaseModel):
    """A batch of signals generated together."""
    batch_id: str
    generated_at: str
    signals_count: int
    pending_count: int
    executed_count: int
    expired_count: int
    signals: List[AlphaSignalResponse]


class SignalsHistoryResponse(BaseModel):
    """Response for signal history with batches."""
    batches: List[SignalBatch]
    total_batches: int
    total_signals: int


class ExecuteSignalRequest(BaseModel):
    """Request to execute a signal."""
    portfolio_id: Optional[str] = None  # Optional, will use alpha's portfolio if not provided


class ExecuteSignalResponse(BaseModel):
    """Response after executing a signal."""
    success: bool
    signal_id: str
    trade_id: Optional[str] = None
    message: str


class ExecuteAllSignalsRequest(BaseModel):
    """Request to execute all pending signals from a batch."""
    batch_id: str
    portfolio_id: Optional[str] = None


class TriggerSignalGenerationRequest(BaseModel):
    """Request to trigger signal generation for an alpha."""
    alpha_id: Optional[str] = Field(None, description="Specific alpha ID (optional, if not provided generates for all running)")


class SignalGenerationTaskResponse(BaseModel):
    """Response after triggering signal generation task."""
    task_id: str
    status: str
    alpha_id: Optional[str] = None
    message: str


class TaskStatusResponse(BaseModel):
    """Response for checking task status."""
    task_id: str
    status: str  # PENDING, STARTED, PROGRESS, SUCCESS, FAILURE, RETRY, REVOKED
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    # Progress info (when status is PROGRESS)
    step: Optional[str] = None  # loading_data, computing_factors, loading_model, running_model, generating_signals, saving_signals
    progress: Optional[int] = None  # 0-100
    message: Optional[str] = None  # Human-readable progress message


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


@router.get("/live/{alpha_id}/signals", response_model=SignalsHistoryResponse)
async def get_alpha_signals(
    alpha_id: str,
    status: Optional[str] = Query(None, description="Filter by status: pending, executed, expired, cancelled"),
    limit: int = Query(10, ge=1, le=50, description="Number of batches to return"),
    offset: int = Query(0, ge=0),
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Get signal history for a live alpha, grouped by batch.
    
    Returns batches of signals ordered by generation date (most recent first).
    Each batch represents signals generated together in a single run.
    """
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    # Verify access
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Build where clause for signals
    where_clause: dict = {"live_alpha_id": alpha_id}
    if status:
        where_clause["status"] = status
    
    # Get all signals for this alpha
    signals = await prisma.alphasignal.find_many(
        where=where_clause,
        order={"generated_at": "desc"},
    )
    
    # Group signals by batch_id
    batches_map: dict = {}
    for sig in signals:
        batch_id = sig.batch_id
        if batch_id not in batches_map:
            batches_map[batch_id] = {
                "batch_id": batch_id,
                "generated_at": sig.generated_at,
                "signals": [],
                "pending_count": 0,
                "executed_count": 0,
                "expired_count": 0,
            }
        
        batches_map[batch_id]["signals"].append(sig)
        if sig.status == "pending":
            batches_map[batch_id]["pending_count"] += 1
        elif sig.status == "executed":
            batches_map[batch_id]["executed_count"] += 1
        elif sig.status == "expired":
            batches_map[batch_id]["expired_count"] += 1
    
    # Sort batches by generated_at (most recent first)
    sorted_batches = sorted(
        batches_map.values(),
        key=lambda x: x["generated_at"],
        reverse=True
    )
    
    # Apply pagination to batches
    total_batches = len(sorted_batches)
    paginated_batches = sorted_batches[offset:offset + limit]
    
    # Build response
    batch_responses = []
    total_signals = 0
    for batch_data in paginated_batches:
        signals_list = [
            AlphaSignalResponse(
                id=s.id,
                live_alpha_id=s.live_alpha_id,
                batch_id=s.batch_id,
                symbol=s.symbol,
                signal_type=s.signal_type,
                quantity=s.quantity,
                predicted_return=s.predicted_return,
                confidence=s.confidence,
                price=s.price,
                allocated_amount=s.allocated_amount,
                rank=s.rank,
                status=s.status,
                generated_at=s.generated_at.isoformat() if hasattr(s.generated_at, "isoformat") else str(s.generated_at),
                executed_at=s.executed_at.isoformat() if s.executed_at and hasattr(s.executed_at, "isoformat") else None,
                expires_at=s.expires_at.isoformat() if s.expires_at and hasattr(s.expires_at, "isoformat") else None,
                trade_id=s.trade_id,
            )
            for s in batch_data["signals"]
        ]
        total_signals += len(signals_list)
        
        batch_responses.append(SignalBatch(
            batch_id=batch_data["batch_id"],
            generated_at=batch_data["generated_at"].isoformat() if hasattr(batch_data["generated_at"], "isoformat") else str(batch_data["generated_at"]),
            signals_count=len(signals_list),
            pending_count=batch_data["pending_count"],
            executed_count=batch_data["executed_count"],
            expired_count=batch_data["expired_count"],
            signals=signals_list,
        ))
    
    return SignalsHistoryResponse(
        batches=batch_responses,
        total_batches=total_batches,
        total_signals=total_signals,
    )


async def get_or_create_alpha_agent(
    prisma: Prisma,
    portfolio_id: str,
    alpha_name: str,
    logger,
) -> tuple[str, str]:
    """Get or create an alpha-type trading agent for executing alpha signals.
    
    Returns (agent_id, allocation_id) tuple.
    """
    # First, try to find an existing alpha agent for this portfolio
    existing_agent = await prisma.tradingagent.find_first(
        where={
            "portfolio_id": portfolio_id,
            "agent_type": "alpha",
            "status": "active",
        },
        include={"allocation": True},
    )
    
    if existing_agent:
        logger.info(f"Found existing alpha agent: {existing_agent.id}")
        return existing_agent.id, existing_agent.portfolio_allocation_id
    
    # No existing alpha agent, create one with a new allocation
    logger.info(f"Creating new alpha agent for portfolio {portfolio_id}")
    
    # Get the portfolio to find its organization
    portfolio = await prisma.portfolio.find_unique(where={"id": portfolio_id})
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")
    
    # Create allocation for the alpha agent (start with 0, will be funded separately)
    allocation = await prisma.portfolioallocation.create(
        data={
            "portfolio_id": portfolio_id,
            "allocation_type": "alpha",
            "target_percentage": 0,  # Will be adjusted based on usage
            "allocated_cash": 0,
            "available_cash": 0,
            "invested_value": 0,
            "metadata": {"created_for": f"alpha_signals:{alpha_name}"},
        }
    )
    
    # Create the alpha agent
    agent = await prisma.tradingagent.create(
        data={
            "portfolio_id": portfolio_id,
            "portfolio_allocation_id": allocation.id,
            "agent_type": "alpha",
            "agent_name": f"Alpha Signal Executor",
            "status": "active",
            "strategy_config": {"source": "alpha_signals"},
            "metadata": {"created_for": alpha_name},
        }
    )
    
    logger.info(f"Created new alpha agent: {agent.id} with allocation: {allocation.id}")
    return agent.id, allocation.id


@router.post("/live/{alpha_id}/signals/{signal_id}/execute", response_model=ExecuteSignalResponse)
async def execute_signal(
    alpha_id: str,
    signal_id: str,
    payload: ExecuteSignalRequest,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Execute a single pending signal as a trade.
    
    Submits the signal as a market order to the trade execution system.
    The signal status will be updated to 'executed' upon successful submission.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get alpha and verify access
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    portfolio_id = payload.portfolio_id or alpha.portfolio_id
    portfolio = await prisma.portfolio.find_unique(where={"id": portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get the signal
    signal = await prisma.alphasignal.find_unique(where={"id": signal_id})
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    if signal.live_alpha_id != alpha_id:
        raise HTTPException(status_code=400, detail="Signal does not belong to this alpha")
    
    if signal.status != "pending":
        raise HTTPException(status_code=400, detail=f"Signal is not pending (status: {signal.status})")
    
    # Check if signal has expired
    if signal.expires_at and datetime.now(timezone.utc) > signal.expires_at:
        await prisma.alphasignal.update(
            where={"id": signal_id},
            data={"status": "expired"}
        )
        raise HTTPException(status_code=400, detail="Signal has expired")
    
    # For SELL signals, verify we have an existing position first
    if signal.signal_type.upper() == "SELL":
        existing_position = await prisma.position.find_first(
            where={
                "portfolio_id": portfolio_id,
                "symbol": signal.symbol,
                "status": "open",
            }
        )
        if not existing_position or existing_position.quantity < signal.quantity:
            # Skip SELL signal - no position to sell
            await prisma.alphasignal.update(
                where={"id": signal_id},
                data={"status": "skipped"}
            )
            return ExecuteSignalResponse(
                success=False,
                signal_id=signal_id,
                trade_id=None,
                message=f"Skipped SELL signal: no open position for {signal.symbol}"
            )
    
    try:
        # Execute trade via TradeExecutionService
        from services.trade_execution_service import TradeExecutionService
        
        trade_service = TradeExecutionService(logger=logger)
        
        # Get or create an alpha agent for this portfolio (required for position creation)
        agent_id = alpha.agent_id
        if not agent_id:
            agent_id, allocation_id = await get_or_create_alpha_agent(
                prisma, portfolio_id, alpha.name, logger
            )
            # Update the alpha to link to this agent for future use
            await prisma.livealpha.update(
                where={"id": alpha_id},
                data={"agent_id": agent_id}
            )
            logger.info(f"Linked alpha {alpha_id} to agent {agent_id}")
        
        # Build job_row for trade execution
        job_row = {
            "request_id": str(uuid.uuid4()),
            "user_id": user.get("id") or user.get("customer_id"),
            "organization_id": portfolio.organization_id,
            "portfolio_id": portfolio_id,
            "customer_id": portfolio.customer_id,
            "symbol": signal.symbol,
            "side": signal.signal_type.upper(),  # "BUY" or "SELL"
            "quantity": signal.quantity,
            "reference_price": signal.price,
            "exchange": "NSE",
            "segment": "EQUITY",
            "agent_id": agent_id,
            "agent_type": "alpha",
            "allocation_id": None,  # Will be resolved from agent
            "triggered_by": f"alpha_signal:{alpha.name}",
            "confidence": signal.confidence,
            "allocated_capital": signal.allocated_amount,
            "take_profit_pct": 0.03,
            "stop_loss_pct": 0.01,
            "explanation": f"Alpha signal: {alpha.name} - {signal.signal_type} {signal.symbol}",
            "filing_time": "",
            "generated_at": signal.generated_at.isoformat() if hasattr(signal.generated_at, "isoformat") else "",
        }
        
        # Persist and execute trade
        events = await trade_service.persist_and_publish([job_row], publish_kafka=False)
        
        if not events or len(events) == 0:
            raise RuntimeError("Failed to create trade execution log")
        
        trade_id = events[0].trade_id
        
        # Execute trade in simulation mode
        result = await trade_service.execute_trade(trade_id, simulate=True)
        
        # Update signal status
        await prisma.alphasignal.update(
            where={"id": signal_id},
            data={
                "status": "executed",
                "executed_at": datetime.now(timezone.utc),
                "trade_id": trade_id,
            }
        )
        
        logger.info(f"✅ Signal {signal_id} executed as trade {trade_id}")
        
        return ExecuteSignalResponse(
            success=True,
            signal_id=signal_id,
            trade_id=trade_id,
            message=f"Signal executed successfully. Trade ID: {trade_id}"
        )
        
    except Exception as e:
        logger.exception(f"Failed to execute signal {signal_id}: {e}")
        return ExecuteSignalResponse(
            success=False,
            signal_id=signal_id,
            trade_id=None,
            message=f"Failed to execute signal: {str(e)}"
        )


@router.post("/live/{alpha_id}/signals/execute-all", response_model=List[ExecuteSignalResponse])
async def execute_all_signals(
    alpha_id: str,
    payload: ExecuteAllSignalsRequest,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Execute all pending signals from a specific batch.
    
    This is a bulk operation that submits all pending signals from the given batch.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Get alpha and verify access
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    portfolio_id = payload.portfolio_id or alpha.portfolio_id
    portfolio = await prisma.portfolio.find_unique(where={"id": portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Get or create an alpha agent for this portfolio (required for position creation)
    agent_id = alpha.agent_id
    if not agent_id:
        agent_id, allocation_id = await get_or_create_alpha_agent(
            prisma, portfolio_id, alpha.name, logger
        )
        # Update the alpha to link to this agent for future use
        await prisma.livealpha.update(
            where={"id": alpha_id},
            data={"agent_id": agent_id}
        )
        logger.info(f"Linked alpha {alpha_id} to agent {agent_id}")
    
    # Get all pending signals for the batch
    signals = await prisma.alphasignal.find_many(
        where={
            "live_alpha_id": alpha_id,
            "batch_id": payload.batch_id,
            "status": "pending",
        },
        order={"rank": "asc"},
    )
    
    if not signals:
        return []
    
    results = []
    
    try:
        from services.trade_execution_service import TradeExecutionService
        trade_service = TradeExecutionService(logger=logger)
        
        for signal in signals:
            # Check expiration
            if signal.expires_at and datetime.now(timezone.utc) > signal.expires_at:
                await prisma.alphasignal.update(
                    where={"id": signal.id},
                    data={"status": "expired"}
                )
                results.append(ExecuteSignalResponse(
                    success=False,
                    signal_id=signal.id,
                    trade_id=None,
                    message="Signal has expired"
                ))
                continue
            
            # For SELL signals, verify we have an existing position first
            if signal.signal_type.upper() == "SELL":
                existing_position = await prisma.position.find_first(
                    where={
                        "portfolio_id": portfolio_id,
                        "symbol": signal.symbol,
                        "status": "open",
                    }
                )
                if not existing_position or existing_position.quantity < signal.quantity:
                    # Skip SELL signal - no position to sell
                    await prisma.alphasignal.update(
                        where={"id": signal.id},
                        data={"status": "skipped"}
                    )
                    results.append(ExecuteSignalResponse(
                        success=False,
                        signal_id=signal.id,
                        trade_id=None,
                        message=f"Skipped SELL signal: no open position for {signal.symbol}"
                    ))
                    continue
            
            try:
                job_row = {
                    "request_id": str(uuid.uuid4()),
                    "user_id": user.get("id") or user.get("customer_id"),
                    "organization_id": portfolio.organization_id,
                    "portfolio_id": portfolio_id,
                    "customer_id": portfolio.customer_id,
                    "symbol": signal.symbol,
                    "side": signal.signal_type.upper(),
                    "quantity": signal.quantity,
                    "reference_price": signal.price,
                    "exchange": "NSE",
                    "segment": "EQUITY",
                    "agent_id": agent_id,  # Use the resolved agent_id
                    "agent_type": "alpha",
                    "allocation_id": None,
                    "triggered_by": f"alpha_signal:{alpha.name}",
                    "confidence": signal.confidence,
                    "allocated_capital": signal.allocated_amount,
                    "take_profit_pct": 0.03,
                    "stop_loss_pct": 0.01,
                    "explanation": f"Alpha signal: {alpha.name} - {signal.signal_type} {signal.symbol}",
                    "filing_time": "",
                    "generated_at": signal.generated_at.isoformat() if hasattr(signal.generated_at, "isoformat") else "",
                }
                
                events = await trade_service.persist_and_publish([job_row], publish_kafka=False)
                
                if not events or len(events) == 0:
                    raise RuntimeError("Failed to create trade")
                
                trade_id = events[0].trade_id
                await trade_service.execute_trade(trade_id, simulate=True)
                
                await prisma.alphasignal.update(
                    where={"id": signal.id},
                    data={
                        "status": "executed",
                        "executed_at": datetime.now(timezone.utc),
                        "trade_id": trade_id,
                    }
                )
                
                results.append(ExecuteSignalResponse(
                    success=True,
                    signal_id=signal.id,
                    trade_id=trade_id,
                    message="Executed successfully"
                ))
                
            except Exception as e:
                logger.warning(f"Failed to execute signal {signal.id}: {e}")
                results.append(ExecuteSignalResponse(
                    success=False,
                    signal_id=signal.id,
                    trade_id=None,
                    message=str(e)
                ))
    
    except Exception as e:
        logger.exception(f"Bulk execute failed: {e}")
        # Return partial results
        for signal in signals:
            if not any(r.signal_id == signal.id for r in results):
                results.append(ExecuteSignalResponse(
                    success=False,
                    signal_id=signal.id,
                    trade_id=None,
                    message=f"Bulk execution error: {str(e)}"
                ))
    
    return results


@router.post("/live/{alpha_id}/signals/{signal_id}/cancel", response_model=AlphaSignalResponse)
async def cancel_signal(
    alpha_id: str,
    signal_id: str,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Cancel a pending signal."""
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    signal = await prisma.alphasignal.find_unique(where={"id": signal_id})
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    if signal.live_alpha_id != alpha_id:
        raise HTTPException(status_code=400, detail="Signal does not belong to this alpha")
    
    if signal.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot cancel signal with status: {signal.status}")
    
    updated = await prisma.alphasignal.update(
        where={"id": signal_id},
        data={"status": "cancelled"}
    )
    
    return AlphaSignalResponse(
        id=updated.id,
        live_alpha_id=updated.live_alpha_id,
        batch_id=updated.batch_id,
        symbol=updated.symbol,
        signal_type=updated.signal_type,
        quantity=updated.quantity,
        predicted_return=updated.predicted_return,
        confidence=updated.confidence,
        price=updated.price,
        allocated_amount=updated.allocated_amount,
        rank=updated.rank,
        status=updated.status,
        generated_at=updated.generated_at.isoformat() if hasattr(updated.generated_at, "isoformat") else str(updated.generated_at),
        executed_at=updated.executed_at.isoformat() if updated.executed_at and hasattr(updated.executed_at, "isoformat") else None,
        expires_at=updated.expires_at.isoformat() if updated.expires_at and hasattr(updated.expires_at, "isoformat") else None,
        trade_id=updated.trade_id,
    )


# ============================================================================
# Live Alpha Workflow Endpoints
# ============================================================================

class MarketDataUpdateResponse(BaseModel):
    """Response for market data update."""
    success: bool
    symbols_count: int
    rows_added: int
    last_date: Optional[str] = None
    message: str


class FactorResult(BaseModel):
    """Factor values for a symbol."""
    symbol: str
    factor_values: dict
    timestamp: str


class FactorsResponse(BaseModel):
    """Response for computed factors."""
    success: bool
    factors: List[FactorResult]
    symbols_count: int
    factors_count: int


class PredictedReturn(BaseModel):
    """Predicted return for a symbol."""
    symbol: str
    predicted_return: float
    confidence: float
    rank: int


class PredictionsResponse(BaseModel):
    """Response for model predictions."""
    success: bool
    predictions: List[PredictedReturn]
    model_type: str


class Signal(BaseModel):
    """Trading signal."""
    symbol: str
    signal_type: str  # buy, sell, hold
    quantity: int
    predicted_return: float
    confidence: float
    price: float
    allocated_amount: float
    rank: int


class SignalsResponse(BaseModel):
    """Response for generated signals."""
    success: bool
    signals: List[Signal]
    strategy_type: str
    topk: int
    batch_id: Optional[str] = None  # UUID of the signal batch for tracking


class MarketDataStatusResponse(BaseModel):
    """Response for market data status check."""
    last_date: Optional[str]
    rows_count: int
    symbols_count: int
    is_up_to_date: bool
    message: str


@router.get("/market-data-status", response_model=MarketDataStatusResponse)
async def get_market_data_status():
    """Check the current status of market data without updating.
    
    Returns the last date in the CSV, total rows, and whether data is up to date.
    """
    from pathlib import Path
    from datetime import datetime, timedelta
    import pandas as pd
    
    quant_stream_path = Path(PROJECT_ROOT) / "quant-stream"
    csv_path = quant_stream_path / ".data" / "indian_stock_market_nifty500.csv"
    
    if not csv_path.exists():
        return MarketDataStatusResponse(
            last_date=None,
            rows_count=0,
            symbols_count=0,
            is_up_to_date=False,
            message="Market data file not found"
        )
    
    try:
        # Read only date and symbol columns for speed
        df = pd.read_csv(csv_path, usecols=['date', 'symbol'])
        
        if df.empty:
            return MarketDataStatusResponse(
                last_date=None,
                rows_count=0,
                symbols_count=0,
                is_up_to_date=False,
                message="Market data file is empty"
            )
        
        # Get stats
        df['date'] = pd.to_datetime(df['date'])
        last_date = df['date'].max()
        rows_count = len(df)
        symbols_count = df['symbol'].nunique()
        
        # Check if up to date (last date is today or yesterday for weekdays)
        today = datetime.now().date()
        last_date_date = last_date.date()
        
        # Account for weekends and market hours
        is_up_to_date = False
        if today.weekday() == 0:  # Monday
            is_up_to_date = last_date_date >= (today - timedelta(days=3))  # Friday
        elif today.weekday() == 6:  # Sunday  
            is_up_to_date = last_date_date >= (today - timedelta(days=2))  # Friday
        elif today.weekday() == 5:  # Saturday
            is_up_to_date = last_date_date >= (today - timedelta(days=1))  # Friday
        else:
            is_up_to_date = last_date_date >= (today - timedelta(days=1))
        
        return MarketDataStatusResponse(
            last_date=last_date.strftime("%Y-%m-%d"),
            rows_count=rows_count,
            symbols_count=symbols_count,
            is_up_to_date=is_up_to_date,
            message="Data is up to date" if is_up_to_date else f"Data last updated: {last_date.strftime('%Y-%m-%d')}"
        )
        
    except Exception as e:
        return MarketDataStatusResponse(
            last_date=None,
            rows_count=0,
            symbols_count=0,
            is_up_to_date=False,
            message=f"Error reading market data: {str(e)}"
        )


@router.post("/update-market-data", response_model=MarketDataUpdateResponse)
async def update_market_data():
    """Update market data by running the update_indian_market_data.py script.
    
    This fetches the latest OHLCV data for Nifty 500 stocks from Groww API.
    """
    import asyncio
    from pathlib import Path
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Path to the update script
    quant_stream_path = Path(PROJECT_ROOT) / "quant-stream"
    script_path = quant_stream_path / "update_indian_market_data.py"
    
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="Market data update script not found")
    
    logger.info(f"Starting market data update from {script_path}")
    
    try:
        # Run the update script asynchronously
        process = await asyncio.create_subprocess_exec(
            "python", str(script_path),
            cwd=str(quant_stream_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        logger.info(f"Market data update process started with PID: {process.pid}")
        
        # Wait for completion with timeout (10 minutes)
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=600.0
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error("Market data update timed out after 10 minutes")
            raise HTTPException(status_code=500, detail="Market data update timed out")
        
        stdout = stdout_bytes.decode('utf-8', errors='replace')
        stderr = stderr_bytes.decode('utf-8', errors='replace')
        
        # Log output
        if stdout:
            logger.info(f"Market data update stdout:\n{stdout[-2000:]}")  # Last 2000 chars
        if stderr:
            logger.warning(f"Market data update stderr:\n{stderr[-1000:]}")
        
        # Parse output for stats
        rows_added = 0
        symbols_count = 500
        
        # Try to extract stats from output
        for line in stdout.split("\n"):
            if "Total new rows added:" in line:
                try:
                    rows_added = int(line.split(":")[-1].strip().replace(",", ""))
                except (ValueError, IndexError):
                    pass
            if "Found" in line and "symbols" in line:
                try:
                    symbols_count = int(line.split("Found")[1].split("symbols")[0].strip())
                except (ValueError, IndexError):
                    pass
        
        if process.returncode != 0:
            error_msg = stderr[:200] if stderr else "Unknown error"
            logger.error(f"Market data update failed: {error_msg}")
            return MarketDataUpdateResponse(
                success=False,
                symbols_count=symbols_count,
                rows_added=0,
                message=f"Update failed: {error_msg}"
            )
        
        logger.info(f"Market data update completed: {symbols_count} symbols, {rows_added} new rows")
        return MarketDataUpdateResponse(
            success=True,
            symbols_count=symbols_count,
            rows_added=rows_added,
            message="Market data updated successfully"
        )
        
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Market data update timed out")
    except Exception as e:
        logger.exception(f"Failed to update market data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update market data: {str(e)}")


@router.post("/live/{alpha_id}/compute-factors", response_model=FactorsResponse)
async def compute_factors_for_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
):
    """Compute factor values for a live alpha using latest market data.
    
    Workflow Step 2: Calculate factor expressions on latest data.
    """
    import json
    from pathlib import Path
    from datetime import datetime, timedelta
    import pandas as pd
    
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    workflow_config = alpha.workflow_config
    if isinstance(workflow_config, str):
        workflow_config = json.loads(workflow_config)
    
    features_config = workflow_config.get("features", [])
    if not features_config:
        raise HTTPException(status_code=400, detail="No factor expressions configured")
    
    try:
        # Import quant-stream for factor computation
        quant_stream_path = Path(PROJECT_ROOT) / "quant-stream"
        if str(quant_stream_path) not in sys.path:
            sys.path.insert(0, str(quant_stream_path))
        
        from quant_stream.backtest.runner import load_market_data, calculate_factors
        
        # Load latest market data - only last 60 days for live signals
        data_path = str(quant_stream_path / ".data" / "indian_stock_market_nifty500.csv")
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        date_ranges = [(start_date, end_date)]
        
        table = load_market_data(data_path=data_path, date_ranges=date_ranges)
        
        # Calculate factors
        _, features_df, _ = calculate_factors(table, features_config)
        
        # Get latest values per symbol
        features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])
        latest_df = features_df.sort_values('timestamp').groupby('symbol').last().reset_index()
        
        # Build response
        factor_names = [f["name"] for f in features_config]
        factors = []
        for _, row in latest_df.iterrows():
            factor_values = {name: float(row.get(name, 0)) for name in factor_names if name in row}
            factors.append(FactorResult(
                symbol=row["symbol"],
                factor_values=factor_values,
                timestamp=row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"])
            ))
        
        return FactorsResponse(
            success=True,
            factors=factors,
            symbols_count=len(factors),
            factors_count=len(factor_names)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compute factors: {str(e)}")


@router.post("/live/{alpha_id}/predict-returns", response_model=PredictionsResponse)
async def predict_returns_for_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
):
    """Predict returns using the frozen trained ML model from backtesting.
    
    Workflow Step 3: Run ML model inference on computed factors to predict next-day returns.
    
    The model is loaded from:
    1. MLflow artifacts (if run_id present in workflow_config.experiment)
    2. Fallback: Use factor signals directly as predictions (no ML model)
    """
    import json
    from pathlib import Path
    from datetime import datetime, timedelta
    import pandas as pd
    import logging
    
    logger = logging.getLogger(__name__)
    
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    workflow_config = alpha.workflow_config
    if isinstance(workflow_config, str):
        workflow_config = json.loads(workflow_config)
    
    model_type = alpha.model_type or workflow_config.get("model", {}).get("type", "LightGBM")
    features_config = workflow_config.get("features", [])
    
    try:
        # Import quant-stream
        quant_stream_path = Path(PROJECT_ROOT) / "quant-stream"
        if str(quant_stream_path) not in sys.path:
            sys.path.insert(0, str(quant_stream_path))
        
        from quant_stream.backtest.runner import load_market_data, calculate_factors
        
        # Load and compute factors - only last 60 days for live signals
        data_path = str(quant_stream_path / ".data" / "indian_stock_market_nifty500.csv")
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        date_ranges = [(start_date, end_date)]
        
        logger.info(f"Loading market data from {start_date} to {end_date}")
        table = load_market_data(data_path=data_path, date_ranges=date_ranges)
        _, features_df, _ = calculate_factors(table, features_config)
        
        # Get latest values per symbol
        features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])
        latest_df = features_df.sort_values('timestamp').groupby('symbol').last().reset_index()
        
        logger.info(f"Got factor values for {len(latest_df)} symbols")
        
        # Get feature columns
        factor_names = [f["name"] for f in features_config]
        available_factors = [f for f in factor_names if f in latest_df.columns]
        
        if not available_factors:
            raise HTTPException(status_code=400, detail="No valid factors found in data")
        
        # Try to load trained model from MLflow
        model = None
        model_loaded_from = "none"
        
        # Check for MLflow run_id in workflow_config
        mlflow_run_id = workflow_config.get("experiment", {}).get("run_id")
        if not mlflow_run_id:
            # Also check for run_name which might contain the run_id
            mlflow_run_id = workflow_config.get("experiment", {}).get("mlflow_run_id")
        
        if mlflow_run_id:
            try:
                from quant_stream.recorder.utils import load_mlflow_run_artifacts
                tracking_uri = f"sqlite:///{quant_stream_path / 'mlruns.db'}"
                logger.info(f"Attempting to load model from MLflow run: {mlflow_run_id}")
                artifacts = load_mlflow_run_artifacts(
                    run_id=mlflow_run_id,
                    artifact_names=["model", "trained_model", "lgb_model", "xgb_model"],
                    tracking_uri=tracking_uri,
                )
                for name in ["model", "trained_model", "lgb_model", "xgb_model"]:
                    if name in artifacts and artifacts[name] is not None:
                        model = artifacts[name]
                        model_loaded_from = f"mlflow:{name}"
                        logger.info(f"Successfully loaded model from MLflow artifact: {name}")
                        break
            except Exception as e:
                logger.warning(f"Failed to load model from MLflow: {e}")
        
        # Prepare features
        X = latest_df[available_factors].fillna(0)
        
        if model is not None and hasattr(model, 'predict'):
            # Use trained frozen model from backtesting
            logger.info(f"Using frozen model ({model_loaded_from}) for predictions")
            predicted_returns = model.predict(X)
        else:
            # Fallback: Use factor signals directly
            # This is a simplified approach - in production you'd want the actual trained model
            logger.warning(f"No trained model available (run_id={mlflow_run_id}). Using factor-based scoring.")
            
            # Use first factor as the signal (consistent with backtest behavior when no model)
            if len(available_factors) == 1:
                # Single factor - use directly
                predicted_returns = X[available_factors[0]].values
            else:
                # Multiple factors - use weighted average based on normalized values
                normalized = (X - X.mean()) / (X.std() + 1e-8)
                predicted_returns = normalized.mean(axis=1).values
            
            # Normalize to reasonable return scale
            pred_std = predicted_returns.std()
            if pred_std > 0:
                predicted_returns = predicted_returns / pred_std * 0.02  # ~2% daily return scale
        
        # Build predictions
        predictions_list = []
        for idx, (_, row) in enumerate(latest_df.iterrows()):
            pred_return = float(predicted_returns[idx])
            # Confidence: 1.0 if model loaded, 0.5 for fallback
            confidence = 1.0 if model is not None else 0.5
            predictions_list.append({
                "symbol": row["symbol"],
                "predicted_return": pred_return,
                "confidence": confidence,
            })
        
        # Sort by predicted return and add rank
        predictions_list.sort(key=lambda x: x["predicted_return"], reverse=True)
        predictions = [
            PredictedReturn(
                symbol=p["symbol"],
                predicted_return=p["predicted_return"],
                confidence=p["confidence"],
                rank=idx + 1
            )
            for idx, p in enumerate(predictions_list)
        ]
        
        logger.info(f"Generated {len(predictions)} predictions using {model_loaded_from if model else 'factor-based scoring'}")
        
        return PredictionsResponse(
            success=True,
            predictions=predictions,
            model_type=model_type if model else f"{model_type} (factor-based fallback)"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to predict returns: {str(e)}")


@router.post("/live/{alpha_id}/generate-signals", response_model=SignalsResponse)
async def generate_signals_for_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
):
    """Generate trading signals using strategy on predicted returns.
    
    Workflow Step 4: Apply TopkDropout strategy to select stocks to buy/sell.
    """
    import json
    from pathlib import Path
    from datetime import datetime, timedelta
    import pandas as pd
    
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    workflow_config = alpha.workflow_config
    if isinstance(workflow_config, str):
        workflow_config = json.loads(workflow_config)
    
    strategy_config = workflow_config.get("strategy", {})
    strategy_type = alpha.strategy_type or strategy_config.get("type", "TopkDropout")
    params = strategy_config.get("params", {})
    topk = params.get("topk", 30)
    # n_drop = params.get("n_drop", 5)  # Reserved for TopkDropout rotation logic
    allocated_amount = float(alpha.allocated_amount)
    
    try:
        # Import quant-stream
        quant_stream_path = Path(PROJECT_ROOT) / "quant-stream"
        if str(quant_stream_path) not in sys.path:
            sys.path.insert(0, str(quant_stream_path))
        
        # Get predictions first
        from quant_stream.backtest.runner import load_market_data, calculate_factors
        
        features_config = workflow_config.get("features", [])
        
        # Load and compute - only last 60 days for live signals
        data_path = str(quant_stream_path / ".data" / "indian_stock_market_nifty500.csv")
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        date_ranges = [(start_date, end_date)]
        
        table = load_market_data(data_path=data_path, date_ranges=date_ranges)
        _, features_df, _ = calculate_factors(table, features_config)
        
        # Get latest values per symbol
        features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])
        latest_df = features_df.sort_values('timestamp').groupby('symbol').last().reset_index()
        
        # Get feature columns and compute predictions
        factor_names = [f["name"] for f in features_config]
        available_factors = [f for f in factor_names if f in latest_df.columns]
        
        if not available_factors:
            return SignalsResponse(
                success=False,
                signals=[],
                strategy_type=strategy_type,
                topk=topk
            )
        
        X = latest_df[available_factors].fillna(0)
        
        # Try to load frozen model from MLflow (same as predict-returns)
        mlflow_run_id = workflow_config.get("experiment", {}).get("run_id")
        if not mlflow_run_id:
            mlflow_run_id = workflow_config.get("experiment", {}).get("mlflow_run_id")
        
        model = None
        
        if mlflow_run_id:
            try:
                from quant_stream.recorder.utils import load_mlflow_run_artifacts
                tracking_uri = f"sqlite:///{quant_stream_path / 'mlruns.db'}"
                artifacts = load_mlflow_run_artifacts(
                    run_id=mlflow_run_id,
                    artifact_names=["model", "trained_model", "lgb_model", "xgb_model"],
                    tracking_uri=tracking_uri,
                )
                for name in ["model", "trained_model", "lgb_model", "xgb_model"]:
                    if name in artifacts and artifacts[name] is not None:
                        model = artifacts[name]
                        break
            except Exception:
                pass
        
        if model is not None and hasattr(model, 'predict'):
            # Use frozen model from backtesting
            predicted_returns = model.predict(X)
        else:
            # Fallback: use factor signals directly
            if len(available_factors) == 1:
                predicted_returns = X[available_factors[0]].values
            else:
                normalized = (X - X.mean()) / (X.std() + 1e-8)
                predicted_returns = normalized.mean(axis=1).values
            # Normalize
            pred_std = predicted_returns.std()
            if pred_std > 0:
                predicted_returns = predicted_returns / pred_std * 0.02
        
        # Add predictions to dataframe
        latest_df['predicted_return'] = predicted_returns
        
        # Sort by predicted return (descending) and select top-k
        ranked_df = latest_df.sort_values('predicted_return', ascending=False)
        buy_candidates = ranked_df.head(topk)
        
        # Calculate allocations (equal weight)
        allocation_per_stock = allocated_amount / topk
        
        signals = []
        batch_id = str(uuid.uuid4())  # Generate unique batch ID for this run
        now = datetime.now(timezone.utc)
        # Signals expire at end of trading day (3:30 PM IST = 10:00 AM UTC for same day)
        expires_at = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now.hour >= 10:
            expires_at = expires_at + timedelta(days=1)
        
        for rank, (_, row) in enumerate(buy_candidates.iterrows(), 1):
            # Require a real close price; skip if missing/invalid instead of using synthetic defaults
            close_val = row.get('close')
            try:
                close_price = float(close_val)
            except (TypeError, ValueError):
                continue
            if close_price <= 0:
                continue
            
            quantity = int(allocation_per_stock / close_price)
            if quantity <= 0:
                continue
            
            pred_return = float(row['predicted_return'])
            confidence = min(1.0, max(0.0, abs(pred_return) * 10))  # Scale confidence
            
            signals.append(Signal(
                symbol=row['symbol'],
                signal_type='buy',
                quantity=quantity,
                predicted_return=pred_return,
                confidence=confidence,
                price=close_price,
                allocated_amount=quantity * close_price,
                rank=rank
            ))
        
        # Persist signals to database
        if signals:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Persisting {len(signals)} signals for alpha {alpha_id} with batch_id {batch_id}")
            
            for sig in signals:
                await prisma.alphasignal.create(
                    data={
                        "live_alpha_id": alpha_id,
                        "batch_id": batch_id,
                        "symbol": sig.symbol,
                        "signal_type": sig.signal_type,
                        "quantity": sig.quantity,
                        "predicted_return": sig.predicted_return,
                        "confidence": sig.confidence,
                        "price": sig.price,
                        "allocated_amount": sig.allocated_amount,
                        "rank": sig.rank,
                        "status": "pending",
                        "generated_at": now,
                        "expires_at": expires_at,
                    }
                )
            
            # Update alpha's last_signal_at and total_signals
            await prisma.livealpha.update(
                where={"id": alpha_id},
                data={
                    "last_signal_at": now,
                    "total_signals": alpha.total_signals + len(signals),
                }
            )
            
            logger.info(f"✅ Successfully persisted {len(signals)} signals")
        
        return SignalsResponse(
            success=True,
            signals=signals,
            strategy_type=strategy_type,
            topk=topk,
            batch_id=batch_id  # Include batch_id in response
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signals: {str(e)}")


# ============================================================================
# Celery Task Trigger & Status Endpoints
# ============================================================================

@router.post("/live/{alpha_id}/trigger-signals", response_model=SignalGenerationTaskResponse)
async def trigger_signal_generation(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Trigger signal generation for a specific alpha via Celery task.
    
    This queues the signal generation to run in the background.
    Use the task status endpoint to check progress.
    The task ID is stored in Redis so it can be retrieved on page reload.
    """
    # Verify alpha exists and user has access
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if alpha.status != "running":
        raise HTTPException(status_code=400, detail=f"Alpha must be running to generate signals (current: {alpha.status})")
    
    try:
        from redis import Redis
        from celery_app import celery_app, BROKER_URL
        
        # Queue the task using send_task (works even if task module not imported)
        # This avoids circular import issues while ensuring task is properly queued
        task = celery_app.send_task(
            "alpha.generate_signals_for_alpha",
            args=[alpha_id],
            queue="trading",
            routing_key="trading"
        )
        
        # Store task ID in Redis so it can be retrieved on page reload
        # Key format: alpha_task:{alpha_id} -> task_id
        # TTL of 1 hour (tasks shouldn't take longer than that)
        redis_client = Redis.from_url(BROKER_URL)
        redis_client.set(f"alpha_task:{alpha_id}", task.id, ex=3600)
        
        return SignalGenerationTaskResponse(
            task_id=task.id,
            status="PENDING",
            alpha_id=alpha_id,
            message=f"Signal generation queued for alpha '{alpha.name}'"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue signal generation: {str(e)}")


@router.post("/trigger-all-signals", response_model=SignalGenerationTaskResponse)
async def trigger_all_signal_generation(
    user: dict = Depends(get_authenticated_user),
):
    """Trigger signal generation for all running alphas via Celery task.
    
    This is the same as the scheduled daily task but triggered manually.
    """
    try:
        from celery_app import celery_app
        
        # Queue the task using send_task (avoids circular import issues)
        task = celery_app.send_task(
            "alpha.generate_daily_signals",
            queue="pipelines",
            routing_key="pipelines"
        )
        
        return SignalGenerationTaskResponse(
            task_id=task.id,
            status="PENDING",
            alpha_id=None,
            message="Signal generation queued for all running alphas"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to queue signal generation: {str(e)}")


@router.get("/live/{alpha_id}/current-task", response_model=Optional[TaskStatusResponse])
async def get_current_task_for_alpha(
    alpha_id: str,
    prisma: Prisma = Depends(prisma_client),
    user: dict = Depends(get_authenticated_user),
):
    """Get the current active task for an alpha (if any).
    
    This is used to resume polling when returning to the page.
    Returns null if no active task.
    """
    from redis import Redis
    from celery.result import AsyncResult
    from celery_app import celery_app, BROKER_URL
    
    # Verify alpha exists and user has access
    alpha = await prisma.livealpha.find_unique(where={"id": alpha_id})
    if not alpha:
        raise HTTPException(status_code=404, detail="Live alpha not found")
    
    portfolio = await prisma.portfolio.find_unique(where={"id": alpha.portfolio_id})
    if not portfolio or portfolio.customer_id != (user.get("customer_id") or user.get("id")):
        raise HTTPException(status_code=403, detail="Not authorized")
    
    try:
        redis_client = Redis.from_url(BROKER_URL)
        task_id = redis_client.get(f"alpha_task:{alpha_id}")
        
        if not task_id:
            return None
        
        task_id = task_id.decode("utf-8") if isinstance(task_id, bytes) else task_id
        
        # Check if task is still active
        result = AsyncResult(task_id, app=celery_app)
        
        # If task is done, clean up Redis and return null
        if result.ready():
            redis_client.delete(f"alpha_task:{alpha_id}")
            return None
        
        # Return current task status
        response = TaskStatusResponse(
            task_id=task_id,
            status=result.status,
            result=None,
            error=None,
            started_at=None,
            completed_at=None,
            step=None,
            progress=None,
            message=None,
        )
        
        if result.status == "PROGRESS":
            info = result.info or {}
            response.step = info.get("step")
            response.progress = info.get("progress")
            response.message = info.get("message")
        
        return response
        
    except Exception as e:
        # Don't fail the page load if Redis is unavailable
        return None


@router.get("/tasks/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    user: dict = Depends(get_authenticated_user),
):
    """Get the status of a Celery task.
    
    Poll this endpoint to check if signal generation is complete.
    Returns progress info (step, progress %, message) when task is running.
    """
    from celery.result import AsyncResult
    from celery_app import celery_app
    
    try:
        result = AsyncResult(task_id, app=celery_app)
        
        response = TaskStatusResponse(
            task_id=task_id,
            status=result.status,
            result=None,
            error=None,
            started_at=None,
            completed_at=None,
            step=None,
            progress=None,
            message=None,
        )
        
        # Check for PROGRESS state (custom state with progress info)
        if result.status == "PROGRESS":
            info = result.info or {}
            response.step = info.get("step")
            response.progress = info.get("progress")
            response.message = info.get("message")
        elif result.ready():
            if result.successful():
                response.result = result.result
                if result.date_done:
                    response.completed_at = result.date_done.isoformat()
            else:
                # Task failed
                response.error = str(result.result) if result.result else "Unknown error"
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")



