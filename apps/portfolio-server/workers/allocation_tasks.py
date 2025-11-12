"""
Celery tasks for portfolio allocation and rebalancing.

These tasks trigger the Pathway allocation pipeline when:
1. A new portfolio is created (initial allocation)
2. Rebalancing date is reached (scheduled rebalancing)
"""

import json
import logging
import math
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from dateutil.relativedelta import relativedelta
from fastapi.encoders import jsonable_encoder

# Ensure portfolio-server root is in path
server_root = Path(__file__).resolve().parents[1]
if str(server_root) not in sys.path:
    sys.path.insert(0, str(server_root))

from celery_app import celery_app
from prisma import fields
from utils import allocate_portfolios

logger = logging.getLogger(__name__)

_JSON_ENCODERS = {
    datetime: lambda value: value.isoformat(),
    date: lambda value: value.isoformat(),
    timedelta: lambda value: value.total_seconds(),
    Decimal: float,
}


def _encode_json(value: Any) -> Any:
    """Encode arbitrary data structures into JSON-serialisable Python objects."""

    def _sanitize(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, (datetime, date)):
            return val.isoformat()
        if isinstance(val, timedelta):
            return val.total_seconds()
        if isinstance(val, Decimal):
            coerced = float(val)
            if math.isnan(coerced) or math.isinf(coerced):
                return None
            return coerced
        if isinstance(val, float):
            if math.isnan(val) or math.isinf(val):
                return None
            return float(val)
        if isinstance(val, (int, str, bool)):
            return val
        if isinstance(val, Mapping):
            return {str(key): _sanitize(sub_val) for key, sub_val in val.items()}
        if isinstance(val, list):
            return [_sanitize(item) for item in val]
        try:
            encoded = jsonable_encoder(val, custom_encoder=_JSON_ENCODERS)
            return _sanitize(encoded)
        except Exception:
            return str(val)

    sanitized = _sanitize(value)
    if sanitized is None:
        return None
    return fields.Json(sanitized)


# ==========================================================================
# Data normalization helpers
# ==========================================================================

def _coerce_to_plain_dict(value: Any) -> Dict[str, Any]:
    """Convert Pathway Json wrappers or JSON strings into plain dicts."""

    if isinstance(value, dict):
        return value

    # Pathway often wraps payloads inside custom Json objects exposing ``value``
    maybe_value = getattr(value, "value", None)
    if isinstance(maybe_value, dict):
        return maybe_value
    if isinstance(maybe_value, str):
        try:
            parsed = json.loads(maybe_value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    if maybe_value is not None and maybe_value is not value:
        nested = _coerce_to_plain_dict(maybe_value)
        if nested:
            return nested

    # Some objects expose conversion helpers
    for attr in ("to_dict", "to_builtin"):
        converter = getattr(value, attr, None)
        if callable(converter):
            try:
                converted = converter()
            except Exception:
                converted = None
            if isinstance(converted, dict):
                return converted
            if converted is not None and converted is not value:
                nested = _coerce_to_plain_dict(converted)
                if nested:
                    return nested

    # Finally, attempt to decode JSON strings
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}

    return {}


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
            from dbManager import DBManager
            db_manager = DBManager.get_instance()
            await db_manager.connect()
            db = db_manager.client
            
            if db is None:
                raise RuntimeError("Database not available")
            
            await db.portfolio.update(
                where={"id": portfolio_id},
                data={"allocation_status": "processing"}
            )
            
            # Execute Pathway allocation pipeline in a thread pool to avoid event loop conflicts
            from concurrent.futures import ThreadPoolExecutor
            import functools
            
            loop = asyncio.get_event_loop()
            
            # Run the synchronous pipeline in a thread pool executor
            with ThreadPoolExecutor(max_workers=1) as executor:
                results = await loop.run_in_executor(
                    executor,
                    functools.partial(
                        allocate_portfolios,
                        [request],
                        logger=logger,
                        audit_path=f"/tmp/portfolio_allocations_{portfolio_id}.jsonl"
                    )
                )
            
            if not results:
                raise ValueError("Allocation pipeline returned no results")
            
            allocation_result = results[0]
            
            if not allocation_result.get("success"):
                raise ValueError(f"Allocation failed: {allocation_result.get('message')}")
            
            # Save allocation weights to portfolioAllocation table
            weights = _coerce_to_plain_dict(allocation_result.get("weights"))

            if not weights:
                weights = _coerce_to_plain_dict(allocation_result.get("weights_json"))

            for allocation_type, weight in weights.items():
                allocation_metadata = {
                    "request_id": request["request_id"],
                    "trigger": "initial_creation",
                    "objective_value": allocation_result.get("objective_value"),
                    "message": allocation_result.get("message"),
                }

                await db.portfolioallocation.create(
                    data={
                        "portfolio_id": portfolio_id,
                        "allocation_type": allocation_type,
                        "target_weight": float(weight),
                        "current_weight": float(weight),
                        "expected_return": allocation_result.get("expected_return"),
                        "expected_risk": allocation_result.get("expected_risk"),
                        "regime": current_regime,
                        "metadata": _encode_json(allocation_metadata),
                    }
                )
            
            # Calculate initial rebalancing date based on frequency
            rebalancing_date = _calculate_next_rebalance_date(
                user_inputs.get("rebalancing_frequency", "quarterly")
            )
            
            # Mark portfolio as ready
            portfolio_metadata = {
                "allocated_at": datetime.utcnow(),
                "allocation_regime": current_regime,
            }

            await db.portfolio.update(
                where={"id": portfolio_id},
                data={
                    "allocation_status": "ready",
                    "rebalancing_date": rebalancing_date,
                    "last_rebalanced_at": datetime.utcnow(),
                    "metadata": _encode_json(portfolio_metadata),
                },
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
                from dbManager import DBManager
                db_manager = DBManager.get_instance()
                await db_manager.connect()
                db = db_manager.client
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
    
    # Create a fresh event loop for this task execution to avoid loop closure issues
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_allocate())
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        # Clean up the loop
        try:
            loop.close()
        except:
            pass


@celery_app.task(name="portfolio.allocate_for_objective", bind=True, max_retries=3)
def allocate_for_objective_task(
    self,
    portfolio_id: str,
    objective_id: str,
    user_id: str,
    organization_id: str,
    user_inputs: Dict[str, Any],
    initial_value: float,
    current_value: Optional[float] = None,
    triggered_by: str = "objective_created",
) -> Dict[str, Any]:
    """
    Celery task to run portfolio allocation triggered by an objective being created or completed.
    
    Args:
        portfolio_id: Database ID of the portfolio
        objective_id: Database ID of the objective that triggered this
        user_id: User who owns the portfolio
        organization_id: Organization ID
        user_inputs: Portfolio preferences from objective
        initial_value: Initial investment amount
        current_value: Current portfolio value (defaults to initial_value)
        triggered_by: What triggered this allocation
        
    Returns:
        Allocation result dictionary
    """
    import asyncio
    
    async def _allocate():
        try:
            logger.info(
                f"Starting allocation for portfolio {portfolio_id} triggered by {triggered_by} "
                f"(objective={objective_id}, user={user_id})"
            )
            
            # Get current regime from regime service
            current_regime = await _get_current_regime()
            
            # Build allocation request
            request = {
                "request_id": f"{triggered_by}_{portfolio_id}_{datetime.utcnow().isoformat()}",
                "user_id": user_id,
                "current_regime": current_regime,
                "user_inputs": user_inputs,
                "initial_value": initial_value,
                "current_value": current_value or initial_value,
                "metadata": {
                    "portfolio_id": portfolio_id,
                    "objective_id": objective_id,
                    "organization_id": organization_id,
                    "trigger": triggered_by,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            }
            
            # Update portfolio status to processing
            from dbManager import DBManager
            db_manager = DBManager.get_instance()
            await db_manager.connect()
            db = db_manager.client
            
            if db is None:
                raise RuntimeError("Database not available")
            
            await db.portfolio.update(
                where={"id": portfolio_id},
                data={"allocation_status": "processing"}
            )
            
            # Execute Pathway allocation pipeline in a thread pool to avoid event loop conflicts
            # Use asyncio.to_thread to run the synchronous pipeline without blocking the event loop
            from concurrent.futures import ThreadPoolExecutor
            import functools
            
            loop = asyncio.get_event_loop()
            
            # Run the synchronous pipeline in a thread pool executor
            with ThreadPoolExecutor(max_workers=1) as executor:
                results = await loop.run_in_executor(
                    executor,
                    functools.partial(
                        allocate_portfolios,
                        [request],
                        logger=logger,
                        audit_path=f"/tmp/portfolio_allocations_{portfolio_id}_{objective_id}.jsonl"
                    )
                )
            
            if not results:
                raise ValueError("Allocation pipeline returned no results")
            
            allocation_result = results[0]
            
            if not allocation_result.get("success"):
                raise ValueError(f"Allocation failed: {allocation_result.get('message')}")
            
            # Now do all database operations after the pipeline
            # Save allocation weights to portfolioAllocation table
            weights = _coerce_to_plain_dict(allocation_result.get("weights"))
            if not weights:
                weights = _coerce_to_plain_dict(allocation_result.get("weights_json"))

            for allocation_type, weight in weights.items():
                allocation_metadata = {
                    "request_id": request["request_id"],
                    "objective_id": objective_id,
                    "trigger": triggered_by,
                    "objective_value": allocation_result.get("objective_value"),
                    "message": allocation_result.get("message"),
                }

                await db.portfolioallocation.create(
                    data={
                        "portfolio_id": portfolio_id,
                        "allocation_type": allocation_type,
                        "target_weight": float(weight),
                        "current_weight": float(weight),
                        "expected_return": allocation_result.get("expected_return"),
                        "expected_risk": allocation_result.get("expected_risk"),
                        "regime": current_regime,
                        "metadata": _encode_json(allocation_metadata),
                    },
                )
            
            # Calculate next rebalancing date
            rebalancing_date = _calculate_next_rebalance_date(
                user_inputs.get("rebalancing_frequency", "quarterly")
            )
            
            # Mark portfolio as ready
            portfolio_metadata = {
                "allocated_at": datetime.utcnow(),
                "allocation_regime": current_regime,
                "objective_id": objective_id,
                "triggered_by": triggered_by,
            }

            await db.portfolio.update(
                where={"id": portfolio_id},
                data={
                    "allocation_status": "ready",
                    "rebalancing_date": rebalancing_date,
                    "last_rebalanced_at": datetime.utcnow(),
                    "next_rebalance_at": rebalancing_date,
                    "metadata": _encode_json(portfolio_metadata),
                },
            )
            
            logger.info(
                f"✅ Successfully allocated portfolio {portfolio_id} for objective {objective_id}: "
                f"{weights} (next rebalance: {rebalancing_date})"
            )
            
            return {
                "success": True,
                "portfolio_id": portfolio_id,
                "objective_id": objective_id,
                "allocation": allocation_result,
                "rebalancing_date": rebalancing_date.isoformat() if rebalancing_date else None,
                "last_rebalanced_at": datetime.utcnow().isoformat(),
                "next_rebalance_at": rebalancing_date.isoformat() if rebalancing_date else None,
            }
            
        except Exception as exc:
            # Mark portfolio as failed
            try:
                from dbManager import DBManager
                db_manager = DBManager.get_instance()
                await db_manager.connect()
                db = db_manager.client
                if db:
                    await db.portfolio.update(
                        where={"id": portfolio_id},
                        data={"allocation_status": "failed"}
                    )
            except:
                pass
            
            logger.error(
                f"❌ Failed to allocate portfolio {portfolio_id} for objective {objective_id}: {exc}",
                exc_info=True
            )
            raise exc
    
    # Create a fresh event loop for this task execution to avoid loop closure issues
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_allocate())
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        # Clean up the loop
        try:
            loop.close()
        except:
            pass


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
            from dbManager import DBManager
            
            db_manager = DBManager.get_instance()
            await db_manager.connect()
            db = db_manager.client
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
            
            # Execute Pathway allocation pipeline for all portfolios in a thread pool
            logger.info(f"Executing Pathway allocation pipeline for {len(requests)} portfolios")
            
            from concurrent.futures import ThreadPoolExecutor
            import functools
            
            loop = asyncio.get_event_loop()
            
            # Run the synchronous pipeline in a thread pool executor
            with ThreadPoolExecutor(max_workers=1) as executor:
                results = await loop.run_in_executor(
                    executor,
                    functools.partial(
                        allocate_portfolios,
                        requests,
                        logger=logger,
                        audit_path=f"/tmp/portfolio_rebalancing_{today.isoformat()}.jsonl"
                    )
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
                        weights = _coerce_to_plain_dict(result.get("weights"))
                        if not weights:
                            weights = _coerce_to_plain_dict(result.get("weights_json"))

                        for allocation_type, weight in weights.items():
                            allocation_metadata = {
                                "request_id": request["request_id"],
                                "trigger": "scheduled_rebalancing",
                                "objective_value": result.get("objective_value"),
                                "drift": result.get("drift"),
                                "days_overdue": request["metadata"]["days_overdue"],
                            }

                            await db.portfolioallocation.create(
                                data={
                                    "portfolio_id": portfolio.id,
                                    "allocation_type": allocation_type,
                                    "target_weight": float(weight),
                                    "current_weight": float(weight),
                                    "expected_return": result.get("expected_return"),
                                    "expected_risk": result.get("expected_risk"),
                                    "regime": current_regime,
                                    "metadata": _encode_json(allocation_metadata),
                                },
                            )
                        
                        # Calculate next rebalancing date
                        next_rebalance = _calculate_next_rebalance_date(
                            rebalancing_freq,
                            from_date=datetime.now()
                        )
                        
                        # Update portfolio
                        portfolio_metadata = {
                            "last_rebalanced_at": datetime.utcnow(),
                            "rebalancing_regime": current_regime,
                            "next_rebalance_date": next_rebalance.isoformat() if next_rebalance else None,
                        }

                        await db.portfolio.update(
                            where={"id": portfolio.id},
                            data={
                                "rebalancing_date": next_rebalance,
                                "last_rebalanced_at": datetime.utcnow(),
                                "allocation_status": "ready",
                                "metadata": _encode_json(portfolio_metadata),
                            },
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
    
    # Create a fresh event loop for this task execution to avoid loop closure issues
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_sweep())
    finally:
        # Clean up the loop
        try:
            loop.close()
        except:
            pass
