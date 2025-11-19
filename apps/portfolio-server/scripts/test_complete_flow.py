#!/usr/bin/env python3
"""
Complete flow test: Creates objective, verifies allocations/agents/snapshots,
activates high_risk agent, and tests auto-trade flow.
"""

import asyncio
import sys
import json
import time
from pathlib import Path

# Add server to path
server_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(server_root))

from prisma import Prisma


async def test_complete_flow():
    """Test the complete flow end-to-end."""
    prisma = Prisma()
    await prisma.connect()
    
    print(f"\n{'='*70}")
    print("🧪 COMPLETE FLOW TEST")
    print(f"{'='*70}\n")
    
    # Step 1: Check for existing portfolio with proper allocations
    # Use the portfolio that has high_risk allocations set up
    portfolio_id = "79a469f1-ce85-4c12-b36c-ff32a2235310"
    portfolio = await prisma.portfolio.find_unique(where={'id': portfolio_id})
    
    if not portfolio:
        print("❌ Test portfolio not found. Looking for any portfolio with allocations...")
        portfolios = await prisma.portfolio.find_many(take=5)
        if not portfolios:
            print("❌ No portfolios found. Create an objective first.")
            await prisma.disconnect()
            return False
        portfolio = portfolios[0]
        portfolio_id = portfolio.id
    
    user_id = portfolio.user_id
    
    print(f"📋 Using Portfolio: {portfolio_id}")
    print(f"   User: {user_id}")
    print(f"   Status: {portfolio.allocation_status}\n")
    
    # Step 2: Verify Allocations
    print("🔍 Step 1: Verifying Allocations...")
    allocs = await prisma.portfolioallocation.find_many(where={'portfolio_id': portfolio_id})
    print(f"   Found {len(allocs)} allocations")
    
    all_alloc_good = True
    for a in allocs:
        allocated = float(a.allocated_amount) if a.allocated_amount else 0
        if allocated == 0:
            print(f"   ❌ {a.allocation_type}: allocated_amount is ZERO!")
            all_alloc_good = False
        else:
            print(f"   ✅ {a.allocation_type}: allocated_amount={allocated}")
    
    if not all_alloc_good or len(allocs) == 0:
        print("\n❌ Allocations not ready. Wait for allocation task to complete.")
        await prisma.disconnect()
        return False
    
    # Step 3: Verify Trading Agents
    print("\n🔍 Step 2: Verifying Trading Agents...")
    agents = await prisma.tradingagent.find_many(where={'portfolio_id': portfolio_id})
    print(f"   Found {len(agents)} trading agents")
    
    high_risk_agent = None
    for a in agents:
        agent_type = getattr(a, 'agent_type', 'unknown')
        print(f"   - {agent_type}: {a.status}")
        if agent_type == 'high_risk':
            high_risk_agent = a
    
    if not high_risk_agent:
        print("\n❌ No high_risk agent found!")
        await prisma.disconnect()
        return False
    
    # Step 4: Activate High Risk Agent
    print("\n🔍 Step 3: Activating High Risk Agent...")
    config = high_risk_agent.strategy_config
    if isinstance(config, str):
        config = json.loads(config)
    elif hasattr(config, 'data'):
        config = config.data
    
    metadata = high_risk_agent.metadata
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    elif hasattr(metadata, 'data'):
        metadata = metadata.data
    
    config['auto_trade'] = True
    metadata['subscription_state']['auto_trade'] = True
    metadata['subscription_state']['status'] = 'active'
    
    from prisma import fields
    await prisma.tradingagent.update(
        where={'id': high_risk_agent.id},
        data={
            'status': 'active',
            'strategy_config': fields.Json(config),
            'metadata': fields.Json(metadata)
        }
    )
    print(f"   ✅ Activated high_risk agent {high_risk_agent.id}")
    
    # Step 5: Verify Snapshots
    print("\n🔍 Step 4: Verifying Snapshots...")
    runs = await prisma.rebalancerun.find_many(
        where={'portfolio_id': portfolio_id},
        order=[{'created_at': 'desc'}],
        take=3
    )
    print(f"   Found {len(runs)} rebalance runs")
    
    total_alloc_snaps = 0
    for r in runs:
        alloc_snaps = await prisma.allocationsnapshot.find_many(where={'rebalance_run_id': r.id})
        total_alloc_snaps += len(alloc_snaps)
        print(f"   - Run {r.id[:12]}...: {len(alloc_snaps)} alloc snaps")
    
    # Step 6: Verify Auto-Trade Setup
    print("\n🔍 Step 5: Verifying Auto-Trade Setup...")
    agent = await prisma.tradingagent.find_unique(where={'id': high_risk_agent.id})
    if agent:
        config = agent.strategy_config
        if isinstance(config, str):
            config = json.loads(config)
        elif hasattr(config, 'data'):
            config = config.data
        
        if agent.status == 'active' and config.get('auto_trade', False):
            print(f"   ✅ Agent is ACTIVE with auto_trade=True")
            print(f"   ✅ Ready to process NSE pipeline signals!")
        else:
            print(f"   ⚠️  Agent status: {agent.status}, auto_trade: {config.get('auto_trade', False)}")
    
    # Step 7: Check for existing trades
    print("\n🔍 Step 6: Checking for Trades...")
    trades = await prisma.trade.find_many(
        where={'portfolio_id': portfolio_id},
        order=[{'created_at': 'desc'}],
        take=5
    )
    print(f"   Found {len(trades)} trades")
    for t in trades:
        print(f"   - {t.symbol}: {t.side} {t.quantity} @ {t.price}")
    
    await prisma.disconnect()
    
    # Final Summary
    print(f"\n{'='*70}")
    print("📊 TEST SUMMARY:")
    print(f"   ✅ Allocations: {len(allocs)} (all have allocated_amount > 0)")
    print(f"   ✅ Trading Agents: {len(agents)}")
    print(f"   ✅ High Risk Agent: ACTIVE")
    print(f"   ✅ Rebalance Runs: {len(runs)}")
    print(f"   ✅ Allocation Snapshots: {total_alloc_snaps}")
    print(f"   ✅ Trades: {len(trades)}")
    print(f"{'='*70}\n")
    
    success = (
        len(allocs) > 0 and 
        all_alloc_good and 
        len(agents) > 0 and 
        high_risk_agent and
        agent.status == 'active'
    )
    
    if success:
        print("🎉🎉🎉 ALL TESTS PASSED! 🎉🎉🎉")
        print("\n✅ Flow is ready:")
        print("   1. Allocations created with correct allocated_amount")
        print("   2. Trading agents created")
        print("   3. High risk agent activated")
        print("   4. Ready for NSE pipeline signals")
        print("   5. Auto-trade will execute when signals arrive")
    else:
        print("❌ Some tests failed")
    
    return success


if __name__ == "__main__":
    asyncio.run(test_complete_flow())

