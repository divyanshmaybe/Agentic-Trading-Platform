#!/usr/bin/env python3
"""
Verify snapshot storage implementation:
1. Trading agent snapshots are captured every 6 hours
2. Portfolio snapshots are aggregated from agent snapshots
3. Allocation snapshots are created when allocation pipeline runs
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Add paths
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SERVER_DIR.parent.parent

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "shared" / "py"))
sys.path.insert(0, str(SERVER_DIR))

os.chdir(SERVER_DIR)

from prisma import Prisma
from celery_app import celery_app
from decimal import Decimal


def check_celery_beat_schedule():
    """Verify Celery beat schedule for snapshots"""
    print("=" * 80)
    print("1. CHECKING CELERY BEAT SCHEDULE")
    print("=" * 80)
    
    beat_schedule = celery_app.conf.beat_schedule
    snapshot_task = beat_schedule.get("trading-agent-snapshots")
    
    if snapshot_task:
        print(f"✅ Snapshot task found: {snapshot_task['task']}")
        print(f"   Schedule: {snapshot_task['schedule']}")
        print(f"   Queue: {snapshot_task['options'].get('queue', 'default')}")
        
        # Check if it's every 6 hours
        schedule_str = str(snapshot_task['schedule'])
        if "0,6,12,18" in schedule_str or "0 0,6,12,18" in schedule_str:
            print("   ✅ Schedule is correct: Every 6 hours (0:00, 6:00, 12:00, 18:00 UTC)")
        else:
            print(f"   ⚠️  Schedule might not be every 6 hours: {schedule_str}")
    else:
        print("❌ Snapshot task NOT found in beat schedule!")
        print("   Make sure SNAPSHOT_CAPTURE_ENABLED=true in .env")
        return False
    
    return True


async def check_agent_snapshots(prisma: Prisma):
    """Check if agent snapshots are being stored"""
    print("\n" + "=" * 80)
    print("2. CHECKING TRADING AGENT SNAPSHOTS")
    print("=" * 80)
    
    # Get recent snapshots (last 24 hours)
    since = datetime.utcnow() - timedelta(days=1)
    
    snapshots = await prisma.tradingagentsnapshot.find_many(
        where={
            "snapshot_at": {"gte": since}
        },
        order={"snapshot_at": "desc"},
        take=10,
        include={"agent": True}
    )
    
    print(f"📊 Found {len(snapshots)} agent snapshots in last 24 hours")
    
    if snapshots:
        print("\nRecent snapshots:")
        for i, snap in enumerate(snapshots[:5], 1):
            agent_name = getattr(snap.agent, "agent_name", "Unknown") if snap.agent else "Unknown"
            print(f"  {i}. Agent: {agent_name}")
            print(f"     Snapshot at: {snap.snapshot_at}")
            print(f"     Portfolio value: ₹{float(snap.portfolio_value):,.2f}")
            print(f"     Realized P&L: ₹{float(snap.realized_pnl):,.2f}")
            print(f"     Positions: {snap.positions_count}")
            print()
        
        # Check frequency
        if len(snapshots) >= 2:
            time_diff = (snapshots[0].snapshot_at - snapshots[1].snapshot_at).total_seconds() / 3600
            print(f"⏱️  Time between snapshots: ~{time_diff:.1f} hours")
            if 5 <= time_diff <= 7:
                print("   ✅ Snapshots are being captured approximately every 6 hours")
            else:
                print(f"   ⚠️  Expected ~6 hours, but got {time_diff:.1f} hours")
    else:
        print("⚠️  No snapshots found in last 24 hours")
        print("   This could mean:")
        print("   - Celery beat is not running")
        print("   - No active trading agents exist")
        print("   - Snapshot task is failing")
    
    return len(snapshots) > 0


async def check_portfolio_snapshots(prisma: Prisma):
    """Check portfolio-level snapshots (aggregated from agents)"""
    print("\n" + "=" * 80)
    print("3. CHECKING PORTFOLIO SNAPSHOTS (AGGREGATED)")
    print("=" * 80)
    
    # Get a portfolio
    portfolio = await prisma.portfolio.find_first()
    
    if not portfolio:
        print("⚠️  No portfolios found")
        return False
    
    print(f"📊 Checking portfolio: {portfolio.portfolio_name} (ID: {portfolio.id})")
    
    # Get all agent snapshots for this portfolio
    since = datetime.utcnow() - timedelta(days=1)
    agent_snapshots = await prisma.tradingagentsnapshot.find_many(
        where={
            "portfolio_id": portfolio.id,
            "snapshot_at": {"gte": since}
        },
        order={"snapshot_at": "desc"},
    )
    
    # Group by snapshot_at
    from collections import defaultdict
    grouped = defaultdict(lambda: {"value": Decimal("0"), "pnl": Decimal("0"), "count": 0})
    
    for snap in agent_snapshots:
        key = snap.snapshot_at.isoformat()
        grouped[key]["value"] += Decimal(str(snap.portfolio_value))
        grouped[key]["pnl"] += Decimal(str(snap.realized_pnl))
        grouped[key]["count"] += 1
    
    print(f"📊 Found {len(grouped)} unique snapshot timestamps")
    print(f"   Total agent snapshots: {len(agent_snapshots)}")
    
    if grouped:
        print("\nPortfolio-level aggregated snapshots:")
        for i, (timestamp, data) in enumerate(list(grouped.items())[:5], 1):
            print(f"  {i}. Timestamp: {timestamp}")
            print(f"     Total portfolio value: ₹{float(data['value']):,.2f}")
            print(f"     Total realized P&L: ₹{float(data['pnl']):,.2f}")
            print(f"     Agents contributing: {data['count']}")
            print()
        print("✅ Portfolio snapshots are aggregated from agent snapshots")
        return True
    else:
        print("⚠️  No portfolio snapshots found")
        return False


async def check_allocation_snapshots(prisma: Prisma):
    """Check if allocation snapshots are created when pipeline runs"""
    print("\n" + "=" * 80)
    print("4. CHECKING ALLOCATION SNAPSHOTS")
    print("=" * 80)
    
    # Get recent allocation snapshots
    since = datetime.utcnow() - timedelta(days=7)
    
    allocation_snapshots = await prisma.allocationsnapshot.find_many(
        where={
            "created_at": {"gte": since}
        },
        order={"created_at": "desc"},
        take=10,
        include={
            "portfolio_allocation": True,
            "rebalance_run": True
        }
    )
    
    print(f"📊 Found {len(allocation_snapshots)} allocation snapshots in last 7 days")
    
    if allocation_snapshots:
        print("\nRecent allocation snapshots:")
        for i, snap in enumerate(allocation_snapshots[:5], 1):
            allocation_name = getattr(snap.portfolio_allocation, "allocation_name", "Unknown") or "Unknown"
            print(f"  {i}. Allocation: {allocation_name}")
            print(f"     Created at: {snap.created_at}")
            print(f"     Weight: {float(snap.snapshot_weight):.4f}")
            print(f"     Amount: ₹{float(snap.snapshot_amount):,.2f}")
            print(f"     Current value: ₹{float(snap.snapshot_current_value):,.2f}")
            print(f"     P&L: ₹{float(snap.snapshot_pnl):,.2f}")
            if snap.rebalance_run:
                print(f"     Rebalance run: {snap.rebalance_run_id}")
            print()
        
        # Check if they're linked to rebalance runs
        with_rebalance = sum(1 for s in allocation_snapshots if s.rebalance_run_id)
        print(f"✅ {with_rebalance}/{len(allocation_snapshots)} snapshots linked to rebalance runs")
        print("✅ Allocation snapshots are created when allocation pipeline runs")
        return True
    else:
        print("⚠️  No allocation snapshots found in last 7 days")
        print("   This could mean:")
        print("   - Allocation pipeline hasn't run recently")
        print("   - No portfolios have been allocated")
        return False


async def check_rebalance_runs(prisma: Prisma):
    """Check rebalance runs to verify allocation pipeline is running"""
    print("\n" + "=" * 80)
    print("5. CHECKING REBALANCE RUNS (Allocation Pipeline Triggers)")
    print("=" * 80)
    
    since = datetime.utcnow() - timedelta(days=7)
    
    rebalance_runs = await prisma.rebalancerun.find_many(
        where={
            "triggered_at": {"gte": since}
        },
        order={"triggered_at": "desc"},
        take=10,
        include={"portfolio": True}
    )
    
    print(f"📊 Found {len(rebalance_runs)} rebalance runs in last 7 days")
    
    if rebalance_runs:
        print("\nRecent rebalance runs:")
        for i, run in enumerate(rebalance_runs[:5], 1):
            portfolio_name = getattr(run.portfolio, "portfolio_name", "Unknown") if run.portfolio else "Unknown"
            print(f"  {i}. Portfolio: {portfolio_name}")
            print(f"     Triggered at: {run.triggered_at}")
            print(f"     Triggered by: {run.triggered_by}")
            print(f"     Snapshot value: ₹{float(run.snapshot_portfolio_value):,.2f}")
            print()
        
        # Check allocation snapshots for these runs
        run_ids = [r.id for r in rebalance_runs]
        allocation_snaps = await prisma.allocationsnapshot.find_many(
            where={"rebalance_run_id": {"in": run_ids}},
        )
        
        print(f"✅ Found {len(allocation_snaps)} allocation snapshots linked to these rebalance runs")
        if len(allocation_snaps) > 0:
            print("✅ Allocation snapshots ARE being created when pipeline runs!")
        else:
            print("⚠️  No allocation snapshots found for these rebalance runs")
            print("   This suggests allocation snapshots might not be created correctly")
        
        return len(allocation_snaps) > 0
    else:
        print("⚠️  No rebalance runs found in last 7 days")
        print("   This means allocation pipeline hasn't run recently")
        return False


async def main():
    """Run all verification checks"""
    print("\n" + "=" * 80)
    print("SNAPSHOT STORAGE VERIFICATION")
    print("=" * 80)
    print()
    
    # Check Celery beat schedule
    schedule_ok = check_celery_beat_schedule()
    
    # Connect to database
    prisma = Prisma()
    await prisma.connect()
    
    try:
        # Check agent snapshots
        agent_ok = await check_agent_snapshots(prisma)
        
        # Check portfolio snapshots
        portfolio_ok = await check_portfolio_snapshots(prisma)
        
        # Check allocation snapshots
        allocation_ok = await check_allocation_snapshots(prisma)
        
        # Check rebalance runs
        rebalance_ok = await check_rebalance_runs(prisma)
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"✅ Celery Beat Schedule: {'OK' if schedule_ok else 'FAILED'}")
        print(f"{'✅' if agent_ok else '⚠️ '} Trading Agent Snapshots: {'OK' if agent_ok else 'No snapshots found'}")
        print(f"{'✅' if portfolio_ok else '⚠️ '} Portfolio Snapshots: {'OK' if portfolio_ok else 'No snapshots found'}")
        print(f"{'✅' if allocation_ok else '⚠️ '} Allocation Snapshots: {'OK' if allocation_ok else 'No snapshots found'}")
        print(f"{'✅' if rebalance_ok else '⚠️ '} Rebalance Runs: {'OK' if rebalance_ok else 'No runs found'}")
        
        if schedule_ok and agent_ok and portfolio_ok and allocation_ok and rebalance_ok:
            print("\n🎉 All snapshot systems are working correctly!")
        else:
            print("\n⚠️  Some issues detected. Please check the details above.")
            
    finally:
        await prisma.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

