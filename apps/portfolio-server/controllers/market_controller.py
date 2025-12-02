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

        # Build list of provider symbols
        provider_symbols = {symbol: self._provider_symbol(symbol) for symbol in unique_symbols}

        for symbol in unique_symbols:
            provider_symbol = provider_symbols[symbol]
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

        # Batch fetch candles if requested
        if candle:
            candles = await self._fetch_candles_batch(
                list(unique_symbols), 
                candle, 
                start=start, 
                end=end
            )

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

    async def _fetch_candles_batch(
        self,
        symbols: List[str],
        resolution: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Dict[str, List[Dict[str, Decimal]]]:
        """
        Batch fetch historical candles for multiple symbols using yahooquery (default).
        Falls back to Angel One API for symbols that fail.
        
        Returns a dict mapping symbol -> list of candles.
        """
        from yahooquery import Ticker
        
        result: Dict[str, List[Dict[str, Decimal]]] = {}
        failed_symbols: List[str] = []
        
        if not symbols:
            return result
        
        # Map resolution to yahooquery interval and period
        yq_interval_map = {
            "1h": "1m",   # 1-minute data for 1 hour
            "1d": "5m",   # 5-minute data for 1 day
            "5d": "15m",  # 15-minute data for 5 days
            "7d": "15m",  # 15-minute data for 7 days
            "30d": "1h",  # 1-hour data for 30 days
            "1y": "1d",   # Daily data for 1 year
        }
        period_map = {
            "1h": "1d",
            "1d": "5d", 
            "5d": "1mo",
            "7d": "1mo",
            "30d": "3mo",
            "1y": "2y",
        }
        
        yq_interval = yq_interval_map.get(resolution, "1d")
        period = period_map.get(resolution, "1y")
        
        # Build ticker string for batch fetch (NSE format with .NS suffix)
        ticker_symbols = [f"{s}.NS" for s in symbols]
        ticker_str = " ".join(ticker_symbols)
        
        logger.info(f"📊 Batch fetching candles for {len(symbols)} symbols via yahooquery: {ticker_str}")
        
        try:
            ticker = Ticker(ticker_str, asynchronous=True)
            hist = ticker.history(period=period, interval=yq_interval)
            
            if isinstance(hist, dict):
                # Error response for all symbols
                logger.warning(f"yahooquery batch error: {hist}")
                failed_symbols = list(symbols)
            elif not hist.empty:
                # DataFrame with multi-index (symbol, date)
                # Group by symbol level
                for yq_symbol in hist.index.get_level_values(0).unique():
                    # Extract original symbol from .NS format
                    original_symbol = yq_symbol.replace('.NS', '').replace('.BO', '')
                    
                    try:
                        symbol_data = hist.loc[yq_symbol]
                        candles: List[Dict[str, Decimal]] = []
                        
                        for timestamp, row in symbol_data.iterrows():
                            # Convert to datetime if needed
                            if hasattr(timestamp, 'to_pydatetime'):
                                timestamp = timestamp.to_pydatetime()
                            
                            candles.append({
                                "timestamp": timestamp,
                                "open": Decimal(str(row["open"])),
                                "high": Decimal(str(row["high"])),
                                "low": Decimal(str(row["low"])),
                                "close": Decimal(str(row["close"])),
                                "volume": Decimal(str(row["volume"])),
                            })
                        
                        if candles:
                            result[original_symbol] = candles
                            logger.info(f"✅ yahooquery: {len(candles)} candles for {original_symbol}")
                        else:
                            failed_symbols.append(original_symbol)
                    except Exception as e:
                        logger.warning(f"Failed to parse yahooquery data for {original_symbol}: {e}")
                        failed_symbols.append(original_symbol)
                
                # Check for symbols that weren't in the result
                for s in symbols:
                    if s not in result and s not in failed_symbols:
                        failed_symbols.append(s)
            else:
                logger.warning("yahooquery returned empty DataFrame")
                failed_symbols = list(symbols)
                
        except Exception as e:
            logger.error(f"yahooquery batch fetch failed: {e}")
            failed_symbols = list(symbols)
        
        # Fallback to Angel One for failed symbols
        if failed_symbols:
            logger.info(f"📡 Falling back to Angel One for {len(failed_symbols)} symbols: {failed_symbols}")
            for symbol in failed_symbols:
                try:
                    candles = await self._fetch_candles_angelone(symbol, resolution, start=start, end=end)
                    if candles:
                        result[symbol] = candles
                except Exception as e:
                    logger.warning(f"Angel One fallback failed for {symbol}: {e}")
        
        logger.info(f"📊 Batch fetch complete: {len(result)}/{len(symbols)} symbols with candle data")
        return result

    async def _fetch_candles_angelone(
        self,
        provider_symbol: str,
        resolution: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Optional[List[Dict[str, Decimal]]]:
        """
        Fetch historical candles from Angel One API.
        """
        # Map user-friendly resolution to Angel One intervals
        resolution_map = {
            "1h": ("ONE_MINUTE", timedelta(hours=1)),
            "1d": ("FIVE_MINUTE", timedelta(days=1)),
            "5d": ("FIFTEEN_MINUTE", timedelta(days=5)),
            "7d": ("FIFTEEN_MINUTE", timedelta(days=7)),
            "30d": ("ONE_HOUR", timedelta(days=30)),
            "1y": ("ONE_DAY", timedelta(days=365)),
        }

        if resolution not in resolution_map:
            return None

        angelone_interval, _ = resolution_map[resolution]
        time_from, time_to = self._resolve_time_range(resolution, start, end)

        # Adjust time range to respect market hours
        from datetime import time as dt_time
        import pytz
        
        ist = pytz.timezone('Asia/Kolkata')
        market_open = dt_time(9, 15)
        market_close = dt_time(15, 30)
        
        time_from_ist = time_from.astimezone(ist) if time_from.tzinfo else ist.localize(time_from)
        time_to_ist = time_to.astimezone(ist) if time_to.tzinfo else ist.localize(time_to)
        
        if time_to_ist.time() > market_close:
            time_to_ist = time_to_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        if time_from_ist.time() < market_open:
            time_from_ist = time_from_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        
        time_from = time_from_ist.replace(tzinfo=None)
        time_to = time_to_ist.replace(tzinfo=None)

        fromdate = time_from.strftime("%Y-%m-%d %H:%M")
        todate = time_to.strftime("%Y-%m-%d %H:%M")

        try:
            candles_raw = self.service.get_historical_candles(
                symbol=provider_symbol,
                interval=angelone_interval,
                fromdate=fromdate,
                todate=todate,
                exchange="NSE"
            )

            if candles_raw:
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
                logger.info(f"✅ Angel One: {len(candles)} candles for {provider_symbol}")
                return candles
        except Exception as e:
            logger.warning(f"Angel One failed for {provider_symbol}: {e}")
        
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
        Fetch historical candles for a single symbol.
        Uses yahooquery as default, falls back to Angel One.
        
        Supports predefined periods: 1h, 1d, 5d, 7d, 30d, 1y
        Or custom date ranges via start/end parameters.
        """
        from yahooquery import Ticker
        
        valid_resolutions = {"1h", "1d", "5d", "7d", "30d", "1y"}
        if resolution not in valid_resolutions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid candle interval. Supported: {', '.join(valid_resolutions)}",
            )

        # Map resolution to yahooquery interval and period
        yq_interval_map = {
            "1h": "1m",
            "1d": "5m",
            "5d": "15m",
            "7d": "15m",
            "30d": "1h",
            "1y": "1d",
        }
        period_map = {
            "1h": "1d",
            "1d": "5d",
            "5d": "1mo",
            "7d": "1mo",
            "30d": "3mo",
            "1y": "2y",
        }
        
        yq_interval = yq_interval_map[resolution]
        period = period_map[resolution]

        # Try yahooquery first (default)
        ticker_candidates = [
            f"{provider_symbol}.NS",  # Standard NSE format
            f"{provider_symbol}.BO",  # BSE format
        ]
        
        for ticker_symbol in ticker_candidates:
            try:
                logger.info(f"📊 Trying yahooquery for {ticker_symbol}")
                ticker = Ticker(ticker_symbol, asynchronous=True)
                hist = ticker.history(period=period, interval=yq_interval)
                
                if isinstance(hist, dict):
                    logger.warning(f"yahooquery error for {ticker_symbol}: {hist}")
                    continue
                
                if not hist.empty:
                    candles: List[Dict[str, Decimal]] = []
                    for idx, row in hist.iterrows():
                        timestamp = idx[1] if isinstance(idx, tuple) else idx
                        if hasattr(timestamp, 'to_pydatetime'):
                            timestamp = timestamp.to_pydatetime()
                        
                        candles.append({
                            "timestamp": timestamp,
                            "open": Decimal(str(row["open"])),
                            "high": Decimal(str(row["high"])),
                            "low": Decimal(str(row["low"])),
                            "close": Decimal(str(row["close"])),
                            "volume": Decimal(str(row["volume"])),
                        })
                    
                    logger.info(f"✅ yahooquery: {len(candles)} candles for {provider_symbol}")
                    return candles
                else:
                    logger.warning(f"yahooquery returned empty data for {ticker_symbol}")
            except Exception as e:
                logger.warning(f"yahooquery failed for {ticker_symbol}: {e}")
                continue
        
        # Fallback to Angel One
        logger.info(f"📡 Falling back to Angel One for {provider_symbol}")
        return await self._fetch_candles_angelone(provider_symbol, resolution, start=start, end=end)

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
