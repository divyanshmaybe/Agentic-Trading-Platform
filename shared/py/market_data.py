from __future__ import annotations

import os

# Disable Pathway progress dashboard before importing pathway
os.environ.setdefault("PATHWAY_DISABLE_PROGRESS", "1")
os.environ.setdefault("PATHWAY_LOG_LEVEL", "warning")

import asyncio
import contextlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import pathway as pw
from pathway.io.python import ConnectorSubject
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = os.getenv("MARKET_DATA_WS_URL", "wss://example.com/stream")
DEFAULT_PROVIDER = "generic"
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
        
        if not all([self.client_code, self.api_key, self.password, self.totp_secret]):
            raise RuntimeError(
                "Angel One requires: ANGELONE_CLIENT_CODE, ANGELONE_API_KEY, ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET"
            )
        
        # These will be set after login
        self.jwt_token = None
        self.feed_token = None
        self.refresh_token = None
        
        # Token cache file path
        self.token_cache_file = os.path.join(
            os.path.dirname(__file__),
            "../../apps/portfolio-server/docs/angelone_tokens.json"
        )
        
        # Token mapping: symbol -> {"exchangeType": int, "token": str, "name": str}
        self._token_map: Dict[str, Dict[str, Any]] = {}
        
        # Load or generate token map
        self._load_or_generate_token_map()
        
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
            logger.info("� Using fallback token map (10 stocks). Full map will be generated by Celery worker.")
            self._token_map = FALLBACK_TOKEN_MAP.copy()
        except Exception as e:
            logger.error(f"Failed to load token map: {e}")
            logger.info("📋 Using fallback token map")
            self._token_map = FALLBACK_TOKEN_MAP.copy()
    
    def _login(self) -> None:
        """Login to Angel One API to get JWT and feed tokens."""
        import pyotp
        import httpx
        
        try:
            # Generate TOTP
            totp = pyotp.TOTP(self.totp_secret).now()
            logger.info(f"Generated TOTP: {totp}")
            
            # Login API endpoint
            login_url = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
            
            # Prepare headers and payload
            headers = {
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
                "clientcode": self.client_code,
                "password": self.password,
                "totp": totp
            }
            
            # Make login request
            with httpx.Client(timeout=30.0) as client:
                response = client.post(login_url, json=payload, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                
                if not data.get("status"):
                    error_msg = data.get("message", "Unknown error")
                    raise RuntimeError(f"Angel One login failed: {error_msg}")
                
                # Extract tokens
                response_data = data.get("data", {})
                self.jwt_token = response_data.get("jwtToken")
                self.feed_token = response_data.get("feedToken")
                self.refresh_token = response_data.get("refreshToken")
                
                if not all([self.jwt_token, self.feed_token]):
                    raise RuntimeError("Failed to get tokens from Angel One login response")
                
                logger.info(f"✅ Angel One login successful! Feed token: {self.feed_token[:10]}...")
                
        except ImportError:
            logger.error("pyotp package not installed. Install: pip install pyotp")
            raise RuntimeError("pyotp required for Angel One TOTP")
        except Exception as e:
            logger.error(f"Angel One login failed: {e}")
            raise
        
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
        return self._token_map.get(symbol.upper())
    
    async def on_connect(self, ws, symbols: Iterable[str]) -> None:
        """Subscribe to initial symbols on connection."""
        if symbols:
            await self._batch_subscribe(ws, list(symbols), subscribe=True)
    
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
                return symbol
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
        normalized = symbol.upper()
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
                        symbol=parsed.symbol,
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
        normalized = symbol.upper()
        self.subject.add_symbol(normalized)

    def get_latest_price(self, symbol: str) -> Optional[Decimal]:
        normalized = symbol.upper()
        with self._lock:
            return self._latest.get(normalized)

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
        self.register_symbol(normalized)
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
            with self._lock:
                old_price = self._latest.get(symbol)
                self._latest[symbol] = price
                if old_price != price:
                    logger.debug(f"💰 {symbol}: {old_price} → {price}")

        # Subscribe to table changes
        pw.io.subscribe(table, on_tick)
        
        # Signal that we're ready to start
        self._started.set()
        
        try:
            # Run with minimal monitoring overhead
            monitoring_level = getattr(pw, "MonitoringLevel", None)
            if monitoring_level is not None and hasattr(monitoring_level, "NONE"):
                pw.run(monitoring_level=monitoring_level.NONE)
            else:
                pw.run()
        except AttributeError:
            pw.run()

    def _select_adapter(self) -> WebsocketAdapter:
        provider = os.getenv("MARKET_DATA_PROVIDER", DEFAULT_PROVIDER).lower()
        if provider == "finnhub":
            return FinnhubAdapter()
        if provider in {"angelone", "angel", "smartapi"}:
            return AngelOneAdapter()
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
