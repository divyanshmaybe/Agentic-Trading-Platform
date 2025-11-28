"""
Angel One Batch Data Fetcher

Fetches historical candle data for multiple tickers in batch using Angel One API.
Returns Polars DataFrame for fast processing.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import httpx
import polars as pl
import pytz

logger = logging.getLogger(__name__)

# Global HTTP client for connection pooling
_HTTPX_CLIENT: Optional[httpx.AsyncClient] = None


async def get_httpx_client() -> httpx.AsyncClient:
    """Get or create a persistent async HTTP client with connection pooling."""
    global _HTTPX_CLIENT
    if _HTTPX_CLIENT is None:
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        _HTTPX_CLIENT = httpx.AsyncClient(
            limits=limits,
            timeout=30.0,
            http2=True,
            verify=True
        )
    return _HTTPX_CLIENT


async def close_httpx_client():
    """Close persistent client on shutdown."""
    global _HTTPX_CLIENT
    if _HTTPX_CLIENT is not None:
        await _HTTPX_CLIENT.aclose()
        _HTTPX_CLIENT = None


class RateLimiter:
    """Simple rate limiter using token bucket algorithm."""
    
    def __init__(self, max_requests: int, time_window: float):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = []
    
    async def acquire(self):
        """Wait until request can be made."""
        import time
        now = time.time()
        
        # Remove old requests outside time window
        self.requests = [t for t in self.requests if now - t < self.time_window]
        
        # Wait if at limit
        while len(self.requests) >= self.max_requests:
            await asyncio.sleep(0.05)
            now = time.time()
            self.requests = [t for t in self.requests if now - t < self.time_window]
        
        self.requests.append(now)


class AngelOneBatchFetcher:
    """
    Batch fetcher for Angel One historical candle data.
    
    Uses HTTP connection pooling and async requests for optimal performance.
    Converts responses directly to Polars DataFrame.
    """
    
    def __init__(
        self,
        jwt_token: str,
        api_key: str,
        client_code: str,
        max_concurrent: int = 5,
        rate_limit_per_sec: int = 10
    ):
        """
        Initialize batch fetcher.
        
        Args:
            jwt_token: Angel One JWT authentication token
            api_key: Angel One API key
            client_code: Angel One client code
            max_concurrent: Maximum concurrent requests (default: 5)
            rate_limit_per_sec: Rate limit per second (default: 10)
        """
        self.jwt_token = jwt_token
        self.api_key = api_key
        self.client_code = client_code
        self.max_concurrent = max_concurrent
        self.rate_limiter = RateLimiter(max_requests=rate_limit_per_sec, time_window=1.0)
        self.base_url = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
        
        # Token map cache (will be populated from MarketDataService if available)
        self._token_map: Dict[str, Dict[str, Any]] = {}
    
    def set_token_map(self, token_map: Dict[str, Dict[str, Any]]):
        """Set token map from MarketDataService."""
        self._token_map = token_map
    
    def _get_token_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get token info for symbol."""
        # Try exact match
        if symbol in self._token_map:
            return self._token_map[symbol]
        
        # Try with -EQ suffix
        if not symbol.endswith("-EQ"):
            eq_symbol = f"{symbol}-EQ"
            if eq_symbol in self._token_map:
                return self._token_map[eq_symbol]
        
        # Try without -EQ suffix
        if symbol.endswith("-EQ"):
            base_symbol = symbol[:-3]
            if base_symbol in self._token_map:
                return self._token_map[base_symbol]
        
        return None
    
    async def fetch_single_symbol(
        self,
        symbol: str,
        interval: str,
        fromdate: str,
        todate: str,
        exchange: str = "NSE"
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical candles for a single symbol.
        
        Args:
            symbol: Symbol name (e.g., 'RELIANCE', 'TCS')
            interval: Time interval ('ONE_MINUTE', 'FIVE_MINUTE', 'FIFTEEN_MINUTE', 'ONE_HOUR', 'ONE_DAY')
            fromdate: Start date in 'YYYY-MM-DD HH:MM' format
            todate: End date in 'YYYY-MM-DD HH:MM' format
            exchange: Exchange name (default: 'NSE')
            
        Returns:
            List of candle dictionaries with keys: timestamp, open, high, low, close, volume
        """
        # Wait for rate limit
        await self.rate_limiter.acquire()
        
        # Get token for symbol
        token_info = self._get_token_info(symbol)
        if not token_info:
            logger.warning(f"No token found for symbol {symbol}")
            return []
        
        symbol_token = token_info.get("token")
        if not symbol_token:
            logger.warning(f"No token available for {symbol}")
            return []
        
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
        
        # Payload
        payload = {
            "exchange": exchange,
            "symboltoken": symbol_token,
            "interval": interval,
            "fromdate": fromdate,
            "todate": todate
        }
        
        try:
            client = await get_httpx_client()
            response = await client.post(self.base_url, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") and data.get("data") and len(data.get("data", [])) > 0:
                    candles = []
                    for candle in data["data"]:
                        # Angel One format: [timestamp_str, open, high, low, close, volume]
                        timestamp_str = candle[0]
                        # Parse timestamp (handle IST timezone)
                        try:
                            # Try parsing with timezone
                            if '+' in timestamp_str or timestamp_str.endswith('Z'):
                                dt = datetime.fromisoformat(timestamp_str.replace('+05:30', '+05:30').replace('Z', '+00:00'))
                            else:
                                # Assume IST if no timezone
                                dt = datetime.fromisoformat(timestamp_str)
                                ist = pytz.timezone('Asia/Kolkata')
                                dt = ist.localize(dt)
                            
                            # Convert to UTC
                            dt_utc = dt.astimezone(pytz.UTC)
                            
                            candles.append({
                                "timestamp": dt_utc,
                                "symbol": symbol,
                                "open": float(candle[1]),
                                "high": float(candle[2]),
                                "low": float(candle[3]),
                                "close": float(candle[4]),
                                "volume": int(candle[5])
                            })
                        except Exception as e:
                            logger.warning(f"Failed to parse timestamp {timestamp_str} for {symbol}: {e}")
                            continue
                    
                    return candles
                else:
                    msg = data.get('message', 'No data available')
                    logger.debug(f"Angel One returned empty data for {symbol}: {msg}")
                    return []
            else:
                logger.error(f"HTTP {response.status_code} for {symbol}: {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"Failed to fetch historical candles for {symbol}: {e}")
            return []
    
    async def fetch_batch(
        self,
        symbols: List[str],
        interval: str,
        fromdate: str,
        todate: str,
        exchange: str = "NSE"
    ) -> pl.DataFrame:
        """
        Fetch historical candles for multiple symbols concurrently.
        
        Args:
            symbols: List of symbol names
            interval: Time interval
            fromdate: Start date in 'YYYY-MM-DD HH:MM' format
            todate: End date in 'YYYY-MM-DD HH:MM' format
            exchange: Exchange name (default: 'NSE')
            
        Returns:
            Polars DataFrame with columns: timestamp, symbol, open, high, low, close, volume
        """
        if not symbols:
            return pl.DataFrame()
        
        logger.info(f"📡 Fetching {len(symbols)} symbols from Angel One API...")
        
        # Create tasks for concurrent fetching
        tasks = [
            self.fetch_single_symbol(symbol, interval, fromdate, todate, exchange)
            for symbol in symbols
        ]
        
        # Process in batches to respect concurrency limit
        all_candles = []
        
        for i in range(0, len(tasks), self.max_concurrent):
            batch_tasks = tasks[i:i + self.max_concurrent]
            results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    all_candles.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error fetching batch: {result}")
            
            progress = min(i + self.max_concurrent, len(tasks))
            logger.debug(f"✓ Fetched {progress}/{len(tasks)} symbols")
        
        if not all_candles:
            logger.warning("No candles fetched from Angel One API")
            return pl.DataFrame()
        
        # Convert to Polars DataFrame
        df = pl.DataFrame(all_candles)
        
        # Ensure timestamp is datetime
        if "timestamp" in df.columns:
            df = df.with_columns([
                pl.col("timestamp").cast(pl.Datetime).alias("timestamp")
            ])
        
        # Sort by symbol and timestamp
        df = df.sort(["symbol", "timestamp"])
        
        logger.info(f"✅ Fetched {len(df)} candles for {len(symbols)} symbols")
        
        return df
    
    async def fetch_all_batched(
        self,
        all_symbols: List[str],
        interval: str = "ONE_DAY",
        period_days: int = 365,
        exchange: str = "NSE"
    ) -> pl.DataFrame:
        """
        Fetch all symbols with automatic date range calculation.
        
        Args:
            all_symbols: List of all symbols to fetch
            interval: Time interval (default: 'ONE_DAY')
            period_days: Number of days of history (default: 365)
            exchange: Exchange name (default: 'NSE')
            
        Returns:
            Polars DataFrame with all candles
        """
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        
        # Format dates for API
        fromdate = start_date.strftime("%Y-%m-%d %H:%M")
        todate = end_date.strftime("%Y-%m-%d %H:%M")
        
        return await self.fetch_batch(all_symbols, interval, fromdate, todate, exchange)


def create_fetcher_from_market_service(market_service) -> AngelOneBatchFetcher:
    """
    Create batch fetcher from existing MarketDataService instance.
    
    Args:
        market_service: Instance of MarketDataService
        
    Returns:
        Configured AngelOneBatchFetcher
    """
    fetcher = AngelOneBatchFetcher(
        jwt_token=market_service.jwt_token,
        api_key=market_service.api_key,
        client_code=market_service.client_code
    )
    
    # Copy token map if available
    if hasattr(market_service, '_token_map'):
        fetcher.set_token_map(market_service._token_map)
    
    return fetcher

