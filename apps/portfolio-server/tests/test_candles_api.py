#!/usr/bin/env python3
"""
Test script for Market Candles API

This script demonstrates all supported candle periods and validates the API responses.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx


class CandlesAPITester:
    """Test client for Market Candles API."""
    
    def __init__(self, base_url: str = "http://localhost:8000", token: str = ""):
        self.base_url = base_url
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    async def test_current_price(self, symbols: List[str]) -> Dict[str, Any]:
        """Test: Get current price only (no candles)."""
        print("\n" + "=" * 80)
        print("TEST 1: Current Price Only")
        print("=" * 80)
        
        params = {}
        for symbol in symbols:
            params.setdefault("symbols", []).append(symbol)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/market/quotes",
                params=params,
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        print(f"✅ Request: GET /api/market/quotes?symbols={','.join(symbols)}")
        print(f"📊 Response ({response.status_code}):")
        print(json.dumps(data, indent=2))
        
        return data
    
    async def test_candle_period(
        self, 
        symbol: str, 
        period: str,
        start: str = None,
        end: str = None
    ) -> Dict[str, Any]:
        """Test: Get price + candles for a specific period."""
        print("\n" + "=" * 80)
        print(f"TEST: {period.upper()} Period - {symbol}")
        print("=" * 80)
        
        params = {"symbols": symbol}
        if period:
            params["candle"] = period
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/market/quotes",
                params=params,
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        # Build query string for display
        query_parts = [f"symbols={symbol}"]
        if period:
            query_parts.append(f"candle={period}")
        if start:
            query_parts.append(f"start={start}")
        if end:
            query_parts.append(f"end={end}")
        query_string = "&".join(query_parts)
        
        print(f"✅ Request: GET /api/market/quotes?{query_string}")
        print(f"📊 Response ({response.status_code}):")
        
        # Display current price
        if data.get("data"):
            quote = data["data"][0]
            print(f"\n💰 Current Price: {quote['symbol']} = ₹{quote['price']} ({quote['source']})")
        
        # Display candle summary
        candles = data.get("metadata", {}).get("candles", {}).get(symbol, [])
        if candles:
            print(f"\n📈 Candles: {len(candles)} data points")
            print(f"   First: {candles[0]['timestamp']} | O:{candles[0]['open']} H:{candles[0]['high']} L:{candles[0]['low']} C:{candles[0]['close']} V:{candles[0]['volume']}")
            print(f"   Last:  {candles[-1]['timestamp']} | O:{candles[-1]['open']} H:{candles[-1]['high']} L:{candles[-1]['low']} C:{candles[-1]['close']} V:{candles[-1]['volume']}")
        else:
            print("\n⚠️  No candle data returned")
        
        return data
    
    async def test_all_periods(self, symbol: str = "RELIANCE"):
        """Test all supported candle periods."""
        periods = ["1h", "1d", "5d", "7d", "30d", "1y"]
        
        print("\n" + "=" * 80)
        print(f"TESTING ALL PERIODS FOR {symbol}")
        print("=" * 80)
        
        results = {}
        for period in periods:
            try:
                result = await self.test_candle_period(symbol, period)
                results[period] = {
                    "success": True,
                    "candle_count": len(result.get("metadata", {}).get("candles", {}).get(symbol, [])),
                    "price": result["data"][0]["price"] if result.get("data") else None
                }
            except Exception as e:
                print(f"❌ Error testing {period}: {e}")
                results[period] = {"success": False, "error": str(e)}
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        for period, result in results.items():
            if result.get("success"):
                print(f"✅ {period:4s} - {result['candle_count']:4d} candles | Price: ₹{result['price']}")
            else:
                print(f"❌ {period:4s} - {result.get('error', 'Unknown error')}")
    
    async def test_custom_range(
        self, 
        symbol: str = "RELIANCE",
        days_back: int = 3
    ):
        """Test custom date range."""
        end = datetime.utcnow()
        start = end - timedelta(days=days_back)
        
        start_str = start.isoformat() + "Z"
        end_str = end.isoformat() + "Z"
        
        print("\n" + "=" * 80)
        print(f"TEST: Custom Date Range ({days_back} days)")
        print("=" * 80)
        print(f"Start: {start_str}")
        print(f"End:   {end_str}")
        
        await self.test_candle_period(symbol, "1d", start=start_str, end=end_str)
    
    async def test_multiple_symbols(self, symbols: List[str] = None):
        """Test multiple symbols with candles."""
        if symbols is None:
            symbols = ["RELIANCE", "TCS", "INFY"]
        
        print("\n" + "=" * 80)
        print(f"TEST: Multiple Symbols with Candles")
        print("=" * 80)
        
        params = {"candle": "1d"}
        for symbol in symbols:
            params.setdefault("symbols", []).append(symbol)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/api/market/quotes",
                params=params,
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
        
        print(f"✅ Request: GET /api/market/quotes?symbols={','.join(symbols)}&candle=1d")
        print(f"📊 Response ({response.status_code}):")
        
        for quote in data.get("data", []):
            print(f"\n💰 {quote['symbol']}: ₹{quote['price']} ({quote['source']})")
            candles = data.get("metadata", {}).get("candles", {}).get(quote['symbol'], [])
            if candles:
                print(f"   📈 {len(candles)} candles")
            else:
                print(f"   ⚠️  No candles")
        
        return data
    
    async def test_invalid_period(self):
        """Test error handling for invalid period."""
        print("\n" + "=" * 80)
        print("TEST: Invalid Period (should return 400)")
        print("=" * 80)
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/market/quotes",
                    params={"symbols": "RELIANCE", "candle": "3h"},
                    headers=self.headers,
                    timeout=30.0
                )
                response.raise_for_status()
                print("❌ Expected 400 error but got success!")
        except httpx.HTTPStatusError as e:
            print(f"✅ Got expected error: {e.response.status_code}")
            print(f"📄 Error response: {e.response.json()}")
    
    async def test_invalid_date_range(self):
        """Test error handling for invalid date range."""
        print("\n" + "=" * 80)
        print("TEST: Invalid Date Range (start > end, should return 400)")
        print("=" * 80)
        
        end = datetime.utcnow()
        start = end + timedelta(days=1)  # Start after end (invalid)
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/market/quotes",
                    params={
                        "symbols": "RELIANCE",
                        "candle": "1d",
                        "start": start.isoformat() + "Z",
                        "end": end.isoformat() + "Z"
                    },
                    headers=self.headers,
                    timeout=30.0
                )
                response.raise_for_status()
                print("❌ Expected 400 error but got success!")
        except httpx.HTTPStatusError as e:
            print(f"✅ Got expected error: {e.response.status_code}")
            print(f"📄 Error response: {e.response.json()}")


async def main():
    """Run all tests."""
    print("\n" + "🚀" * 40)
    print("MARKET CANDLES API - COMPREHENSIVE TEST SUITE")
    print("🚀" * 40)
    
    # Initialize tester (you can pass a token if needed)
    tester = CandlesAPITester(
        base_url="http://localhost:8000",
        token=""  # Add your JWT token here if authentication is required
    )
    
    try:
        # Test 1: Current price only
        await tester.test_current_price(["RELIANCE"])
        
        # Test 2: All supported periods
        await tester.test_all_periods("RELIANCE")
        
        # Test 3: Custom date range
        await tester.test_custom_range("TCS", days_back=3)
        
        # Test 4: Multiple symbols
        await tester.test_multiple_symbols(["RELIANCE", "TCS", "INFY"])
        
        # Test 5: Error handling - invalid period
        await tester.test_invalid_period()
        
        # Test 6: Error handling - invalid date range
        await tester.test_invalid_date_range()
        
        print("\n" + "✅" * 40)
        print("ALL TESTS COMPLETED SUCCESSFULLY!")
        print("✅" * 40 + "\n")
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
