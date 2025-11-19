#!/usr/bin/env python3
"""
Comprehensive verification script for the complete portfolio allocation and trading flow.
Run this after creating an objective to verify everything is working.
"""

import asyncio
import sys
from pathlib import Path

# Add server to path
server_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(server_root))

from prisma import Prisma


async def verify_complete_flow(portfolio_id: str, user_id: str):
    """Verify the complete flow: allocations, agents, snapshots, and trading."""
    prisma = Prisma()
    await prisma.connect()
    
    print(f"\n{'='*70}")
    print("🔍 COMPREHENSIVE FLOW VERIFICATION")
    print(f"{'='*70}\n")
    
    # 1. Verify Portfolio
    portfolio = await prisma.portfolio.find_unique(where={'id': portfolio_id})
    if not portfolio:
        print(f"❌ Portfolio {portfolio_id} not found!")
        await prisma.disconnect()
        return False
    
    print(f"✅ Portfolio found:")
    print(f"   investment_amount: {portfolio.investment_amount}")
    print(f"   initial_investment: {portfolio.initial_investment}")
    print(f"   current_value: {portfolio.current_value}")
    
    # 2. Verify Allocations
    allocs = await prisma.portfolioallocation.find_many(where={'portfolio_id': portfolio_id})
    print(f"\n📊 Allocations: {len(allocs)}")
    all_alloc_good = True
    for a in allocs:
        allocated = float(a.allocated_amount) if a.allocated_amount else 0
        print(f"   - {a.allocation_type}: allocated_amount={allocated}, weight={a.target_weight}")
        if allocated == 0:
            print(f"      ❌ ERROR: allocated_amount is ZERO!")
            all_alloc_good = False
        else:
            print(f"      ✅ allocated_amount is correct")
    
    if not all_alloc_good:
        print("\n❌ Allocations have zero allocated_amount!")
        await prisma.disconnect()
        return False
    
    # 3. Verify Trading Agents
    agents = await prisma.tradingagent.find_many(where={'portfolio_id': portfolio_id})
    print(f"\n🤖 Trading Agents: {len(agents)}")
    high_risk_agent = None
    for a in agents:
        agent_type = getattr(a, 'agent_type', 'unknown')
        status = a.status
        print(f"   - {agent_type}: {status}")
        if agent_type == 'high_risk':
            high_risk_agent = a
    
    if len(agents) == 0:
        print("\n❌ No trading agents created!")
        await prisma.disconnect()
        return False
    
    # 4. Verify Rebalance Runs and Snapshots
    runs = await prisma.rebalancerun.find_many(
        where={'portfolio_id': portfolio_id},
        order=[{'created_at': 'desc'}],
        take=5
    )
    print(f"\n🔄 Rebalance Runs: {len(runs)}")
    total_alloc_snaps = 0
    for r in runs:
        alloc_snaps = await prisma.allocationsnapshot.find_many(where={'rebalance_run_id': r.id})
        total_alloc_snaps += len(alloc_snaps)
        print(f"   - Run {r.id[:12]}...: {len(alloc_snaps)} alloc snaps")
    
    # 5. Check High Risk Agent Status
    print(f"\n🎯 High Risk Agent Status:")
    if high_risk_agent:
        print(f"   Agent ID: {high_risk_agent.id}")
        print(f"   Status: {high_risk_agent.status}")
        print(f"   Allocation ID: {high_risk_agent.portfolio_allocation_id}")
        
        # Check strategy config
        import json
        config = high_risk_agent.strategy_config
        if isinstance(config, str):
            config = json.loads(config)
        auto_trade = config.get("auto_trade", False) if isinstance(config, dict) else False
        print(f"   Auto Trade: {auto_trade}")
        
        if high_risk_agent.status == 'active' and auto_trade:
            print(f"   ✅ High Risk Agent is ACTIVE and ready for auto-trading!")
        else:
            print(f"   ⚠️  High Risk Agent needs activation (status={high_risk_agent.status}, auto_trade={auto_trade})")
    else:
        print(f"   ❌ No high_risk agent found!")
    
    await prisma.disconnect()
    
    # Final Summary
    print(f"\n{'='*70}")
    print("📊 VERIFICATION SUMMARY:")
    print(f"   ✅ Allocations: {len(allocs)} (all have allocated_amount > 0)")
    print(f"   ✅ Trading Agents: {len(agents)}")
    print(f"   ✅ Rebalance Runs: {len(runs)}")
    print(f"   ✅ Allocation Snapshots: {total_alloc_snaps}")
    print(f"{'='*70}\n")
    
    success = (
        len(allocs) > 0 and 
        all_alloc_good and 
        len(agents) > 0 and 
        len(runs) > 0 and 
        total_alloc_snaps > 0
    )
    
    if success:
        print("🎉🎉🎉 ALL CHECKS PASSED! 🎉🎉🎉")
    else:
        print("❌ Some checks failed")
    
    return success


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python verify_complete_flow.py <portfolio_id> <user_id>")
        sys.exit(1)
    
    portfolio_id = sys.argv[1]
    user_id = sys.argv[2]
    
    asyncio.run(verify_complete_flow(portfolio_id, user_id))

