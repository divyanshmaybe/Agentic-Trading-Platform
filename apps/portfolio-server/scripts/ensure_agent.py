
import asyncio
import os
import sys
import json
from pathlib import Path

# Add parent and shared to path
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
shared_py_dir = os.path.abspath(os.path.join(parent_dir, "../../shared/py"))
sys.path.insert(0, parent_dir)
sys.path.insert(0, shared_py_dir)

from dotenv import load_dotenv
env_path = os.path.join(parent_dir, ".env")
load_dotenv(env_path)

from db_context import get_db_connection
from prisma import Json

async def ensure_high_risk_agent():
    print("Checking for high-risk agent...")
    async with get_db_connection() as client:
        # Find a portfolio
        portfolio = await client.portfolio.find_first(
            where={"status": "active"},
            include={"allocations": True}
        )
        
        if not portfolio:
            print("No active portfolio found. Creating one...")
            # Create a dummy user and portfolio if needed (simplified)
            # For now, assume at least one portfolio exists or fail
            print("❌ No active portfolio found. Please create a portfolio first.")
            return False

        print(f"Using portfolio: {portfolio.id} ({portfolio.portfolio_name})")

        # Check for high_risk allocation
        allocation = await client.portfolioallocation.find_first(
            where={
                "portfolio_id": portfolio.id,
                "allocation_type": "high_risk"
            }
        )

        if not allocation:
            print("Creating high_risk allocation...")
            allocation = await client.portfolioallocation.create(
                data={
                    "portfolio_id": portfolio.id,
                    "allocation_type": "high_risk",
                    "target_weight": 0.2,
                    "current_weight": 0.2,
                    "allocated_amount": 100000, # 1 Lakh
                    "available_cash": 100000,
                    "metadata": Json({"created_by": "ensure_agent.py"})
                }
            )
        else:
            print(f"Found high_risk allocation: {allocation.id}")
            # Ensure it has cash
            if float(allocation.available_cash or 0) < 10000:
                print("Top up allocation cash...")
                await client.portfolioallocation.update(
                    where={"id": allocation.id},
                    data={"available_cash": 100000, "allocated_amount": 100000}
                )

        # Check for high_risk agent
        agent = await client.tradingagent.find_first(
            where={
                "portfolio_id": portfolio.id,
                "agent_type": "high_risk"
            }
        )

        if not agent:
            print("Creating high_risk agent...")
            agent = await client.tradingagent.create(
                data={
                    "portfolio_id": portfolio.id,
                    "portfolio_allocation_id": allocation.id,
                    "agent_type": "high_risk",
                    "agent_name": "High Risk Alpha Agent",
                    "status": "active",
                    "strategy_config": Json({"auto_trade": True, "risk_level": "high"}),
                    "metadata": Json({"created_by": "ensure_agent.py"})
                }
            )
        else:
            print(f"Found high_risk agent: {agent.id}")
            # Ensure auto_trade is enabled
            config = agent.strategy_config or {}
            if not config.get("auto_trade"):
                print("Enabling auto_trade...")
                config["auto_trade"] = True
                await client.tradingagent.update(
                    where={"id": agent.id},
                    data={"strategy_config": Json(config), "status": "active"}
                )
            
            # Ensure allocation link is correct
            if agent.portfolio_allocation_id != allocation.id:
                 await client.tradingagent.update(
                    where={"id": agent.id},
                    data={"portfolio_allocation_id": allocation.id}
                )

        print("✅ High-risk agent ready.")
        return True

if __name__ == "__main__":
    asyncio.run(ensure_high_risk_agent())
