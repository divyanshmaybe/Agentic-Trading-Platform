from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import httpx
from fastapi import HTTPException, status
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_data import MarketDataService

from market_data import get_market_data_service
from schemas import MarketQuote, MarketQuoteResponse

logger = logging.getLogger(__name__)


class MarketController:
    """Handles market quote retrieval with live, REST, and fallback sources."""

    def __init__(self) -> None:
        self._service: Optional["MarketDataService"] = None

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

    async def get_quotes(
        self,
        symbols: Sequence[str],
        *,
        candle: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> MarketQuoteResponse:
        unique_symbols = self._normalize_symbols(symbols)
        if not unique_symbols:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Symbols cannot be empty",
            )

        quotes: List[MarketQuote] = []
        missing: List[str] = []
        candles: Dict[str, List[Dict[str, Decimal]]] = {}

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

            if candle:
                candle_data = await self._fetch_candles(provider_symbol, candle, start=start, end=end)
                if candle_data:
                    candles[symbol] = candle_data

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

        response = MarketQuoteResponse(
            data=quotes,
            count=len(quotes),
            requested_at=datetime.utcnow(),
            missing=missing or None,
        )

        if candles:
            # Attach candles payload as metadata on response
            response.metadata = {"candles": candles}

        return response

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

    @property
    def service(self) -> "MarketDataService":
        """Lazy-load market data service only when needed"""
        if self._service is None:
            self._service = get_market_data_service()
        return self._service

    async def _get_price(self, provider_symbol: str) -> tuple[Optional[Decimal], str, str]:
        # Try REST API first to avoid WebSocket connection
        price = await self._fetch_rest_price(provider_symbol)
        if price is not None:
            return price, "rest-api", "rest-api"
        
        # Only use WebSocket service if explicitly enabled and REST failed
        use_websocket = os.getenv("MARKET_DATA_USE_WEBSOCKET", "false").lower() in ("true", "1", "yes")
        if not use_websocket:
            return None, "unavailable", "rest-api-only"
        
        # WebSocket fallback (only if enabled)
        try:
            price = self.service.get_latest_price(provider_symbol)
            if price is not None:
                return price, "cache", self.service.adapter.name

            self.service.register_symbol(provider_symbol)
            price = await self.service.await_price(provider_symbol, timeout=3.0)
            if price is not None:
                return price, "live-stream", self.service.adapter.name
        except RuntimeError:
            price = None

        return None, "unavailable", self.service.adapter.name if self._service else "unavailable"

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

    async def _fetch_candles(
        self,
        provider_symbol: str,
        resolution: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Optional[List[Dict[str, Decimal]]]:
        """
        Fetch historical candles using Angel One Historical API.
        
        Supports predefined periods: 1h, 1d, 5d, 7d, 30d, 1y
        Or custom date ranges via start/end parameters.
        """
        # Map user-friendly resolution to Angel One intervals
        resolution_map = {
            "1h": ("ONE_MINUTE", timedelta(hours=1)),      # 1-min candles for 1 hour
            "1d": ("FIVE_MINUTE", timedelta(days=1)),      # 5-min candles for 1 day
            "5d": ("FIFTEEN_MINUTE", timedelta(days=5)),   # 15-min candles for 5 days
            "7d": ("FIFTEEN_MINUTE", timedelta(days=7)),   # 15-min candles for 7 days
            "30d": ("ONE_HOUR", timedelta(days=30)),       # 1-hour candles for 30 days
            "1y": ("ONE_DAY", timedelta(days=365)),        # Daily candles for 1 year
        }

        if resolution not in resolution_map:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid candle interval. Supported: {', '.join(resolution_map.keys())}",
            )

        angelone_interval, default_range = resolution_map[resolution]
        time_from, time_to = self._resolve_time_range(resolution, start, end)

        # Format dates for Angel One API (YYYY-MM-DD HH:MM)
        fromdate = time_from.strftime("%Y-%m-%d %H:%M")
        todate = time_to.strftime("%Y-%m-%d %H:%M")

        # Check if using Angel One adapter
        from market_data import AngelOneAdapter
        
        if not isinstance(self.service.adapter, AngelOneAdapter):
            logger.warning(
                "Candle data requires Angel One adapter. Current provider: %s",
                self.service.adapter.name
            )
            return None

        # Fetch candles from Angel One
        adapter: AngelOneAdapter = self.service.adapter
        candles_raw = adapter.get_historical_candles(
            symbol=provider_symbol,
            interval=angelone_interval,
            fromdate=fromdate,
            todate=todate,
            exchange="NSE"
        )

        if not candles_raw:
            logger.warning(f"No candle data returned for {provider_symbol}")
            return None

        # Convert to response format with Decimal types
        candles: List[Dict[str, Decimal]] = []
        for candle in candles_raw:
            candles.append({
                "timestamp": candle["timestamp"],
                "open": Decimal(str(candle["open"])),
                "high": Decimal(str(candle["high"])),
                "low": Decimal(str(candle["low"])),
                "close": Decimal(str(candle["close"])),
                "volume": Decimal(str(candle["volume"])),
            })

        logger.info(f"✅ Fetched {len(candles)} candles for {provider_symbol} ({resolution})")
        return candles

    def _resolve_time_range(
        self,
        resolution: str,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> Tuple[datetime, datetime]:
        """
        Resolve time range for candle data queries.
        
        Supports custom ranges (start/end) or predefined periods:
        - 1h: Last 1 hour
        - 1d: Last 1 day
        - 5d: Last 5 days
        - 7d: Last 7 days
        - 30d: Last 30 days
        - 1y: Last 1 year
        """
        now = datetime.utcnow()

        if start and end:
            if start >= end:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="start must be earlier than end",
                )
            return start, end

        if end and not start:
            mapping = {
                "1h": (end - timedelta(hours=1), end),
                "1d": (end - timedelta(days=1), end),
                "5d": (end - timedelta(days=5), end),
                "7d": (end - timedelta(days=7), end),
                "30d": (end - timedelta(days=30), end),
                "1y": (end - timedelta(days=365), end),
            }
            return mapping[resolution]

        if start and not end:
            mapping = {
                "1h": start + timedelta(hours=1),
                "1d": start + timedelta(days=1),
                "5d": start + timedelta(days=5),
                "7d": start + timedelta(days=7),
                "30d": start + timedelta(days=30),
                "1y": start + timedelta(days=365),
            }
            return start, mapping[resolution]

        # Default range when none provided
        defaults = {
            "1h": now - timedelta(hours=1),
            "1d": now - timedelta(days=1),
            "5d": now - timedelta(days=5),
            "7d": now - timedelta(days=7),
            "30d": now - timedelta(days=30),
            "1y": now - timedelta(days=365),
        }
        return defaults[resolution], now

    def get_subscribed_symbols(self) -> dict:
        """
        Get list of all currently subscribed symbols from the WebSocket adapter.
        Returns count and list of symbols that are actively streaming prices.
        """
        if self._service is None:
            return {
                "subscribed": [],
                "count": 0,
                "provider": "unavailable",
                "message": "Market data service not initialized"
            }
        adapter = self.service.adapter
        if hasattr(adapter, 'get_subscribed_symbols'):
            symbols = adapter.get_subscribed_symbols()
            return {
                "subscribed": symbols,
                "count": len(symbols),
                "provider": adapter.name,
            }
        return {
            "subscribed": [],
            "count": 0,
            "provider": adapter.name if adapter else "unknown",
            "message": "Adapter does not support subscription tracking"
        }
