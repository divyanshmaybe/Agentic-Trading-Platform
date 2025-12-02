
import asyncio
import os
import sys
from datetime import datetime

# Add parent and shared to path
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
shared_py_dir = os.path.abspath(os.path.join(parent_dir, "../../shared/py"))
sys.path.insert(0, parent_dir)
sys.path.insert(0, shared_py_dir)

from db_context import get_db_connection

async def check_logs():
    async with get_db_connection() as client:
        logs = await client.tradeexecutionlog.find_many(
            order={"created_at": "desc"},
            include={"trade": True}
        )
        print(f"Found {len(logs)} logs")
        for log in logs:
            print(f"ID: {log.id}")
            print(f"Status: {log.status}")
            print(f"Error: {log.error_message}")
            print(f"Trade Delay: {log.trade_delay}")
            print(f"Created At: {log.created_at}")
            print(f"Updated At: {log.updated_at}")
            if log.trade:
                print(f"Trade Status: {log.trade.status}")
                print(f"Trade Symbol: {log.trade.symbol}")
            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(check_logs())
