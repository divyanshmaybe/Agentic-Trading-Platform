"""
Utilities for invoking the portfolio allocation pipeline.

These helpers provide a thin abstraction over the Pathway pipeline so that
service layers (e.g. user onboarding flows or scheduled rebalancing tasks) can
request allocations without dealing with the underlying streaming primitives.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

# Suppress verbose Pathway sink logging
os.environ.setdefault("PATHWAY_LOG_LEVEL", "WARNING")
logging.getLogger("pathway").setLevel(logging.WARNING)
logging.getLogger("pathway.io").setLevel(logging.WARNING)
logging.getLogger("pathway.io.kafka").setLevel(logging.WARNING)

# Ensure the pipelines package is importable when executed from workers or scripts.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipelines.portfolio import (  # type: ignore  # noqa: E402
    PortfolioAllocationRequest,
    run_portfolio_allocation_requests,
)

LOGGER = logging.getLogger(__name__)


def prepare_allocation_requests(
    raw_requests: Iterable[Mapping[str, Any]],
    *,
    default_regime: str = "sideways",
) -> List[PortfolioAllocationRequest]:
    """
    Convert raw dictionaries into ``PortfolioAllocationRequest`` instances.

    Each raw request must contain the following keys:
        - ``user_id``
        - ``user_inputs`` (dict with optimisation preferences)
        - ``initial_value`` (float)

    Optional keys:
        - ``current_regime`` (defaults to ``default_regime``)
        - ``current_value``
        - ``value_history``
        - ``segment_history``
        - ``use_rolling_metrics``
        - ``lookback_semi_annual``
        - ``metadata``

    Args:
        raw_requests: Iterable of dictionaries describing rebalance requests.
        default_regime: Fallback regime when not specified.

    Returns:
        List of ``PortfolioAllocationRequest`` objects ready for execution.
    """

    requests: List[PortfolioAllocationRequest] = []
    for item in raw_requests:
        try:
            request_id = str(item.get("request_id") or item.get("user_id") or len(requests))
            request = PortfolioAllocationRequest(
                request_id=request_id,
                user_id=str(item["user_id"]),
                current_regime=str(item.get("current_regime", default_regime)),
                user_inputs=dict(item["user_inputs"]),
                initial_value=float(item["initial_value"]),
                current_value=item.get("current_value"),
                value_history=item.get("value_history"),
                segment_history=item.get("segment_history"),
                use_rolling_metrics=bool(item.get("use_rolling_metrics", True)),
                lookback_semi_annual=int(item.get("lookback_semi_annual", 4)),
                metadata=dict(item.get("metadata", {})),
            )
            requests.append(request)
        except Exception as e:
            # Log but don't crash - skip invalid requests
            import logging
            logging.getLogger(__name__).error(f"❌ Failed to prepare allocation request: {e}. Item: {item}", exc_info=True)
    return requests


def allocate_portfolios(
    requests: Sequence[Mapping[str, Any]],
    *,
    logger: Optional[logging.Logger] = None,
    audit_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Execute the allocation pipeline for the provided requests.

    This helper is typically invoked by:
        * User onboarding workflows to establish an initial allocation.
        * Scheduled rebalancing jobs when a user's rebalance window is reached.

    Args:
        requests: Sequence of dictionaries accepted by ``prepare_allocation_requests``.
        logger: Optional logger; defaults to module-level logger.
        audit_path: Optional filesystem path where allocations will additionally
            be persisted as JSON Lines for auditing.

    Returns:
        List of allocation result dictionaries matching ``AllocationResultSchema``.
    """

    logger = logger or LOGGER
    prepared = prepare_allocation_requests(requests)
    
    logger.info(f"📋 prepare_allocation_requests returned {len(prepared)} prepared requests from {len(requests)} raw requests")
    
    if not prepared:
        logger.warning(f"⚠️ No allocation requests prepared! Raw requests: {requests}")
        logger.info("No allocation requests received; returning empty result set.")
        return []

    logger.info("Executing portfolio allocation pipeline for %s request(s)", len(prepared))
    try:
        results = run_portfolio_allocation_requests(prepared, logger=logger, write_to_path=audit_path)
        logger.info("Portfolio allocation pipeline completed with %s result(s)", len(results))
        return results
    except Exception as exc:
        logger.error(f"Portfolio allocation pipeline failed: {exc}", exc_info=True)
        raise

