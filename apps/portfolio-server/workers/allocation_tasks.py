"""
Celery tasks for portfolio allocation and rebalancing.

These tasks trigger the Pathway allocation pipeline when:
1. A new portfolio is created (initial allocation)
2. Rebalancing date is reached (scheduled rebalancing)
"""

import json
import logging
import math
import os
import sys
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

from dateutil.relativedelta import relativedelta
from fastapi.encoders import jsonable_encoder

# Aggressively suppress verbose Pathway sink logging
os.environ.setdefault("PATHWAY_LOG_LEVEL", "ERROR")
os.environ.setdefault("PATHWAY_DISABLE_PROGRESS", "1")
os.environ.setdefault("PATHWAY_MONITORING_LEVEL", "none")
# Suppress all Pathway loggers at multiple levels
for logger_name in ["pathway", "pathway.io", "pathway.io.kafka", "pathway.io.filesystem", 
                    "pathway.io.jsonlines", "pathway.io.csv", "pathway.internals"]:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.ERROR)
    logger.propagate = False  # Prevent propagation to root logger

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

ALLOCATION_SUBSCRIPTION_MAP: Dict[str, str] = {
    "equity": "high_risk",
    "high_risk": "high_risk",
    "alpha": "alpha",
    "quant": "alpha",
    "debt": "low_risk",
    "fixed_income": "low_risk",
    "low_risk": "low_risk",
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


def _json_to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, fields.Json):
        try:
            return dict(value.data or {})
        except Exception:
            return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


async def _get_user_subscriptions(db: Any, user_id: Optional[str]) -> Set[str]:
    if not user_id:
        return set()

    try:
        rows = await db.query_raw(
            "SELECT subscriptions FROM users WHERE id = $1",
            user_id,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to fetch subscriptions for user %s: %s", user_id, exc)
        return set()

    if not rows:
        return set()

    row = rows[0]
    subscriptions = None
    if isinstance(row, Mapping):
        subscriptions = row.get("subscriptions")
    else:
        subscriptions = getattr(row, "subscriptions", None)

    if not subscriptions:
        return set()

    try:
        return {str(item).lower() for item in subscriptions if item}
    except TypeError:
        return {str(subscriptions).lower()}


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
    
    delta = frequency_map.get(frequency.lower(), relativedelta(months=6))  # Default to semi_annually
    next_date = start + delta
    
    logger.info(f"Calculated next rebalance date: {next_date.date()} (frequency={frequency})")
    return next_date


async def _ensure_trading_agent(
    db: Any,
    *,
    portfolio_id: str,
    allocation: Any,
    allocation_type: str,
    request_context: Mapping[str, Any],
    objective_id: Optional[str] = None,
    user_subscriptions: Optional[Set[str]] = None,
) -> bool:
    """Create or update a trading agent linked to the portfolio allocation."""

    normalized_type = str(allocation_type or "").strip().lower()
    if not normalized_type:
        normalized_type = "unspecified"

    subscription_key = ALLOCATION_SUBSCRIPTION_MAP.get(normalized_type, normalized_type)
    subscriptions = user_subscriptions or set()
    auto_trade_enabled = subscription_key in subscriptions
    
    agent_name = " ".join(part.capitalize() for part in normalized_type.replace("_", " ").split())
    if agent_name and "agent" not in agent_name.lower():
        agent_name = f"{agent_name} Agent"
    elif not agent_name:
        agent_name = "Automated Agent"

    request_metadata = {
        "request_id": request_context.get("request_id"),
        "trigger": request_context.get("trigger"),
        "regime": request_context.get("current_regime") or request_context.get("regime"),
        "timestamp": request_context.get("timestamp"),
    }

    existing_agent = await db.tradingagent.find_first(
        where={"portfolio_allocation_id": getattr(allocation, "id", None)}
    )
    
    # PRESERVE status if agent is already active with auto_trade enabled
    # Only pause agents if they're being explicitly disabled or if this is a subscription sync event
    existing_status = str(getattr(existing_agent, "status", "")).lower() if existing_agent else ""
    existing_config_raw = _json_to_dict(getattr(existing_agent, "strategy_config", None) if existing_agent else None)
    existing_auto_trade = bool(existing_config_raw.get("auto_trade", False)) if existing_config_raw else False
    
    trigger = str(request_context.get("trigger", "")).lower()
    is_subscription_sync = "subscription" in trigger or "sync" in trigger
    
    # If this is NOT a subscription sync, and agent is already active with auto_trade, keep it active
    # Don't let rebalancing or other operations pause active trading agents
    if not is_subscription_sync and existing_status == "active" and existing_auto_trade:
        status = "active"
    else:
        # Only update status for subscription syncs or when creating new agents
        status = "active" if auto_trade_enabled else "paused"

    existing_metadata = _json_to_dict(getattr(existing_agent, "metadata", None) if existing_agent else None)
    trading_metadata = {
        **existing_metadata,
        "portfolio_allocation_id": getattr(allocation, "id", None),
        "portfolio_id": portfolio_id,
        "objective_id": objective_id,
        "request": {k: v for k, v in request_metadata.items() if v is not None},
    }

    events = trading_metadata.get("subscription_events", [])
    events = [event for event in events if isinstance(event, Mapping)]
    events.append(
        {
            "auto_trade": auto_trade_enabled,
            "status": status,
            "subscription_key": subscription_key,
            "trigger": request_metadata.get("trigger"),
            "timestamp": request_metadata.get("timestamp") or datetime.utcnow().isoformat(),
        }
    )
    trading_metadata["subscription_events"] = events[-20:]
    trading_metadata["subscription_state"] = {
        "auto_trade": auto_trade_enabled,
        "status": status,
        "subscription_key": subscription_key,
        "updated_at": datetime.utcnow().isoformat(),
    }

    existing_config = _json_to_dict(getattr(existing_agent, "strategy_config", None) if existing_agent else None)
    strategy_config = {
        **existing_config,
        "allocation_type": normalized_type,
        "subscription_key": subscription_key,
        "auto_trade": auto_trade_enabled,
        "synced_at": datetime.utcnow().isoformat(),
    }

    data_payload = {
        "portfolio_id": portfolio_id,
        "agent_type": normalized_type,
        "agent_name": agent_name,
        "strategy_config": _encode_json(strategy_config),
        "metadata": _encode_json(trading_metadata),
        "status": status,
    }

    if existing_agent:
        await db.tradingagent.update(where={"id": existing_agent.id}, data=data_payload)
        return True  # Agent was updated, return True to indicate success

    await db.tradingagent.create(
        data={**data_payload, "portfolio_allocation_id": getattr(allocation, "id", None)}
    )
    return True  # Agent was created, return True to indicate success


# ============================================================================
# Celery Tasks
# ============================================================================


# @celery_app.task(name="portfolio.allocate_new_portfolio", bind=True, max_retries=3)
# def allocate_new_portfolio_task(
#     self,
#     portfolio_id: str,
#     user_id: str,
#     organization_id: str,
#     user_inputs: Dict[str, Any],
#     initial_value: float,
# ) -> Dict[str, Any]:
#     """
#     Celery task to run portfolio allocation for a newly created portfolio.
    
#     Args:
#         portfolio_id: Database ID of the portfolio
#         user_id: User who owns the portfolio
#         organization_id: Organization ID
#         user_inputs: Portfolio preferences (risk tolerance, horizon, etc.)
#         initial_value: Initial investment amount
        
#     Returns:
#         Allocation result dictionary
#     """
#     logger.info(f"🚀 allocate_new_portfolio_task RECEIVED: portfolio={portfolio_id}, user={user_id}, org={organization_id}")
#     import asyncio
    
#     async def _allocate():
#         try:
#             logger.info(
#                 f"Starting initial allocation for portfolio {portfolio_id} "
#                 f"(user={user_id}, org={organization_id})"
#             )
            
#             # Get current regime from regime service
#             logger.info(f"Fetching current market regime for portfolio {portfolio_id}...")
#             current_regime = await _get_current_regime()
#             logger.info(f"Current regime: {current_regime}")
            
#             # Build allocation request
#             logger.debug(f"Building allocation request for portfolio {portfolio_id}...")
#             request = {
#                 "request_id": f"initial_{portfolio_id}_{datetime.utcnow().isoformat()}",
#                 "user_id": user_id,
#                 "current_regime": current_regime,
#                 "user_inputs": user_inputs,
#                 "initial_value": initial_value,
#                 "current_value": initial_value,
#                 "metadata": {
#                     "portfolio_id": portfolio_id,
#                     "organization_id": organization_id,
#                     "trigger": "initial_creation",
#                     "timestamp": datetime.utcnow().isoformat(),
#                 }
#             }
#             logger.debug(f"Allocation request built for portfolio {portfolio_id}")
            
#             # Update portfolio status to processing
#             logger.info(f"Connecting to database for portfolio {portfolio_id}...")
#             # Use Prisma directly to avoid event loop issues with DBManager singleton
#             from prisma import Prisma
#             db = Prisma()
#             await db.connect()
#             logger.info(f"Database connected for portfolio {portfolio_id}")
            
#             logger.info(f"Fetching user subscriptions for user {user_id}...")
#             user_subscriptions = await _get_user_subscriptions(db, user_id)
#             logger.info(f"User subscriptions retrieved: {user_subscriptions}")
            
#             logger.info(f"Updating portfolio {portfolio_id} status to 'processing'...")
#             await db.portfolio.update(
#                 where={"id": portfolio_id},
#                 data={"allocation_status": "processing"}
#             )
#             logger.info(f"Portfolio {portfolio_id} status updated to 'processing'")
            
#             # Execute Pathway allocation pipeline in a thread pool to avoid event loop conflicts
#             from concurrent.futures import ThreadPoolExecutor
#             import functools
            
#             loop = asyncio.get_event_loop()
            
#             # Run the synchronous pipeline in a thread pool executor with timeout
#             logger.info(f"Executing allocation pipeline for portfolio {portfolio_id}...")
#             with ThreadPoolExecutor(max_workers=1) as executor:
#                 try:
#                     results = await asyncio.wait_for(
#                         loop.run_in_executor(
#                     executor,
#                     functools.partial(
#                         allocate_portfolios,
#                         [request],
#                         logger=logger,
#                         audit_path=f"/tmp/portfolio_allocations_{portfolio_id}.jsonl"
#                     )
#                         ),
#                         timeout=300.0  # 5 minute timeout
#                 )
#                     logger.info(f"Allocation pipeline completed for portfolio {portfolio_id}")
#                 except asyncio.TimeoutError:
#                     logger.error(f"Allocation pipeline timed out after 5 minutes for portfolio {portfolio_id}")
#                     raise TimeoutError(f"Allocation pipeline timed out for portfolio {portfolio_id}")
            
#             if not results:
#                 logger.error("Allocation pipeline returned no results")
#                 raise ValueError("Allocation pipeline returned no results")
            
#             allocation_result = results[0]
            
#             # Log allocation result for debugging
#             logger.info(
#                 f"Allocation result for portfolio {portfolio_id}: "
#                 f"has_weights={bool(allocation_result.get('weights'))}, "
#                 f"has_weights_json={bool(allocation_result.get('weights_json'))}, "
#                 f"success={allocation_result.get('success', 'N/A')}, "
#                 f"keys={list(allocation_result.keys())}"
#             )
            
#             # Check for weights directly instead of relying on "success" field
#             # Try multiple ways to extract weights
#             weights = None
            
#             # First try direct weights field
#             weights_raw = allocation_result.get("weights")
#             if weights_raw:
#                 weights = _coerce_to_plain_dict(weights_raw)
#                 logger.debug(f"Extracted weights from 'weights' field: {weights}")
            
#             # If not found, try weights_json (might be a string)
#             if not weights:
#                 weights_json_raw = allocation_result.get("weights_json")
#                 if weights_json_raw:
#                     # If it's a string, parse it
#                     if isinstance(weights_json_raw, str):
#                         try:
#                             weights = json.loads(weights_json_raw)
#                             logger.debug(f"Parsed weights from 'weights_json' string: {weights}")
#                         except (json.JSONDecodeError, TypeError):
#                             weights = _coerce_to_plain_dict(weights_json_raw)
#                     else:
#                         weights = _coerce_to_plain_dict(weights_json_raw)
#                     logger.debug(f"Extracted weights from 'weights_json' field: {weights}")
            
#             # If still no weights, log warning but continue with default allocation
#             if not weights:
#                 logger.warning(
#                     f"No weights found in allocation result for portfolio {portfolio_id}. "
#                     f"Result keys: {list(allocation_result.keys())}. "
#                     f"Result sample: {str(allocation_result)[:500]}. "
#                     f"Using defaults from transcript.py."
#                 )
#                 # Use defaults from transcript.py (single source of truth)
#                 from utils.user_inputs_helper import create_user_inputs
#                 default_user_inputs = create_user_inputs(
#                     investment_horizon_years=15,  # Default value
#                     expected_return_target=0.18,  # Default value
#                     risk_tolerance="medium"  # Default value
#                 )
#                 weights = default_user_inputs.get("allocation_strategy", {
#                     "low_risk": 0.6,
#                     "high_risk": 0.2,
#                     "alpha": 0.2,
#                     "liquid": 0.0
#                 })
#                 logger.info(f"Using default weights from transcript.py: {weights}")
            
#             # Validate weights sum to approximately 1.0
#             if weights:
#                 weight_sum = sum(weights.values())
#                 if abs(weight_sum - 1.0) > 0.01:
#                     logger.warning(
#                         f"Weights sum to {weight_sum} instead of 1.0 for portfolio {portfolio_id}. "
#                         f"Normalizing weights."
#                     )
#                     weights = {k: v / weight_sum for k, v in weights.items()}

#             # Ensure downstream consumers receive the resolved weights payload
#             allocation_result["weights"] = weights
            
#             # Get investable amount from portfolio or initial_value
#             portfolio_record = await db.portfolio.find_unique(where={"id": portfolio_id})
#             investable_amount = float(initial_value)
#             if portfolio_record:
#                 investable_amount = float(
#                     portfolio_record.investment_amount or 
#                     portfolio_record.initial_investment or 
#                     initial_value
#                 )
            
#             allocations_created = []
#             trading_agents_created = []

#             for allocation_type, weight in weights.items():
#                 # Calculate allocated amount based on weight
#                 allocated_amount = investable_amount * float(weight)
                
#                 allocation_metadata = {
#                     "request_id": request["request_id"],
#                     "trigger": "initial_creation",
#                     "objective_value": allocation_result.get("objective_value"),
#                     "message": allocation_result.get("message"),
#                 }
#                 allocation_payload = {
#                     "target_weight": float(weight),
#                     "current_weight": float(weight),
#                     "allocated_amount": allocated_amount,
#                     "current_value": allocated_amount,  # Initially same as allocated
#                     "expected_return": allocation_result.get("expected_return"),
#                     "expected_risk": allocation_result.get("expected_risk"),
#                     "regime": current_regime,
#                     "metadata": _encode_json(allocation_metadata),
#                 }

#                 existing_allocation = await db.portfolioallocation.find_first(
#                     where={
#                         "portfolio_id": portfolio_id,
#                         "allocation_type": allocation_type,
#                     }
#                 )

#                 if existing_allocation:
#                     allocation_record = await db.portfolioallocation.update(
#                         where={"id": existing_allocation.id},
#                         data=allocation_payload,
#                     )
#                 else:
#                     allocation_record = await db.portfolioallocation.create(
#                         data={
#                             "portfolio_id": portfolio_id,
#                             "allocation_type": allocation_type,
#                             **allocation_payload,
#                         }
#                     )

#                 agent_context = dict(request.get("metadata") or {})
#                 agent_context["request_id"] = request["request_id"]
#                 agent_context["current_regime"] = current_regime

#                 allocations_created.append(allocation_record)
                
#                 # Create trading agent for this allocation
#                 try:
#                     agent_created = await _ensure_trading_agent(
#                     db,
#                     portfolio_id=portfolio_id,
#                     allocation=allocation_record,
#                     allocation_type=allocation_type,
#                     request_context=agent_context,
#                     objective_id=None,
#                     user_subscriptions=user_subscriptions,
#                 )
#                     if agent_created is not False:
#                         trading_agents_created.append(allocation_type)
#                         logger.info(
#                             f"✅ Created/updated trading agent for allocation {allocation_record.id} "
#                             f"(type: {allocation_type})"
#                         )
#                 except Exception as agent_exc:
#                     logger.error(
#                         f"❌ Failed to create trading agent for allocation {allocation_record.id}: {agent_exc}",
#                         exc_info=True
#                     )
            
#             # Validate that allocations and agents were created
#             if not allocations_created:
#                 raise ValueError(f"No allocations were created for portfolio {portfolio_id}")
            
#             logger.info(
#                 f"✅ Created {len(allocations_created)} allocations and {len(trading_agents_created)} trading agents "
#                 f"for portfolio {portfolio_id}"
#             )
            
#             # Get portfolio record for _persist_allocation_result
#             # Reload portfolio with allocations to ensure we have the latest data
#             try:
#                 portfolio = await db.portfolio.find_unique(
#                     where={"id": portfolio_id},
#                     include={"allocations": True}
#                 )
#             except TypeError:
#                 # Fallback if include is not supported (e.g., in test mocks)
#                 logger.debug("find_unique with include not supported, trying without include")
#                 portfolio = await db.portfolio.find_unique(
#                     where={"id": portfolio_id}
#                 )
            
#             if not portfolio:
#                 raise ValueError(f"Portfolio {portfolio_id} not found after allocation creation")
            
#             # Ensure portfolio has allocations attribute
#             if not hasattr(portfolio, "allocations"):
#                 try:
#                     allocations = await db.portfolioallocation.find_many(
#                         where={"portfolio_id": portfolio_id}
#                     )
#                     portfolio.allocations = allocations
#                 except Exception as alloc_exc:
#                     logger.warning(
#                         f"Failed to fetch allocations for portfolio {portfolio_id}: {alloc_exc}"
#                     )
#                     portfolio.allocations = []
            
#             # Call _persist_allocation_result to create allocation snapshots
#             try:
#                 from services.pipeline_service import PipelineService
#                 # PipelineService expects a string path to the server root
#                 server_root_str = str(Path(__file__).resolve().parents[1])
#                 pipeline_service = PipelineService(server_root_str, logger=logger)
                
#                 allocation_count = len(getattr(portfolio, "allocations", []) or [])
#                 logger.info(
#                     f"Calling _persist_allocation_result for portfolio {portfolio_id} "
#                     f"with {allocation_count} allocations"
#                 )
                
#                 await pipeline_service._persist_allocation_result(
#                     client=db,
#                     portfolio=portfolio,
#                     result=allocation_result,
#                     as_of=datetime.utcnow(),
#                     triggered_by="initial_creation",
#                     trigger_reason="New portfolio initial allocation",
#                 )
#                 logger.info(
#                     f"✅ Created allocation snapshots for portfolio {portfolio_id} "
#                     f"(rebalance run and allocation snapshots)"
#                 )
#             except Exception as snapshot_exc:
#                 logger.error(
#                     f"❌ Failed to create allocation snapshots for portfolio {portfolio_id}: {snapshot_exc}",
#                     exc_info=True
#                 )
#                 # Don't fail the entire task if snapshot creation fails
            
#             # Calculate initial rebalancing date based on frequency from portfolio
#             # Note: rebalancing_frequency is NOT in user_inputs (transcript.py format)
#             # It comes from portfolio model, not user_inputs
#             rebalancing_freq = "quarterly"  # Default
#             if portfolio and portfolio.rebalancing_frequency:
#                 if isinstance(portfolio.rebalancing_frequency, dict):
#                     rebalancing_freq = portfolio.rebalancing_frequency.get("frequency", "quarterly")
#                 elif isinstance(portfolio.rebalancing_frequency, str):
#                     rebalancing_freq = portfolio.rebalancing_frequency
            
#             rebalancing_date = _calculate_next_rebalance_date(rebalancing_freq)
            
#             # Mark portfolio as ready
#             portfolio_metadata = {
#                 "allocated_at": datetime.utcnow(),
#                 "allocation_regime": current_regime,
#             }

#             await db.portfolio.update(
#                 where={"id": portfolio_id},
#                 data={
#                     "allocation_status": "ready",
#                     "rebalancing_date": rebalancing_date,
#                     "last_rebalanced_at": datetime.utcnow(),
#                     "metadata": _encode_json(portfolio_metadata),
#                 },
#             )
            
#             logger.info(
#                 f"✅ Successfully allocated portfolio {portfolio_id}: "
#                 f"{weights} (next rebalance: {rebalancing_date})"
#             )
            
#             return {
#                 "success": True,
#                 "portfolio_id": portfolio_id,
#                 "allocation": allocation_result,
#                 "rebalancing_date": rebalancing_date.isoformat() if rebalancing_date else None,
#             }
            
#         except Exception as exc:
#             # Mark portfolio as failed
#             try:
#                 from prisma import Prisma
#                 error_db = Prisma()
#                 await error_db.connect()
#                 await error_db.portfolio.update(
#                         where={"id": portfolio_id},
#                         data={"allocation_status": "failed"}
#                     )
#                 await error_db.disconnect()
#             except:
#                 pass
#         finally:
#             # Always disconnect database
#             try:
#                 await db.disconnect()
#             except:
#                 pass
            
#             logger.error(
#                 f"❌ Failed to allocate portfolio {portfolio_id}: {exc}",
#                 exc_info=True
#             )
#             raise exc
    
#     # Create a fresh event loop for this task execution to avoid loop closure issues
#     loop = asyncio.new_event_loop()
#     asyncio.set_event_loop(loop)
#     try:
#         return loop.run_until_complete(_allocate())
#     except Exception as exc:
#         # Retry with exponential backoff
#         raise self.retry(exc=exc, countdown=2 ** self.request.retries)
#     finally:
#         # Clean up the loop
#         try:
#             loop.close()
#         except:
#             pass


@celery_app.task(name="portfolio.allocate_for_objective", bind=True, max_retries=3)
def allocate_for_objective_task(
    self,
    portfolio_id: str,
    objective_id: str,
    user_id: str,
    user_inputs: Dict[str, Any],
    initial_value: float,
    available_cash: Optional[float] = None,
    triggered_by: str = "objective_created",
) -> Dict[str, Any]:
    """
    Celery task to run portfolio allocation triggered by an objective being created or completed.
    
    Args:
        portfolio_id: Database ID of the portfolio
        objective_id: Database ID of the objective that triggered this
        user_id: User who owns the portfolio
        user_inputs: Portfolio preferences from objective
        initial_value: Initial investment amount
        available_cash: Available cash in portfolio (defaults to initial_value)
        triggered_by: What triggered this allocation
        
    Returns:
        Allocation result dictionary
    """
    import time
    import asyncio
    
    task_start = time.time()
    logger.info(f"🚀 allocate_for_objective_task RECEIVED: portfolio={portfolio_id}, objective={objective_id}, user={user_id}, triggered_by={triggered_by}")
    
    async def _allocate():
        try:
            logger.info(f"Starting allocation for portfolio {portfolio_id} triggered by {triggered_by}")
            
            # Get current regime from regime service
            regime_start = time.time()
            current_regime = await _get_current_regime()
            logger.info(f"Regime fetch took {time.time() - regime_start:.2f}s: {current_regime}")
            
            # Build allocation request
            request = {
                "request_id": f"{triggered_by}_{portfolio_id}_{datetime.utcnow().isoformat()}",
                "user_id": user_id,
                "current_regime": current_regime,
                "user_inputs": user_inputs,
                "initial_value": initial_value,
                "current_value": available_cash or initial_value,  # Pathway expects current_value
                "metadata": {
                    "portfolio_id": portfolio_id,
                    "objective_id": objective_id,
                    "trigger": triggered_by,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            }
            
            # Update portfolio status to processing
            from dbManager import DBManager
            db_manager = DBManager.get_instance()
            
            db_start = time.time()
            async with db_manager.session() as db:
                user_subscriptions = await _get_user_subscriptions(db, user_id)
                await db.portfolio.update(
                    where={"id": portfolio_id},
                    data={"allocation_status": "processing"}
                )
                logger.info(f"DB operations took {time.time() - db_start:.2f}s")
            
                # Execute Pathway allocation pipeline in a thread pool to avoid event loop conflicts
                # Use asyncio.to_thread to run the synchronous pipeline without blocking the event loop
                from concurrent.futures import ThreadPoolExecutor
                import functools
                
                loop = asyncio.get_event_loop()
                
                # Run the synchronous pipeline in a thread pool executor with timeout
                pipeline_start = time.time()
                logger.info(f"Starting Pathway allocation pipeline for portfolio {portfolio_id}")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    try:
                        results = await asyncio.wait_for(
                            loop.run_in_executor(
                                executor,
                                functools.partial(
                                    allocate_portfolios,
                                    [request],
                                    logger=logger,
                                    audit_path=f"/tmp/portfolio_allocations_{portfolio_id}_{objective_id}.jsonl"
                                )
                            ),
                            timeout=60.0  # 60 second timeout (reduced from 5 minutes)
                        )
                        pipeline_duration = time.time() - pipeline_start
                        logger.info(f"✅ Pathway pipeline completed in {pipeline_duration:.2f}s")
                    except asyncio.TimeoutError:
                        logger.error(f"Allocation pipeline timed out after 60s for portfolio {portfolio_id}")
                        raise TimeoutError(f"Allocation pipeline timed out for portfolio {portfolio_id}")
                
                if not results:
                    logger.error("Allocation pipeline returned no results")
                    raise ValueError("Allocation pipeline returned no results")
                
                allocation_result = results[0]
                
                # Check for weights directly instead of relying on "success" field
                # Try multiple ways to extract weights
                weights = None
                
                # First try direct weights field
                weights_raw = allocation_result.get("weights")
                if weights_raw:
                    weights = _coerce_to_plain_dict(weights_raw)
                
                # If not found, try weights_json (might be a string)
                if not weights:
                    weights_json_raw = allocation_result.get("weights_json")
                    if weights_json_raw:
                        # If it's a string, parse it
                        if isinstance(weights_json_raw, str):
                            try:
                                weights = json.loads(weights_json_raw)
                            except (json.JSONDecodeError, TypeError):
                                weights = _coerce_to_plain_dict(weights_json_raw)
                        else:
                            weights = _coerce_to_plain_dict(weights_json_raw)
                
                # If still no weights, log warning but continue with default allocation
                if not weights:
                    logger.warning(f"No weights found for portfolio {portfolio_id}, using defaults")
                    # Use defaults from transcript.py (single source of truth)
                    from utils.user_inputs_helper import create_user_inputs
                    default_user_inputs = create_user_inputs(
                        investment_horizon_years=15,  # Default value
                        expected_return_target=0.18,  # Default value
                        risk_tolerance="medium"  # Default value
                    )
                    weights = default_user_inputs.get("allocation_strategy", {
                        "low_risk": 0.6,
                        "high_risk": 0.15,
                        "alpha": 0.15,
                        "liquid": 0.1
                    })
                    logger.info(f"Using default weights from transcript.py: {weights}")
                
                # Validate weights sum to approximately 1.0
                if weights:
                    weight_sum = sum(weights.values())
                    if abs(weight_sum - 1.0) > 0.01:
                        logger.warning(
                            f"Weights sum to {weight_sum} instead of 1.0 for portfolio {portfolio_id}. "
                            f"Normalizing weights."
                        )
                        weights = {k: v / weight_sum for k, v in weights.items()}
    
                # Ensure downstream consumers receive the resolved weights payload
                allocation_result["weights"] = weights
                
                # Get investable amount from portfolio or initial_value
                # Retry a few times in case of database replication delay
                portfolio_record = None
                max_retries = 3
                for retry in range(max_retries):
                    portfolio_record = await db.portfolio.find_unique(where={"id": portfolio_id})
                    if portfolio_record:
                        break
                    if retry < max_retries - 1:
                        logger.info(f"Portfolio {portfolio_id} not found, retrying in 2 seconds... (attempt {retry + 1}/{max_retries})")
                        await asyncio.sleep(2)
                
                if not portfolio_record:
                    logger.warning(
                        f"⚠️ Portfolio {portfolio_id} not found in database after {max_retries} retries. "
                        f"Skipping allocation creation. This may be a test/demo portfolio ID."
                    )
                    return {
                        "status": "skipped",
                        "reason": "portfolio_not_found",
                        "portfolio_id": portfolio_id,
                        "objective_id": objective_id,
                        "message": f"Portfolio {portfolio_id} not found in database",
                    }
                
                investable_amount = float(
                    portfolio_record.investment_amount or 
                    portfolio_record.initial_investment or 
                    initial_value
                )
                
                logger.info(f"💰 Investable amount: {investable_amount}, Weights: {weights}")
                logger.info(f"🔄 Starting allocation creation loop for {len(weights)} segments...")
                
                allocations_created = []
                trading_agents_created = []
    
                for allocation_type, weight in weights.items():
                    logger.info(f"🔹 Processing allocation: type={allocation_type}, weight={weight}")
                    
                    # Calculate allocated amount based on weight
                    allocated_amount = investable_amount * float(weight)
                    
                    allocation_metadata = {
                        "request_id": request["request_id"],
                        "objective_id": objective_id,
                        "trigger": triggered_by,
                        "objective_value": allocation_result.get("objective_value"),
                        "message": allocation_result.get("message"),
                    }
    
                    allocation_payload = {
                        "target_weight": float(weight),
                        "current_weight": float(weight),
                        "allocated_amount": allocated_amount,
                        "available_cash": allocated_amount,  # Initially same as allocated
                        "expected_return": allocation_result.get("expected_return"),
                        "expected_risk": allocation_result.get("expected_risk"),
                        "regime": current_regime,
                        "metadata": _encode_json(allocation_metadata),
                    }
    
                    existing_allocation = await db.portfolioallocation.find_first(
                        where={
                            "portfolio_id": portfolio_id,
                            "allocation_type": allocation_type,
                        }
                    )
    
                    if existing_allocation:
                        allocation_record = await db.portfolioallocation.update(
                            where={"id": existing_allocation.id},
                            data=allocation_payload,
                        )
                    else:
                        allocation_record = await db.portfolioallocation.create(
                            data={
                                "portfolio_id": portfolio_id,
                                "allocation_type": allocation_type,
                                **allocation_payload,
                            },
                        )
    
                    agent_context = dict(request.get("metadata") or {})
                    agent_context["request_id"] = request["request_id"]
                    agent_context["current_regime"] = current_regime
    
                    allocations_created.append(allocation_record)
                    
                    # Create trading agent for this allocation
                    try:
                        agent_created = await _ensure_trading_agent(
                        db,
                        portfolio_id=portfolio_id,
                        allocation=allocation_record,
                        allocation_type=allocation_type,
                        request_context=agent_context,
                        objective_id=objective_id,
                        user_subscriptions=user_subscriptions,
                    )
                        if agent_created is not False:
                            trading_agents_created.append(allocation_type)
                            logger.info(
                                f"✅ Created/updated trading agent for allocation {allocation_record.id} "
                                f"(type: {allocation_type})"
                            )
                    except Exception as agent_exc:
                        logger.error(
                            f"❌ Failed to create trading agent for allocation {allocation_record.id}: {agent_exc}",
                            exc_info=True
                        )
                
                # Validate that allocations and agents were created
                if not allocations_created:
                    raise ValueError(f"No allocations were created for portfolio {portfolio_id}")
                
                logger.info(
                    f"✅ Created {len(allocations_created)} allocations and {len(trading_agents_created)} trading agents "
                    f"for portfolio {portfolio_id}"
                )
                
                # Get portfolio record for _persist_allocation_result
                # Reload portfolio with allocations to ensure we have the latest data
                try:
                    portfolio = await db.portfolio.find_unique(
                        where={"id": portfolio_id},
                        include={"allocations": True}
                    )
                except TypeError:
                    # Fallback if include is not supported (e.g., in test mocks)
                    logger.debug("find_unique with include not supported, trying without include")
                    portfolio = await db.portfolio.find_unique(
                        where={"id": portfolio_id}
                    )
                
                if not portfolio:
                    raise ValueError(f"Portfolio {portfolio_id} not found after allocation creation")
                
                # Ensure portfolio has allocations attribute
                if not hasattr(portfolio, "allocations"):
                    try:
                        allocations = await db.portfolioallocation.find_many(
                            where={"portfolio_id": portfolio_id}
                        )
                        portfolio.allocations = allocations
                    except Exception as alloc_exc:
                        logger.warning(
                            f"Failed to fetch allocations for portfolio {portfolio_id}: {alloc_exc}"
                        )
                        portfolio.allocations = []
                
                # Call _persist_allocation_result to create allocation snapshots
                try:
                    from services.pipeline_service import PipelineService
                    # PipelineService expects a string path to the server root
                    server_root_str = str(Path(__file__).resolve().parents[1])
                    pipeline_service = PipelineService(server_root_str, logger=logger)
                    
                    allocation_count = len(getattr(portfolio, "allocations", []) or [])
                    logger.info(
                        f"Calling _persist_allocation_result for portfolio {portfolio_id} "
                        f"with {allocation_count} allocations"
                    )
                    
                    await pipeline_service._persist_allocation_result(
                        client=db,
                        portfolio=portfolio,
                        result=allocation_result,
                        as_of=datetime.utcnow(),
                        triggered_by=triggered_by,
                        trigger_reason=f"Objective {objective_id} allocation",
                    )
                    logger.info(
                        f"✅ Created allocation snapshots for portfolio {portfolio_id} "
                        f"(rebalance run and allocation snapshots)"
                    )
                except Exception as snapshot_exc:
                    logger.error(
                        f"❌ Failed to create allocation snapshots for portfolio {portfolio_id}: {snapshot_exc}",
                        exc_info=True
                    )
                    # Don't fail the entire task if snapshot creation fails
                
                # Calculate next rebalancing date based on frequency from portfolio
                # Note: rebalancing_frequency is NOT in user_inputs (transcript.py format)
                # It comes from portfolio model, not user_inputs
                rebalancing_freq = "quarterly"  # Default
                if portfolio and portfolio.rebalancing_frequency:
                    if isinstance(portfolio.rebalancing_frequency, dict):
                        rebalancing_freq = portfolio.rebalancing_frequency.get("frequency", "quarterly")
                    elif isinstance(portfolio.rebalancing_frequency, str):
                        rebalancing_freq = portfolio.rebalancing_frequency
                
                rebalancing_date = _calculate_next_rebalance_date(rebalancing_freq)
                
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
                
                total_duration = time.time() - task_start
                logger.info(
                    f"✅ Portfolio {portfolio_id} allocated in {total_duration:.2f}s | "
                    f"{len(allocations_created)} allocations, {len(trading_agents_created)} agents | "
                    f"Weights: {weights}"
                )
                
                return {
                    "success": True,
                    "portfolio_id": portfolio_id,
                    "objective_id": objective_id,
                    "allocations_created": len(allocations_created),
                    "trading_agents_created": len(trading_agents_created),
                    "allocation": allocation_result,
                    "rebalancing_date": rebalancing_date.isoformat() if rebalancing_date else None,
                    "last_rebalanced_at": datetime.utcnow().isoformat(),
                    "next_rebalance_at": rebalancing_date.isoformat() if rebalancing_date else None,
                    "duration_seconds": total_duration,
                }
            
        except Exception as exc:
            # Mark portfolio as failed
            try:
                # Use DBManager session for error handling
                from dbManager import DBManager
                error_db_manager = DBManager.get_instance()
                async with error_db_manager.session() as error_db:
                    await error_db.portfolio.update(
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
    except (ValueError, KeyError) as exc:
        # Don't retry on bad input data (missing portfolio, invalid config, etc.)
        logger.error(
            f"Allocation task failed with invalid input (portfolio={portfolio_id}, "
            f"objective={objective_id}): {exc}. Not retrying."
        )
        raise exc
    except Exception as exc:
        # Retry transient errors with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        # Clean up the loop
        try:
            loop.close()
        except:
            pass


@celery_app.task(
    name="portfolio.check_regime_and_rebalance",
    bind=True,
    soft_time_limit=600,  # 10 minutes soft limit
    time_limit=660,  # 11 minutes hard limit
    acks_late=False,  # Acknowledge immediately to prevent re-queue
)
def check_regime_and_rebalance_task(self) -> Dict[str, Any]:
    """
    Daily Celery beat task that runs 1 hour before market open (8:15 AM for 9:15 AM market).
    
    This task:
    1. Calculates current market regime
    2. Compares with previous regime (stored in Redis/cache)
    3. If regime changed: Triggers rebalancing for ALL active portfolios
    4. If regime same: Only rebalances portfolios with rebalancing_date <= today
    5. Also handles pending portfolios (allocation_status="pending")
    
    Market Timing:
    - NSE/BSE opens at 9:15 AM IST
    - This runs at 8:15 AM IST (1 hour before)
    - Ensures portfolios are rebalanced before market opens
    
    Returns:
        Summary of regime check and rebalancing operations
    """
    import asyncio
    
    async def _check_and_rebalance():
        try:
            redis_client = None
            lock_acquired = False
            lock_owner = None
            lock_key = os.getenv("REGIME_TASK_LOCK_KEY", "locks:regime:check")
            lock_ttl = int(os.getenv("REGIME_TASK_LOCK_TTL", "900"))

            redis_url = os.getenv("REGIME_LOCK_REDIS_URL") or os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
            try:
                import redis

                redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
            except Exception as redis_exc:
                logger.warning(
                    f"Regime lock disabled - Redis unavailable ({redis_url}): {redis_exc}"
                )
                redis_client = None

            if redis_client:
                host = os.getenv("HOSTNAME") or getattr(os, "uname", lambda: type("U", (), {"nodename": "unknown"})())().nodename  # type: ignore[misc]
                lock_owner = f"{host}:{os.getpid()}:{uuid.uuid4()}"
                try:
                    lock_acquired = bool(
                        redis_client.set(lock_key, lock_owner, nx=True, ex=lock_ttl)
                    )
                except Exception as lock_exc:
                    logger.warning(f"Failed to acquire regime lock: {lock_exc}")
                    lock_acquired = False

                if not lock_acquired:
                    logger.info(
                        f"Skipping regime check; lock '{lock_key}' already held by {redis_client.get(lock_key) if redis_client else 'unknown'}"
                    )
                    return {
                        "success": True,
                        "skipped": True,
                        "reason": "regime_check_in_progress",
                        "portfolios_checked": 0,
                        "pending_allocated": 0,
                        "due_date_rebalanced": 0,
                        "regime_change_rebalanced": 0,
                        "regime_changed": False,
                        "current_regime": None,
                        "previous_regime": None,
                    }

            # Use DBManager with session context manager for proper connection handling
            from dbManager import DBManager
            db_manager = DBManager.get_instance()
            
            async with db_manager.session() as db:
                today = datetime.now()
                logger.info(f"🔍 Running regime check and rebalancing sweep for {today.date()}")
                
                # Calculate current market regime
                logger.info("📊 Calculating current market regime...")
                current_regime = await _get_current_regime()
                logger.info(f"Current regime: {current_regime}")
                
                # Get previous regime from cache/database
                try:
                    if redis_client is None:
                        raise RuntimeError("Redis unavailable for regime cache")

                    previous_regime = redis_client.get("market:regime:current")
                    regime_changed = (
                        previous_regime is not None and previous_regime != current_regime
                    )

                    redis_client.set("market:regime:current", current_regime)
                    redis_client.set("market:regime:last_updated", datetime.utcnow().isoformat())

                    if regime_changed:
                        logger.warning(
                            f"🚨 REGIME CHANGE DETECTED: {previous_regime} → {current_regime}. "
                            f"Triggering rebalancing for ALL active portfolios."
                        )
                    else:
                        logger.info(
                            f"✅ Regime unchanged ({current_regime}). "
                            f"Only rebalancing portfolios with due dates."
                        )
                except Exception as redis_exc:
                    logger.warning(f"Failed to check previous regime from Redis: {redis_exc}")
                    regime_changed = False  # Default to no change if Redis unavailable
                    previous_regime = current_regime
                
                # 1. Find pending portfolios (never allocated) - always process these
                pending_portfolios = await db.portfolio.find_many(
                    where={
                        "AND": [
                            {"allocation_status": "pending"},
                            {"status": "active"},
                        ]
                    },
                    include={
                        "allocations": True,
                    }
                )
                
                # 2. Find portfolios due for rebalancing (rebalancing_date <= today)
                portfolios_to_rebalance = await db.portfolio.find_many(
                    where={
                        "AND": [
                            {"rebalancing_date": {"lte": today}},
                            {"rebalancing_date": {"not": None}},
                            {"allocation_status": "ready"},
                            {"status": "active"},
                        ]
                    },
                    include={
                        "allocations": True,
                    }
                )
                
                # 3. If regime changed, add ALL active portfolios for rebalancing
                regime_change_portfolios = []
                if regime_changed:
                    regime_change_portfolios = await db.portfolio.find_many(
                        where={
                            "AND": [
                                {"allocation_status": "ready"},
                                {"status": "active"},
                            ]
                        },
                        include={
                            "allocations": True,
                        }
                    )
                    # Remove duplicates (portfolios already in rebalancing list)
                    rebalance_ids = {p.id for p in portfolios_to_rebalance}
                    regime_change_portfolios = [
                        p for p in regime_change_portfolios 
                        if p.id not in rebalance_ids
                    ]
                
                all_portfolios = pending_portfolios + portfolios_to_rebalance + regime_change_portfolios
                
                if not all_portfolios:
                    logger.info(
                        f"No portfolios need attention. "
                        f"Regime: {current_regime} (changed: {regime_changed})"
                    )
                    return {
                        "success": True,
                        "portfolios_checked": 0,
                        "pending_allocated": 0,
                        "due_date_rebalanced": 0,
                        "regime_change_rebalanced": 0,
                        "regime_changed": regime_changed,
                        "current_regime": current_regime,
                        "previous_regime": previous_regime,
                    }
                
                logger.info(
                    f"Found: {len(pending_portfolios)} pending, "
                    f"{len(portfolios_to_rebalance)} due for rebalancing, "
                    f"{len(regime_change_portfolios)} regime-change rebalancing"
                )
                
                # Build allocation requests for all portfolios
                requests = []
                portfolio_map = {}
                
                # Process pending portfolios (initial allocation)
                for portfolio in pending_portfolios:
                    # Build user inputs from portfolio (matching transcript.py format)
                    from utils.user_inputs_helper import extract_user_inputs_from_portfolio
                    user_inputs = extract_user_inputs_from_portfolio(portfolio)
                    
                    request = {
                        "request_id": f"initial_allocation_{portfolio.id}_{today.isoformat()}",
                        "user_id": portfolio.customer_id,
                        "current_regime": current_regime,
                        "user_inputs": user_inputs,
                        "initial_value": float(portfolio.investment_amount),
                        "current_value": float(portfolio.available_cash or portfolio.investment_amount),
                        "metadata": {
                            "portfolio_id": portfolio.id,
                            "trigger": "initial_allocation",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    }
                    requests.append(request)
                    portfolio_map[portfolio.id] = {
                        "portfolio": portfolio,
                        "is_initial": True,
                        "rebalancing_freq": "quarterly",  # Default
                    }
                
                # Process portfolios due for rebalancing
                for portfolio in portfolios_to_rebalance:
                    # Build user inputs from portfolio (matching transcript.py format)
                    from utils.user_inputs_helper import extract_user_inputs_from_portfolio
                    user_inputs = extract_user_inputs_from_portfolio(portfolio)
                    
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
                    
                    days_overdue = (today.date() - portfolio.rebalancing_date).days if portfolio.rebalancing_date else 0
                    
                    request = {
                        "request_id": f"rebalance_{portfolio.id}_{today.isoformat()}",
                        "user_id": portfolio.customer_id,
                        "current_regime": current_regime,
                        "user_inputs": user_inputs,
                        "initial_value": float(portfolio.investment_amount),
                        "current_value": float(portfolio.available_cash),  # Pathway expects current_value
                        "value_history": value_history,
                        "metadata": {
                            "portfolio_id": portfolio.id,
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
                        "is_initial": False,
                        "is_regime_change": False,
                        "rebalancing_freq": rebalancing_freq,
                    }
                
                # Process portfolios needing regime-change rebalancing
                for portfolio in regime_change_portfolios:
                    # Build user inputs from portfolio (matching transcript.py format)
                    from utils.user_inputs_helper import extract_user_inputs_from_portfolio
                    user_inputs = extract_user_inputs_from_portfolio(portfolio)
                    
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
                    
                    request = {
                        "request_id": f"regime_change_{portfolio.id}_{today.isoformat()}",
                        "user_id": portfolio.customer_id,
                        "current_regime": current_regime,
                        "user_inputs": user_inputs,
                        "initial_value": float(portfolio.investment_amount),
                        "current_value": float(portfolio.available_cash),
                        "value_history": value_history,
                        "metadata": {
                            "portfolio_id": portfolio.id,
                            "trigger": "regime_change",
                            "previous_regime": previous_regime,
                            "current_regime": current_regime,
                            "rebalancing_frequency": rebalancing_freq,
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    }
                    requests.append(request)
                    portfolio_map[portfolio.id] = {
                        "portfolio": portfolio,
                        "is_initial": False,
                        "is_regime_change": True,
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
                initial_allocated_count = 0
                due_date_rebalanced_count = 0
                regime_change_rebalanced_count = 0
                failed_count = 0
                
                for i, result in enumerate(results):
                    request = requests[i]
                    portfolio_data = portfolio_map[request["metadata"]["portfolio_id"]]
                    portfolio = portfolio_data["portfolio"]
                    rebalancing_freq = portfolio_data["rebalancing_freq"]
                    is_initial = portfolio_data.get("is_initial", False)
                    is_regime_change = portfolio_data.get("is_regime_change", False)
                    
                    if result.get("success"):
                        try:
                            # Save new allocation weights
                            weights = _coerce_to_plain_dict(result.get("weights"))
                            if not weights:
                                weights = _coerce_to_plain_dict(result.get("weights_json"))

                            owner_id = getattr(portfolio, "user_id", None) or getattr(portfolio, "customer_id", None)
                            user_subscriptions = await _get_user_subscriptions(db, owner_id)
                            
                            # Determine trigger type
                            if is_initial:
                                trigger = "initial_allocation"
                            elif is_regime_change:
                                trigger = "regime_change"
                            else:
                                trigger = "scheduled_rebalancing"

                            for allocation_type, weight in weights.items():
                                allocation_metadata = {
                                    "request_id": request["request_id"],
                                    "trigger": trigger,
                                    "objective_value": result.get("objective_value"),
                                    "drift": result.get("drift"),
                                    "regime": current_regime,
                                }
                                
                                if is_regime_change:
                                    allocation_metadata["previous_regime"] = previous_regime
                                    allocation_metadata["regime_changed"] = True
                                elif not is_initial:
                                    allocation_metadata["days_overdue"] = request["metadata"].get("days_overdue", 0)

                                allocation_payload = {
                                    "target_weight": float(weight),
                                    "current_weight": float(weight),
                                    "expected_return": result.get("expected_return"),
                                    "expected_risk": result.get("expected_risk"),
                                    "regime": current_regime,
                                    "metadata": _encode_json(allocation_metadata),
                                }

                                existing_allocation = await db.portfolioallocation.find_first(
                                    where={
                                        "portfolio_id": portfolio.id,
                                        "allocation_type": allocation_type,
                                    }
                                )

                                if existing_allocation:
                                    allocation_record = await db.portfolioallocation.update(
                                        where={"id": existing_allocation.id},
                                        data=allocation_payload,
                                    )
                                else:
                                    allocation_record = await db.portfolioallocation.create(
                                        data={
                                            "portfolio_id": portfolio.id,
                                            "allocation_type": allocation_type,
                                            **allocation_payload,
                                        },
                                    )

                                agent_context = dict(request.get("metadata") or {})
                                agent_context["request_id"] = request["request_id"]
                                agent_context["current_regime"] = current_regime

                                await _ensure_trading_agent(
                                    db,
                                    portfolio_id=portfolio.id,
                                    allocation=allocation_record,
                                    allocation_type=allocation_type,
                                    request_context=agent_context,
                                    objective_id=getattr(portfolio, "objective_id", None),
                                    user_subscriptions=user_subscriptions,
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
                            
                            if is_initial:
                                initial_allocated_count += 1
                                logger.info(
                                    f"✅ Initial allocation completed for portfolio {portfolio.id} "
                                    f"(weights: {weights}, next: {next_rebalance})"
                                )
                            elif is_regime_change:
                                regime_change_rebalanced_count += 1
                                logger.info(
                                    f"✅ Regime-change rebalancing completed for portfolio {portfolio.id} "
                                    f"({previous_regime} → {current_regime}, weights: {weights})"
                                )
                            else:
                                due_date_rebalanced_count += 1
                                logger.info(
                                    f"✅ Scheduled rebalancing completed for portfolio {portfolio.id} "
                                    f"(weights: {weights}, next: {next_rebalance})"
                                )
                        except Exception as save_exc:
                            logger.error(
                                f"❌ Failed to save allocation results for {portfolio.id}: {save_exc}",
                                exc_info=True
                            )
                            failed_count += 1
                    else:
                        logger.error(
                            f"❌ Failed to allocate portfolio {portfolio.id}: "
                            f"{result.get('message')}"
                        )
                        failed_count += 1
                
                return {
                    "success": True,
                    "portfolios_checked": len(all_portfolios),
                    "pending_allocated": initial_allocated_count,
                    "due_date_rebalanced": due_date_rebalanced_count,
                    "regime_change_rebalanced": regime_change_rebalanced_count,
                    "portfolios_failed": failed_count,
                    "date": today.isoformat(),
                    "regime_changed": regime_changed,
                    "current_regime": current_regime,
                    "previous_regime": previous_regime,
                }
            
        except Exception as exc:
            logger.error(f"❌ Regime check and rebalancing failed: {exc}", exc_info=True)
            return {
                "success": False,
                "error": str(exc),
            }
        finally:
            if redis_client and lock_acquired and lock_owner:
                try:
                    current_holder = redis_client.get(lock_key)
                    if current_holder == lock_owner:
                        redis_client.delete(lock_key)
                        logger.debug(f"Released regime lock {lock_key}")
                except Exception as release_exc:
                    logger.warning(f"Failed to release regime lock {lock_key}: {release_exc}")
    
    # Create a fresh event loop for this task execution to avoid loop closure issues
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_check_and_rebalance())
    finally:
        # Clean up the loop
        try:
            loop.close()
        except:
            pass


@celery_app.task(name="portfolio.retrain_regime_model", bind=True)
def retrain_regime_model_task(self):
    """
    Retrain the HMM-based regime classification model with fresh historical data.
    
    This task runs daily at 8:30 AM IST (before market opens at 9:15 AM) to ensure
    the regime model is updated with the latest market data for optimal predictions.
    
    The model is trained on 2+ years of historical NSE (Nifty 50) data using yfinance
    to avoid Angel One rate limits.
    
    Returns:
        Dictionary with training results including success status, regime names, and sample count
    """
    logger.info("🔄 Starting daily regime model retraining task...")
    
    try:
        from services.regime_service import RegimeService
        from datetime import datetime
        
        # Get RegimeService singleton
        regime_service = RegimeService.get_instance()
        
        # Retrain model with data from 2020 to present
        result = regime_service.retrain_model(
            start_date="2020-01-01",
            end_date=None,  # Use current date
            n_regimes=4
        )
        
        if result.get("success"):
            logger.info(
                f"✅ Regime model retrained successfully | "
                f"Samples: {result.get('training_samples', 0)} | "
                f"Regimes: {list(result.get('regimes', {}).values())}"
            )
        else:
            logger.error(f"❌ Regime model retraining failed: {result.get('message')}")
        
        return result
        
    except Exception as exc:
        logger.error(f"❌ Regime model retraining task failed: {exc}", exc_info=True)
        return {
            "success": False,
            "message": f"Task execution failed: {str(exc)}",
            "regimes": {},
            "training_samples": 0
        }
