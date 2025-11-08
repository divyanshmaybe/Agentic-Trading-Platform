from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Set

import httpx
from fastapi import HTTPException, status

from market_data import get_market_data_service
from schemas import MarketQuote, MarketQuoteResponse

logger = logging.getLogger(__name__)


class MarketController:
    """Handles market quote retrieval with live, REST, and fallback sources."""

    def __init__(self) -> None:
        self.service = get_market_data_service()

        self.fallback_enabled = os.getenv("MARKET_DATA_ENABLE_FALLBACK", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.fallback_base = Decimal(os.getenv("MARKET_DATA_FALLBACK_BASE", "100.00"))
        self.fallback_step = Decimal(os.getenv("MARKET_DATA_FALLBACK_STEP", "5.00"))
        self.finnhub_http_url = os.getenv("FINNHUB_HTTP_URL", "https://finnhub.io/api/v1/quote")

        self.symbol_prefix = os.getenv("MARKET_DATA_SYMBOL_PREFIX", "")
        self.symbol_suffix = os.getenv("MARKET_DATA_SYMBOL_SUFFIX", "")
        raw_map = os.getenv("MARKET_DATA_SYMBOL_MAP", "{}")
        try:
            self.symbol_map: Dict[str, str] = json.loads(raw_map)
        except json.JSONDecodeError:
            logger.warning("Invalid MARKET_DATA_SYMBOL_MAP JSON; defaulting to empty map")
            self.symbol_map = {}

    async def get_quotes(self, symbols: Sequence[str]) -> MarketQuoteResponse:
        unique_symbols = self._normalize_symbols(symbols)
        if not unique_symbols:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Symbols cannot be empty",
            )

        quotes: List[MarketQuote] = []
        missing: List[str] = []

        for symbol in unique_symbols:
            provider_symbol = self._provider_symbol(symbol)
            price, source, provider = await self._get_price(provider_symbol)

            if price is not None:
                quotes.append(
                    MarketQuote(
                        symbol=symbol,
                        price=price,
                        provider=provider,
                        source=source,
                    )
                )
            else:
                missing.append(symbol)

        if missing and self.fallback_enabled:
            for symbol in list(missing):
                fallback = self._fallback_price(symbol)
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

    def _normalize_symbols(self, symbols: Sequence[str]) -> Set[str]:
        normalized: Set[str] = set()
        for symbol in symbols:
            if symbol and isinstance(symbol, str):
                trimmed = symbol.strip().upper()
                if trimmed:
                    normalized.add(trimmed)
        return normalized

    def _provider_symbol(self, symbol: str) -> str:
        lookup = symbol.upper()
        mapped = self.symbol_map.get(lookup) or self.symbol_map.get(symbol) or lookup
        if self.symbol_prefix or self.symbol_suffix:
            return f"{self.symbol_prefix}{mapped}{self.symbol_suffix}"
        return mapped

    def _fallback_price(self, symbol: str) -> Decimal:
        offset = sum(ord(ch) for ch in symbol) % 20
        return (self.fallback_base + (self.fallback_step * Decimal(offset))).quantize(Decimal("0.01"))

    async def _get_price(self, provider_symbol: str) -> tuple[Optional[Decimal], str, str]:
        price = self.service.get_latest_price(provider_symbol)
        if price is not None:
            return price, "cache", self.service.adapter.name

        self.service.register_symbol(provider_symbol)
        try:
            price = await self.service.await_price(provider_symbol, timeout=3.0)
            if price is not None:
                return price, "live-stream", self.service.adapter.name
        except RuntimeError:
            price = None

        price = await self._fetch_rest_price(provider_symbol)
        if price is not None:
            return price, "rest-api", "rest-api"

        return None, "unavailable", self.service.adapter.name

    async def _fetch_rest_price(self, provider_symbol: str) -> Optional[Decimal]:
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
                response = await client.get(self.finnhub_http_url, params=params)
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
