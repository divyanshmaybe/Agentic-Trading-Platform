"""
Market Candles API Client Library

Simple Python client for interacting with the Market Candles API.

Example usage:
    from candles_client import CandlesClient
    
    client = CandlesClient(base_url="http://localhost:8000", token="your_jwt_token")
    
    # Get current price
    quotes = await client.get_quotes(["RELIANCE", "TCS"])
    print(quotes)
    
    # Get price + last 1 day candles
    quotes = await client.get_quotes(["RELIANCE"], candle="1d")
    print(quotes["metadata"]["candles"]["RELIANCE"])
    
    # Get price + custom date range
    quotes = await client.get_quotes_range(
        ["RELIANCE"], 
        start=datetime(2024, 1, 10, 9, 15),
        end=datetime(2024, 1, 15, 15, 30),
        period="1d"
    )
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx


class CandlesClient:
    """Client for Market Candles API."""
    
    def __init__(
        self, 
        base_url: str = "http://localhost:8000",
        token: str = "",
        timeout: float = 30.0
    ):
        """
        Initialize the client.
        
        Args:
            base_url: API base URL (default: http://localhost:8000)
            token: JWT authentication token
            timeout: Request timeout in seconds (default: 30.0)
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    async def get_quotes(
        self,
        symbols: List[str],
        candle: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get market quotes for symbols.
        
        Args:
            symbols: List of stock symbols (e.g., ["RELIANCE", "TCS"])
            candle: Optional candle period (e.g., "1h", "1d", "5d", "7d", "30d", "1y")
        
        Returns:
            API response with current prices and optional candle data
        
        Example:
            # Current price only
            quotes = await client.get_quotes(["RELIANCE"])
            print(quotes["data"][0]["price"])
            
            # With 1-day candles
            quotes = await client.get_quotes(["RELIANCE"], candle="1d")
            candles = quotes["metadata"]["candles"]["RELIANCE"]
            print(f"Got {len(candles)} candles")
        """
        params = {}
        for symbol in symbols:
            params.setdefault("symbols", []).append(symbol)
        
        if candle:
            params["candle"] = candle
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/market/quotes",
                params=params,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_quotes_range(
        self,
        symbols: List[str],
        start: datetime,
        end: datetime,
        period: str = "1d"
    ) -> Dict[str, Any]:
        """
        Get market quotes with custom date range.
        
        Args:
            symbols: List of stock symbols
            start: Start datetime
            end: End datetime
            period: Candle period (determines interval granularity)
        
        Returns:
            API response with current prices and candles in date range
        
        Example:
            from datetime import datetime
            
            quotes = await client.get_quotes_range(
                ["RELIANCE"],
                start=datetime(2024, 1, 10, 9, 15),
                end=datetime(2024, 1, 15, 15, 30),
                period="1d"
            )
        """
        params = {"candle": period}
        for symbol in symbols:
            params.setdefault("symbols", []).append(symbol)
        
        params["start"] = start.isoformat() + "Z"
        params["end"] = end.isoformat() + "Z"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/market/quotes",
                params=params,
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
    
    async def get_current_price(self, symbol: str) -> float:
        """
        Get current price for a single symbol.
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
        
        Returns:
            Current price as float
        
        Example:
            price = await client.get_current_price("RELIANCE")
            print(f"RELIANCE: ₹{price}")
        """
        quotes = await self.get_quotes([symbol])
        if quotes["data"]:
            return float(quotes["data"][0]["price"])
        raise ValueError(f"No price data for {symbol}")
    
    async def get_candles(
        self,
        symbol: str,
        period: str = "1d"
    ) -> List[Dict[str, Any]]:
        """
        Get candle data for a single symbol.
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            period: Candle period (e.g., "1h", "1d", "5d", "7d", "30d", "1y")
        
        Returns:
            List of candle dictionaries with keys: timestamp, open, high, low, close, volume
        
        Example:
            candles = await client.get_candles("RELIANCE", period="1d")
            for candle in candles:
                print(f"{candle['timestamp']}: O:{candle['open']} C:{candle['close']}")
        """
        quotes = await self.get_quotes([symbol], candle=period)
        return quotes.get("metadata", {}).get("candles", {}).get(symbol, [])
    
    async def get_ohlcv(
        self,
        symbol: str,
        period: str = "1d"
    ) -> tuple[List[float], List[float], List[float], List[float], List[int]]:
        """
        Get OHLCV data as separate lists (useful for plotting).
        
        Args:
            symbol: Stock symbol
            period: Candle period
        
        Returns:
            Tuple of (opens, highs, lows, closes, volumes)
        
        Example:
            opens, highs, lows, closes, volumes = await client.get_ohlcv("RELIANCE", "1d")
            
            import matplotlib.pyplot as plt
            plt.plot(closes, label="Close")
            plt.legend()
            plt.show()
        """
        candles = await self.get_candles(symbol, period)
        
        opens = [float(c["open"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        closes = [float(c["close"]) for c in candles]
        volumes = [int(float(c["volume"])) for c in candles]
        
        return opens, highs, lows, closes, volumes
    
    async def get_timestamps(
        self,
        symbol: str,
        period: str = "1d"
    ) -> List[str]:
        """
        Get timestamps for candle data.
        
        Args:
            symbol: Stock symbol
            period: Candle period
        
        Returns:
            List of timestamp strings
        
        Example:
            timestamps = await client.get_timestamps("RELIANCE", "1d")
            print(f"First: {timestamps[0]}, Last: {timestamps[-1]}")
        """
        candles = await self.get_candles(symbol, period)
        return [c["timestamp"] for c in candles]
    
    async def get_summary(
        self,
        symbol: str,
        period: str = "1d"
    ) -> Dict[str, Any]:
        """
        Get summary statistics for candle data.
        
        Args:
            symbol: Stock symbol
            period: Candle period
        
        Returns:
            Dictionary with summary stats: current_price, candle_count, 
            first_timestamp, last_timestamp, high, low, avg_volume
        
        Example:
            summary = await client.get_summary("RELIANCE", "1d")
            print(f"High: ₹{summary['high']}, Low: ₹{summary['low']}")
        """
        quotes = await self.get_quotes([symbol], candle=period)
        candles = quotes.get("metadata", {}).get("candles", {}).get(symbol, [])
        
        if not candles:
            return {
                "symbol": symbol,
                "current_price": float(quotes["data"][0]["price"]) if quotes["data"] else None,
                "candle_count": 0,
                "error": "No candle data available"
            }
        
        opens, highs, lows, closes, volumes = await self.get_ohlcv(symbol, period)
        
        return {
            "symbol": symbol,
            "period": period,
            "current_price": float(quotes["data"][0]["price"]) if quotes["data"] else None,
            "candle_count": len(candles),
            "first_timestamp": candles[0]["timestamp"],
            "last_timestamp": candles[-1]["timestamp"],
            "high": max(highs) if highs else None,
            "low": min(lows) if lows else None,
            "avg_volume": sum(volumes) / len(volumes) if volumes else None,
            "total_volume": sum(volumes) if volumes else None
        }


# Convenience functions for quick usage

async def get_price(symbol: str, base_url: str = "http://localhost:8000", token: str = "") -> float:
    """Quick function to get current price."""
    client = CandlesClient(base_url=base_url, token=token)
    return await client.get_current_price(symbol)


async def get_candles(
    symbol: str, 
    period: str = "1d",
    base_url: str = "http://localhost:8000",
    token: str = ""
) -> List[Dict[str, Any]]:
    """Quick function to get candle data."""
    client = CandlesClient(base_url=base_url, token=token)
    return await client.get_candles(symbol, period)


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def demo():
        """Demo of the client library."""
        client = CandlesClient(
            base_url="http://localhost:8000",
            token=""  # Add your token here
        )
        
        print("🔍 Fetching RELIANCE current price...")
        price = await client.get_current_price("RELIANCE")
        print(f"💰 RELIANCE: ₹{price}")
        
        print("\n📊 Fetching 1-day candles...")
        candles = await client.get_candles("RELIANCE", period="1d")
        print(f"📈 Got {len(candles)} candles")
        
        print("\n📉 Summary statistics:")
        summary = await client.get_summary("RELIANCE", period="1d")
        print(f"   High: ₹{summary['high']}")
        print(f"   Low: ₹{summary['low']}")
        print(f"   Avg Volume: {summary['avg_volume']:,.0f}")
        
        print("\n📐 OHLCV data:")
        opens, highs, lows, closes, volumes = await client.get_ohlcv("RELIANCE", "1d")
        print(f"   Opens: {len(opens)} data points")
        print(f"   Closes: {closes[:3]}...")  # First 3 closes
    
    asyncio.run(demo())
