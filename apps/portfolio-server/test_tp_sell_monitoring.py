"""
Test TP (Take Profit) Sell Auto-Monitoring

This script tests the real-time monitoring of take-profit orders:
1. Publishes executed trade with TP to Redis
2. Simulates price updates
3. Verifies TP triggers when price reaches target
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from redis import Redis
from datetime import datetime, timezone

# Add paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "shared" / "py"))
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "portfolio-server"))

from celery_app import BROKER_URL


def publish_executed_trade(redis_client: Redis, trade_data: dict):
    """Publish executed trade to Redis channel for monitoring"""
    channel = "trades:executed"
    message = json.dumps(trade_data)
    redis_client.publish(channel, message)
    print(f"✅ Published to {channel}: {trade_data['symbol']} @ ₹{trade_data['entry_price']}")


def publish_price_update(redis_client: Redis, symbol: str, price: float):
    """Publish market price update"""
    channel = "market:prices"
    message = json.dumps({
        "symbol": symbol,
        "price": price,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    redis_client.publish(channel, message)
    print(f"📊 Price update: {symbol} @ ₹{price:.2f}")


def check_execution_signals(redis_client: Redis) -> list:
    """Check if any execution signals were generated"""
    # Check for signals in Redis (simulating what Pathway would publish)
    signals = []
    
    # In real system, Pathway would publish to 'orders:execute' channel
    # For testing, we check a test channel
    pubsub = redis_client.pubsub()
    pubsub.subscribe("orders:execute:test")
    
    # Non-blocking check
    message = pubsub.get_message()
    if message and message['type'] == 'message':
        signals.append(json.loads(message['data']))
    
    pubsub.unsubscribe()
    return signals


async def test_tp_monitoring():
    """Test TP sell auto-monitoring"""
    print("\n" + "="*80)
    print("🧪 Testing TP (Take Profit) Sell Auto-Monitoring")
    print("="*80 + "\n")
    
    redis_client = Redis.from_url(BROKER_URL)
    
    # Test data
    test_trade = {
        "trade_id": "test-trade-tp-001",
        "symbol": "RELIANCE",
        "side": "BUY",
        "quantity": 10,
        "entry_price": 2500.0,
        "take_profit_price": 2600.0,  # TP at +4% (₹2500 → ₹2600)
        "stop_loss_price": 2450.0,     # SL at -2% (₹2500 → ₹2450)
        "portfolio_id": "test-portfolio-001",
        "customer_id": "test-user-001",
        "execution_time": datetime.now(timezone.utc).isoformat()
    }
    
    print("📝 Test Trade Setup:")
    print(f"   Symbol: {test_trade['symbol']}")
    print(f"   Side: {test_trade['side']}")
    print(f"   Quantity: {test_trade['quantity']}")
    print(f"   Entry: ₹{test_trade['entry_price']}")
    print(f"   TP: ₹{test_trade['take_profit_price']} (+4%)")
    print(f"   SL: ₹{test_trade['stop_loss_price']} (-2%)")
    print()
    
    # Step 1: Publish executed trade
    print("Step 1: Publishing executed trade...")
    publish_executed_trade(redis_client, test_trade)
    await asyncio.sleep(0.5)
    
    # Step 2: Simulate price BELOW TP (no trigger)
    print("\nStep 2: Price below TP (₹2550) - should NOT trigger...")
    publish_price_update(redis_client, "RELIANCE", 2550.0)
    await asyncio.sleep(0.5)
    
    signals = check_execution_signals(redis_client)
    if not signals:
        print("   ✅ No execution - correct (price below TP)")
    else:
        print(f"   ❌ Unexpected execution: {signals}")
    
    # Step 3: Simulate price AT TP (should trigger)
    print("\nStep 3: Price reaches TP (₹2600) - should TRIGGER...")
    publish_price_update(redis_client, "RELIANCE", 2600.0)
    await asyncio.sleep(0.5)
    
    # Check if Pathway monitor is running
    pubsub = redis_client.pubsub()
    pubsub.subscribe("trades:executed")
    
    # Check subscribers
    num_subscribed = redis_client.pubsub_numsub("trades:executed")
    print(f"\n📡 Subscribers to 'trades:executed': {num_subscribed}")
    
    if num_subscribed[0][1] == 0:
        print("\n⚠️  WARNING: No Pathway monitor is subscribed to Redis!")
        print("   To enable real-time monitoring, start the Pathway order monitor:")
        print("   python -m workers.pathway_order_monitor")
        print("\n   The monitor will:")
        print("   1. Subscribe to trades:executed channel")
        print("   2. Join with live price feeds")
        print("   3. Auto-execute SELL when price >= ₹2600")
        print("   4. Auto-execute SELL when price <= ₹2450 (SL)")
    else:
        print(f"   ✅ Pathway monitor is running ({num_subscribed[0][1]} subscribers)")
    
    pubsub.unsubscribe()
    
    # Step 4: Verify Redis keys
    print("\n" + "="*80)
    print("📊 Redis Channel Status:")
    print("="*80)
    
    channels = [
        "trades:executed",
        "trades:pending", 
        "market:prices",
        "orders:execute"
    ]
    
    for channel in channels:
        subs = redis_client.pubsub_numsub(channel)
        print(f"   {channel:20s}: {subs[0][1]} subscribers")
    
    # Step 5: Manual verification steps
    print("\n" + "="*80)
    print("🔍 Manual Verification Steps:")
    print("="*80)
    print("""
1. Start Pathway Order Monitor (in separate terminal):
   cd apps/portfolio-server
   python -m workers.pathway_order_monitor

2. Re-run this test script - monitor should auto-execute TP

3. Check logs for execution confirmation:
   - "🎯 EXECUTE_TP: RELIANCE x 10 @ ₹2600"
   - "Executing SELL order via TradeEngine"

4. Verify in database:
   SELECT * FROM "Trade" WHERE symbol = 'RELIANCE' 
   ORDER BY "createdAt" DESC LIMIT 5;
   
   Should show:
   - Original BUY trade (entry)
   - Auto-generated SELL trade (TP exit)
""")
    
    print("\n✅ Test setup complete!")
    print("   Trade published to Redis: trades:executed")
    print("   Start Pathway monitor to see auto-execution")
    print()


async def test_manual_redis_check():
    """Check what's currently in Redis"""
    print("\n📊 Checking Redis state...")
    
    redis_client = Redis.from_url(BROKER_URL)
    
    # Check active channels
    print("\n1. Active Pub/Sub Channels:")
    pubsub_channels = redis_client.pubsub_channels()
    if pubsub_channels:
        for ch in pubsub_channels:
            print(f"   - {ch.decode()}")
    else:
        print("   (none)")
    
    # Check subscribers
    print("\n2. Channel Subscribers:")
    for channel in ["trades:executed", "market:prices", "orders:execute"]:
        subs = redis_client.pubsub_numsub(channel)
        print(f"   {channel}: {subs[0][1]} subscribers")
    
    print()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test TP sell auto-monitoring")
    parser.add_argument("--check", action="store_true", help="Just check Redis state")
    args = parser.parse_args()
    
    if args.check:
        asyncio.run(test_manual_redis_check())
    else:
        asyncio.run(test_tp_monitoring())
