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
            verify=True
        )
    return _HTTPX_CLIENT


async def close_httpx_client():
    """Close persistent client on shutdown."""
    global _HTTPX_CLIENT
    if _HTTPX_CLIENT is not None:
        await _HTTPX_CLIENT.aclose()
        _HTTPX_CLIENT = None


# Rate limiting removed - internal server use only
# No need to throttle our own API calls


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
        max_concurrent: int = 50
    ):
        """
        Initialize batch fetcher.
        
        Args:
            jwt_token: Angel One JWT authentication token
            api_key: Angel One API key
            client_code: Angel One client code
            max_concurrent: Maximum concurrent requests (default: 50)
        """
        self.jwt_token = jwt_token
        self.api_key = api_key
        self.client_code = client_code
        self.max_concurrent = max_concurrent
        self.base_url = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
        
        # Token map cache (will be populated from MarketDataService if available)
        self._token_map: Dict[str, Dict[str, Any]] = {}
    
    def set_token_map(self, token_map: Dict[str, Dict[str, Any]]):
        """Set token map from MarketDataService."""
        self._token_map = token_map
    
    def _get_token_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get token info for symbol. Angel One uses symbol-EQ format."""
        # Always use -EQ suffix for NSE stocks
        symbol_key = f"{symbol}-EQ" if not symbol.endswith("-EQ") else symbol
        
        if symbol_key in self._token_map:
            return self._token_map[symbol_key]
        
        logger.warning(f"Symbol {symbol} (key: {symbol_key}) not found in token map")
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
            
            # Single attempt - fail fast
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
        
        # Process all with semaphore concurrency control
        all_candles = []
        batch_size = 100  # Large batches for speed
        
        for i in range(0, len(tasks), batch_size):
            batch_tasks = tasks[i:i + batch_size]
            
            # Use semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(self.max_concurrent)
            
            async def fetch_with_semaphore(task):
                async with semaphore:
                    return await task
            
            wrapped_tasks = [fetch_with_semaphore(task) for task in batch_tasks]
            results = await asyncio.gather(*wrapped_tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, list):
                    all_candles.extend(result)
                elif isinstance(result, Exception):
                    logger.error(f"Error fetching batch: {result}")
            
            progress = min(i + batch_size, len(tasks))
            if progress % 50 == 0 or progress == len(tasks):
                logger.info(f"✓ Progress: {progress}/{len(tasks)} symbols ({progress*100//len(tasks)}%)")
        
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
            interval: Angel One interval format ('ONE_DAY', 'ONE_HOUR', 'FIVE_MINUTE', etc.)
            period_days: Number of days of history (default: 365)
            exchange: Exchange name (default: 'NSE')
            
        Returns:
            Polars DataFrame with all candles
        """
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        
        # Format dates for Angel One API (use market hours for intraday, otherwise full day)
        if interval in ["ONE_MINUTE", "FIVE_MINUTE", "FIFTEEN_MINUTE", "ONE_HOUR"]:
            fromdate = start_date.replace(hour=9, minute=15, second=0).strftime("%Y-%m-%d %H:%M")
            todate = end_date.replace(hour=15, minute=30, second=0).strftime("%Y-%m-%d %H:%M")
        else:
            fromdate = start_date.strftime("%Y-%m-%d %H:%M")
            todate = end_date.strftime("%Y-%m-%d %H:%M")
        
        logger.info(f"Fetching from {fromdate} to {todate} with interval {interval}")
        
        return await self.fetch_batch(all_symbols, interval, fromdate, todate, exchange)


def create_fetcher_from_market_service(market_service) -> AngelOneBatchFetcher:
    """
    Create batch fetcher from existing MarketDataService instance.
    Fetches latest token mappings from Angel One API.
    
    Args:
        market_service: Instance of MarketDataService
        
    Returns:
        Configured AngelOneBatchFetcher
    """
    import json
    import requests
    
    fetcher = AngelOneBatchFetcher(
        jwt_token=market_service.jwt_token,
        api_key=market_service.api_key,
        client_code=market_service.client_code
    )
    
    # Fetch latest token map from Angel One API
    logger.info("📡 Fetching latest instrument master from Angel One API...")
    try:
        # Use Angel One's official instrument master API
        url = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        instruments = response.json()
        
        # Build token map for NSE equity symbols (exch_seg = "NSE", symbol ends with "-EQ")
        token_map = {}
        for instrument in instruments:
            # Angel One API format: {"token":"11536","symbol":"TCS-EQ","name":"TCS","exch_seg":"NSE",...}
            exch_seg = instrument.get("exch_seg", "")
            symbol = instrument.get("symbol", "")
            
            # Focus on NSE equity (exch_seg="NSE" and symbol ends with "-EQ")
            if exch_seg == "NSE" and symbol.endswith("-EQ"):
                token = instrument.get("token", "")
                name = instrument.get("name", "")
                
                if symbol and token:
                    # Store with full info - key is already in "SYMBOL-EQ" format from API
                    token_map[symbol] = {
                        "token": token,
                        "name": name if name else symbol.replace("-EQ", ""),
                        "symbol": symbol
                    }
        
        logger.info(f"✅ Loaded {len(token_map):,} NSE equity tokens from Angel One API")
        
        # Log sample tokens for debugging
        if token_map:
            sample_keys = list(token_map.keys())[:5]
            logger.debug(f"Sample tokens: {sample_keys}")
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch instrument master from Angel One: {e}")
        logger.info("🔄 Falling back to local token file...")
        
        # Fallback to local file if API fails
        import os
        from pathlib import Path
        
        token_file_paths = [
            Path(__file__).parent.parent.parent / "docs" / "angelone_tokens.json",
            Path(__file__).parent.parent.parent.parent.parent / "scripts" / "angelone_tokens.json",
        ]
        
        token_map = {}
        for token_file in token_file_paths:
            if token_file.exists():
                try:
                    with open(token_file, 'r') as f:
                        token_map = json.load(f)
                    logger.info(f"✅ Loaded {len(token_map):,} token mappings from {token_file}")
                    break
                except Exception as e:
                    logger.error(f"Failed to load token map from {token_file}: {e}")
                    continue
        
        if not token_map:
            logger.warning("⚠️ Token map not found, fetcher may not work properly")
    
    fetcher.set_token_map(token_map)
    
    return fetcher

