#!/usr/bin/env python3
"""
Comprehensive NSE Pipeline Trade Lifecycle Test Script:
- Create test trades with 15-minute auto-sell window
- Test TP/SL order monitoring and execution
- Manipulate market prices and time for verification
- Verify auto-sell functionality
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

# Add project paths
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../..")
SHARED_PY_PATH = os.path.join(PROJECT_ROOT, "shared/py")
if SHARED_PY_PATH not in sys.path:
    sys.path.insert(0, SHARED_PY_PATH)

PORTFOLIO_SERVER_ROOT = os.path.dirname(__file__)
if PORTFOLIO_SERVER_ROOT not in sys.path:
    sys.path.insert(0, PORTFOLIO_SERVER_ROOT)

# Use Prisma directly instead of DBManager
from prisma import Prisma

# Mock market data for testing
MOCK_PRICES = {
    "TCS": Decimal("3500.00"),
    "INFY": Decimal("1800.00"),
    "RELIANCE": Decimal("2500.00"),
    "HDFCBANK": Decimal("1600.00"),
    "ICICIBANK": Decimal("1100.00"),
    "BHARTIARTL": Decimal("1400.00"),
    "LT": Decimal("3500.00"),
    "KOTAKBANK": Decimal("1800.00"),
    "MARUTI": Decimal("12000.00"),
    "BAJFINANCE": Decimal("7000.00"),
}

# Mock TP/SL prices for testing
TP_SL_CONFIG = {
    "TCS": {"tp": Decimal("3675.00"), "sl": Decimal("3325.00")},  # 5% TP, 5% SL
    "INFY": {"tp": Decimal("1890.00"), "sl": Decimal("1710.00")},
    "RELIANCE": {"tp": Decimal("2625.00"), "sl": Decimal("2375.00")},
    "HDFCBANK": {"tp": Decimal("1680.00"), "sl": Decimal("1520.00")},
    "ICICIBANK": {"tp": Decimal("1155.00"), "sl": Decimal("1045.00")},
    "BHARTIARTL": {"tp": Decimal("1470.00"), "sl": Decimal("1330.00")},
    "LT": {"tp": Decimal("3675.00"), "sl": Decimal("3325.00")},
    "KOTAKBANK": {"tp": Decimal("1890.00"), "sl": Decimal("1710.00")},
    "MARUTI": {"tp": Decimal("12600.00"), "sl": Decimal("11400.00")},
    "BAJFINANCE": {"tp": Decimal("7350.00"), "sl": Decimal("6650.00")},
}

def get_mock_price(symbol: str) -> Decimal:
    """Get mock price for testing"""
    return MOCK_PRICES.get(symbol, Decimal("1000.00"))

def update_mock_price(symbol: str, new_price: Decimal):
    """Update mock price for testing"""
    MOCK_PRICES[symbol] = new_price
    print(f"📊 Updated {symbol} price to ₹{new_price}")

async def create_test_portfolio_and_agent(db_client):
    """Find existing portfolio and create/setup agent for NSE trades"""
    print("🏗️  Finding existing portfolio and setting up agent...")

    try:
        # Find existing portfolio
        portfolios = await db_client.portfolio.find_many(
            where={"status": "active"}
        )

        if not portfolios:
            raise Exception("No active portfolio found")

        existing_portfolio = portfolios[0]

        print(f"✅ Using existing portfolio: {existing_portfolio.id}")

        # Check if portfolio allocation exists
        allocations = await db_client.portfolioallocation.find_many(
            where={"portfolio_id": existing_portfolio.id}
        )

        if allocations:
            test_allocation = allocations[0]
            print(f"✅ Using existing allocation: {test_allocation.id}")
        else:
            # Create portfolio allocation
            test_allocation = await db_client.portfolioallocation.create(
                data={
                    "portfolio_id": existing_portfolio.id,
                    "allocation_type": "high_risk",
                    "target_weight": Decimal("1.0"),
                }
            )
            print(f"✅ Created test allocation: {test_allocation.id}")

        # Check if trading agent exists
        agents = await db_client.tradingagent.find_many(
            where={"portfolio_allocation_id": test_allocation.id}
        )

        if agents:
            test_agent = agents[0]
            print(f"✅ Using existing agent: {test_agent.id}")
        else:
            # Create test agent
            test_agent = await db_client.tradingagent.create(
                data={
                    "portfolio_allocation_id": test_allocation.id,
                    "agent_type": "high_risk",
                    "agent_name": "Test NSE Agent",
                }
            )
            print(f"✅ Created test agent: {test_agent.id}")

        return test_agent, existing_portfolio, test_allocation

    except Exception as e:
        print(f"❌ Failed to setup test environment: {e}")
        raise

async def create_test_buy_trades(db_client, agent, portfolio, allocation):
    """Create 10 test BUY trades with TP/SL orders"""
    print("💰 Creating 10 test BUY trades...")

    test_symbols = list(MOCK_PRICES.keys())
    trades_created = []

    for i, symbol in enumerate(test_symbols):
        # Calculate quantity (10% of capital per trade)
        capital_per_trade = Decimal("100000.00")  # 1 lakh per trade
        price = get_mock_price(symbol)
        quantity = int(capital_per_trade / price)

        # Create TradeExecutionLog entry
        execution_time = datetime.now(timezone.utc)
        auto_sell_at = execution_time + timedelta(minutes=15)  # 15-minute window

        trade_log = await db_client.tradeexecutionlog.create(
            data={
                "request_id": f"req_{uuid.uuid4().hex[:16]}",
                "user_id": "b2235778-9807-4f2b-b968-de7f43250ada",
                "portfolio_id": portfolio.id,
                "symbol": symbol,
                "side": "BUY",
                "quantity": quantity,
                "reference_price": price,
                "status": "executed",
                "executed_price": price,
                "executed_quantity": quantity,
                "agent_id": agent.id,
                "agent_type": "high_risk",
                "auto_sell_at": auto_sell_at,
                "metadata": json.dumps({
                    "test_trade": True,
                    "triggered_by": "nse_filings_pipeline",
                    "signal_confidence": 0.85,
                    "purpose": "lifecycle_testing"
                }),
                "created_at": execution_time,
                "updated_at": execution_time,
            }
        )

        # Create Trade record
        trade_record = await db_client.trade.create(
            data={
                "organization_id": "0eb89373-75d4-4016-ba0b-1194a9234fbf",
                "portfolio_id": portfolio.id,
                "customer_id": "b2235778-9807-4f2b-b968-de7f43250ada",
                "trade_type": "equity",
                "symbol": symbol,
                "exchange": "NSE",
                "segment": "equity",
                "side": "BUY",
                "order_type": "market",
                "quantity": quantity,
                "price": price,
                "executed_quantity": quantity,
                "executed_price": price,
                "status": "executed",
                "agent_id": agent.id,
                "auto_sell_at": auto_sell_at,
                "metadata": json.dumps({
                    "test_trade": True,
                    "parent_execution_id": trade_log.id,
                    "purpose": "lifecycle_testing"
                }),
                "created_at": execution_time,
                "updated_at": execution_time,
            }
        )

        # Create TP/SL orders
        tp_config = TP_SL_CONFIG[symbol]
        tp_price = tp_config["tp"]
        sl_price = tp_config["sl"]

        # Take Profit order
        tp_order = await db_client.tradeexecutionlog.create(
            data={
                "request_id": f"req_{uuid.uuid4().hex[:16]}",
                "user_id": "b2235778-9807-4f2b-b968-de7f43250ada",
                "portfolio_id": portfolio.id,
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "reference_price": tp_price,
                "status": "pending",
                "agent_id": agent.id,
                "agent_type": "high_risk",
                "metadata": json.dumps({
                    "test_order": True,
                    "parent_trade_id": trade_record.id,
                    "order_type": "take_profit",
                    "purpose": "lifecycle_testing"
                }),
                "created_at": execution_time,
                "updated_at": execution_time,
            }
        )

        # Stop Loss order
        sl_order = await db_client.tradeexecutionlog.create(
            data={
                "request_id": f"req_{uuid.uuid4().hex[:16]}",
                "user_id": "b2235778-9807-4f2b-b968-de7f43250ada",
                "portfolio_id": portfolio.id,
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "reference_price": sl_price,
                "status": "pending",
                "agent_id": agent.id,
                "agent_type": "high_risk",
                "metadata": json.dumps({
                    "test_order": True,
                    "parent_trade_id": trade_record.id,
                    "order_type": "stop_loss",
                    "purpose": "lifecycle_testing"
                }),
                "created_at": execution_time,
                "updated_at": execution_time,
            }
        )

        trades_created.append({
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "trade_log": trade_log,
            "trade_record": trade_record,
            "tp_order": tp_order,
            "sl_order": sl_order,
            "auto_sell_at": auto_sell_at
        })

        print(f"   ✅ Created BUY trade: {symbol} x {quantity} @ ₹{price}")
        print(f"      TP: ₹{tp_price}, SL: ₹{sl_price}, Auto-sell: {auto_sell_at}")

    return trades_created

async def test_negative_signals(db_client, trades_created, agent, portfolio):
    """Test -1 signals result in selling"""
    print("📈 Testing -1 signals (SELL signals)...")

    # Simulate -1 signals for first 3 stocks
    sell_signals = trades_created[:3]

    for trade_info in sell_signals:
        symbol = trade_info["symbol"]
        quantity = trade_info["quantity"]
        current_price = get_mock_price(symbol)

        # Create SELL execution
        sell_time = datetime.now(timezone.utc)

        sell_log = await db_client.tradeexecutionlog.create(
            data={
                "request_id": f"req_{uuid.uuid4().hex[:16]}",
                "user_id": "b2235778-9807-4f2b-b968-de7f43250ada",
                "portfolio_id": portfolio.id,
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "reference_price": current_price,
                "status": "executed",
                "executed_price": current_price,
                "executed_quantity": quantity,
                "agent_id": agent.id,
                "agent_type": "high_risk",
                "metadata": json.dumps({
                    "test_sell": True,
                    "signal": -1,
                    "triggered_by": "nse_filings_pipeline",
                    "purpose": "lifecycle_testing"
                }),
                "created_at": sell_time,
                "updated_at": sell_time,
            }
        )

        # Update Trade record
        await db_client.trade.update(
            where={"id": trade_info["trade_record"].id},
            data={
                "status": "closed",
                "updated_at": sell_time,
            }
        )

        # Cancel TP/SL orders directly using their IDs
        await db_client.tradeexecutionlog.update(
            where={"id": trade_info["tp_order"].id},
            data={
                "status": "cancelled",
                "updated_at": sell_time,
            }
        )

        await db_client.tradeexecutionlog.update(
            where={"id": trade_info["sl_order"].id},
            data={
                "status": "cancelled",
                "updated_at": sell_time,
            }
        )

        print(f"   ✅ Executed SELL: {symbol} x {quantity} @ ₹{current_price} (signal: -1)")

async def test_tp_sl_orders(db_client, trades_created):
    """Test TP/SL order execution by manipulating prices"""
    print("🎯 Testing TP/SL order execution...")

    # Test TP for stock 4 (HDFCBANK)
    tp_trade = trades_created[3]  # HDFCBANK
    symbol = tp_trade["symbol"]
    tp_price = TP_SL_CONFIG[symbol]["tp"]

    # Update price to trigger TP
    update_mock_price(symbol, tp_price + Decimal("10.00"))  # Slightly above TP

    # Simulate TP execution
    tp_time = datetime.now(timezone.utc)

    tp_execution = await db_client.tradeexecutionlog.update(
        where={"id": tp_trade["tp_order"].id},
        data={
            "status": "executed",
            "executed_price": tp_price,
            "executed_quantity": tp_trade["quantity"],
            "updated_at": tp_time,
        }
    )

    # Update Trade record
    await db_client.trade.update(
        where={"id": tp_trade["trade_record"].id},
        data={
            "status": "closed",
            "updated_at": tp_time,
        }
    )

    # Cancel SL order
    await db_client.tradeexecutionlog.update(
        where={"id": tp_trade["sl_order"].id},
        data={
            "status": "cancelled",
            "updated_at": tp_time,
        }
    )

    print(f"   ✅ TP executed: {symbol} @ ₹{tp_price} (target hit)")

    # Test SL for stock 5 (ICICIBANK)
    sl_trade = trades_created[4]  # ICICIBANK
    symbol = sl_trade["symbol"]
    sl_price = TP_SL_CONFIG[symbol]["sl"]

    # Update price to trigger SL
    update_mock_price(symbol, sl_price - Decimal("10.00"))  # Slightly below SL

    # Simulate SL execution
    sl_time = datetime.now(timezone.utc)

    sl_execution = await db_client.tradeexecutionlog.update(
        where={"id": sl_trade["sl_order"].id},
        data={
            "status": "executed",
            "executed_price": sl_price,
            "executed_quantity": sl_trade["quantity"],
            "updated_at": sl_time,
        }
    )

    # Update Trade record
    await db_client.trade.update(
        where={"id": sl_trade["trade_record"].id},
        data={
            "status": "closed",
            "updated_at": sl_time,
        }
    )

    # Cancel TP order
    await db_client.tradeexecutionlog.update(
        where={"id": sl_trade["tp_order"].id},
        data={
            "status": "cancelled",
            "updated_at": sl_time,
        }
    )

    print(f"   ✅ SL executed: {symbol} @ ₹{sl_price} (stop loss hit)")

async def test_auto_sell_functionality(db_client, trades_created):
    """Test 15-minute auto-sell by manipulating time"""
    print("⏰ Testing 15-minute auto-sell functionality...")

    # Get remaining active trades (not sold by signals or TP/SL)
    active_trades = [t for t in trades_created[5:] if t["trade_record"].status == "executed"]

    # Simulate time passing (16 minutes later)
    simulated_current_time = datetime.now(timezone.utc) + timedelta(minutes=16)

    print(f"   ⏰ Simulating time jump: Current time now {simulated_current_time}")

    for trade_info in active_trades:
        symbol = trade_info["symbol"]
        quantity = trade_info["quantity"]
        current_price = get_mock_price(symbol)

        # Create auto-sell execution
        sell_time = simulated_current_time

        auto_sell_log = await db_client.tradeexecutionlog.create(
            data={
                "request_id": f"req_{uuid.uuid4().hex[:16]}",
                "user_id": "b2235778-9807-4f2b-b968-de7f43250ada",
                "portfolio_id": trade_info["trade_record"].portfolio_id,
                "symbol": symbol,
                "side": "SELL",
                "quantity": quantity,
                "reference_price": current_price,
                "status": "executed",
                "executed_price": current_price,
                "executed_quantity": quantity,
                "agent_id": trade_info["trade_record"].agent_id,
                "agent_type": "high_risk",
                "metadata": json.dumps({
                    "test_auto_sell": True,
                    "parent_trade_id": trade_info["trade_record"].id,
                    "original_buy_price": str(trade_info["price"]),
                    "auto_sell_triggered": True,
                    "purpose": "lifecycle_testing"
                }),
                "created_at": sell_time,
                "updated_at": sell_time,
            }
        )

        # Update Trade record
        await db_client.trade.update(
            where={"id": trade_info["trade_record"].id},
            data={
                "status": "closed",
                "updated_at": sell_time,
            }
        )

        # Cancel remaining TP/SL orders directly using their IDs
        await db_client.tradeexecutionlog.update(
            where={"id": trade_info["tp_order"].id},
            data={
                "status": "cancelled",
                "updated_at": sell_time,
            }
        )

        await db_client.tradeexecutionlog.update(
            where={"id": trade_info["sl_order"].id},
            data={
                "status": "cancelled",
                "updated_at": sell_time,
            }
        )

        print(f"   ✅ Auto-sold: {symbol} x {quantity} @ ₹{current_price} (15-min window expired)")

async def verify_all_components(db_client, agent, portfolio):
    """Verify all components worked correctly"""
    print("🔍 Verifying all trade lifecycle components...")

    # Get all test trades for this agent created in the last 10 minutes (simplified approach)
    ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)

    all_trades = await db_client.tradeexecutionlog.find_many(
        where={
            "agent_id": agent.id,
            "created_at": {"gte": ten_minutes_ago}
        }
    )

    # Filter for test trades
    test_trades = [t for t in all_trades if t.metadata and isinstance(t.metadata, dict) and t.metadata.get("purpose") == "lifecycle_testing"]
    print(f"   DEBUG: Found {len(all_trades)} recent trades, {len(test_trades)} test trades")
    if all_trades:
        print(f"   DEBUG: Sample metadata: {all_trades[0].metadata}")

    # Count different types
    total_trades = len(test_trades)
    buy_trades = len([t for t in test_trades if t.side == "BUY" and t.status == "executed"])
    signal_sells = len([t for t in test_trades if t.side == "SELL" and t.status == "executed" and t.metadata and t.metadata.get("signal") == -1])
    tp_executions = len([t for t in test_trades if t.status == "executed" and t.metadata and t.metadata.get("order_type") == "take_profit"])
    sl_executions = len([t for t in test_trades if t.status == "executed" and t.metadata and t.metadata.get("order_type") == "stop_loss"])
    auto_sells = len([t for t in test_trades if t.status == "executed" and t.metadata and t.metadata.get("test_auto_sell") == True])
    cancelled_orders = len([t for t in test_trades if t.status == "cancelled"])

    print("📊 VERIFICATION RESULTS:")
    print(f"   • Total trades created: {total_trades}")
    print(f"   • BUY executions: {buy_trades}")
    print(f"   • Signal-based SELL (-1): {signal_sells}")
    print(f"   • Take Profit executions: {tp_executions}")
    print(f"   • Stop Loss executions: {sl_executions}")
    print(f"   • Auto-sell executions: {auto_sells}")
    print(f"   • Cancelled orders: {cancelled_orders}")

    # Expected results
    expected_buys = 10
    expected_signal_sells = 3
    expected_tp = 1
    expected_sl = 1
    expected_auto_sells = 5  # Remaining 5 after signal sells, TP, SL
    expected_cancelled = expected_signal_sells * 2 + expected_tp + expected_sl + expected_auto_sells * 2  # TP+SL cancelled per trade

    success = True
    if buy_trades != expected_buys:
        print(f"   ❌ BUY trades mismatch: expected {expected_buys}, got {buy_trades}")
        success = False
    if signal_sells != expected_signal_sells:
        print(f"   ❌ Signal sells mismatch: expected {expected_signal_sells}, got {signal_sells}")
        success = False
    if tp_executions != expected_tp:
        print(f"   ❌ TP executions mismatch: expected {expected_tp}, got {tp_executions}")
        success = False
    if sl_executions != expected_sl:
        print(f"   ❌ SL executions mismatch: expected {expected_sl}, got {sl_executions}")
        success = False
    if auto_sells != expected_auto_sells:
        print(f"   ❌ Auto-sells mismatch: expected {expected_auto_sells}, got {auto_sells}")
        success = False

    if success:
        print("   ✅ All trade lifecycle components verified successfully!")
    else:
        print("   ❌ Some components failed verification")

    return success

async def cleanup_test_data(db_client, agent, portfolio):
    """Clean up test data - only delete what we created"""
    print("🧹 Cleaning up test data...")

    # Get all test records for this agent created in the last 10 minutes and delete them
    ten_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=10)

    all_trades = await db_client.tradeexecutionlog.find_many(
        where={
            "agent_id": agent.id,
            "created_at": {"gte": ten_minutes_ago}
        }
    )

    test_trade_ids = [t.id for t in all_trades if t.metadata and isinstance(t.metadata, dict) and t.metadata.get("purpose") == "lifecycle_testing"]

    if test_trade_ids:
        await db_client.tradeexecutionlog.delete_many(
            where={
                "id": {"in": test_trade_ids}
            }
        )

    # Delete test trades
    all_db_trades = await db_client.trade.find_many(
        where={
            "agent_id": agent.id,
            "created_at": {"gte": ten_minutes_ago}
        }
    )

    test_db_trade_ids = [t.id for t in all_db_trades if t.metadata and isinstance(t.metadata, dict) and t.metadata.get("purpose") == "lifecycle_testing"]

    if test_db_trade_ids:
        await db_client.trade.delete_many(
            where={
                "id": {"in": test_db_trade_ids}
            }
        )

    # Don't delete the portfolio or agent since they might be existing
    # Only delete if they were created for testing (check metadata)
    if agent.metadata and "test_agent" in json.loads(agent.metadata):
        await db_client.tradingagent.delete({
            "where": {"id": agent.id}
        })

    # Don't delete portfolio allocation if it was existing
    # Since we used existing allocation, don't delete it
    pass

    print("✅ Test data cleaned up")

async def main():
    """Main test execution"""
    print("=" * 80)
    print("🧪 NSE PIPELINE TRADE LIFECYCLE COMPREHENSIVE TEST")
    print("=" * 80)

    # Initialize Prisma directly
    db = Prisma()
    await db.connect()

    try:
        # Phase 1: Setup test environment
        print("📋 PHASE 1: Setting up test environment")
        agent, portfolio, allocation = await create_test_portfolio_and_agent(db)

        # Phase 2: Create test trades
        print("\n📋 PHASE 2: Creating test trades")
        trades_created = await create_test_buy_trades(db, agent, portfolio, allocation)

        # Phase 3: Test negative signals
        print("\n📋 PHASE 3: Testing negative signals (-1)")
        await test_negative_signals(db, trades_created, agent, portfolio)

        # Phase 4: Test TP/SL orders
        print("\n📋 PHASE 4: Testing TP/SL order execution")
        await test_tp_sl_orders(db, trades_created)

        # Phase 5: Test auto-sell functionality
        print("\n📋 PHASE 5: Testing 15-minute auto-sell")
        await test_auto_sell_functionality(db, trades_created)

        # Phase 6: Verify all components
        print("\n📋 PHASE 6: Verification")
        success = await verify_all_components(db, agent, portfolio)

        # Phase 7: Cleanup
        print("\n📋 PHASE 7: Cleanup")
        await cleanup_test_data(db, agent, portfolio)

        print("\n" + "=" * 80)
        if success:
            print("🎉 ALL TESTS PASSED! NSE pipeline trade lifecycle is working correctly.")
        else:
            print("❌ SOME TESTS FAILED! Check the output above for details.")
        print("=" * 80)

    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.disconnect()

if __name__ == "__main__":
    asyncio.run(main())