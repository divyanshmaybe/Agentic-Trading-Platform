"""
Celery tasks for portfolio allocation and rebalancing.

These tasks trigger the Pathway allocation pipeline when:
1. A new portfolio is created (initial allocation)
2. Rebalancing date is reached (scheduled rebalancing)
"""

import logging
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional
from dateutil.relativedelta import relativedelta

# Ensure portfolio-server root is in path
server_root = Path(__file__).resolve().parents[1]
if str(server_root) not in sys.path:
    sys.path.insert(0, str(server_root))

from celery_app import celery_app
from utils import allocate_portfolios

logger = logging.getLogger(__name__)


# ============================================================================
# Helper Functions
# ============================================================================

async def _get_current_regime() -> str:
    """
    Fetch current market regime from regime service.
    
    Returns:
        Current regime name (e.g., "bull_market", "bear_market", "sideways", "high_volatility")
    """
    try:
        # Try to get regime from regime service
        from services.regime_service import RegimeService
        
        regime_service = RegimeService.get_instance()
        current = regime_service.get_current_regime()
        
        if current and current.get("regime"):
            regime_name = current["regime"].lower().replace(" ", "_")
            logger.info(f"Retrieved current regime from service: {regime_name}")
            return regime_name
    except Exception as exc:
        logger.warning(f"Failed to get regime from service: {exc}, using default")
    
    # Fallback to sideways if regime service unavailable
    return "sideways"


def _calculate_next_rebalance_date(
    frequency: str,
    from_date: Optional[datetime] = None
) -> Optional[datetime]:
    """
    Calculate next rebalancing date based on frequency.
    
    Args:
        frequency: Rebalancing frequency ("monthly", "quarterly", "semi_annually", "annually", "never")
        from_date: Starting date (defaults to today)
        
    Returns:
        Next rebalancing date, or None if frequency is "never"
    """
    if frequency == "never":
        return None
    
    start = from_date or datetime.now()
    
    frequency_map = {
        "monthly": relativedelta(months=1),
        "quarterly": relativedelta(months=3),
        "semi_annually": relativedelta(months=6),
        "annually": relativedelta(years=1),
    }
    
    delta = frequency_map.get(frequency.lower(), relativedelta(months=3))  # Default to quarterly
    next_date = start + delta
    
    logger.info(f"Calculated next rebalance date: {next_date.date()} (frequency={frequency})")
    return next_date


# ============================================================================
# Celery Tasks
# ============================================================================


@celery_app.task(name="portfolio.allocate_new_portfolio", bind=True, max_retries=3)
def allocate_new_portfolio_task(
    self,
    portfolio_id: str,
    user_id: str,
    organization_id: str,
    user_inputs: Dict[str, Any],
    initial_value: float,
) -> Dict[str, Any]:
    """
    Celery task to run portfolio allocation for a newly created portfolio.
    
    Args:
        portfolio_id: Database ID of the portfolio
        user_id: User who owns the portfolio
        organization_id: Organization ID
        user_inputs: Portfolio preferences (risk tolerance, horizon, etc.)
        initial_value: Initial investment amount
        
    Returns:
        Allocation result dictionary
    """
    import asyncio
    
    async def _allocate():
        try:
            logger.info(
                f"Starting initial allocation for portfolio {portfolio_id} "
                f"(user={user_id}, org={organization_id})"
            )
            
            # Get current regime from regime service
            current_regime = await _get_current_regime()
            
            # Build allocation request
            request = {
                "request_id": f"initial_{portfolio_id}_{datetime.utcnow().isoformat()}",
                "user_id": user_id,
                "current_regime": current_regime,
                "user_inputs": user_inputs,
                "initial_value": initial_value,
                "current_value": initial_value,
                "metadata": {
                    "portfolio_id": portfolio_id,
                    "organization_id": organization_id,
                    "trigger": "initial_creation",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            }
            
            # Update portfolio status to processing
            from baseApp import get_db_manager
            db = get_db_manager().prisma
            
            if db is None:
                raise RuntimeError("Database not available")
            
            await db.portfolio.update(
                where={"id": portfolio_id},
                data={"allocation_status": "processing"}
            )
            
            # Execute Pathway allocation pipeline
            results = allocate_portfolios(
                [request],
                logger=logger,
                audit_path=f"/tmp/portfolio_allocations_{portfolio_id}.jsonl"
            )
            
            if not results:
                raise ValueError("Allocation pipeline returned no results")
            
            allocation_result = results[0]
            
            if not allocation_result.get("success"):
                raise ValueError(f"Allocation failed: {allocation_result.get('message')}")
            
            # Save allocation weights to portfolioAllocation table
            weights = allocation_result.get("weights", {})
            
            for allocation_type, weight in weights.items():
                await db.portfolioallocation.create(
                    data={
                        "portfolio_id": portfolio_id,
                        "allocation_type": allocation_type,
                        "target_weight": float(weight),
                        "current_weight": float(weight),
                        "expected_return": allocation_result.get("expected_return"),
                        "expected_risk": allocation_result.get("expected_risk"),
                        "regime": current_regime,
                        "metadata": {
                            "request_id": request["request_id"],
                            "trigger": "initial_creation",
                            "objective_value": allocation_result.get("objective_value"),
                            "message": allocation_result.get("message"),
                        }
                    }
                )
            
            # Calculate initial rebalancing date based on frequency
            rebalancing_date = _calculate_next_rebalance_date(
                user_inputs.get("rebalancing_frequency", "quarterly")
            )
            
            # Mark portfolio as ready
            await db.portfolio.update(
                where={"id": portfolio_id},
                data={
                    "allocation_status": "ready",
                    "rebalancing_date": rebalancing_date,
                    "last_rebalanced_at": datetime.utcnow(),
                    "metadata": {
                        "allocated_at": datetime.utcnow().isoformat(),
                        "allocation_regime": current_regime,
                    }
                }
            )
            
            logger.info(
                f"✅ Successfully allocated portfolio {portfolio_id}: "
                f"{weights} (next rebalance: {rebalancing_date})"
            )
            
            return {
                "success": True,
                "portfolio_id": portfolio_id,
                "allocation": allocation_result,
                "rebalancing_date": rebalancing_date.isoformat() if rebalancing_date else None,
            }
            
        except Exception as exc:
            # Mark portfolio as failed
            try:
                from baseApp import get_db_manager
                db = get_db_manager().prisma
                if db:
                    await db.portfolio.update(
                        where={"id": portfolio_id},
                        data={"allocation_status": "failed"}
                    )
            except:
                pass
            
            logger.error(
                f"❌ Failed to allocate portfolio {portfolio_id}: {exc}",
                exc_info=True
            )
            raise exc
    
    try:
        return asyncio.run(_allocate())
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(name="portfolio.daily_rebalancing_sweep", bind=True)
def daily_rebalancing_sweep_task(self) -> Dict[str, Any]:
    """
    Daily Celery beat task to check for portfolios that need rebalancing.
    
    Runs 1 hour before market open to rebalance portfolios whose
    rebalancing_date is today.
    
    Returns:
        Summary of rebalancing operations
    """
    import asyncio
    
    async def _sweep():
        try:
            from baseApp import get_db_manager
            
            db = get_db_manager().prisma
            if db is None:
                raise RuntimeError("Database not available")
            
            today = datetime.now().date()
            logger.info(f"Running daily rebalancing sweep for {today}")
            
            # Find portfolios with rebalancing_date <= today (includes overdue portfolios)
            # This ensures we catch any portfolios that were missed
            portfolios_to_rebalance = await db.portfolio.find_many(
                where={
                    "AND": [
                        {"rebalancing_date": {"lte": today}},
                        {"rebalancing_date": {"not": None}},
                        {"allocation_status": "ready"},  # Only rebalance ready portfolios
                        {"status": "active"},  # Only active portfolios
                    ]
                },
                include={
                    "allocations": True,
                }
            )
            
            if not portfolios_to_rebalance:
                logger.info("No portfolios due for rebalancing today or overdue")
                return {
                    "success": True,
                    "portfolios_checked": 0,
                    "portfolios_rebalanced": 0,
                }
            
            logger.info(
                f"Found {len(portfolios_to_rebalance)} portfolios to rebalance "
                f"(including overdue)"
            )
            
            # Get current regime once for all portfolios
            current_regime = await _get_current_regime()
            
            # Build allocation requests for all due portfolios
            requests = []
            portfolio_map = {}
            
            for portfolio in portfolios_to_rebalance:
                # Build user inputs from portfolio settings
                user_inputs = {
                    "risk_tolerance": portfolio.risk_tolerance,
                    "investment_horizon_years": portfolio.investment_horizon_years,
                    "liquidity_needs": portfolio.liquidity_needs or "medium",
                    "expected_return_target": float(portfolio.expected_return_target),
                }
                
                # Get historical allocation data
                allocations = portfolio.allocations if hasattr(portfolio, "allocations") else []
                value_history = [float(alloc.expected_return) for alloc in allocations if alloc.expected_return] if allocations else None
                
                # Get rebalancing frequency from portfolio
                rebalancing_freq = "quarterly"  # Default
                if portfolio.rebalancing_frequency:
                    if isinstance(portfolio.rebalancing_frequency, dict):
                        rebalancing_freq = portfolio.rebalancing_frequency.get("frequency", "quarterly")
                    elif isinstance(portfolio.rebalancing_frequency, str):
                        rebalancing_freq = portfolio.rebalancing_frequency
                
                days_overdue = (today - portfolio.rebalancing_date).days if portfolio.rebalancing_date else 0
                
                request = {
                    "request_id": f"rebalance_{portfolio.id}_{today.isoformat()}",
                    "user_id": portfolio.customer_id,
                    "current_regime": current_regime,
                    "user_inputs": user_inputs,
                    "initial_value": float(portfolio.investment_amount),
                    "current_value": float(portfolio.current_value),
                    "value_history": value_history,
                    "metadata": {
                        "portfolio_id": portfolio.id,
                        "organization_id": portfolio.organization_id,
                        "trigger": "scheduled_rebalancing",
                        "scheduled_date": portfolio.rebalancing_date.isoformat() if portfolio.rebalancing_date else None,
                        "days_overdue": days_overdue,
                        "rebalancing_frequency": rebalancing_freq,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                }
                requests.append(request)
                portfolio_map[portfolio.id] = {
                    "portfolio": portfolio,
                    "rebalancing_freq": rebalancing_freq,
                }
            
            # Execute Pathway allocation pipeline for all portfolios
            logger.info(f"Executing Pathway allocation pipeline for {len(requests)} portfolios")
            results = allocate_portfolios(
                requests,
                logger=logger,
                audit_path=f"/tmp/portfolio_rebalancing_{today.isoformat()}.jsonl"
            )
            
            # Save results to database
            rebalanced_count = 0
            failed_count = 0
            
            for i, result in enumerate(results):
                request = requests[i]
                portfolio_data = portfolio_map[request["metadata"]["portfolio_id"]]
                portfolio = portfolio_data["portfolio"]
                rebalancing_freq = portfolio_data["rebalancing_freq"]
                
                if result.get("success"):
                    try:
                        # Save new allocation weights
                        weights = result.get("weights", {})
                        
                        for allocation_type, weight in weights.items():
                            await db.portfolioallocation.create(
                                data={
                                    "portfolio_id": portfolio.id,
                                    "allocation_type": allocation_type,
                                    "target_weight": float(weight),
                                    "current_weight": float(weight),
                                    "expected_return": result.get("expected_return"),
                                    "expected_risk": result.get("expected_risk"),
                                    "regime": current_regime,
                                    "metadata": {
                                        "request_id": request["request_id"],
                                        "trigger": "scheduled_rebalancing",
                                        "objective_value": result.get("objective_value"),
                                        "drift": result.get("drift"),
                                        "days_overdue": request["metadata"]["days_overdue"],
                                    }
                                }
                            )
                        
                        # Calculate next rebalancing date
                        next_rebalance = _calculate_next_rebalance_date(
                            rebalancing_freq,
                            from_date=datetime.now()
                        )
                        
                        # Update portfolio
                        await db.portfolio.update(
                            where={"id": portfolio.id},
                            data={
                                "rebalancing_date": next_rebalance,
                                "last_rebalanced_at": datetime.utcnow(),
                                "allocation_status": "ready",
                                "metadata": {
                                    "last_rebalanced_at": datetime.utcnow().isoformat(),
                                    "rebalancing_regime": current_regime,
                                    "next_rebalance_date": next_rebalance.isoformat() if next_rebalance else None,
                                }
                            }
                        )
                        
                        rebalanced_count += 1
                        logger.info(
                            f"✅ Rebalanced portfolio {portfolio.id} "
                            f"(weights: {weights}, next: {next_rebalance})"
                        )
                    except Exception as save_exc:
                        logger.error(
                            f"❌ Failed to save rebalancing results for {portfolio.id}: {save_exc}",
                            exc_info=True
                        )
                        failed_count += 1
                else:
                    logger.error(
                        f"❌ Failed to rebalance portfolio {portfolio.id}: "
                        f"{result.get('message')}"
                    )
                    failed_count += 1
            
            return {
                "success": True,
                "portfolios_checked": len(portfolios_to_rebalance),
                "portfolios_rebalanced": rebalanced_count,
                "portfolios_failed": failed_count,
                "date": today.isoformat(),
                "regime": current_regime,
            }
            
        except Exception as exc:
            logger.error(f"❌ Rebalancing sweep failed: {exc}", exc_info=True)
            return {
                "success": False,
                "error": str(exc),
            }
    
    return asyncio.run(_sweep())
