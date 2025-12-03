"""
Database State Verification Script

Quick script to check database state using Prisma directly.
Useful for debugging and verifying pipeline state.

Usage:
    python scripts/verify_db_state.py --symbol RELIANCE
    python scripts/verify_db_state.py --trade-id <trade_id>
    python scripts/verify_db_state.py --all
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from decimal import Decimal

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from prisma import Prisma


async def verify_db_state(symbol: str = None, trade_id: str = None, show_all: bool = False):
    """Verify database state."""
    prisma = Prisma()
    await prisma.connect()
    
    client = prisma
    
    print("=" * 70)
    print("DATABASE STATE VERIFICATION")
    print("=" * 70)
    
    if trade_id:
        # Show specific trade details
        trade = await client.trade.find_unique(
            where={"id": trade_id},
            include={
                "portfolio": True,
                "agent": {"include": {"allocation": True}},
                "executions": True
            }
        )
        
        if trade:
            print(f"\n📊 TRADE: {trade_id}")
            print(f"  Symbol: {trade.symbol}")
            print(f"  Side: {trade.side}")
            print(f"  Quantity: {trade.quantity}")
            print(f"  Price: ₹{trade.price}")
            print(f"  Status: {trade.status}")
            print(f"  Executed Price: ₹{trade.executed_price}")
            print(f"  Realized P&L: ₹{trade.realized_pnl}")
            print(f"  Auto Sell At: {trade.auto_sell_at}")
            print(f"  TP Price: ₹{trade.take_profit_price}")
            print(f"  SL Price: ₹{trade.stop_loss_price}")
            print(f"  Source: {trade.source}")
            print(f"  Portfolio: {trade.portfolio_id[:8]}")
            print(f"  Agent: {trade.agent_id[:8] if trade.agent_id else 'None'}")
        else:
            print(f"❌ Trade {trade_id} not found")
    
    elif symbol:
        # Show all data for symbol
        print(f"\n📊 SYMBOL: {symbol.upper()}")
        
        # Trades
        trades = await client.trade.find_many(
            where={"symbol": {"equals": symbol, "mode": "insensitive"}},
            order={"created_at": "desc"},
            take=10,
            include={"portfolio": True, "agent": True}
        )
        
        print(f"\n  TRADES ({len(trades)}):")
        for trade in trades:
            print(
                f"    {trade.id[:8]}: {trade.side} {trade.quantity} @ ₹{trade.price} | "
                f"Status: {trade.status} | P&L: ₹{trade.realized_pnl or 0} | "
                f"Auto-sell: {trade.auto_sell_at}"
            )
        
        # Positions
        positions = await client.position.find_many(
            where={"symbol": {"equals": symbol, "mode": "insensitive"}}
        )
        
        print(f"\n  POSITIONS ({len(positions)}):")
        for pos in positions:
            print(
                f"    {pos.id[:8]}: Qty: {pos.quantity} | Avg Buy: ₹{pos.average_buy_price} | "
                f"Status: {pos.status} | P&L: ₹{pos.realized_pnl}"
            )
        
        # TP/SL Orders
        tp_sl_orders = await client.trade.find_many(
            where={
                "symbol": {"equals": symbol, "mode": "insensitive"},
                "source": "nse_pipeline_tp_sl"
            },
            order={"created_at": "desc"},
            take=10
        )
        
        print(f"\n  TP/SL ORDERS ({len(tp_sl_orders)}):")
        for order in tp_sl_orders:
            order_type = "TP" if "take_profit" in str(order.metadata).lower() else "SL"
            print(
                f"    {order.id[:8]}: {order_type} {order.side} {order.quantity} @ ₹{order.price} | "
                f"Status: {order.status}"
            )
    
    elif show_all:
        # Show overall statistics
        trades_count = await client.trade.count()
        positions_count = await client.position.count()
        portfolios_count = await client.portfolio.count()
        agents_count = await client.tradingagent.count()
        
        print(f"\n📊 OVERALL STATISTICS:")
        print(f"  Total Trades: {trades_count}")
        print(f"  Total Positions: {positions_count}")
        print(f"  Total Portfolios: {portfolios_count}")
        print(f"  Total Agents: {agents_count}")
        
        # Recent trades
        recent_trades = await client.trade.find_many(
            order={"created_at": "desc"},
            take=5,
            include={"portfolio": True}
        )
        
        print(f"\n  RECENT TRADES:")
        for trade in recent_trades:
            print(
                f"    {trade.id[:8]}: {trade.symbol} {trade.side} {trade.quantity} @ ₹{trade.price} | "
                f"Status: {trade.status}"
            )
    
    await prisma.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify database state")
    parser.add_argument("--symbol", type=str, help="Stock symbol to check")
    parser.add_argument("--trade-id", type=str, help="Specific trade ID to check")
    parser.add_argument("--all", action="store_true", help="Show all statistics")
    
    args = parser.parse_args()
    
    if not args.symbol and not args.trade_id and not args.all:
        parser.print_help()
        sys.exit(1)
    
    asyncio.run(verify_db_state(
        symbol=args.symbol,
        trade_id=args.trade_id,
        show_all=args.all
    ))

