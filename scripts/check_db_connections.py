#!/usr/bin/env python3
"""
Check and manage PostgreSQL connections.

Usage:
    python scripts/check_db_connections.py          # Show connections
    python scripts/check_db_connections.py --kill   # Kill idle connections
"""

import os
import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import asyncio
from prisma import Prisma


async def show_connections(db_url: str):
    """Show current database connections."""
    client = Prisma(datasource={"url": db_url})
    
    try:
        await client.connect()
        
        # Query to show all connections
        query = """
        SELECT 
            pid,
            usename,
            application_name,
            client_addr,
            state,
            state_change,
            EXTRACT(EPOCH FROM (NOW() - state_change))::int as idle_seconds,
            query
        FROM pg_stat_activity
        WHERE datname = current_database()
        ORDER BY state_change DESC;
        """
        
        result = await client.query_raw(query)
        
        db_name = db_url.split('/')[-1].split('?')[0]
        
        print(f"\n{'='*100}")
        print(f"Database Connections (Database: {db_name})")
        print(f"{'='*100}\n")
        
        total = len(result)
        active = sum(1 for r in result if r['state'] == 'active')
        idle = sum(1 for r in result if r['state'] == 'idle')
        idle_in_transaction = sum(1 for r in result if 'idle in transaction' in (r['state'] or ''))
        
        print(f"Total connections: {total}")
        print(f"  Active: {active}")
        print(f"  Idle: {idle}")
        print(f"  Idle in transaction: {idle_in_transaction}\n")
        
        for conn in result:
            idle_time = f"{conn['idle_seconds']}s" if conn['idle_seconds'] else "N/A"
            print(f"PID: {conn['pid']:6} | User: {conn['usename']:15} | State: {conn['state']:20} | Idle: {idle_time}")
            if conn['query'] and conn['query'] != '<IDLE>':
                query_preview = conn['query'][:80].replace('\n', ' ')
                print(f"  Query: {query_preview}")
            print()
            
    finally:
        await client.disconnect()


async def kill_idle_connections(db_url: str, max_idle_seconds: int = 300):
    """Kill idle connections older than max_idle_seconds."""
    client = Prisma(datasource={"url": db_url})
    
    try:
        await client.connect()
        
        # Find idle connections
        query = f"""
        SELECT pid, state, EXTRACT(EPOCH FROM (NOW() - state_change))::int as idle_seconds
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND state = 'idle'
          AND pid != pg_backend_pid()
          AND EXTRACT(EPOCH FROM (NOW() - state_change)) > {max_idle_seconds};
        """
        
        idle_conns = await client.query_raw(query)
        
        print(f"\nFound {len(idle_conns)} idle connections older than {max_idle_seconds}s")
        
        killed = 0
        for conn in idle_conns:
            try:
                await client.execute_raw(f"SELECT pg_terminate_backend({conn['pid']});")
                print(f"✅ Killed PID {conn['pid']} (idle for {conn['idle_seconds']}s)")
                killed += 1
            except Exception as e:
                print(f"❌ Failed to kill PID {conn['pid']}: {e}")
        
        print(f"\n✅ Killed {killed}/{len(idle_conns)} connections")
        
    finally:
        await client.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="Manage PostgreSQL connections")
    parser.add_argument("--kill", action="store_true", help="Kill idle connections")
    parser.add_argument("--max-idle", type=int, default=300, help="Max idle time in seconds (default: 300)")
    parser.add_argument("--db-url", type=str, help="Database URL (default: from DATABASE_URL env)")
    
    args = parser.parse_args()
    
    # Get database URL
    db_url = args.db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL not set and --db-url not provided")
        sys.exit(1)
    
    if args.kill:
        await kill_idle_connections(db_url, args.max_idle)
    else:
        await show_connections(db_url)


if __name__ == "__main__":
    asyncio.run(main())
