#!/usr/bin/env python3
"""
Reset and Audit Script - Comprehensive trading system audit tool.

This script:
1. Resets all positions, trades, and related data
2. Restores available cash for testing
3. Provides functions to verify system state

Usage:
    python scripts/reset_and_audit.py --reset      # Reset all trading data
    python scripts/reset_and_audit.py --status     # Show current status
    python scripts/reset_and_audit.py --portfolio  # Show portfolio details
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from decimal import Decimal

# Add parent and shared to path
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
shared_py_dir = os.path.abspath(os.path.join(parent_dir, "../../shared/py"))
sys.path.insert(0, parent_dir)
sys.path.insert(0, shared_py_dir)

# Load .env file from portfolio-server directory
from dotenv import load_dotenv
env_path = os.path.join(parent_dir, ".env")
load_dotenv(env_path)
print(f"📁 Loaded .env from: {env_path}")
print(f"📊 DATABASE_URL: {os.getenv('DATABASE_URL', 'NOT SET')[:50]}...")

# Use db_context for proper connection handling (auto-closes connections)
from db_context import get_db_connection


async def reset_all_trading_data():
    """
    Reset all positions, trades, trade execution logs, and restore cash.
    
    CRITICAL: This will DELETE all trading data and reset allocations.
    """
    print("\n" + "="*60)
    print("🔄 RESETTING ALL TRADING DATA")
    print("="*60)
    
    async with get_db_connection() as client:
        try:
            # Step 1: Get all portfolios and allocations for cash restoration
            portfolios = await client.portfolio.find_many(
                include={"allocations": True, "positions": True, "trades": True}
            )
            
            print(f"\n📊 Found {len(portfolios)} portfolio(s)")
            
            for portfolio in portfolios:
                portfolio_id = portfolio.id
                initial_investment = float(portfolio.initial_investment or 0)
                
                print(f"\n--- Portfolio: {portfolio.portfolio_name or portfolio_id[:8]} ---")
                print(f"  Initial Investment: ₹{initial_investment:,.2f}")
                print(f"  Current Cash: ₹{float(portfolio.available_cash or 0):,.2f}")
                print(f"  Positions: {len(portfolio.positions or [])}")
                print(f"  Trades: {len(portfolio.trades or [])}")
                
                # Count allocations
                if portfolio.allocations:
                    for alloc in portfolio.allocations:
                        print(f"  Allocation [{alloc.allocation_type}]: cash=₹{float(alloc.available_cash or 0):,.2f}")
            
            # Step 2: Delete trade execution logs first (foreign key dependency)
            deleted_logs = await client.tradeexecutionlog.delete_many(where={})
            print(f"\n✅ Deleted {deleted_logs} trade execution log(s)")
            
            # Step 3: Delete all trades
            deleted_trades = await client.trade.delete_many(where={})
            print(f"✅ Deleted {deleted_trades} trade(s)")
            
            # Step 4: Delete all positions
            deleted_positions = await client.position.delete_many(where={})
            print(f"✅ Deleted {deleted_positions} position(s)")
            
            # Step 5: Reset portfolio and allocation cash/PnL
            for portfolio in portfolios:
                portfolio_id = portfolio.id
                initial_investment = float(portfolio.initial_investment or 0)
                
                # Reset portfolio-level fields
                await client.portfolio.update(
                    where={"id": portfolio_id},
                    data={
                        "available_cash": initial_investment,
                        "total_realized_pnl": 0,
                        "allocation_trades": json.dumps([]),
                    }
                )
                print(f"✅ Reset portfolio {portfolio_id[:8]}: available_cash=₹{initial_investment:,.2f}")
                
                # Reset allocations
                if portfolio.allocations:
                    for alloc in portfolio.allocations:
                        alloc_initial = float(alloc.allocated_amount or 0)
                        await client.portfolioallocation.update(
                            where={"id": alloc.id},
                            data={
                                "available_cash": alloc_initial,
                                "realized_pnl": 0,
                                "pnl": 0,
                                "pnl_percentage": 0,
                            }
                        )
                        print(f"  ✅ Reset allocation [{alloc.allocation_type}]: available_cash=₹{alloc_initial:,.2f}")
            
            # Step 6: Reset trading agents
            agents = await client.tradingagent.find_many()
            for agent in agents:
                await client.tradingagent.update(
                    where={"id": agent.id},
                    data={
                        "realized_pnl": 0,
                        "last_executed_at": None,
                        "error_count": 0,
                        "last_error_message": None,
                        "metadata": json.dumps({}),
                    }
                )
            print(f"✅ Reset {len(agents)} trading agent(s)")
            
            print("\n" + "="*60)
            print("✅ ALL TRADING DATA RESET SUCCESSFULLY")
            print("="*60)
            
        except Exception as e:
            print(f"\n❌ Error during reset: {e}")
            import traceback
            traceback.print_exc()


async def show_status():
    """Show current trading system status."""
    print("\n" + "="*60)
    print("📊 TRADING SYSTEM STATUS")
    print("="*60)
    
    async with get_db_connection() as client:
        try:
            # Portfolios
            portfolios = await client.portfolio.find_many(include={"allocations": True})
            print(f"\n📦 Portfolios: {len(portfolios)}")
            
            # Positions
            positions = await client.position.find_many()
            open_positions = [p for p in positions if p.status == "open"]
            closed_positions = [p for p in positions if p.status == "closed"]
            print(f"\n📈 Positions: {len(positions)} total ({len(open_positions)} open, {len(closed_positions)} closed)")
            
            for pos in open_positions:
                print(f"  - {pos.symbol}: {pos.quantity} units @ ₹{float(pos.average_buy_price or 0):.2f} ({pos.position_type})")
            
            # Trades
            trades = await client.trade.find_many(order={"created_at": "desc"}, take=20)
            trade_statuses = {}
            for t in trades:
                status = t.status
                trade_statuses[status] = trade_statuses.get(status, 0) + 1
            
            print(f"\n💰 Recent Trades: {len(trades)}")
            for status, count in trade_statuses.items():
                print(f"  - {status}: {count}")
            
            # Trade Execution Logs
            logs = await client.tradeexecutionlog.find_many()
            log_statuses = {}
            for log in logs:
                status = log.status
                log_statuses[status] = log_statuses.get(status, 0) + 1
            
            print(f"\n📋 Trade Execution Logs: {len(logs)}")
            for status, count in log_statuses.items():
                print(f"  - {status}: {count}")
            
            # Trading Agents
            agents = await client.tradingagent.find_many(include={"allocation": True})
            print(f"\n🤖 Trading Agents: {len(agents)}")
            for agent in agents:
                alloc_cash = float(agent.allocation.available_cash or 0) if agent.allocation else 0
                alloc_amount = float(agent.allocation.allocated_amount or 0) if agent.allocation else 0
                print(f"  - {agent.agent_name} ({agent.agent_type}): realized_pnl=₹{float(agent.realized_pnl or 0):,.2f}, alloc_cash=₹{alloc_cash:,.2f}/{alloc_amount:,.2f}")
            
            print("\n" + "="*60)
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


async def show_portfolio_details():
    """Show detailed portfolio information."""
    print("\n" + "="*60)
    print("📊 PORTFOLIO DETAILS")
    print("="*60)
    
    async with get_db_connection() as client:
        try:
            portfolios = await client.portfolio.find_many(
                include={
                    "allocations": True,
                    "positions": True,
                    "trades": True,
                    "agents": True,
                }
            )
            
            for portfolio in portfolios:
                print(f"\n{'='*40}")
                print(f"Portfolio: {portfolio.portfolio_name or 'Unnamed'}")
                print(f"{'='*40}")
                print(f"  ID: {portfolio.id}")
                print(f"  Initial Investment: ₹{float(portfolio.initial_investment or 0):,.2f}")
                print(f"  Investment Amount: ₹{float(portfolio.investment_amount or 0):,.2f}")
                print(f"  Available Cash: ₹{float(portfolio.available_cash or 0):,.2f}")
                print(f"  Total Realized PnL: ₹{float(portfolio.total_realized_pnl or 0):,.2f}")
                print(f"  Status: {portfolio.status}")
                
                # Allocations
                print(f"\n  📦 Allocations ({len(portfolio.allocations or [])}):")
                for alloc in portfolio.allocations or []:
                    print(f"    - {alloc.allocation_type}")
                    print(f"      Target Weight: {float(alloc.target_weight or 0)*100:.1f}%")
                    print(f"      Allocated Amount: ₹{float(alloc.allocated_amount or 0):,.2f}")
                    print(f"      Available Cash: ₹{float(alloc.available_cash or 0):,.2f}")
                    print(f"      Realized PnL: ₹{float(alloc.realized_pnl or 0):,.2f}")
                
                # Agents
                print(f"\n  🤖 Trading Agents ({len(portfolio.agents or [])}):")
                for agent in portfolio.agents or []:
                    print(f"    - {agent.agent_name} ({agent.agent_type})")
                    print(f"      Status: {agent.status}")
                    print(f"      Realized PnL: ₹{float(agent.realized_pnl or 0):,.2f}")
                    if agent.last_executed_at:
                        print(f"      Last Executed: {agent.last_executed_at}")
                
                # Positions
                open_pos = [p for p in (portfolio.positions or []) if p.status == "open"]
                print(f"\n  📈 Open Positions ({len(open_pos)}):")
                for pos in open_pos:
                    print(f"    - {pos.symbol}: {pos.quantity} @ ₹{float(pos.average_buy_price or 0):.2f}")
                    print(f"      Type: {pos.position_type}, Realized PnL: ₹{float(pos.realized_pnl or 0):.2f}")
                
                # Recent Trades
                print(f"\n  💰 Recent Trades ({len(portfolio.trades or [])}):")
                for trade in portfolio.trades or []:
                    side = trade.side
                    symbol = trade.symbol
                    qty = trade.quantity
                    price = float(trade.executed_price or trade.price or 0)
                    status = trade.status
                    auto_sell_at = getattr(trade, "auto_sell_at", None)
                    auto_cover_at = getattr(trade, "auto_cover_at", None)
                    
                    print(f"    - {side} {symbol} x{qty} @ ₹{price:.2f} [{status}]")
                    if auto_sell_at:
                        print(f"      Auto-sell at: {auto_sell_at}")
                    if auto_cover_at:
                        print(f"      Auto-cover at: {auto_cover_at}")
            
            print("\n" + "="*60)
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()


async def verify_db_relations():
    """Verify database relations are properly set up."""
    print("\n" + "="*60)
    print("🔍 DATABASE RELATIONS VERIFICATION")
    print("="*60)
    
    issues = []
    
    async with get_db_connection() as client:
        try:
            # Check positions have proper relations
            positions = await client.position.find_many(include={"portfolio": True, "agent": True, "allocation": True})
            print(f"\n📈 Checking {len(positions)} positions...")
            
            for pos in positions:
                if not pos.portfolio:
                    issues.append(f"Position {pos.id[:8]} missing portfolio relation")
                if not pos.agent:
                    issues.append(f"Position {pos.id[:8]} missing agent relation")
                if not pos.allocation:
                    issues.append(f"Position {pos.id[:8]} missing allocation relation")
            
            # Check trades have proper relations
            trades = await client.trade.find_many(include={"portfolio": True, "agent": True})
            print(f"💰 Checking {len(trades)} trades...")
            
            for trade in trades:
                if not trade.portfolio:
                    issues.append(f"Trade {trade.id[:8]} missing portfolio relation")
            
            # Check agents have allocation
            agents = await client.tradingagent.find_many(include={"allocation": True})
            print(f"🤖 Checking {len(agents)} agents...")
            
            for agent in agents:
                if not agent.allocation:
                    issues.append(f"Agent {agent.id[:8]} ({agent.agent_name}) missing allocation relation")
            
            # Check allocations are linked
            allocations = await client.portfolioallocation.find_many(include={"portfolio": True})
            print(f"📦 Checking {len(allocations)} allocations...")
            
            for alloc in allocations:
                if not alloc.portfolio:
                    issues.append(f"Allocation {alloc.id[:8]} missing portfolio relation")
            
            # Report issues
            if issues:
                print(f"\n⚠️ Found {len(issues)} issues:")
                for issue in issues:
                    print(f"  - {issue}")
            else:
                print("\n✅ All database relations are properly set up!")
            
            print("\n" + "="*60)
            return len(issues) == 0
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset and audit trading system")
    parser.add_argument("--reset", action="store_true", help="Reset all trading data")
    parser.add_argument("--status", action="store_true", help="Show current system status")
    parser.add_argument("--portfolio", action="store_true", help="Show portfolio details")
    parser.add_argument("--verify", action="store_true", help="Verify database relations")
    
    args = parser.parse_args()
    
    if args.reset:
        confirm = input("⚠️ This will DELETE all positions, trades, and reset cash. Continue? [y/N]: ")
        if confirm.lower() == "y":
            asyncio.run(reset_all_trading_data())
        else:
            print("Cancelled.")
    elif args.status:
        asyncio.run(show_status())
    elif args.portfolio:
        asyncio.run(show_portfolio_details())
    elif args.verify:
        asyncio.run(verify_db_relations())
    else:
        asyncio.run(show_status())
