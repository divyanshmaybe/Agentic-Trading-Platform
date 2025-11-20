#!/usr/bin/env python3
"""
Test position creation by triggering a BUY trade signal
"""
import asyncio
import json
from datetime import datetime
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from services.trade_execution_service import TradeExecutionService


async def test_position_creation():
    """Test position creation with a BUY trade"""
    
    service = TradeExecutionService()
    
    # Create a test trade payload
    test_payload = {
        "user_id": "cebf1b4a-7eb0-4a66-8c39-66ba43c43b9c",
        "portfolio_id": "41abb733-cae6-4d77-bca4-b867bb2e4b34",
        "agent_id": "a3348aff-aa14-4063-bc35-47ce18f6c17a",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "segment": "EQ",
        "side": "BUY",
        "quantity": 10,
        "reference_price": 1250.50,
        "allocation": 15000.0,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "test_position_creation",
    }
    
    print(f"\n{'='*60}")
    print(f"🧪 Testing Position Creation for {test_payload['symbol']}")
    print(f"{'='*60}\n")
    print(f"📋 Test Payload:")
    print(json.dumps(test_payload, indent=2))
    print()
    
    # Persist and execute trade
    print("🚀 Persisting and executing trade...")
    result = await service.persist_and_publish(test_payload)
    
    print(f"\n{'='*60}")
    print(f"✅ Trade Execution Result:")
    print(f"{'='*60}\n")
    print(json.dumps(result, indent=2, default=str))
    print()
    
    # Wait for execution
    print("⏳ Waiting 3 seconds for trade execution and position creation...")
    await asyncio.sleep(3)
    
    # Check position in DB
    from shared.py.dbManager import DBManager
    db = DBManager()
    await db.connect()
    
    positions = await db.client.position.find_many(
        where={
            "portfolio_id": test_payload["portfolio_id"],
            "symbol": test_payload["symbol"],
        },
        order_by={"updated_at": "desc"}
    )
    
    print(f"\n{'='*60}")
    print(f"📊 Position Records for {test_payload['symbol']}:")
    print(f"{'='*60}\n")
    
    if positions:
        for pos in positions:
            print(f"Position ID: {pos.id}")
            print(f"Symbol: {pos.symbol}")
            print(f"Quantity: {pos.quantity}")
            print(f"Average Buy Price: ₹{pos.average_buy_price}")
            print(f"Current Price: ₹{pos.current_price}")
            print(f"Current Value: ₹{pos.current_value}")
            print(f"Status: {pos.status}")
            print(f"Agent ID: {pos.agent_id}")
            print(f"Opened At: {pos.opened_at}")
            print(f"Metadata: {pos.metadata}")
            print("-" * 60)
    else:
        print("❌ No position found!")
    
    await db.disconnect()
    print()


if __name__ == "__main__":
    asyncio.run(test_position_creation())
