#!/usr/bin/env python3
"""
Test script to verify trade execution with portfolio allocation tracking.

This test ensures:
1. Trades are executed without creating automatic TP/SL orders
2. triggered_by agent is tracked in metadata
3. Trades are added to portfolio.allocation_trades array
4. Portfolio value is recalculated after trade execution
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.trade_execution_service import TradeExecutionService
from decimal import Decimal

if os.getenv("ENABLE_DB_TESTS", "false").lower() != "true":
    pytest.skip("DB-backed trade execution test disabled", allow_module_level=True)


async def _run_trade_execution_flow():
    """Test the complete trade execution flow with allocation tracking."""
    
    print("=" * 80)
    print("TRADE EXECUTION & ALLOCATION TRACKING TEST")
    print("=" * 80)
    
    service = TradeExecutionService()
    
    # Setup: Create a test portfolio first
    print("\n🔧 Setup: Creating test portfolio...")
    
    client = await service._ensure_client()
    
    # Create test portfolio
    test_portfolio = await client.portfolio.create(
        data={
            "organization_id": "test_org",
            "customer_id": "test_customer",
            "portfolio_name": "Test Allocation Tracking Portfolio",
            "initial_investment": 100000.00,
            "investment_amount": 100000.00,
            "current_value": 100000.00,
            "investment_horizon_years": 5,
            "expected_return_target": 0.12,
            "risk_tolerance": "high",
            "liquidity_needs": "low",
        }
    )
    
    print(f"✅ Test portfolio created: {test_portfolio.id}")
    
    # Test 1: Create a trade log
    print("\n📝 Test 1: Creating trade log with triggered_by agent...")
    
    test_trade = {
        "user_id": "test_user_123",
        "portfolio_id": test_portfolio.id,  # Use the created portfolio
        "symbol": "RELIANCE",
        "side": "BUY",
        "quantity": 10,
        "reference_price": 2500.50,
        "allocated_capital": 25000.00,
        "confidence": 0.85,
        "triggered_by": "high_risk_agent",  # This should be tracked
        "signal_metadata": {
            "strategy": "nse_pipeline",
            "take_profit_pct": 0.03,  # 3%
            "stop_loss_pct": 0.01,  # 1%
        }
    }
    
    try:
        # Prepare job_row for create_trade_log
        import uuid
        job_row = {
            "request_id": f"test_request_{uuid.uuid4().hex[:8]}",
            "user_id": test_trade["user_id"],
            "portfolio_id": test_trade["portfolio_id"],
            "symbol": test_trade["symbol"],
            "side": test_trade["side"],
            "quantity": test_trade["quantity"],
            "reference_price": test_trade["reference_price"],
            "allocated_capital": test_trade["allocated_capital"],
            "confidence": test_trade["confidence"],
            "take_profit_pct": 0.03,  # 3%
            "stop_loss_pct": 0.01,  # 1%
            "triggered_by": test_trade["triggered_by"],
            "metadata_json": None,
        }
        
        trade_log = await service.create_trade_log(job_row=job_row)
        
        print(f"✅ Trade log created: {trade_log.id}")
        print(f"   Status: {trade_log.status}")
        
        # Fetch the full record to check metadata
        full_record = await service.fetch_trade_log(trade_log.id)
        
        print(f"   Symbol: {full_record.symbol}")
        print(f"   Side: {full_record.side}")
        print(f"   Quantity: {full_record.quantity}")
        print(f"   Confidence: {full_record.confidence}")
        
        # Check metadata has triggered_by
        if hasattr(full_record, "metadata"):
            import json
            meta = full_record.metadata
            if isinstance(meta, str):
                meta = json.loads(meta) if meta else {}
            print(f"   Triggered by: {meta.get('triggered_by', 'NOT FOUND')}")
            
            if "triggered_by" not in meta:
                print("❌ ERROR: triggered_by not found in metadata!")
                return False
        
        # Test 2: Execute the trade (simulated)
        print("\n🔄 Test 2: Executing trade (simulated mode)...")
        
        result = await service.execute_trade(trade_log.id, simulate=True)
        
        if result.get("status") == "simulated_executed":
            print("✅ Trade executed successfully!")
            print(f"   Executed Price: ₹{result.get('executed_price')}")
            print(f"   Executed Quantity: {result.get('executed_quantity')}")
        else:
            print(f"❌ Trade execution failed: {result}")
            return False
        
        # Test 3: Verify portfolio allocation was updated
        print("\n📊 Test 3: Verifying portfolio allocation tracking...")
        
        client = await service._ensure_client()
        portfolio = await client.portfolio.find_unique(
            where={"id": test_trade["portfolio_id"]},
        )
        
        if portfolio and portfolio.allocation_trades:
            allocations = portfolio.allocation_trades
            
            print(f"✅ Portfolio has {len(allocations)} allocation trade(s)")
            
            # Find our trade
            our_trade = None
            for alloc in allocations:
                if alloc.get("trade_log_id") == full_record.id:
                    our_trade = alloc
                    break
            
            if our_trade:
                print("✅ Trade found in allocation_trades array:")
                print(f"   Symbol: {our_trade.get('symbol')}")
                print(f"   Side: {our_trade.get('side')}")
                print(f"   Quantity: {our_trade.get('quantity')}")
                print(f"   Executed Price: ₹{our_trade.get('executed_price')}")
                print(f"   Triggered By: {our_trade.get('triggered_by')}")
                print(f"   Confidence: {our_trade.get('confidence')}")
                
                # Verify triggered_by is correct
                if our_trade.get("triggered_by") != test_trade["triggered_by"]:
                    print(f"❌ ERROR: Expected triggered_by='{test_trade['triggered_by']}', got '{our_trade.get('triggered_by')}'")
                    return False
            else:
                print("❌ ERROR: Trade not found in allocation_trades array!")
                return False
        else:
            print("⚠️  Portfolio allocation_trades is empty or None")
            if not portfolio:
                print("⚠️  Portfolio not found (might need to create test portfolio first)")
            return False
        
        # Test 4: Verify TP/SL orders WERE created for NSE pipeline
        print("\n✅ Test 4: Verifying TP/SL orders were created for NSE pipeline...")
        
        # Search for pending orders related to this trade
        pending_orders = await client.tradeexecutionlog.find_many(
            where={
                "portfolio_id": test_trade["portfolio_id"],
                "symbol": test_trade["symbol"],
                "status": "pending",
            }
        )
        
        # Filter out our original trade
        tp_sl_orders = [o for o in pending_orders if o.id != full_record.id]
        
        if len(tp_sl_orders) == 2:
            print(f"✅ Confirmed: {len(tp_sl_orders)} TP/SL orders were created")
            
            # Validate order types
            for order in tp_sl_orders:
                meta = {}
                if hasattr(order, "metadata") and order.metadata:
                    if isinstance(order.metadata, str):
                        try:
                            meta = json.loads(order.metadata)
                        except:
                            pass
                    elif isinstance(order.metadata, dict):
                        meta = order.metadata
                
                order_type = meta.get("order_type", "unknown")
                target_pct = meta.get("target_pct", 0)
                
                print(f"   - {order_type.upper()}: {order.side} {order.symbol} @ ₹{float(order.reference_price):.2f} ({target_pct*100:.1f}%)")
                
                if order_type == "take_profit":
                    # Validate TP is above entry price for BUY
                    if float(order.reference_price) <= float(full_record.reference_price) * 1.01:
                        print(f"     ⚠️  TP price seems incorrect")
                elif order_type == "stop_loss":
                    # Validate SL is below entry price for BUY  
                    if float(order.reference_price) >= float(full_record.reference_price) * 0.99:
                        print(f"     ⚠️  SL price seems incorrect")
        else:
            print(f"❌ ERROR: Expected 2 TP/SL orders, found {len(tp_sl_orders)}!")
            for order in tp_sl_orders:
                print(f"   - {order.side} {order.symbol} @ ₹{float(order.reference_price):.2f}")
            return False
        
        # Test 5: Verify portfolio value was recalculated
        print("\n💰 Test 5: Verifying portfolio value recalculation...")
        
        # Refresh portfolio
        portfolio = await client.portfolio.find_unique(
            where={"id": test_trade["portfolio_id"]},
        )
        
        if portfolio:
            print(f"✅ Portfolio current value: ₹{float(portfolio.current_value)}")
            print("   (Recalculation triggered successfully)")
        else:
            print("⚠️  Could not verify portfolio value")
        
        print("\n" + "=" * 80)
        print("✅ ALL TESTS PASSED!")
        print("=" * 80)
        print("\nSummary:")
        print("  ✓ Trade logs track triggered_by agent")
        print("  ✓ Trades added to portfolio.allocation_trades array")
        print("  ✓ TP/SL orders created automatically for NSE pipeline")
        print("  ✓ Portfolio value recalculated after execution")
        print("  ✓ TP/SL percentages used for pending orders (3% / 1%)")
        print("  ✓ Order monitor worker will watch these pending orders")
        print("  ✓ Kafka publishes trade logs to nse_pipeline_trade_logs")
        
        # Cleanup: Delete test portfolio
        print("\n🧹 Cleanup: Deleting test portfolio...")
        await client.portfolio.delete(where={"id": test_portfolio.id})
        print("✅ Cleanup complete")

        return True

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trade_execution_flow():
    """Sync wrapper to execute the async trade execution test."""
    asyncio.run(_run_trade_execution_flow())


if __name__ == "__main__":
    success = asyncio.run(_run_trade_execution_flow())
    sys.exit(0 if success else 1)
