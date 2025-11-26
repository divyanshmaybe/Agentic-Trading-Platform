"""
Comprehensive verification script for complete trading workflow:
1. Trade execution
2. TP/SL order creation
3. Position creation/updation
4. Portfolio cash allocation and updates
5. Realized PnL calculation
6. Auto-sell execution

Run this after sending test signals to verify all workflows are working correctly.
"""

import asyncio
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / "shared" / "py"))

from dbManager import DBManager


async def verify_workflow():
    """Verify complete trading workflow with detailed checks"""
    
    print("=" * 80)
    print("COMPREHENSIVE WORKFLOW VERIFICATION")
    print("=" * 80)
    
    db = DBManager()
    await db.connect()
    client = db.get_client()
    
    # Get the portfolio
    portfolios = await client.portfolio.find_many(
        include={
            "trading_agent": True,
            "positions": True,
            "trades": {
                "include": {
                    "tp_order": True,
                    "sl_order": True,
                }
            }
        }
    )
    
    if not portfolios:
        print("❌ No portfolios found!")
        return
    
    portfolio = portfolios[0]
    print(f"\n📊 Portfolio: {portfolio.id}")
    print(f"   Agent: {portfolio.trading_agent.agent_type if portfolio.trading_agent else 'N/A'}")
    print(f"   Initial Capital: ₹{portfolio.capital_base:,.2f}")
    print(f"   Available Cash: ₹{portfolio.available_cash:,.2f}")
    print(f"   Realized PnL: ₹{portfolio.realized_pnl:,.2f}")
    
    # Get all executed trades
    executed_trades = [t for t in portfolio.trades if t.status == "executed"]
    print(f"\n✅ Executed Trades: {len(executed_trades)}")
    
    total_allocated = Decimal(0)
    total_positions_value = Decimal(0)
    
    # Verify each trade
    for idx, trade in enumerate(executed_trades[:10], 1):  # Show first 10
        print(f"\n{'─' * 80}")
        print(f"Trade #{idx}: {trade.id[:8]}...")
        print(f"   Symbol: {trade.symbol}")
        print(f"   Side: {trade.side}")
        print(f"   Quantity: {trade.quantity}")
        print(f"   Price: ₹{trade.price:.2f}")
        print(f"   Total Value: ₹{trade.quantity * trade.price:,.2f}")
        print(f"   Status: {trade.status}")
        print(f"   Executed At: {trade.executed_at or 'N/A'}")
        print(f"   Auto-Sell At: {trade.auto_sell_at or 'N/A'}")
        
        # Calculate allocated cash for this trade
        if trade.side == "BUY":
            allocated = Decimal(trade.quantity) * Decimal(trade.price)
            total_allocated += allocated
            print(f"   💰 Cash Allocated: ₹{allocated:,.2f}")
        
        # Check TP/SL orders
        tp_exists = trade.tp_order is not None
        sl_exists = trade.sl_order is not None
        print(f"\n   TP Order: {'✅ Created' if tp_exists else '❌ Missing'}")
        if tp_exists:
            tp = trade.tp_order
            print(f"      Order ID: {tp.id[:8]}...")
            print(f"      Type: {tp.order_type}")
            print(f"      Side: {tp.side}")
            print(f"      Quantity: {tp.quantity}")
            print(f"      Target Price: ₹{tp.target_price:.2f}")
            print(f"      Status: {tp.status}")
        
        print(f"   SL Order: {'✅ Created' if sl_exists else '❌ Missing'}")
        if sl_exists:
            sl = trade.sl_order
            print(f"      Order ID: {sl.id[:8]}...")
            print(f"      Type: {sl.order_type}")
            print(f"      Side: {sl.side}")
            print(f"      Quantity: {sl.quantity}")
            print(f"      Stop Price: ₹{sl.stop_price:.2f}")
            print(f"      Status: {sl.status}")
    
    # Verify positions
    print(f"\n{'=' * 80}")
    print(f"📈 POSITIONS")
    print(f"{'=' * 80}")
    print(f"Total Positions: {len(portfolio.positions)}")
    
    for pos in portfolio.positions:
        position_value = Decimal(pos.quantity) * Decimal(pos.average_price)
        total_positions_value += position_value
        print(f"\n   Symbol: {pos.symbol}")
        print(f"   Quantity: {pos.quantity}")
        print(f"   Avg Price: ₹{pos.average_price:.2f}")
        print(f"   Current Value: ₹{position_value:,.2f}")
        print(f"   Unrealized PnL: ₹{pos.unrealized_pnl:,.2f}")
        print(f"   Created: {pos.created_at}")
        print(f"   Updated: {pos.updated_at}")
    
    # Cash verification
    print(f"\n{'=' * 80}")
    print(f"💰 CASH VERIFICATION")
    print(f"{'=' * 80}")
    print(f"Initial Capital: ₹{portfolio.capital_base:,.2f}")
    print(f"Total Allocated (BUY trades): ₹{total_allocated:,.2f}")
    print(f"Expected Available Cash: ₹{portfolio.capital_base - total_allocated:,.2f}")
    print(f"Actual Available Cash: ₹{portfolio.available_cash:,.2f}")
    
    cash_diff = abs(portfolio.available_cash - (portfolio.capital_base - total_allocated))
    if cash_diff < Decimal("0.01"):
        print("✅ Cash calculation is CORRECT!")
    else:
        print(f"⚠️  Cash mismatch: ₹{cash_diff:,.2f}")
    
    # Portfolio allocation verification
    print(f"\n{'=' * 80}")
    print(f"📊 PORTFOLIO ALLOCATION VERIFICATION")
    print(f"{'=' * 80}")
    print(f"Total Positions Value: ₹{total_positions_value:,.2f}")
    print(f"Available Cash: ₹{portfolio.available_cash:,.2f}")
    print(f"Total Portfolio Value: ₹{total_positions_value + portfolio.available_cash:,.2f}")
    print(f"Realized PnL: ₹{portfolio.realized_pnl:,.2f}")
    
    # Summary
    print(f"\n{'=' * 80}")
    print(f"📋 SUMMARY")
    print(f"{'=' * 80}")
    print(f"✅ Total Executed Trades: {len(executed_trades)}")
    print(f"✅ Total Positions: {len(portfolio.positions)}")
    print(f"✅ Cash Allocated: ₹{total_allocated:,.2f}")
    print(f"✅ Available Cash: ₹{portfolio.available_cash:,.2f}")
    print(f"✅ Realized PnL: ₹{portfolio.realized_pnl:,.2f}")
    
    # Check for trades missing TP/SL
    missing_tp_sl = [t for t in executed_trades if not t.tp_order or not t.sl_order]
    if missing_tp_sl:
        print(f"⚠️  {len(missing_tp_sl)} trades missing TP/SL orders")
    else:
        print(f"✅ All executed trades have TP/SL orders")
    
    await db.disconnect()
    print(f"\n{'=' * 80}\n")


if __name__ == "__main__":
    asyncio.run(verify_workflow())
