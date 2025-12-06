"""
Simple Market Data Service
Request → Subscribe → Return Price
No Pathway, no complex threading - just simple async WebSocket
"""

import asyncio
import json
import logging
import os
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set
import websockets
from websockets.exceptions import ConnectionClosedError

logger = logging.getLogger(__name__)

# Map legacy/delisted tickers to their current Angel One equivalents so
# old portfolio positions (e.g. HDFC) can still fetch quotes via HDFCBANK.
SYMBOL_ALIASES: Dict[str, str] = {
    "HDFC": "HDFCBANK",
    "HDFC-EQ": "HDFCBANK-EQ",
    "HDFC.NS": "HDFCBANK",
}


class AngelOneAdapter:
    """Adapter for Angel One market data operations."""
    
    def __init__(self, service: "MarketDataService"):
        self.service = service
        self.name = "simple-angelone"
    
    def get_historical_candles(
        self,
        symbol: str,
        interval: str,
        fromdate: str,
        todate: str,
        exchange: str = "NSE"
    ) -> List[Dict[str, Any]]:
        """Fetch historical candles from Angel One API."""
        return self.service.get_historical_candles(symbol, interval, fromdate, todate, exchange)


class MarketDataService:
    """
    Simple market data service that:
    1. Maintains a single WebSocket connection
    2. Subscribes to symbols on-demand
    3. Caches prices in memory
    4. Returns prices immediately when requested
    """
    
    _instance: Optional["MarketDataService"] = None
    _lock = asyncio.Lock()
    
    def __init__(self):
        # Load environment variables
        from dotenv import load_dotenv
        import os
        
        # Try to load .env from various possible locations
        env_loaded = False
        possible_paths = [
            os.path.join(os.path.dirname(__file__), "../../.env"),  # shared/py/../../.env
            os.path.join(os.path.dirname(__file__), "../../../.env"),  # shared/py/../../../.env
            ".env",  # current directory
            "../.env",  # parent directory
            "../../.env",  # grandparent directory
        ]
        
        for env_path in possible_paths:
            if os.path.exists(env_path):
                load_dotenv(env_path, override=False)
                logger.info(f"Loaded environment from {env_path}")
                env_loaded = True
                break
        
        if not env_loaded:
            logger.warning("No .env file found, using system environment variables")
        
        self.client_code = os.getenv("ANGELONE_CLIENT_CODE")
        self.api_key = os.getenv("ANGELONE_API_KEY")
        self.password = os.getenv("ANGELONE_PASSWORD")
        self.totp_secret = os.getenv("ANGELONE_TOTP_SECRET")
        
        if not all([self.client_code, self.api_key, self.password, self.totp_secret]):
            raise RuntimeError("Angel One credentials required")
        
        # Simple in-memory cache
        self._prices: Dict[str, Decimal] = {}
        self._subscribed: Set[str] = set()
        
        # WebSocket connection
        self._ws: Optional[websockets.WebSocketServerProtocol] = None
        self._ws_task: Optional[asyncio.Task] = None
        self._connected = False
        self._token_map: Dict[str, Dict[str, any]] = {}
        self._init_done = False
        
        # Load token map (sync)
        self._load_token_map()
        
        # Login to get tokens (sync)
        self._login()
        
    async def _ensure_init(self):
        """Ensure WebSocket is started"""
        if not self._init_done:
            self._init_done = True
            await self._start_websocket()
    
    @classmethod
    async def get_instance(cls) -> "MarketDataService":
        """Get singleton instance"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        await cls._instance._ensure_init()
        return cls._instance
    
    def _load_token_map(self):
        """Load token map from Angel One API - ALL symbols"""
        try:
            import httpx
            
            # Fetch directly from Angel One API
            url = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
            response = httpx.get(url, timeout=30)
            response.raise_for_status()
            
            instruments = response.json()
            
            # Load ALL symbols (no filtering)
            token_map = {}
            for instrument in instruments:
                symbol = instrument.get("symbol", "")
                if symbol:  # Only skip if symbol is empty
                    # Map exch_seg to exchangeType for WebSocket subscription
                    exch_seg = instrument.get("exch_seg", "")
                    exchange_type = 1  # Default to NSE
                    if exch_seg == "NSE":
                        exchange_type = 1
                    elif exch_seg == "BSE":
                        exchange_type = 3
                    elif exch_seg in ["NFO", "MCX", "CDS"]:
                        exchange_type = 2
                    
                    token_map[symbol] = {
                        "token": instrument["token"],
                        "symbol": symbol,
                        "name": instrument.get("name", ""),
                        "expiry": instrument.get("expiry", ""),
                        "strike": instrument.get("strike", ""),
                        "lotsize": instrument.get("lotsize", "1"),
                        "instrumenttype": instrument.get("instrumenttype", ""),
                        "exch_seg": exch_seg,
                        "exchangeType": exchange_type,  # Add exchangeType for WebSocket
                        "tick_size": instrument.get("tick_size", "0.05"),
                    }
            
            self._token_map = token_map
            logger.info(f"✅ Loaded {len(self._token_map):,} symbols from Angel One API (all exchanges)")
        except Exception as e:
            logger.error(f"❌ Failed to load token map from Angel One API: {e}")
            self._token_map = {}
    
    def _login(self):
        """Login to Angel One to get feed token with retry logic"""
        import pyotp
        import httpx
        import time

        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                totp = pyotp.TOTP(self.totp_secret).now()
                
                url = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
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
                
                payload = {
                    "clientcode": self.client_code,
                    "password": self.password,
                    "totp": totp,
                }
                
                response = httpx.post(url, json=payload, headers=headers, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                if data.get("status") and data.get("data"):
                    self.feed_token = data["data"]["feedToken"]
                    self.jwt_token = data["data"]["jwtToken"]
                    logger.info("✅ Angel One login successful")
                    return
                else:
                    raise RuntimeError(f"Login failed: {data}")
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    logger.warning(
                        f"⚠️ Angel One 403 error (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s..."
                    )
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                raise
            except Exception as e:
                logger.warning(
                    f"⚠️ Angel One login failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                raise
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol (strip .NS, handle aliases)"""
        upper = symbol.upper()
        if upper.endswith(".NS"):
            upper = upper[:-3]
        # Apply alias mapping before checking the token map
        upper = SYMBOL_ALIASES.get(upper, upper)
        # Try to find in token map (exact match first)
        if upper in self._token_map:
            return upper
        # Try with -EQ suffix (Angel One NSE equity symbols require this)
        eq_symbol = f"{upper}-EQ"
        eq_symbol = SYMBOL_ALIASES.get(eq_symbol, eq_symbol)
        if eq_symbol in self._token_map:
            # Emit a one-time log to help trace alias lookups in production
            if upper != symbol.upper():
                logger.info("Symbol %s normalized to %s via alias table", symbol, eq_symbol)
            return eq_symbol
        return upper
    
    def _get_token_info(self, symbol: str, prefer_exchange: str = "NSE") -> Optional[Dict]:
        """
        Get token info for symbol with automatic fallback.
        
        For equities, tries the symbol as-is, then EQ → BE → BL → N1 → N2 variants.
        Angel One API requires -EQ suffix for NSE equity symbols.
        Prefers NSE tokens over BSE when both are available.
        
        Returns the token info dict with an added '_matched_key' field containing
        the actual key that was matched in the token map.
        """
        # First try to normalize the symbol (handles .NS suffix, aliases, etc.)
        normalized = self._normalize_symbol(symbol)
        
        # Collect all matching tokens, preferring NSE
        candidates = []
        
        if normalized in self._token_map:
            info = self._token_map[normalized].copy()
            info['_matched_key'] = normalized
            candidates.append(info)
        
        # If not found and symbol doesn't already have a segment suffix, try variants
        upper = symbol.upper()
        if upper.endswith(".NS"):
            upper = upper[:-3]
        
        # Try equity variants: EQ → BE → BL → N1 → N2
        variants = ['EQ', 'BE', 'BL', 'N1', 'N2']
        for variant in variants:
            symbol_key = f"{upper}-{variant}"
            if symbol_key in self._token_map:
                info = self._token_map[symbol_key].copy()
                info['_matched_key'] = symbol_key
                candidates.append(info)
        
        if not candidates:
            return None
        
        # Prefer the exchange matching prefer_exchange (default NSE)
        exchange_priority = {"NSE": 0, "BSE": 1, "NFO": 2, "MCX": 3, "CDS": 4}
        preferred_priority = exchange_priority.get(prefer_exchange, 1)
        
        # Sort by: 1) matching preferred exchange, 2) exchange priority, 3) original order
        def sort_key(info):
            exch = info.get("exch_seg", "")
            is_preferred = 0 if exch == prefer_exchange else 1
            priority = exchange_priority.get(exch, 99)
            return (is_preferred, priority)
        
        candidates.sort(key=sort_key)
        return candidates[0]
    
    def has_symbol(self, symbol: str) -> bool:
        """Check if symbol exists in Angel One token map"""
        return self._get_token_info(symbol) is not None
    
    def search_similar_symbols(self, symbol: str, limit: int = 5) -> List[str]:
        """Find similar symbols in token map (for debugging invalid symbols)"""
        normalized = self._normalize_symbol(symbol).upper()
        matches = []
        
        for token_symbol in self._token_map.keys():
            if normalized in token_symbol or token_symbol in normalized:
                matches.append(token_symbol)
                if len(matches) >= limit:
                    break
        
        return matches
    
    async def _start_websocket(self):
        """Start WebSocket connection in background"""
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(self._websocket_loop())
    
    async def _websocket_loop(self):
        """Main WebSocket connection loop with proper error handling"""
        ws_url = f"wss://smartapisocket.angelone.in/smart-stream?clientCode={self.client_code}&feedToken={self.feed_token}&apiKey={self.api_key}"
        
        reconnect_delay = 5
        max_reconnect_delay = 60
        
        while True:
            ws = None
            try:
                async with websockets.connect(
                    ws_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=10,  # Add close timeout
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    logger.info("✅ WebSocket connected")
                    
                    # Subscribe to already requested symbols
                    if self._subscribed:
                        await self._subscribe_batch(list(self._subscribed), ws)
                    
                    # Listen for messages
                    async for message in ws:
                        await self._handle_message(message)
                        
            except ConnectionClosedError as e:
                logger.warning(f"WebSocket closed: {e}, reconnecting in {reconnect_delay}s...")
                self._connected = False
                self._ws = None
                # Gracefully close the connection
                if ws and not ws.closed:
                    try:
                        await asyncio.wait_for(ws.close(), timeout=2.0)
                    except Exception:
                        pass
                await asyncio.sleep(reconnect_delay)
                # Exponential backoff
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            except Exception as e:
                logger.error(f"WebSocket error: {e}, reconnecting in {reconnect_delay}s...")
                self._connected = False
                self._ws = None
                # Gracefully close the connection
                if ws and not ws.closed:
                    try:
                        await asyncio.wait_for(ws.close(), timeout=2.0)
                    except Exception:
                        pass
                await asyncio.sleep(reconnect_delay)
                # Exponential backoff
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
            else:
                # Successful connection - reset delay
                reconnect_delay = 5
    
    async def _subscribe_batch(self, symbols: list, ws=None):
        """Subscribe to batch of symbols"""
        if ws is None:
            ws = self._ws
        if ws is None:
            return
        
        # Group by exchange type
        exchange_groups: Dict[int, list] = {}
        
        for symbol in symbols:
            token_info = self._get_token_info(symbol)
            if not token_info:
                logger.warning(f"No token for {symbol}, skipping")
                continue
            
            ex_type = token_info.get("exchangeType", 1)
            token = token_info.get("token")
            if not token:
                continue
            
            if ex_type not in exchange_groups:
                exchange_groups[ex_type] = []
            exchange_groups[ex_type].append(token)
        
        if not exchange_groups:
            return
        
        token_list = [
            {"exchangeType": ex_type, "tokens": tokens}
            for ex_type, tokens in exchange_groups.items()
        ]
        
        request = {
            "correlationID": f"req_{int(time.time() * 1000)}",
            "action": 1,  # subscribe
            "params": {
                "mode": 1,  # LTP mode (can upgrade to mode 2 for Quote later)
                "tokenList": token_list
            }
        }
        
        await ws.send(json.dumps(request))
        logger.info(f"✅ Subscribed to {len(symbols)} symbols")
    
    async def _handle_message(self, message):
        """Handle WebSocket message"""
        if isinstance(message, str):
            if message == "pong":
                logger.debug("Received pong")
                return
            # Try to parse JSON error messages
            try:
                error_data = json.loads(message)
                if "errorCode" in error_data:
                    logger.error(f"Angel One error: {error_data}")
            except:
                logger.debug(f"Received text message: {message[:100]}")
            return
        
        if isinstance(message, bytes):
            # Parse binary LTP message (51 bytes)
            if len(message) < 51:
                logger.debug(f"Binary message too short: {len(message)} bytes")
                return
            
            token_bytes = message[2:27]
            token = token_bytes.split(b'\x00')[0].decode('utf-8').strip()
            exchange_type = message[1]
            
            # Parse LTP (8 bytes at index 43)
            ltp_raw = int.from_bytes(message[43:51], byteorder='little', signed=True)
            price = Decimal(ltp_raw) / Decimal('100')
            
            # Find symbol from token
            symbol = self._find_symbol_by_token(token, exchange_type)
            if symbol:
                symbol_upper = symbol.upper()
                # Store in multiple formats for easy lookup
                self._prices[symbol_upper] = price
                # Also store with -EQ suffix if it doesn't have it
                if not symbol_upper.endswith("-EQ"):
                    self._prices[f"{symbol_upper}-EQ"] = price
                # Also store without -EQ if it has it
                if symbol_upper.endswith("-EQ"):
                    self._prices[symbol_upper[:-3]] = price
                logger.debug(f"💰 {symbol_upper}: {price}")
            else:
                logger.debug(f"Symbol not found for token {token}, exchange {exchange_type}")
    
    def _find_symbol_by_token(self, token: str, exchange_type: int) -> Optional[str]:
        """Find symbol from token"""
        for symbol, info in self._token_map.items():
            if info.get("token") == token and info.get("exchangeType") == exchange_type:
                # Return both with and without -EQ for cache lookup
                if symbol.endswith("-EQ"):
                    base = symbol[:-3]
                    # Store in both formats
                    return base  # Return base name
                return symbol
        return None
    
    def register_symbol(self, symbol: str) -> None:
        """Register symbol for subscription (compatibility method)"""
        # Subscription happens automatically in get_price/await_price
        pass
    
    def get_latest_price(self, symbol: str) -> Optional[Decimal]:
        """Get cached price (synchronous, no wait)"""
        normalized = self._normalize_symbol(symbol).upper()
        # Try exact match first
        price = self._prices.get(normalized)
        if price is not None:
            return price
        # Try without -EQ suffix
        if normalized.endswith("-EQ"):
            return self._prices.get(normalized[:-3])
        # Try with -EQ suffix
        return self._prices.get(f"{normalized}-EQ")
    
    def get_or_fetch_price(self, symbol: str) -> Decimal:
        """
        Get price synchronously (blocks until price available or timeout).
        For async contexts, use await_price() instead.
        """
        normalized = self._normalize_symbol(symbol).upper()
        
        # Fast path: check cache
        if normalized in self._prices:
            return self._prices[normalized]
        
        # Need to fetch - try to use existing event loop
        try:
            # Check if we're in a thread with an event loop
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context with a running loop
                # Can't block here - return cached price or raise error
                raise RuntimeError(
                    f"Price for {symbol} not in cache. Use await_price() in async context."
                )
            except RuntimeError:
                # No running loop - we can create one
                # This works in sync context (main thread or worker thread)
                return asyncio.run(self._get_price_async(normalized, timeout=1.0))
        except Exception as e:
            # Fallback: return None or raise
            logger.warning(f"Failed to fetch price for {symbol}: {e}")
            raise
    
    async def await_price(self, symbol: str, timeout: float = 3.0) -> Decimal:
        """Wait for price (async)"""
        normalized = self._normalize_symbol(symbol).upper()
        return await self._get_price_async(normalized, timeout)
    
    async def _get_price_async(self, normalized: str, timeout: float = 1.0) -> Decimal:
        """
        Internal async method to get price:
        1. Check cache
        2. If not cached, subscribe and wait
        3. Return price
        """
        # Fast path: check cache (try multiple formats)
        price = self._get_cached_price_multi(normalized)
        if price is not None:
            return price
        
        # Ensure WebSocket is running
        await self._ensure_init()
        
        if self._ws_task is None or self._ws_task.done():
            await self._start_websocket()
            # Wait a bit for connection
            await asyncio.sleep(0.5)

        # Wait for connection
        for _ in range(10):  # 1 second max
            if self._connected and self._ws:
                break
            await asyncio.sleep(0.1)
        
        if not self._connected or not self._ws:
            raise RuntimeError("WebSocket not connected")
        
        # Get the token map symbol for subscription (might be different format)
        token_info = self._get_token_info(normalized)
        if not token_info:
            # NO FALLBACK - Fail fast if symbol not in Angel One token map
            similar = self.search_similar_symbols(normalized, limit=3)
            similar_msg = f" Similar symbols found: {', '.join(similar)}" if similar else ""
            
            logger.error(
                f"❌ Symbol {normalized} not found in Angel One token map. "
                f"This symbol is either delisted, invalid, or not supported by Angel One. "
                f"Total available symbols: {len(self._token_map):,}.{similar_msg}"
            )
            raise RuntimeError(
                f"Symbol '{normalized}' not found in Angel One token map. "
                f"Check if the symbol is valid and supported by Angel One.{similar_msg}"
            )

        
        # Use the token map key for subscription
        token_map_symbol = None
        for sym, info in self._token_map.items():
            if info.get("token") == token_info.get("token") and info.get("exchangeType") == token_info.get("exchangeType"):
                token_map_symbol = sym
                break
        
        if not token_map_symbol:
            raise RuntimeError(f"Could not find token map symbol for {normalized}")
        
        # Subscribe if not already subscribed (use token map symbol)
        if token_map_symbol not in self._subscribed:
            self._subscribed.add(token_map_symbol)
            await self._subscribe_batch([token_map_symbol], self._ws)
        
        # Wait for price (poll cache with multiple formats)
        deadline = time.time() + timeout
        while time.time() < deadline:
            price = self._get_cached_price_multi(normalized)
            if price is not None:
                return price
            await asyncio.sleep(0.05)  # 50ms polling

        # Check one more time
        price = self._get_cached_price_multi(normalized)
        if price is not None:
            return price

        raise RuntimeError(f"Price for {normalized} not available (timeout {timeout}s)")
    
    def _get_cached_price_multi(self, normalized: str) -> Optional[Decimal]:
        """Get cached price trying multiple symbol formats"""
        # Try exact match first
        price = self._prices.get(normalized)
        if price is not None:
            return price
        # Try without -EQ suffix
        if normalized.endswith("-EQ"):
            price = self._prices.get(normalized[:-3])
            if price is not None:
                return price
        # Try with -EQ suffix
        if not normalized.endswith("-EQ"):
            price = self._prices.get(f"{normalized}-EQ")
            if price is not None:
                return price
        return None
    
    async def subscribe_nifty500(self) -> int:
        """
        Subscribe to all Nifty 500 symbols in bulk.
        Returns the number of symbols successfully subscribed.
        """
        try:
            from nifty500_symbols import get_nifty500_symbols
            symbols = get_nifty500_symbols()
            logger.info(f"📊 Subscribing to {len(symbols)} Nifty 500 symbols...")
        except ImportError:
            logger.warning("nifty500_symbols module not found, skipping Nifty 500 subscription")
            return 0
        except Exception as e:
            logger.error(f"Failed to load Nifty 500 symbols: {e}")
            return 0
        
        if not symbols:
            logger.warning("No Nifty 500 symbols found")
            return 0
        
        # Ensure WebSocket is running
        await self._ensure_init()
        
        if self._ws_task is None or self._ws_task.done():
            await self._start_websocket()
            # Wait for connection
            await asyncio.sleep(1.0)
        
        # Wait for connection to be ready
        for _ in range(20):  # 2 seconds max
            if self._connected and self._ws:
                break
            await asyncio.sleep(0.1)
        
        if not self._connected or not self._ws:
            logger.error("WebSocket not connected, cannot subscribe to Nifty 500")
            return 0
        
        # Filter symbols that exist in token map
        valid_symbols = []
        for symbol in symbols:
            normalized = self._normalize_symbol(symbol)
            if self._get_token_info(normalized):
                valid_symbols.append(normalized)
                # Mark as subscribed
                self._subscribed.add(normalized)
        
        if not valid_symbols:
            logger.warning("No valid symbols found in token map for Nifty 500")
            return 0
        
        # Subscribe in bulk (all at once - Angel One supports up to 1000)
        try:
            await self._subscribe_batch(valid_symbols, self._ws)
            logger.info(f"✅ Successfully subscribed to {len(valid_symbols)} Nifty 500 symbols")
            return len(valid_symbols)
        except Exception as e:
            logger.error(f"Failed to subscribe to Nifty 500 symbols: {e}")
            return 0
    
    def get_historical_candles(
        self,
        symbol: str,
        interval: str,
        fromdate: str,
        todate: str,
        exchange: str = "NSE"
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical candle data from Angel One API.
        
        Args:
            symbol: Symbol name (e.g., 'RELIANCE', 'TCS')
            interval: Time interval ('ONE_MINUTE', 'FIVE_MINUTE', 'FIFTEEN_MINUTE', 'ONE_HOUR', 'ONE_DAY')
            fromdate: Start date in 'YYYY-MM-DD HH:MM' format
            todate: End date in 'YYYY-MM-DD HH:MM' format
            exchange: Exchange name (default: 'NSE')
            
        Returns:
            List of candle dictionaries with keys: timestamp, open, high, low, close, volume
        """
        import httpx
        from datetime import datetime
        
        # Get token for symbol, preferring the specified exchange
        token_info = self._get_token_info(symbol, prefer_exchange=exchange)
        if not token_info:
            logger.warning(f"No token found for symbol {symbol}")
            return []
        
        symbol_token = token_info.get("token")
        if not symbol_token:
            logger.warning(f"No token available for {symbol}")
            return []
        
        # Use the exchange from token_info if it matches, otherwise use specified exchange
        actual_exchange = token_info.get("exch_seg", exchange)
        
        # Use the matched key from _get_token_info (no need for reverse lookup)
        api_symbol = token_info.get("_matched_key") or token_info.get("symbol") or symbol
        
        logger.debug(f"Fetching historical candles for {symbol} (API symbol: {api_symbol}, token: {symbol_token}, exchange: {actual_exchange}) ({interval}) from {fromdate} to {todate}")
        
        # API endpoint
        url = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
        
        # Headers
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
        
        # Payload - use actual_exchange from token info
        payload = {
            "exchange": actual_exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": fromdate,
            "todate": todate
        }
        
        logger.info(f"Angel One API request: symbol={symbol}, matched_key={api_symbol}, token={symbol_token}, exchange={exchange}, interval={interval}, from={fromdate}, to={todate}")
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Log the full response for debugging
                    if not data.get("data"):
                        logger.warning(f"Angel One API response for {symbol}: status={data.get('status')}, message={data.get('message')}, errorcode={data.get('errorcode')}")
                    
                    # Check if response has data field and it's not empty
                    if data.get("status") and data.get("data") and len(data.get("data", [])) > 0:
                        candles = []
                        for candle in data["data"]:
                            # Angel One format: [timestamp_str, open, high, low, close, volume]
                            timestamp_str = candle[0]
                            # Parse timestamp (remove timezone offset for UTC)
                            dt = datetime.fromisoformat(timestamp_str.replace('+05:30', ''))
                            
                            candles.append({
                                "timestamp": dt,
                                "open": float(candle[1]),
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                                "volume": int(candle[5])
                            })
                        
                        logger.info(f"✅ Fetched {len(candles)} candles for {symbol}")
                        return candles
                    else:
                        msg = data.get('message', 'No data available')
                        logger.warning(f"Angel One returned empty data for {symbol}: {msg}")
                        return []
                else:
                    logger.error(f"HTTP {response.status_code} for {symbol}: {response.text}")
                    return []
                    
        except Exception as e:
            logger.error(f"Failed to fetch historical candles for {symbol}: {e}")
            return []
    
    @property
    def adapter(self):
        """Return adapter for compatibility with code expecting an adapter object"""
        return AngelOneAdapter(self)


# Global instance
_service: Optional[MarketDataService] = None


def get_market_data_service() -> MarketDataService:
    """Get market data service instance"""
    global _service
    if _service is None:
        _service = MarketDataService()
    return _service


def get_live_price(symbol: str) -> Decimal:
    """Get price (sync)"""
    service = get_market_data_service()
    return service.get_or_fetch_price(symbol)


async def await_live_price(symbol: str, timeout: float = 10.0) -> Decimal:
    """Get price (async)"""
    service = get_market_data_service()
    return await service.await_price(symbol, timeout=timeout)


async def subscribe_nifty500_on_startup():
    """Subscribe to all Nifty 500 symbols at startup (background task)"""
    try:
        service = get_market_data_service()
        count = await service.subscribe_nifty500()
        logger.info(f"🎯 Nifty 500 subscription complete: {count} symbols")
    except Exception as e:
        logger.error(f"Failed to subscribe to Nifty 500 on startup: {e}")
