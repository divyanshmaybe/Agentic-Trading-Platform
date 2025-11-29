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
    """Handles market quote retrieval with live market data sources."""

    def __init__(self) -> None:
        self._service: Optional["MarketDataService"] = None
        
        self.finnhub_http_url = os.getenv("FINNHUB_HTTP_URL", "https://finnhub.io/api/v1/quote")
        
        logger.info("✅ Market controller initialized - No fallback pricing, fail fast on data unavailability")

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

        if missing:
            # Fail fast - no fallback pricing allowed
            logger.error(
                "❌ Market data unavailable for %d symbol(s): %s",
                len(missing),
                ", ".join(missing)
            )

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

    @property
    def service(self) -> "MarketDataService":
        """Lazy-load market data service only when needed"""
        if self._service is None:
            self._service = get_market_data_service()
        return self._service

    async def _get_price(self, provider_symbol: str) -> tuple[Optional[Decimal], str, str]:
        # NO FALLBACK: Fail fast if price not available
        # 1. Check cache (instant)
        # 2. Wait for WebSocket (up to 10s)
        # 3. If both fail, return None (no REST API fallback)
        
        import time
        start_time = time.time()
        
        use_websocket = os.getenv("MARKET_DATA_USE_WEBSOCKET", "true").lower() in ("true", "1", "yes")
        
        # Try WebSocket first if enabled
        if use_websocket:
            try:
                # Check cache first (instant)
                price = self.service.get_latest_price(provider_symbol)
                if price is not None:
                    logger.debug(f"[PERF] {provider_symbol} from cache in {(time.time()-start_time)*1000:.1f}ms")
                    return price, "cache", self.service.adapter.name

                # Subscribe and wait (10s timeout)
                self.service.register_symbol(provider_symbol)
                ws_start = time.time()
                price = await self.service.await_price(provider_symbol, timeout=10.0)
                if price is not None:
                    logger.info(f"[PERF] {provider_symbol} from WebSocket in {(time.time()-ws_start)*1000:.1f}ms")
                    return price, "live-stream", self.service.adapter.name
            except RuntimeError as ws_err:
                logger.error(
                    f"❌ {provider_symbol} not available after {(time.time()-start_time)*1000:.1f}ms: {ws_err}. "
                    f"Symbol may not be in Angel One token map or connection failed."
                )
            except Exception as ws_exc:
                logger.error(f"❌ WebSocket error for {provider_symbol}: {ws_exc}")

        # NO FALLBACK - fail fast
        logger.error(
            f"❌ Price unavailable for {provider_symbol} after {(time.time()-start_time)*1000:.1f}ms. "
            f"Check if symbol exists in Angel One token map."
        )
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
                        "REST API failed for %s: %s %s",
                        provider_symbol,
                        response.status_code,
                        response.text,
                    )
                    return None
                data = response.json()
        except Exception as exc:
            logger.warning("REST API request failed for %s: %s", provider_symbol, exc)
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
        Fetch historical candles from Angel One and yfinance sources.
        
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

        # Adjust time range to respect market hours (9:15 AM to 3:30 PM IST)
        # If requested time is after market close, use previous trading day
        from datetime import timezone, time as dt_time
        import pytz
        
        ist = pytz.timezone('Asia/Kolkata')
        market_open = dt_time(9, 15)
        market_close = dt_time(15, 30)
        
        # Convert to IST for market hour check
        time_from_ist = time_from.astimezone(ist) if time_from.tzinfo else ist.localize(time_from)
        time_to_ist = time_to.astimezone(ist) if time_to.tzinfo else ist.localize(time_to)
        
        # If end time is after market close, adjust to market close
        if time_to_ist.time() > market_close:
            time_to_ist = time_to_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        
        # If start time is before market open, adjust to market open
        if time_from_ist.time() < market_open:
            time_from_ist = time_from_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        
        # Convert back to UTC/naive for API
        time_from = time_from_ist.replace(tzinfo=None)
        time_to = time_to_ist.replace(tzinfo=None)

        # Format dates for Angel One API (YYYY-MM-DD HH:MM)
        fromdate = time_from.strftime("%Y-%m-%d %H:%M")
        todate = time_to.strftime("%Y-%m-%d %H:%M")

        # Try Angel One first
        try:
            logger.info(f"Trying Angel One historical API for {provider_symbol}")
            candles_raw = self.service.get_historical_candles(
                symbol=provider_symbol,
                interval=angelone_interval,
                fromdate=fromdate,
                todate=todate,
                exchange="NSE"
            )

            if candles_raw:
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

                logger.info(f"✅ Fetched {len(candles)} candles from Angel One for {provider_symbol} ({resolution})")
                return candles
            else:
                logger.warning(f"Angel One returned empty candles for {provider_symbol}")
        except Exception as e:
            logger.warning(f"Angel One historical API failed for {provider_symbol}: {e}")

        # Try yfinance as alternative source
        try:
            import yfinance as yf
            
            # Map resolution to yfinance interval
            yf_interval_map = {
                "1h": "1m",   # yfinance doesn't have 1h, use 1m
                "1d": "5m",
                "5d": "15m", 
                "7d": "15m",
                "30d": "1h",
                "1y": "1d",
            }
            yf_interval = yf_interval_map.get(resolution, "1d")
            
            # Try different ticker formats for NSE
            ticker_candidates = [
                f"{provider_symbol}.NS",  # Standard NSE format
                f"{provider_symbol}.BO",  # BSE format
                provider_symbol,          # Raw symbol
            ]
            
            for ticker_symbol in ticker_candidates:
                try:
                    logger.info(f"Trying yfinance with {ticker_symbol}")
                    ticker = yf.Ticker(ticker_symbol)
                    
                    # Adjust period based on resolution
                    period_map = {
                        "1h": "1d",
                        "1d": "5d", 
                        "5d": "1mo",
                        "7d": "1mo",
                        "30d": "3mo",
                        "1y": "2y",
                    }
                    period = period_map.get(resolution, "1y")
                    
                    hist = ticker.history(period=period, interval=yf_interval)
                    if not hist.empty:
                        # Convert to our format
                        candles: List[Dict[str, Decimal]] = []
                        for idx, row in hist.iterrows():
                            candles.append({
                                "timestamp": idx.to_pydatetime(),
                                "open": Decimal(str(row["Open"])),
                                "high": Decimal(str(row["High"])),
                                "low": Decimal(str(row["Low"])),
                                "close": Decimal(str(row["Close"])),
                                "volume": Decimal(str(row["Volume"])),
                            })
                        
                        logger.info(f"✅ Fetched {len(candles)} candles from yfinance for {provider_symbol} using {ticker_symbol}")
                        return candles
                    else:
                        logger.warning(f"yfinance returned empty data for {ticker_symbol}")
                except Exception as e:
                    logger.warning(f"yfinance failed for {ticker_symbol}: {e}")
                    continue
            
            logger.warning(f"yfinance failed for all ticker candidates for {provider_symbol}")
        except Exception as e:
            logger.error(f"yfinance data fetch failed for {provider_symbol}: {e}")

        logger.error(f"No candle data available for {provider_symbol} from any source")
        return None

    def _resolve_time_range(
        self,
        resolution: str,
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> Tuple[datetime, datetime]:
        """
        Resolve time range for candle data queries.
        
        Supports custom ranges (start/end) or predefined periods:
        - 1h: Last 1 hour (within last trading session)
        - 1d: Last 1 day
        - 5d: Last 5 days
        - 7d: Last 7 days
        - 30d: Last 30 days
        - 1y: Last 1 year
        """
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        
        # Get current IST time
        now_ist = datetime.now(ist)
        now = now_ist.replace(tzinfo=None)

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

        # Default range when none provided - use last completed trading session
        # For intraday, go back to last market close
        if resolution in ["1h", "1d"]:
            # Get last market close (3:30 PM IST)
            last_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
            
            # If current time is before market close today, use yesterday's close
            if now < last_close:
                last_close = last_close - timedelta(days=1)
            
            # Start from appropriate time before close
            if resolution == "1h":
                start_time = last_close - timedelta(hours=6)  # 6 hours of market data
            else:  # 1d
                start_time = last_close - timedelta(days=1)
            
            return start_time, last_close
        
        # For longer periods, use standard lookback
        defaults = {
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
