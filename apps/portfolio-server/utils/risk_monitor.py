"""
Helpers for preparing inputs to the Pathway risk monitoring pipeline.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from pipelines.risk import RiskMonitorRequest  # type: ignore  # noqa: E402


DEFAULT_THRESHOLD_MAP = {
    "low": 3.0,
    "very_low": 2.0,
    "conservative": 3.0,
    "moderate": 5.0,
    "balanced": 5.0,
    "growth": 7.0,
    "aggressive": 8.0,
    "high": 10.0,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:
        return default


def _as_dict(obj: Any) -> Mapping[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return obj
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    if hasattr(obj, "__slots__"):
        return {slot: getattr(obj, slot) for slot in getattr(obj, "__slots__", [])}
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return {}


def _extract_metadata(raw: Any) -> Mapping[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str):
        try:
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, Mapping) else {}
        except Exception:
            return {}
    return _as_dict(raw)


def _derive_threshold(
    portfolio_meta: Mapping[str, Any],
    position_meta: Mapping[str, Any],
    risk_tolerance: str,
    fallback: float = 5.0,
) -> float:
    override = position_meta.get("risk_threshold_pct") or portfolio_meta.get("risk_threshold_pct")
    if override is not None:
        return abs(_safe_float(override, fallback))

    tolerance = (risk_tolerance or "").strip().lower()
    if not tolerance:
        return fallback

    return abs(DEFAULT_THRESHOLD_MAP.get(tolerance, fallback))


def _extract_contact_emails(
    portfolio_meta: Mapping[str, Any],
    position_meta: Mapping[str, Any],
) -> Sequence[str]:
    candidates = []
    for key in ("alert_emails", "risk_emails", "contact_emails"):
        if key in position_meta:
            candidates = position_meta[key]
            break
        if key in portfolio_meta:
            candidates = portfolio_meta[key]
            break
    if isinstance(candidates, str):
        return [candidates]
    if isinstance(candidates, Sequence):
        return [str(item) for item in candidates if item]
    return []


def prepare_risk_monitor_requests(
    positions: Iterable[Any],
    *,
    market_data_service: Optional[Any] = None,
    logger: Optional[logging.Logger] = None,
) -> List[RiskMonitorRequest]:
    """
    Convert Prisma position records into RiskMonitorRequest objects.
    """

    logger = logger or logging.getLogger(__name__)
    requests: List[RiskMonitorRequest] = []

    for position in positions:
        portfolio = getattr(position, "portfolio", None)
        if portfolio is None:
            logger.debug("Skipping position %s with no portfolio relation", getattr(position, "id", "<unknown>"))
            continue

        portfolio_meta = _extract_metadata(getattr(portfolio, "metadata", None))
        position_meta = _extract_metadata(getattr(position, "metadata", None))

        symbol = getattr(position, "symbol", None)
        if not symbol:
            logger.debug("Skipping position %s with missing symbol", getattr(position, "id", "<unknown>"))
            continue

        quantity = _safe_float(getattr(position, "quantity", 0))
        average_price = _safe_float(getattr(position, "average_buy_price", 0))
        current_price = _safe_float(getattr(position, "current_price", 0))
        raw_day_change = position_meta.get("intraday_change_pct")
        day_change_pct = _safe_float(raw_day_change) if raw_day_change is not None else None
        total_change_pct = _safe_float(
            getattr(position, "pnl_percentage", position_meta.get("total_change_pct", 0.0))
        )

        # Refresh current price from market data service if available
        if market_data_service and hasattr(market_data_service, "get_latest_price"):
            try:
                market_data_service.register_symbol(symbol)
            except Exception:
                pass
            latest_price = market_data_service.get_latest_price(symbol)
            if latest_price is not None and latest_price > 0:
                current_price = float(latest_price)

        threshold_pct = _derive_threshold(
            portfolio_meta,
            position_meta,
            getattr(portfolio, "risk_tolerance", "") or portfolio_meta.get("risk_tolerance", ""),
        )

        contact_emails = _extract_contact_emails(portfolio_meta, position_meta)

        request = RiskMonitorRequest(
            request_id=str(getattr(position, "id", uuid.uuid4())),
            user_id=str(getattr(portfolio, "user_id", "") or getattr(portfolio, "customer_id", "") or getattr(portfolio, "organization_id", "")),
            portfolio_id=str(getattr(portfolio, "id")),
            portfolio_name=str(getattr(portfolio, "portfolio_name", "Portfolio")),
            symbol=str(symbol),
            quantity=quantity,
            average_price=average_price,
            current_price=current_price,
            threshold_pct=threshold_pct,
            risk_tolerance=str(getattr(portfolio, "risk_tolerance", portfolio_meta.get("risk_tolerance", "unknown"))),
            contact_emails=contact_emails,
            day_change_pct=_safe_float(day_change_pct, None) if day_change_pct is not None else None,
            total_change_pct=total_change_pct,
            organization_id=getattr(portfolio, "organization_id", None),
            customer_id=getattr(portfolio, "customer_id", None),
            exchange=getattr(position, "exchange", None),
            segment=getattr(position, "segment", None),
            metadata={
                "position_id": str(getattr(position, "id", "")),
                "position_type": getattr(position, "position_type", None),
                "captured_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        requests.append(request)

    return requests


__all__ = ["prepare_risk_monitor_requests"]

