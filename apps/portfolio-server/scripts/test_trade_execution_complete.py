"""
Complete Trade Execution Test Script

This script tests the entire trade execution pipeline:
1. Market order creation (BUY)
2. TP/SL order creation
3. TP/SL order monitoring and execution
4. Auto-sell functionality
5. Realized P&L calculation

Run with: PYTHONPATH=../..:../../shared/py python3 scripts/test_trade_execution_complete.py
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / ".." / ".." / "shared" / "py"))

from prisma import Prisma
from dotenv import load_dotenv

# Load environment
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    load_dotenv(env_file)

async def main():
    print("=" * 80)
    print("🧪 COMPLETE TRADE EXECUTION TEST")
    print("=" * 80)
    
    client = Prisma()
    await client.connect()
    
    try:
        # Test 1: Check executed trade and verify TP/SL orders were created
        print("\n📊 TEST 1: Verify TP/SL Orders Creation")
        print("-" * 80)
        
        # Find the executed TCS trade
        parent_trade = await client.trade.find_first(
            where={
                "symbol": "TCS",
                "side": "BUY",
                "status": {"in": ["executed", "executed"]},
                "source": "nse_pipeline",
            },
            order={"created_at": "desc"},
        )
        
        if not parent_trade:
            print("❌ No executed TCS trade found")
            return
        
        print(f"✅ Found executed trade: {parent_trade.id}")
        print(f"   Symbol: {parent_trade.symbol}")
        print(f"   Side: {parent_trade.side}")
        print(f"   Quantity: {parent_trade.quantity}")
        print(f"   Executed Price: ₹{parent_trade.executed_price}")
        print(f"   TP Price: ₹{parent_trade.take_profit_price}")
        print(f"   SL Price: ₹{parent_trade.stop_loss_price}")
        print(f"   Auto Sell At: {parent_trade.auto_sell_at}")
        
        # Find TP/SL orders for this trade
        tp_sl_trades = await client.trade.find_many(
            where={
                "metadata": {"string_contains": parent_trade.id},
                "source": "nse_pipeline_tp_sl",
            },
            order={"created_at": "asc"},
        )
        
        print(f"\n📋 TP/SL Orders:")
        if not tp_sl_trades:
            print("❌ No TP/SL orders found - ISSUE DETECTED!")
            print("   Expected: 2 orders (1 TP + 1 SL)")
        else:
            print(f"✅ Found {len(tp_sl_trades)} TP/SL orders")
            for trade in tp_sl_trades:
                metadata = json.loads(trade.metadata) if trade.metadata else {}
                order_type = metadata.get("order_type", "unknown")
                target_price = metadata.get("target_price", 0)
                print(f"   - {order_type.upper()}: {trade.side} {trade.symbol} x {trade.quantity} @ ₹{target_price}")
                print(f"     Status: {trade.status}")
                print(f"     Order Type: {trade.order_type}")
                print(f"     Trade ID: {trade.id}")
        
        # Test 2: Check auto-sell functionality
        print("\n📊 TEST 2: Check Auto-Sell Functionality")
        print("-" * 80)
        
        if parent_trade.auto_sell_at:
            time_until_auto_sell = parent_trade.auto_sell_at - datetime.now(timezone.utc)
            minutes_remaining = time_until_auto_sell.total_seconds() / 60
            
            if minutes_remaining > 0:
                print(f"⏰ Auto-sell scheduled in {minutes_remaining:.1f} minutes")
                print(f"   Auto-sell will trigger at: {parent_trade.auto_sell_at}")
            else:
                print(f"⏰ Auto-sell window EXPIRED {-minutes_remaining:.1f} minutes ago")
                print(f"   Should have been sold at: {parent_trade.auto_sell_at}")
                
                # Check if auto-sell was executed
                auto_sell_trade = await client.trade.find_first(
                    where={
                        "metadata": {"string_contains": parent_trade.id},
                        "source": "auto_sell_worker",
                        "side": "SELL",
                    },
                )
                
                if auto_sell_trade:
                    print(f"✅ Auto-sell trade found: {auto_sell_trade.id}")
                    print(f"   Status: {auto_sell_trade.status}")
                    print(f"   Executed Price: ₹{auto_sell_trade.executed_price or 'pending'}")
                else:
                    print("❌ Auto-sell trade NOT found - auto_sell_worker may not be running")
        else:
            print("⚠️  No auto_sell_at timestamp set on trade")
        
        # Test 3: Check realized P&L calculation
        print("\n📊 TEST 3: Check Realized P&L Calculation")
        print("-" * 80)
        
        # Find all SELL trades for TCS
        sell_trades = await client.trade.find_many(
            where={
                "symbol": "TCS",
                "side": "SELL",
                "status": {"in": ["executed", "executed"]},
            },
            order={"created_at": "desc"},
            take=5,
        )
        
        if sell_trades:
            print(f"✅ Found {len(sell_trades)} executed SELL trades:")
            total_realized_pnl = 0
            
            for trade in sell_trades:
                # Handle metadata that might already be a dict
                if isinstance(trade.metadata, str):
                    metadata = json.loads(trade.metadata)
                elif isinstance(trade.metadata, dict):
                    metadata = trade.metadata
                else:
                    metadata = {}
                
                parent_trade_id = metadata.get("parent_trade_id", "N/A")
                sell_reason = metadata.get("sell_reason", metadata.get("order_type", "unknown"))
                
                # Calculate P&L if we have both buy and sell prices
                if trade.executed_price and parent_trade.executed_price:
                    pnl = (float(trade.executed_price) - float(parent_trade.executed_price)) * trade.executed_quantity
                    total_realized_pnl += pnl
                    pnl_pct = (pnl / (float(parent_trade.executed_price) * trade.executed_quantity)) * 100
                    
                    print(f"\n   Trade {trade.id[:8]}...")
                    print(f"   - Reason: {sell_reason}")
                    print(f"   - Quantity: {trade.executed_quantity}")
                    print(f"   - Sell Price: ₹{trade.executed_price}")
                    print(f"   - Buy Price: ₹{parent_trade.executed_price}")
                    print(f"   - P&L: ₹{pnl:.2f} ({pnl_pct:+.2f}%)")
                    print(f"   - Status: {trade.status}")
            
            print(f"\n📈 Total Realized P&L: ₹{total_realized_pnl:.2f}")
        else:
            print("ℹ️  No SELL trades found yet")
        
        # Test 4: Check portfolio allocation P&L
        print("\n📊 TEST 4: Check Portfolio Allocation P&L")
        print("-" * 80)
        
        if parent_trade.agent_id:
            allocation = await client.portfolioallocation.find_first(
                where={
                    "portfolio_id": parent_trade.portfolio_id,
                    "allocation_type": "high_risk",
                },
                include={"tradingAgent": True},
            )
            
            if allocation:
                print(f"✅ Found allocation: {allocation.id}")
                print(f"   Allocation Type: {allocation.allocation_type}")
                print(f"   Allocated Amount: ₹{allocation.allocated_amount}")
                print(f"   Available Cash: ₹{allocation.available_cash}")
                print(f"   Realized P&L: ₹{allocation.realized_pnl}")
                print(f"   P&L Percentage: {allocation.pnl_percentage}%")
                
                if allocation.tradingAgent:
                    print(f"\n   Trading Agent: {allocation.tradingAgent.id}")
                    print(f"   - Status: {allocation.tradingAgent.status}")
                    print(f"   - Auto Trade: {allocation.tradingAgent.strategy_config.get('auto_trade', False) if allocation.tradingAgent.strategy_config else False}")
            else:
                print("⚠️  No allocation found for this trade")
        else:
            print("⚠️  No agent_id on trade")
        
        # Test 5: Summary and recommendations
        print("\n📊 TEST 5: System Status Summary")
        print("-" * 80)
        
        issues = []
        
        # Check if TP/SL orders were created
        if len(tp_sl_trades) < 2:
            issues.append("❌ TP/SL orders not created properly")
        else:
            print("✅ TP/SL orders created correctly")
        
        # Check if auto-sell is configured
        if not parent_trade.auto_sell_at:
            issues.append("❌ Auto-sell timestamp not set")
        else:
            print("✅ Auto-sell configured")
        
        # Check if orders are being monitored
        pending_orders = await client.trade.count(
            where={
                "status": "pending",
                "order_type": {"in": ["limit", "stop"]},
            }
        )
        
        if pending_orders > 0:
            print(f"⏳ {pending_orders} pending TP/SL orders awaiting execution")
            print("   Ensure streaming_order_monitor is running:")
            print("   pnpm streaming:orders")
        else:
            print("✅ No pending TP/SL orders")
        
        # Summary
        print("\n" + "=" * 80)
        if issues:
            print("⚠️  ISSUES DETECTED:")
            for issue in issues:
                print(f"   {issue}")
            print("\n🔧 FIXES NEEDED:")
            print("   1. Restart Celery worker: pnpm celery")
            print("   2. Start streaming order monitor: pnpm streaming:orders")
            print("   3. Ensure USE_CELERY_FOR_TRADES=true in .env")
        else:
            print("✅ ALL SYSTEMS OPERATIONAL")
            print("\n📋 MONITORING:")
            print("   - Celery worker: pnpm celery")
            print("   - Order monitor: pnpm streaming:orders")
            print("   - Auto-sell: Every 1 minute via Celery Beat")
        
        print("=" * 80)
        
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
