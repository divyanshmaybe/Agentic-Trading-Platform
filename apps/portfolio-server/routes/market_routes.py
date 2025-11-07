"""Market data routes exposing live quotes via the shared price stream."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Set

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from auth_middleware import protect_route  # type: ignore
from market_data import get_market_data_service
from schemas import MarketQuote, MarketQuoteResponse

logger = logging.getLogger(__name__)

FALLBACK_ENABLED = os.getenv("MARKET_DATA_ENABLE_FALLBACK", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FALLBACK_BASE = Decimal(os.getenv("MARKET_DATA_FALLBACK_BASE", "100.00"))
FALLBACK_STEP = Decimal(os.getenv("MARKET_DATA_FALLBACK_STEP", "5.00"))
FINNHUB_HTTP_URL = os.getenv("FINNHUB_HTTP_URL", "https://finnhub.io/api/v1/quote")

SYMBOL_PREFIX = os.getenv("MARKET_DATA_SYMBOL_PREFIX", "")
SYMBOL_SUFFIX = os.getenv("MARKET_DATA_SYMBOL_SUFFIX", "")
SYMBOL_MAP_RAW = os.getenv("MARKET_DATA_SYMBOL_MAP", "{}")
try:
    SYMBOL_MAP: Dict[str, str] = json.loads(SYMBOL_MAP_RAW)
except json.JSONDecodeError:
    SYMBOL_MAP = {}

router = APIRouter(prefix="/market", tags=["Market"])


def _normalize_user(user: dict) -> dict:
    return {
        "id": user.get("id") or user.get("_id"),
        "organization_id": user.get("organization_id") or user.get("organizationId"),
        "customer_id": user.get("customer_id") or user.get("customerId"),
        "role": user.get("role"),
        "email": user.get("email"),
        "raw": user,
    }


async def get_authenticated_user(request: Request) -> dict:
    """Resolve the authenticated user via auth middleware."""
    raw_user = getattr(request.state, "user", None)
    if raw_user:
        normalized = _normalize_user(raw_user)
        request.state.user = normalized
        return normalized
    raw_user = await protect_route(request)
    normalized = _normalize_user(raw_user)
    request.state.user = normalized
    return normalized


def _fallback_price(symbol: str) -> Decimal:
    offset = sum(ord(ch) for ch in symbol) % 20
    return (FALLBACK_BASE + (FALLBACK_STEP * Decimal(offset))).quantize(
        Decimal("0.01")
    )


def _provider_symbol(symbol: str) -> str:
    lookup = symbol.upper()
    mapped = SYMBOL_MAP.get(lookup) or SYMBOL_MAP.get(symbol) or lookup
    if SYMBOL_PREFIX or SYMBOL_SUFFIX:
        return f"{SYMBOL_PREFIX}{mapped}{SYMBOL_SUFFIX}"
    return mapped


def _original_symbol(provider_symbol: str) -> str:
    for original, mapped in SYMBOL_MAP.items():
        candidate = f"{SYMBOL_PREFIX}{mapped}{SYMBOL_SUFFIX}" if any([SYMBOL_PREFIX, SYMBOL_SUFFIX]) else mapped
        if candidate == provider_symbol:
            return original
    return provider_symbol


@router.get("/quotes", response_model=MarketQuoteResponse)
async def get_market_quotes(
    request: Request,
    symbols: List[str] = Query(..., alias="symbols"),
    user: dict = Depends(get_authenticated_user),
) -> MarketQuoteResponse:
    """
    Get live market quotes for the given symbols.
    Uses the WebSocket-based market data service.
    """
    if not symbols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one symbol must be provided",
        )

    unique_symbols: Set[str] = {
        symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()
    }
    if not unique_symbols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Symbols cannot be empty",
        )

    quotes: List[MarketQuote] = []
    missing: List[str] = []

    service = get_market_data_service()

    for symbol in unique_symbols:
        provider_symbol = _provider_symbol(symbol)
        price = service.get_latest_price(provider_symbol)
        source = "cache"
        if price is None:
            service.register_symbol(provider_symbol)
            try:
                price = await service.await_price(provider_symbol, timeout=3.0)
                source = "live-stream"
            except RuntimeError:
                price = None

        if price is None:
            rest_price = await _fetch_rest_price(provider_symbol)
            if rest_price is not None:
                price = rest_price
                source = "rest-api"

        if price is not None:
            quotes.append(
                MarketQuote(
                    symbol=symbol,
                    price=price,
                    provider=service.adapter.name if source != "rest-api" else "rest-api",
                    source=source,
                )
            )
        else:
            missing.append(symbol)

    if missing and FALLBACK_ENABLED:
        for symbol in missing:
            fallback = _fallback_price(symbol)
            quotes.append(
                MarketQuote(
                    symbol=symbol,
                    price=fallback,
                    provider="fallback",
                    source="deterministic-fallback",
                )
            )
        missing = []

    if not quotes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live market data unavailable for requested symbols",
        )

    return MarketQuoteResponse(
        data=quotes,
        count=len(quotes),
        requested_at=datetime.utcnow(),
        missing=missing or None,
    )


async def _fetch_rest_price(provider_symbol: str) -> Optional[Decimal]:
    token = (
        os.getenv("FINNHUB_API_TOKEN")
        or os.getenv("FINNHUB_TOKEN")
        or os.getenv("FINNHUB_API_KEY")
    )
    if not token:
        return None

    params = {"symbol": provider_symbol, "token": token}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(FINNHUB_HTTP_URL, params=params)
            if response.status_code != 200:
                logger.warning(
                    "REST fallback failed for %s: %s %s",
                    provider_symbol,
                    response.status_code,
                    response.text,
                )
                return None
            data = response.json()
    except Exception as exc:
        logger.warning("REST fallback request failed for %s: %s", provider_symbol, exc)
        return None

    price = data.get("c") or data.get("current") or data.get("price")
    if price is None:
        return None

    try:
        return Decimal(str(price))
    except Exception:
        return None

