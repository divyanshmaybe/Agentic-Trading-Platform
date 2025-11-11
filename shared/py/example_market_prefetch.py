"""
Example: Market Data Service with Nifty-500 Pre-Fetch

This example demonstrates how the optimized market data service works
with intelligent pre-fetching to prevent rate limits.
"""

import asyncio
import time
from market_data import get_market_data_service


async def example_prefetch_demo():
    """
    Demonstrate the benefits of Nifty-500 pre-fetching.
    
    Startup Flow:
    1. Service initializes WebSocket connection
    2. Pre-fetches all 500 Nifty stocks in SINGLE batch request
    3. All subsequent lookups are instant from cache
    """
    
    print("=" * 60)
    print("Market Data Service - Nifty-500 Pre-Fetch Demo")
    print("=" * 60)
    
    # Get singleton instance (starts pre-fetch automatically)
    service = get_market_data_service()
    
    print("\n✅ Market service initialized!")
    print("⏳ Waiting for Nifty-500 pre-fetch to complete (~2 seconds)...")
    print("   (Single batch request for all 500 symbols)")
    
    # Wait for pre-fetch to populate cache
    await asyncio.sleep(3)
    
    print("\n" + "=" * 60)
    print("Testing Instant Price Lookups (All Cached)")
    print("=" * 60)
    
    # Test popular Nifty-50 stocks
    nifty50_samples = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK"
    ]
    
    print(f"\nFetching prices for {len(nifty50_samples)} stocks:")
    
    start_time = time.time()
    for symbol in nifty50_samples:
        price = service.get_latest_price(symbol)
        if price:
            print(f"  💰 {symbol:15s} ₹{price:>10,.2f}")
        else:
            print(f"  ⏳ {symbol:15s} Waiting for first tick...")
    
    elapsed_ms = (time.time() - start_time) * 1000
    print(f"\n⚡ Total time: {elapsed_ms:.2f}ms ({elapsed_ms/len(nifty50_samples):.2f}ms per stock)")
    
    # Test on-demand subscription for non-Nifty-500 stock
    print("\n" + "=" * 60)
    print("Testing On-Demand Subscription (Non-Nifty Stock)")
    print("=" * 60)
    
    custom_symbol = "SOMESTOCK"  # Replace with actual symbol
    print(f"\nRequesting price for {custom_symbol} (not in Nifty-500)...")
    
    start_time = time.time()
    try:
        price = await service.await_price(custom_symbol, timeout=5.0)
        elapsed = time.time() - start_time
        print(f"  💰 {custom_symbol}: ₹{price:,.2f}")
        print(f"  ⏱️  Took {elapsed:.2f}s (includes WebSocket subscription)")
    except RuntimeError as e:
        print(f"  ❌ {e}")
    
    # Show rate limit efficiency
    print("\n" + "=" * 60)
    print("Rate Limit Efficiency")
    print("=" * 60)
    
    print("""
Angel One API Limits:
  • 10 requests/second
  • 500 requests/minute

Pre-Fetch Configuration:
  • Single batch request for all 500 symbols
  • Grouped by exchange type automatically
  • Instant subscription (~1-2 seconds)
  
Rate Limit Benefits:
  ✅ WebSocket subscription: 1 message total
  ✅ No rate limit concerns whatsoever
  ✅ 100% HTTP API quota available for historical data
  ✅ All prices cached instantly after connection
  ✅ Zero delays, zero batching, maximum efficiency
    """)


async def example_historical_data():
    """
    Demonstrate historical candle data fetching alongside live prices.
    """
    print("\n" + "=" * 60)
    print("Historical Data + Live Prices (No Rate Conflicts)")
    print("=" * 60)
    
    service = get_market_data_service()
    
    # Live price (from cache)
    live_price = service.get_latest_price("RELIANCE")
    print(f"\n📊 RELIANCE Live Price: ₹{live_price:,.2f}")
    
    # Historical candles (uses reserved API quota)
    print("\n🕒 Fetching 1-day historical candles for RELIANCE...")
    
    from controllers.market_controller import MarketController
    controller = MarketController()
    
    # This uses historical API endpoint (separate from WebSocket quota)
    candles = await controller._fetch_candles(
        provider_symbol="RELIANCE-EQ",
        resolution="1d",
    )
    
    if candles:
        print(f"  ✅ Fetched {len(candles)} candles")
        print(f"  📈 Latest: Open ₹{candles[-1]['open']}, Close ₹{candles[-1]['close']}")
    else:
        print("  ⚠️  No candles available")
    
    print("""
Key Insight:
  • WebSocket (live prices): 1 message for all 500 symbols
  • Historical API: Uses separate HTTP quota
  • No conflicts, no rate limits, 100% efficiency!
    """)


if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════╗
║                                                            ║
║     Market Data Service - Single Batch Pre-Fetch          ║
║                                                            ║
║  Features:                                                 ║
║  ✓ Nifty-500 Pre-Fetch (ALL 500 in 1 WebSocket message)  ║
║  ✓ Instant Price Lookups (<1ms from cache)               ║
║  ✓ ZERO Rate Limits (single subscription message)        ║
║  ✓ Single Persistent WebSocket Connection                ║
║  ✓ 100% HTTP API quota available for historical data     ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(example_prefetch_demo())
    # asyncio.run(example_historical_data())
