from __future__ import annotations

import os

# Disable Pathway progress dashboard before importing pathway
os.environ["PATHWAY_DISABLE_PROGRESS"] = "1"
os.environ.setdefault("PATHWAY_PROGRESS_DISABLE", "1")
os.environ.setdefault("PW_DISABLE_PROGRESS", "1")
os.environ["PATHWAY_LOG_LEVEL"] = "warning"

import asyncio
import contextlib
import json
import logging
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import fcntl
import tempfile

import pathway as pw
from pathway.io.python import ConnectorSubject
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = os.getenv("MARKET_DATA_WS_URL", "wss://example.com/stream")
DEFAULT_PROVIDER = "angelone"
DEFAULT_RETRY_SECONDS = 5


class MarketTickSchema(pw.Schema):
    """Pathway schema for streaming market ticks."""

    symbol: str = pw.column_definition(primary_key=True)
    price: str
    provider: str
    raw: str
    received_at: float


@dataclass
class WebsocketMessage:
    symbol: str
    price: Decimal
    raw: Dict[str, Any]


class WebsocketAdapter:
    """Adapter interface for websocket market data providers."""

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:  # pragma: no cover - template
        raise NotImplementedError

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:  # pragma: no cover - template
        raise NotImplementedError

    async def subscribe_symbol(self, ws, symbol: str) -> None:  # pragma: no cover - template
        raise NotImplementedError

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:  # pragma: no cover - template
        raise NotImplementedError

    def normalize_symbol(self, symbol: str) -> str:
        """Return provider-specific canonical symbol used for subscriptions."""
        return symbol.upper()

    def aliases_for(self, symbol: str) -> Sequence[str]:
        canonical = self.normalize_symbol(symbol).upper()
        display = symbol.upper()
        if canonical == display:
            return [canonical]
        return [display, canonical]


class GenericJSONAdapter(WebsocketAdapter):
    """Adapter for generic JSON websocket feeds with {"symbol": ..., "price": ...}."""

    def __init__(self) -> None:
        super().__init__("generic-json")
        self.ws_url = os.getenv("MARKET_DATA_WS_URL", DEFAULT_WS_URL)
        self.subscribe_key = os.getenv("MARKET_DATA_SUBSCRIBE_KEY", "subscribe")
        self.channel_key = os.getenv("MARKET_DATA_CHANNEL_KEY", "symbol")
        self.price_key = os.getenv("MARKET_DATA_PRICE_KEY", "price")
        self.symbol_key = os.getenv("MARKET_DATA_SYMBOL_KEY", "symbol")
        self.payload_template = os.getenv("MARKET_DATA_SUBSCRIBE_TEMPLATE")
        self.unsubscribe_template = os.getenv("MARKET_DATA_UNSUBSCRIBE_TEMPLATE")

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        for symbol in symbols:
            await self.subscribe_symbol(ws, symbol)

    async def subscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_payload(symbol, subscribe=True)
        if payload:
            await ws.send(payload)

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_payload(symbol, subscribe=False)
        if payload:
            await ws.send(payload)

    def _build_payload(self, symbol: str, subscribe: bool) -> Optional[str]:
        if self.payload_template:
            payload = self.payload_template.format(symbol=symbol, action=self.subscribe_key)
            if not subscribe and self.unsubscribe_template:
                payload = self.unsubscribe_template.format(symbol=symbol, action="unsubscribe")
            return payload

        message = {
            self.subscribe_key: subscribe,
            self.channel_key: symbol,
        }
        return json.dumps(message)

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Market stream discarded non-JSON payload: %s", message)
            return []

        if isinstance(payload, dict):
            symbol = payload.get(self.symbol_key)
            price = payload.get(self.price_key)
        else:
            return []

        if not symbol or price is None:
            return []

        try:
            price_decimal = Decimal(str(price))
        except Exception:  # pragma: no cover - defensive
            logger.debug("Market stream received invalid price payload: %s", payload)
            return []

        return [WebsocketMessage(symbol=symbol.upper(), price=price_decimal, raw=payload)]


class FinnhubAdapter(WebsocketAdapter):
    """Adapter for the Finnhub trade websocket."""

    def __init__(self) -> None:
        super().__init__("finnhub")
        base_url = os.getenv("MARKET_DATA_WS_URL") or os.getenv("FINNHUB_WS_URL") or "wss://ws.finnhub.io"
        token = (
            os.getenv("FINNHUB_API_TOKEN")
            or os.getenv("FINNHUB_TOKEN")
            or os.getenv("FINNHUB_API_KEY")
        )

        parsed = urlparse(base_url)
        query = parse_qs(parsed.query, keep_blank_values=True)

        existing_token = None
        if "token" in query and query["token"]:
            existing_token = query["token"][0]

        if not existing_token and token:
            query["token"] = [token]
        elif existing_token:
            query["token"] = [existing_token]

        if query:
            query_string = urlencode({key: value[0] for key, value in query.items()})
            self.ws_url = urlunparse(parsed._replace(query=query_string))
        else:
            self.ws_url = base_url
            if not token:
                logger.warning(
                    "Finnhub websocket URL has no token. Ensure your URL already includes ?token=..."
                )

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        for symbol in symbols:
            await self.subscribe_symbol(ws, symbol)

    async def subscribe_symbol(self, ws, symbol: str) -> None:
        await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:
        await ws.send(json.dumps({"type": "unsubscribe", "symbol": symbol}))

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Finnhub stream discarded non-JSON payload: %s", message)
            return []

        msg_type = payload.get("type")
        if msg_type == "ping":
            return []
        if msg_type != "trade":
            return []

        data = payload.get("data") or []
        messages: List[WebsocketMessage] = []
        for entry in data:
            symbol = entry.get("s")
            price = entry.get("p")
            if not symbol or price is None:
                continue
            try:
                price_decimal = Decimal(str(price))
            except Exception:
                continue
            messages.append(
                WebsocketMessage(
                    symbol=symbol.upper(),
                    price=price_decimal,
                    raw=entry,
                )
            )
        return messages


class AngelOneAdapter(WebsocketAdapter):
    """Adapter for Angel One SmartAPI WebSocket 2.0 streaming."""

    def __init__(self) -> None:
        super().__init__("angelone")
        self.base_ws_url = os.getenv("ANGELONE_WS_URL", "wss://smartapisocket.angelone.in/smart-stream")
        self.client_code = os.getenv("ANGELONE_CLIENT_CODE")
        self.api_key = os.getenv("ANGELONE_API_KEY")
        self.password = os.getenv("ANGELONE_PASSWORD")
        self.totp_secret = os.getenv("ANGELONE_TOTP_SECRET")
        
        # Pre-fetch configuration
        self.enable_nifty500_prefetch = os.getenv("ENABLE_NIFTY500_PREFETCH", "true").lower() in ("true", "1", "yes")
        
        if not all([self.client_code, self.api_key, self.password, self.totp_secret]):
            raise RuntimeError(
                "Angel One requires: ANGELONE_CLIENT_CODE, ANGELONE_API_KEY, ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET"
            )
        
        # These will be set after login
        self.jwt_token = None
        self.feed_token = None
        self.refresh_token = None
        self._token_expiry: Optional[float] = None
        
        # Token cache file path
        self.token_cache_file = os.path.join(
            os.path.dirname(__file__),
            "../../apps/portfolio-server/docs/angelone_tokens.json"
        )
        
        # Token mapping: canonical symbol -> metadata
        self._token_map: Dict[str, Dict[str, Any]] = {}
        # Lookup maps for alias resolution
        self._alias_to_symbol: Dict[str, str] = {}
        self._symbol_to_alias: Dict[str, str] = {}
        
        # Load or generate token map
        self._load_or_generate_token_map()
        
        # File-based lock to serialize logins across processes
        lock_dir = Path(tempfile.gettempdir()) / "angelone_locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        self._login_lock_path = lock_dir / "login.lock"

        # Perform login to get tokens
        self._login()
        
        # Build WebSocket URL with query params
        self.ws_url = f"{self.base_ws_url}?clientCode={self.client_code}&feedToken={self.feed_token}&apiKey={self.api_key}"
        
        # Heartbeat tracking
        self._last_heartbeat = time.time()
        self._heartbeat_interval = 30
    
    def _load_or_generate_token_map(self) -> None:
        """Load token map from cache file or use fallback."""
        from angelone_token_generator import load_angelone_token_map, FALLBACK_TOKEN_MAP
        
        try:
            # Try to load from cache
            self._token_map = load_angelone_token_map(self.token_cache_file)
            logger.info(f"✅ Loaded {len(self._token_map):,} Angel One tokens from cache")
        except FileNotFoundError:
            # Cache doesn't exist yet - use minimal fallback
            # Celery worker will generate full map asynchronously
            logger.warning(
                f"⚠️  Angel One token cache not found at {self.token_cache_file}"
            )
            logger.info("📋 Using fallback token map (10 symbols). Full map will be generated by Celery worker.")
            self._token_map = FALLBACK_TOKEN_MAP.copy()
        except Exception as e:
            logger.error(f"Failed to load token map: {e}")
            logger.info("📋 Using fallback token map")
            self._token_map = FALLBACK_TOKEN_MAP.copy()
        
        # Validate Nifty-500 list availability (for pre-fetch optimization)
        self._validate_nifty500_availability()

        self._inject_index_tokens()
        self._build_aliases()
    
    def _validate_nifty500_availability(self) -> None:
        """
        Validate Nifty-500 symbol list is available for pre-fetching.
        Logs helpful messages if missing, but doesn't block startup.
        """
        if not self.enable_nifty500_prefetch:
            logger.info("ℹ️  Nifty-500 pre-fetch is disabled (ENABLE_NIFTY500_PREFETCH=false)")
            return
        
        try:
            from nifty500_symbols import get_nifty500_symbols, get_nifty500_count
            
            count = get_nifty500_count()
            logger.info(f"✅ Nifty-500 list ready for pre-fetch ({count} symbols)")
            
        except ImportError:
            logger.warning(
                "⚠️  nifty500_symbols.py not found! Nifty-500 pre-fetch will be disabled.\n"
                "   To enable pre-fetching:\n"
                "   1. Run: generate_angelone_tokens_task Celery worker\n"
                "   2. Or manually run: python -c 'from angelone_token_generator import generate_nifty500_symbols; generate_nifty500_symbols()'\n"
                "   Pre-fetch benefits: Instant price lookups, no rate limits for Nifty-500 stocks"
            )
        except Exception as e:
            logger.warning(f"⚠️  Failed to validate Nifty-500 list: {e}")


    def _inject_index_tokens(self) -> None:
        """Ensure important index symbols are present in the token map."""
        index_overrides: Dict[str, Dict[str, Any]] = {
            "NIFTY 50": {
                "token": os.getenv("ANGELONE_TOKEN_NIFTY50", "99926000"),
                "name": "NIFTY 50",
                "tradingSymbol": "NIFTY 50",
                "symbol": "NIFTY 50",
                "exchange": "NSE",
                "exchangeType": 1,
                "instrumentType": "INDEX",
            },
            "NIFTY BANK": {
                "token": os.getenv("ANGELONE_TOKEN_BANKNIFTY", "99926009"),
                "name": "NIFTY BANK",
                "tradingSymbol": "NIFTY BANK",
                "symbol": "NIFTY BANK",
                "exchange": "NSE",
                "exchangeType": 1,
                "instrumentType": "INDEX",
            },
        }

        for canonical, details in index_overrides.items():
            if canonical not in self._token_map:
                self._token_map[canonical] = details

        # Register alias overrides for index symbols so lookups succeed
        alias_overrides = {
            "^NSEI": "NIFTY 50",
            "NSEI": "NIFTY 50",
            "NIFTY50": "NIFTY 50",
            "NIFTY_50": "NIFTY 50",
            "^NSEBANK": "NIFTY BANK",
            "BANKNIFTY": "NIFTY BANK",
            "NIFTYBANK": "NIFTY BANK",
        }

        self._alias_overrides = getattr(self, "_alias_overrides", {})
        self._alias_overrides.update(alias_overrides)

    def _build_aliases(self) -> None:
        """Create alias mappings for easier symbol lookup."""
        self._alias_to_symbol.clear()
        self._symbol_to_alias.clear()

        for canonical, info in self._token_map.items():
            canonical_upper = canonical.upper()
            self._alias_to_symbol[canonical_upper] = canonical
            self._symbol_to_alias[canonical] = canonical_upper

            # Common NSE suffixes
            stripped = canonical_upper
            for suffix in ("-EQ", "-BE", "-BL", "-PP"):
                if stripped.endswith(suffix):
                    base = stripped.removesuffix(suffix)
                    if base and base not in self._alias_to_symbol:
                        self._alias_to_symbol[base] = canonical
                    break

            # Also register aliases without exchange separators
            normalized = stripped.replace(" ", "")
            if normalized not in self._alias_to_symbol:
                self._alias_to_symbol[normalized] = canonical

        for alias, canonical in getattr(self, "_alias_overrides", {}).items():
            canonical_entry = canonical if canonical in self._token_map else canonical.upper()
            self._alias_to_symbol[alias.upper()] = canonical_entry
            if canonical_entry not in self._symbol_to_alias:
                self._symbol_to_alias[canonical_entry] = canonical_entry.upper()
 
    def normalize_symbol(self, symbol: str) -> str:
        upper = symbol.upper()
        if upper.startswith("^"):
            upper = upper[1:]
        if upper in self._alias_to_symbol:
            return self._alias_to_symbol[upper].upper()
        if not upper.endswith("-EQ") and f"{upper}-EQ" in self._alias_to_symbol:
            return self._alias_to_symbol[f"{upper}-EQ"].upper()
        return upper

    def aliases_for(self, symbol: str) -> Sequence[str]:
        canonical = self.normalize_symbol(symbol)
        aliases = {canonical.upper()}
        display = canonical
        if canonical.endswith("-EQ"):
            display = canonical[:-3]
            aliases.add(display.upper())
        aliases.add(symbol.upper())
        return list(aliases)

    def _login(self) -> None:
        """Login to Angel One API to get JWT and feed tokens."""
        import pyotp
        import httpx

        # Serialize logins across processes to avoid reusing the same TOTP
        with open(self._login_lock_path, "w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                # Reuse existing session if still valid
                if self.jwt_token and self.feed_token and self._token_expiry and time.time() < self._token_expiry - 5:
                    logger.debug("Reusing cached Angel One session tokens")
                    return

                login_url = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
                headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "X-UserType": "USER",
                    "X-SourceID": "WEB",
                    "X-ClientLocalIP": "127.0.0.1",
                    "X-ClientPublicIP": "127.0.0.1",
                    "X-MACAddress": "00:00:00:00:00:00",
                    "X-PrivateKey": self.api_key,
                }

                attempts = int(os.getenv("ANGELONE_LOGIN_RETRIES", "3"))
                for attempt in range(attempts):
                    totp = pyotp.TOTP(self.totp_secret).now()
                    logger.info(f"Generated TOTP: {totp}")
                    payload = {
                        "clientcode": self.client_code,
                        "password": self.password,
                        "totp": totp,
                    }

                    try:
                        with httpx.Client(timeout=30.0) as client:
                            response = client.post(login_url, json=payload, headers=headers)
                            response.raise_for_status()

                        data = response.json()
                        if not data.get("status"):
                            raise RuntimeError(data.get("message", "Unknown error"))

                        response_data = data.get("data", {})
                        self.jwt_token = response_data.get("jwtToken")
                        self.feed_token = response_data.get("feedToken")
                        self.refresh_token = response_data.get("refreshToken")

                        if not all([self.jwt_token, self.feed_token]):
                            raise RuntimeError("Login response missing tokens")

                        ttl = int(os.getenv("ANGELONE_SESSION_TTL_SECONDS", "300"))
                        self._token_expiry = time.time() + ttl
                        logger.info("✅ Angel One login successful! Feed token: %s...", self.feed_token[:10])
                        break
                    except httpx.HTTPStatusError as exc:
                        status = exc.response.status_code
                        logger.error("Angel One login failed with status %s: %s", status, exc)
                        if status == 403 and attempt < attempts - 1:
                            wait_for = max(2.0, 30.0 - (time.time() % 30.0))
                            logger.warning(
                                "Angel One rejected TOTP (attempt %s/%s); waiting %.1fs for next window",
                                attempt + 1,
                                attempts,
                                wait_for,
                            )
                            time.sleep(wait_for)
                            continue
                        raise
                else:
                    raise RuntimeError("Angel One login failed after retries")
            except ImportError:
                logger.error("pyotp package not installed. Install: pip install pyotp")
                raise RuntimeError("pyotp required for Angel One TOTP")
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
        
    def _load_token_map(self) -> None:
        """Load token mapping from environment or file."""
        # You can load from a JSON file or environment variable
        # Format: {"RELIANCE": {"exchangeType": 1, "token": "2885"}, ...}
        token_map_str = os.getenv("ANGELONE_TOKEN_MAP", "{}")
        try:
            self._token_map = json.loads(token_map_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse ANGELONE_TOKEN_MAP, using empty map")
            self._token_map = {}
    
    def _get_token_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get exchange type and token for a symbol."""
        upper = symbol.upper()
        if upper in self._token_map:
            return self._token_map[upper]

        canonical = self._alias_to_symbol.get(upper)
        if canonical:
            return self._token_map.get(canonical)

        # Try with -EQ fallback if not already attempted
        if not upper.endswith("-EQ"):
            canonical = self._alias_to_symbol.get(f"{upper}-EQ")
            if canonical:
                return self._token_map.get(canonical)

        return None
    
    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        """Subscribe to initial symbols on connection."""
        # Pre-fetch Nifty 500 symbols if enabled
        if self.enable_nifty500_prefetch:
            await self._prefetch_nifty500(ws)
        
        # Subscribe to any additional requested symbols
        if symbols:
            await self._batch_subscribe(ws, list(symbols), subscribe=True)
    
    async def _prefetch_nifty500(self, ws) -> None:
        """
        Pre-fetch all Nifty 500 symbols in a SINGLE batch request.
        
        Angel One WebSocket supports subscribing to multiple symbols in one request
        by grouping them by exchange type. This is the most efficient approach:
        - Single API request for all 500 symbols
        - Instant subscription
        - No rate limit concerns
        - All prices streaming immediately
        """
        try:
            from nifty500_symbols import get_nifty500_symbols
            
            nifty500 = get_nifty500_symbols()
            logger.info(f"📊 Pre-fetching ALL {len(nifty500)} Nifty-500 symbols in single batch...")
            
            # Subscribe to all symbols in ONE batch request
            # The _batch_subscribe method groups by exchange type automatically
            await self._batch_subscribe(ws, nifty500, subscribe=True)
            
            logger.info(f"✅ Nifty-500 pre-fetch complete! All {len(nifty500)} symbols subscribed and streaming.")
            
        except ImportError:
            logger.warning(
                "⚠️  nifty500_symbols module not found. "
                "Nifty-500 pre-fetch disabled. Only on-demand symbol subscriptions will work."
            )
        except Exception as e:
            logger.error(f"❌ Failed to pre-fetch Nifty-500 symbols: {e}", exc_info=True)
    
    async def subscribe_symbol(self, ws, symbol: str) -> None:
        """Subscribe to a single symbol."""
        await self._batch_subscribe(ws, [symbol], subscribe=True)
    
    async def unsubscribe_symbol(self, ws, symbol: str) -> None:
        """Unsubscribe from a single symbol."""
        await self._batch_subscribe(ws, [symbol], subscribe=False)
    
    async def _batch_subscribe(self, ws, symbols: List[str], subscribe: bool) -> None:
        """
        Batch subscribe/unsubscribe to multiple symbols.
        Angel One format:
        {
            "correlationID": "abcde12345",
            "action": 1,  # 1=subscribe, 0=unsubscribe
            "params": {
                "mode": 1,  # 1=LTP, 2=Quote, 3=SnapQuote
                "tokenList": [
                    {
                        "exchangeType": 1,  # 1=nse_cm, 2=nse_fo, 3=bse_cm, etc.
                        "tokens": ["10626", "5290"]
                    }
                ]
            }
        }
        """
        # Group symbols by exchange type
        exchange_groups: Dict[int, List[str]] = {}
        
        for symbol in symbols:
            token_info = self._get_token_info(symbol)
            if not token_info:
                logger.warning(f"No token mapping found for {symbol}, skipping")
                continue
            
            exchange_type = token_info.get("exchangeType", 1)  # Default to NSE CM
            token = token_info.get("token")
            
            if not token:
                logger.warning(f"No token found for {symbol}, skipping")
                continue
            
            if exchange_type not in exchange_groups:
                exchange_groups[exchange_type] = []
            exchange_groups[exchange_type].append(token)
        
        if not exchange_groups:
            return
        
        # Build tokenList
        token_list = [
            {"exchangeType": ex_type, "tokens": tokens}
            for ex_type, tokens in exchange_groups.items()
        ]
        
        # Build request
        request = {
            "correlationID": f"req_{int(time.time() * 1000)}",
            "action": 1 if subscribe else 0,
            "params": {
                "mode": 1,  # LTP mode for now (can be configurable)
                "tokenList": token_list
            }
        }
        
        await ws.send(json.dumps(request))
        logger.info(f"{'Subscribed to' if subscribe else 'Unsubscribed from'} {len(symbols)} symbols")
    
    async def send_heartbeat(self, ws) -> None:
        """Send heartbeat ping message."""
        current_time = time.time()
        if current_time - self._last_heartbeat >= self._heartbeat_interval:
            await ws.send("ping")
            self._last_heartbeat = current_time
    
    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:
        """
        Handle Angel One WebSocket messages.
        - Text messages: "pong" (heartbeat response) or JSON error responses
        - Binary messages: Market data in binary format (Little Endian)
        """
        # Handle text messages (heartbeat, errors)
        if isinstance(message, str):
            if message == "pong":
                return []
            
            # Try to parse as JSON error
            try:
                error_data = json.loads(message)
                if "errorCode" in error_data:
                    logger.error(f"Angel One error: {error_data}")
                return []
            except json.JSONDecodeError:
                return []
        
        # Handle binary data
        if isinstance(message, bytes):
            return self._parse_binary_message(message)
        
        return []
    
    def _parse_binary_message(self, data: bytes) -> Sequence[WebsocketMessage]:
        """
        Parse binary market data from Angel One.
        
        LTP Mode (51 bytes):
        - Subscription Mode (1 byte) at index 0
        - Exchange Type (1 byte) at index 1
        - Token (25 bytes) at index 2-26
        - Sequence Number (8 bytes) at index 27
        - Exchange Timestamp (8 bytes) at index 35
        - Last Traded Price (8 bytes) at index 43
        """
        try:
            if len(data) < 51:
                logger.debug(f"Binary packet too small: {len(data)} bytes")
                return []
            
            # Parse subscription mode
            subscription_mode = data[0]
            
            # Parse exchange type
            exchange_type = data[1]
            
            # Parse token (25 bytes, null-terminated string)
            token_bytes = data[2:27]
            token = token_bytes.split(b'\x00')[0].decode('utf-8').strip()
            
            # Parse LTP (8 bytes at index 43, int64 little endian)
            ltp_raw = int.from_bytes(data[43:51], byteorder='little', signed=True)
            
            # Convert price: divide by 100 for stocks (paise to rupees)
            # For currencies, divide by 10000000.0 for 4 decimal places
            if exchange_type == 5:  # MCX
                price = Decimal(ltp_raw) / Decimal('10000000.0')
            else:
                price = Decimal(ltp_raw) / Decimal('100')
            
            # Find symbol from token
            symbol = self._find_symbol_by_token(token, exchange_type)
            if not symbol:
                logger.debug(f"Symbol not found for token {token}, exchange {exchange_type}")
                return []
            
            return [
                WebsocketMessage(
                    symbol=symbol.upper(),
                    price=price,
                    raw={"token": token, "exchangeType": exchange_type, "mode": subscription_mode}
                )
            ]
            
        except Exception as e:
            logger.error(f"Error parsing Angel One binary message: {e}")
            return []
    
    def _find_symbol_by_token(self, token: str, exchange_type: int) -> Optional[str]:
        """Find symbol name from token and exchange type."""
        for symbol, info in self._token_map.items():
            if info.get("token") == token and info.get("exchangeType") == exchange_type:
                # Return preferred alias without NSE suffix if available
                alias = self._symbol_to_alias.get(symbol, symbol)
                if alias.endswith("-EQ"):
                    return alias.removesuffix("-EQ")
                return alias
        return None
    
    def get_historical_candles(
        self,
        symbol: str,
        interval: str,
        fromdate: str,
        todate: str,
        exchange: str = "NSE"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch historical candle data from Angel One Historical API.
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE", "TCS")
            interval: Candle interval - ONE_MINUTE, THREE_MINUTE, FIVE_MINUTE, 
                     TEN_MINUTE, FIFTEEN_MINUTE, THIRTY_MINUTE, ONE_HOUR, ONE_DAY
            fromdate: Start datetime in format "YYYY-MM-DD HH:MM"
            todate: End datetime in format "YYYY-MM-DD HH:MM"
            exchange: Exchange name (default: "NSE")
        
        Returns:
            List of candle dictionaries with keys: timestamp, open, high, low, close, volume
            Returns None if request fails or symbol not found
        """
        import httpx
        
        # Normalize symbol and get token
        normalized = self.normalize_symbol(symbol)
        token_info = self._token_map.get(normalized)
        
        if not token_info:
            logger.warning(f"Symbol {symbol} (normalized: {normalized}) not found in token map")
            return None
        
        symbol_token = token_info.get("token")
        if not symbol_token:
            logger.warning(f"No token found for symbol {normalized}")
            return None
        
        exchange = token_info.get("exchange", exchange)
        
        # Validate interval
        valid_intervals = {
            "ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", 
            "TEN_MINUTE", "FIFTEEN_MINUTE", "THIRTY_MINUTE",
            "ONE_HOUR", "ONE_DAY"
        }
        if interval not in valid_intervals:
            logger.error(f"Invalid interval: {interval}. Must be one of {valid_intervals}")
            return None
        
        # Prepare API request
        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
        
        headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": self.api_key
        }
        
        payload = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": fromdate,
            "todate": todate
        }
        
        retries = int(os.getenv("ANGELONE_HISTORICAL_RETRIES", "4"))
        backoff = float(os.getenv("ANGELONE_HISTORICAL_BACKOFF_SECONDS", "2.0"))

        for attempt in range(1, retries + 1):
            try:
                with httpx.Client(timeout=30.0) as client:
                    response = client.post(url, json=payload, headers=headers)
                    response.raise_for_status()
                    
                    data = response.json()
                    
                    if not data.get("status"):
                        error_msg = data.get("message", "Unknown error")
                        logger.error(f"Angel One candle API failed: {error_msg}")
                        # Retry on transient rate-limit messages
                        if attempt < retries and "try after sometime" in error_msg.lower():
                            sleep_for = backoff * attempt
                            logger.warning("Retrying historical fetch for %s in %.1fs", symbol, sleep_for)
                            time.sleep(sleep_for)
                            continue
                        return None
                    
                    # Extract candle data
                    candles_raw = data.get("data", [])
                    
                    if not candles_raw:
                        logger.warning(f"No candle data returned for {symbol}")
                        return None
                    
                    # Transform to standard format
                    candles = []
                    for candle in candles_raw:
                        if len(candle) >= 6:
                            candles.append({
                                "timestamp": candle[0],  # ISO format timestamp
                                "open": float(candle[1]),
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                                "volume": int(candle[5]) if candle[5] is not None else 0,
                            })
                    
                    logger.info(f"✅ Fetched {len(candles)} candles for {symbol} ({interval})")
                    return candles
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text
                logger.error(
                    "HTTP error fetching candles for %s: %s - %s",
                    symbol,
                    status,
                    body,
                )
                if status in (429, 403) and "exceeding access rate" in body.lower() and attempt < retries:
                    sleep_for = backoff * attempt
                    logger.warning("Rate limited by Angel One. Sleeping %.1fs before retrying %s", sleep_for, symbol)
                    time.sleep(sleep_for)
                    continue
                return None
            except Exception as e:
                logger.error(f"Error fetching candles for {symbol}: {e}")
                if attempt < retries:
                    sleep_for = backoff * attempt
                    logger.warning("Retrying historical fetch for %s in %.1fs after exception", symbol, sleep_for)
                    time.sleep(sleep_for)
                    continue
                return None

        return None


class FivePaisaAdapter(WebsocketAdapter):
    """Adapter for 5paisa websocket price streams with configurable payloads."""

    def __init__(self) -> None:
        super().__init__("5paisa")
        ws_url = os.getenv("MARKET_DATA_WS_URL") or os.getenv("FIVEPAISA_WS_URL")
        if not ws_url:
            raise RuntimeError("FIVEPAISA_WS_URL environment variable is required for 5paisa market data")
        self.ws_url = ws_url
        self.auth_message = os.getenv("FIVEPAISA_AUTH_MESSAGE")
        self.subscribe_template = os.getenv("FIVEPAISA_SUBSCRIBE_TEMPLATE")
        self.unsubscribe_template = os.getenv("FIVEPAISA_UNSUBSCRIBE_TEMPLATE")
        self.symbol_key = os.getenv("FIVEPAISA_SYMBOL_KEY", "Symbol")
        self.price_keys = [
            key.strip()
            for key in os.getenv("FIVEPAISA_PRICE_KEYS", "LastTradedPrice,LastRate,LTP,Price").split(",")
            if key.strip()
        ]
        self.batch_key = os.getenv("FIVEPAISA_BATCH_KEY", "Data")

    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        if self.auth_message:
            await ws.send(self.auth_message)
        for symbol in symbols:
            await self.subscribe_symbol(ws, symbol)

    async def subscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_subscription(symbol, subscribe=True)
        if payload:
            await ws.send(payload)

    async def unsubscribe_symbol(self, ws, symbol: str) -> None:
        payload = self._build_subscription(symbol, subscribe=False)
        if payload:
            await ws.send(payload)

    def _build_subscription(self, symbol: str, subscribe: bool) -> Optional[str]:
        template = self.subscribe_template if subscribe else self.unsubscribe_template
        if template:
            try:
                return template.format(symbol=symbol)
            except Exception:
                logger.warning("5paisa subscription template formatting failed for symbol %s", symbol)
                return None
        default_payload = {
            "Method": "SUBSCRIBE_L2" if subscribe else "UNSUBSCRIBE_L2",
            "Instrument": [symbol],
        }
        return json.dumps(default_payload)

    async def handle_message(self, message: str) -> Sequence[WebsocketMessage]:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("5paisa stream discarded non-JSON payload: %s", message)
            return []

        entries: List[Dict[str, Any]] = []
        batch = payload.get(self.batch_key) or payload.get(self.batch_key.lower())
        if isinstance(batch, list):
            entries.extend(batch)
        elif isinstance(payload, dict):
            entries.append(payload)

        messages: List[WebsocketMessage] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            symbol = entry.get(self.symbol_key) or entry.get(self.symbol_key.lower()) or entry.get("Token")
            price = self._extract_price(entry)
            if not symbol or price is None:
                continue
            messages.append(
                WebsocketMessage(
                    symbol=str(symbol).upper(),
                    price=price,
                    raw=entry,
                )
            )
        return messages

    def _extract_price(self, entry: Dict[str, Any]) -> Optional[Decimal]:
        for key in self.price_keys:
            value = entry.get(key) or entry.get(key.lower())
            if value is None:
                continue
            try:
                return Decimal(str(value))
            except Exception:
                continue
        return None


class MarketPriceSubject(ConnectorSubject):
    """Pathway connector subject managing a single websocket connection."""

    def __init__(self, adapter: WebsocketAdapter, retry_seconds: int = DEFAULT_RETRY_SECONDS) -> None:
        super().__init__()
        self._adapter = adapter
        self._retry_seconds = retry_seconds
        self._symbols: Set[str] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._symbol_queue: Optional[asyncio.Queue[str]] = None
        self._pending: Set[str] = set()
        self._lock = threading.Lock()

    @property
    def adapter(self) -> WebsocketAdapter:
        return self._adapter
    
    @property
    def _deletions_enabled(self) -> bool:
        """Disable deletions for better performance since we only add price updates."""
        return False

    def add_symbol(self, symbol: str) -> None:
        normalized = self._adapter.normalize_symbol(symbol).upper()
        with self._lock:
            if normalized in self._symbols:
                return
            self._symbols.add(normalized)
            if self._loop and self._loop.is_running() and self._symbol_queue is not None:
                asyncio.run_coroutine_threadsafe(self._symbol_queue.put(normalized), self._loop)
            else:
                self._pending.add(normalized)

    def run(self) -> None:
        """Main entry point called by Pathway in dedicated thread."""
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        while True:
            try:
                await self._run_single_connection()
            except asyncio.CancelledError:  # pragma: no cover - shutdown path
                raise
            except Exception as exc:  # pragma: no cover - logging only
                logger.exception("MarketPriceSubject reconnect triggered: %s", exc)
                await asyncio.sleep(self._retry_seconds)

    async def _run_single_connection(self) -> None:
        import websockets

        url = getattr(self._adapter, "ws_url", DEFAULT_WS_URL)
        logger.info("Connecting to market data stream: %s", url)
        
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            self._loop = asyncio.get_running_loop()
            self._symbol_queue = asyncio.Queue()

            # Add pending symbols to queue
            for symbol in list(self._pending):
                await self._symbol_queue.put(symbol)
            self._pending.clear()

            # Initial connection and subscription
            await self._adapter.on_connect(ws, list(self._symbols))

            # Run message consumer and subscription dispatcher concurrently
            consumer = asyncio.create_task(self._consume_messages(ws))
            subscriber = asyncio.create_task(self._dispatch_subscriptions(ws, self._symbol_queue))

            done, pending = await asyncio.wait(
                {consumer, subscriber},
                return_when=asyncio.FIRST_EXCEPTION,
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            # Re-raise exceptions
            for task in done:
                if task.exception():
                    raise task.exception()
                    
        self._symbol_queue = None
        self._loop = None

    async def _consume_messages(self, ws) -> None:
        """Consume WebSocket messages and push to Pathway buffer."""
        async for message in ws:
            try:
                # Send heartbeat for Angel One if needed
                if isinstance(self._adapter, AngelOneAdapter):
                    await self._adapter.send_heartbeat(ws)
                
                parsed_messages = await self._adapter.handle_message(message)
                if not parsed_messages:
                    continue
                    
                # Send each parsed message to Pathway immediately
                for parsed in parsed_messages:
                    self.next(
                        symbol=parsed.symbol.upper(),
                        price=str(parsed.price),
                        provider=self._adapter.name,
                        raw=json.dumps(parsed.raw, default=str),
                        received_at=time.time(),
                    )
            except Exception as exc:
                logger.error(f"Error processing message: {exc}", exc_info=True)
                continue

    async def _dispatch_subscriptions(self, ws, queue: asyncio.Queue[str]) -> None:
        """Handle dynamic symbol subscriptions."""
        while True:
            symbol = await queue.get()
            try:
                await self._adapter.subscribe_symbol(ws, symbol)
                logger.info("Subscribed to %s", symbol)
            except Exception as exc:
                logger.error("Failed to subscribe %s: %s", symbol, exc)
                self._pending.add(symbol)
                await asyncio.sleep(self._retry_seconds)


class MarketDataService:
    """Singleton service exposing cached market prices sourced via Pathway stream."""

    _instance: Optional["MarketDataService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, adapter: Optional[WebsocketAdapter] = None) -> None:
        os.environ.setdefault("PATHWAY_DISABLE_PROGRESS", "1")
        os.environ.setdefault("PATHWAY_LOG_LEVEL", "warning")
        self.adapter = adapter or self._select_adapter()
        self.subject = MarketPriceSubject(self.adapter)
        self._latest: Dict[str, Decimal] = {}
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._runner_thread = threading.Thread(target=self._run_pathway_runtime, daemon=True)
        self._runner_thread.start()
        self._started.wait(timeout=10)

    @classmethod
    def get_instance(cls) -> "MarketDataService":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register_symbol(self, symbol: str) -> None:
        normalized = self.adapter.normalize_symbol(symbol)
        self.subject.add_symbol(normalized)

    def get_latest_price(self, symbol: str) -> Optional[Decimal]:
        normalized = symbol.upper()
        with self._lock:
            price = self._latest.get(normalized)
            if price is not None:
                return price
            alt = self.adapter.normalize_symbol(symbol).upper()
            if alt != normalized:
                return self._latest.get(alt)
            return None

    def get_or_fetch_price(self, symbol: str) -> Decimal:
        normalized = symbol.upper()
        price = self.get_latest_price(normalized)
        if price is not None:
            return price

        logger.info("Waiting for first tick for %s", normalized)
        self.register_symbol(normalized)

        for _ in range(20):
            price = self.get_latest_price(normalized)
            if price is not None:
                return price
            time.sleep(0.5)

        raise RuntimeError(f"Live price for {normalized} unavailable from provider {self.adapter.name}")

    async def await_price(self, symbol: str, timeout: float = 3.0) -> Decimal:
        """Wait for a price update for the given symbol with short timeout for responsiveness."""
        normalized = symbol.upper()
        self.register_symbol(symbol)
        deadline = time.time() + timeout

        # Quick initial check
        price = self.get_latest_price(normalized)
        if price is not None:
            return price

        # Poll with short intervals for real-time responsiveness
        while time.time() < deadline:
            price = self.get_latest_price(normalized)
            if price is not None:
                return price
            await asyncio.sleep(0.1)  # Poll every 100ms

        raise RuntimeError(f"Timed out waiting for live price for {normalized}")

    def _run_pathway_runtime(self) -> None:
        """Run Pathway runtime with optimized settings for real-time streaming."""
        try:
            monitoring_level = getattr(pw, "MonitoringLevel", None)
            if monitoring_level and hasattr(pw, "set_monitoring_config"):
                pw.set_monitoring_config(monitoring_level=monitoring_level.NONE)
        except Exception:
            logger.debug("Unable to set Pathway monitoring configuration", exc_info=True)

        # Read from the WebSocket subject
        table = pw.io.python.read(
            self.subject,
            schema=MarketTickSchema,
            autocommit_duration_ms=100,  # Commit every 100ms for near real-time updates
            name="market_data_stream",
        )

        def on_tick(key, row, time, is_addition) -> None:
            """Process each price update immediately."""
            if not is_addition:
                return
            try:
                price = Decimal(row["price"])
            except Exception:
                logger.debug("Skipping tick with invalid price: %s", row)
                return
            symbol = row["symbol"].upper()
            aliases = self.adapter.aliases_for(symbol)
            with self._lock:
                for alias in aliases:
                    old_price = self._latest.get(alias.upper())
                    self._latest[alias.upper()] = price
                    if old_price != price:
                        logger.debug(f"💰 {alias}: {old_price} → {price}")

        # Subscribe to table changes
        pw.io.subscribe(table, on_tick)
        
        # Signal that we're ready to start
        self._started.set()
        
        try:
            monitoring_level = getattr(pw, "MonitoringLevel", None)
            if monitoring_level is not None and hasattr(monitoring_level, "NONE"):
                pw.run(monitoring_level=monitoring_level.NONE)
            else:
                pw.run()
        finally:
            logger.info("Pathway runtime shut down")

    def _select_adapter(self) -> WebsocketAdapter:
        provider = os.getenv("MARKET_DATA_PROVIDER", DEFAULT_PROVIDER).lower()
        if provider == "finnhub":
            return FinnhubAdapter()
        if provider in {"angelone", "angel", "smartapi"}:
            try:
                return AngelOneAdapter()
            except RuntimeError as exc:
                raise RuntimeError(
                    "Angel One adapter configuration is incomplete. "
                    "Please set ANGELONE_CLIENT_CODE, ANGELONE_API_KEY, "
                    "ANGELONE_PASSWORD, and ANGELONE_TOTP_SECRET."
                ) from exc
        if provider in {"5paisa", "fivepaisa"}:
            return FivePaisaAdapter()
        return GenericJSONAdapter()


def get_market_data_service() -> MarketDataService:
    return MarketDataService.get_instance()


def get_live_price(symbol: str) -> Decimal:
    service = get_market_data_service()
    return service.get_or_fetch_price(symbol)


async def await_live_price(symbol: str, timeout: float = 10.0) -> Decimal:
    service = get_market_data_service()
    return await service.await_price(symbol, timeout=timeout)
