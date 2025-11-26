"""
Symbol-based risk monitoring - more efficient for multi-user platforms.

Instead of iterating through positions, we:
1. Get unique symbols being held across ALL users
2. Fetch price ONCE per symbol
3. Use SQL to find affected users based on their settings
4. Send batched alerts
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

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


async def fetch_unique_holdings(db_client) -> Set[str]:
    """
    Get unique symbols being held across ALL open positions.
    
    Returns:
        Set of unique symbol strings
    """
    positions = await db_client.position.find_many(
        where={"status": "open"},
        select={"symbol": True},
        distinct=["symbol"],
    )
    
    return {pos.symbol for pos in positions if pos.symbol}


async def fetch_affected_users_for_symbol(
    db_client,
    symbol: str,
    current_price: float,
    logger: Optional[logging.Logger] = None,
) -> List[RiskMonitorRequest]:
    """
    Find all users whose risk settings are violated for this symbol.
    
    Strategy:
    1. Fetch ALL positions for this symbol
    2. Calculate drawdown for each
    3. Get threshold from portfolio risk_tolerance
    4. Filter positions where drawdown exceeds threshold
    
    Args:
        db_client: Prisma database client
        symbol: Stock symbol to check
        current_price: Current market price for the symbol
        logger: Optional logger
        
    Returns:
        List of RiskMonitorRequest objects for affected users
    """
    logger = logger or logging.getLogger(__name__)
    
    # Fetch all positions for this symbol (with portfolio relation)
    positions = await db_client.position.find_many(
        where={
            "symbol": symbol,
            "status": "open",
        },
        include={
            "portfolio": True,
        }
    )
    
    if not positions:
        return []
    
    requests: List[RiskMonitorRequest] = []
    
    for position in positions:
        portfolio = position.portfolio
        if not portfolio:
            continue
        
        average_price = _safe_float(position.average_buy_price, 0.0)
        if average_price <= 0:
            continue
        
        # Calculate drawdown
        drawdown_pct = ((current_price - average_price) / average_price) * 100.0
        
        # Get threshold from risk tolerance
        risk_tolerance = (portfolio.risk_tolerance or "medium").lower()
        threshold_pct = DEFAULT_THRESHOLD_MAP.get(risk_tolerance, 5.0)
        
        # Check if threshold is breached
        if drawdown_pct > -abs(threshold_pct):
            continue  # No breach, skip
        
        # Extract contact emails from metadata
        contact_emails = []
        if portfolio.metadata:
            meta = portfolio.metadata if isinstance(portfolio.metadata, dict) else {}
            for key in ("alert_emails", "risk_emails", "contact_emails"):
                if key in meta and meta[key]:
                    emails = meta[key]
                    if isinstance(emails, str):
                        contact_emails = [emails]
                    elif isinstance(emails, list):
                        contact_emails = [str(e) for e in emails if e]
                    break
        
        # Build risk request for this affected user
        request = RiskMonitorRequest(
            request_id=str(position.id),
            user_id=str(portfolio.user_id or portfolio.customer_id or portfolio.organization_id or ""),
            portfolio_id=str(portfolio.id),
            portfolio_name=str(portfolio.portfolio_name or "Portfolio"),
            symbol=symbol,
            quantity=_safe_float(position.quantity, 0.0),
            average_price=average_price,
            current_price=current_price,
            threshold_pct=threshold_pct,
            risk_tolerance=risk_tolerance,
            contact_emails=contact_emails,
            total_change_pct=drawdown_pct,
            organization_id=portfolio.organization_id,
            customer_id=portfolio.customer_id,
            exchange=position.exchange,
            segment=position.segment,
            metadata={
                "position_id": str(position.id),
                "position_type": position.position_type,
                "captured_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        
        requests.append(request)
        
        logger.debug(
            f"User {request.user_id} affected: {symbol} drop {drawdown_pct:.2f}% "
            f"(threshold {threshold_pct:.2f}%)"
        )
    
    return requests


async def prepare_symbol_based_risk_requests(
    db_client,
    market_service,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[RiskMonitorRequest], Dict[str, Any]]:
    """
    Symbol-based risk monitoring: iterate through unique holdings, not users.
    
    Process:
    1. Get unique symbols across ALL positions
    2. For each symbol:
       a. Fetch current price ONCE
       b. Query database for affected users (SQL filtering)
       c. Build risk requests only for affected users
    
    Args:
        db_client: Prisma database client
        market_service: Market data service with live prices
        logger: Optional logger
        
    Returns:
        Tuple of (risk_requests, metadata)
    """
    logger = logger or logging.getLogger(__name__)
    
    # Step 1: Get unique symbols
    unique_symbols = await fetch_unique_holdings(db_client)
    
    if not unique_symbols:
        logger.info("No unique holdings found")
        return [], {"unique_symbols": 0, "prices_fetched": 0}
    
    logger.info(f"Found {len(unique_symbols)} unique holdings: {sorted(unique_symbols)}")
    
    # Step 2: For each symbol, get price and find affected users
    all_requests: List[RiskMonitorRequest] = []
    prices_fetched = 0
    
    for symbol in sorted(unique_symbols):
        try:
            # Fetch price ONCE per symbol
            market_service.register_symbol(symbol)
            current_price = market_service.get_latest_price(symbol)
            
            if current_price is None or current_price <= 0:
                logger.warning(f"No valid price for {symbol}, skipping")
                continue
            
            current_price_float = float(current_price)
            prices_fetched += 1
            
            logger.debug(f"Checking {symbol} at price ₹{current_price_float:.2f}")
            
            # Query database for affected users
            affected_requests = await fetch_affected_users_for_symbol(
                db_client,
                symbol,
                current_price_float,
                logger,
            )
            
            if affected_requests:
                logger.info(
                    f"{symbol}: {len(affected_requests)} user(s) affected at "
                    f"₹{current_price_float:.2f}"
                )
                all_requests.extend(affected_requests)
            else:
                logger.debug(f"{symbol}: No users affected")
            
        except Exception as exc:
            logger.error(f"Error processing {symbol}: {exc}", exc_info=True)
            continue
    
    metadata = {
        "unique_symbols": len(unique_symbols),
        "prices_fetched": prices_fetched,
        "affected_users": len(all_requests),
        "symbols_processed": sorted(unique_symbols),
    }
    
    logger.info(
        f"Symbol-based risk monitoring: {len(unique_symbols)} symbols, "
        f"{prices_fetched} prices fetched, {len(all_requests)} users affected"
    )
    
    return all_requests, metadata


async def collect_risk_monitor_requests(
    db_client,
    market_service,
    logger: Optional[logging.Logger] = None,
) -> Tuple[List[RiskMonitorRequest], Dict[str, Any]]:
    """Backward-compatible wrapper used by streaming monitor startup."""
    return await prepare_symbol_based_risk_requests(
        db_client=db_client,
        market_service=market_service,
        logger=logger,
    )


__all__ = [
    "fetch_unique_holdings",
    "fetch_affected_users_for_symbol",
    "prepare_symbol_based_risk_requests",
    "collect_risk_monitor_requests",
]
