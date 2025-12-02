
import asyncio
import os
import sys
import subprocess
import time
import json
from datetime import datetime

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

def run_script(script_name, args=[]):
    cmd = [sys.executable, os.path.join(script_dir, script_name)] + args
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Error running {script_name}:")
        print(result.stderr)
        return False
    print(result.stdout)
    return True

async def verify_buy_trade(symbol):
    print(f"\n🔍 Verifying BUY trade for {symbol}...")
    async with get_db_connection() as client:
        # Check Trade
        trade = await client.trade.find_first(
            where={
                "symbol": symbol,
                "side": "BUY",
                "status": "executed" # Or pending if execution is slow, but we expect executed
            },
            order={"created_at": "desc"},
            include={"executions": True}
        )
        
        if not trade:
            print("❌ No executed BUY trade found!")
            return False
        
        print(f"✅ Found BUY trade: {trade.id} | Qty: {trade.quantity} | Price: {trade.executed_price}")
        
        # Check Position
        position = await client.position.find_first(
            where={
                "symbol": symbol,
                "status": "open"
            }
        )
        
        if not position:
            print("❌ No open position found!")
            return False
            
        print(f"✅ Found Open Position: {position.id} | Qty: {position.quantity} | Avg Price: {position.average_buy_price}")
        
        # Check Execution Log and Delay
        if trade.executions:
            log = trade.executions[0]
            print(f"✅ Found Execution Log: {log.id}")
            if log.trade_delay is not None:
                print(f"✅ Trade Delay: {log.trade_delay} ms")
            else:
                print("⚠️ Trade Delay is None!")
        else:
            print("⚠️ No execution log found linked to trade!")

        # Check Auto Sell/Cover
        if trade.auto_sell_at:
             print(f"✅ Auto Sell At: {trade.auto_sell_at}")
        else:
             print("ℹ️ Auto Sell At not set (might be optional)")

        return True

async def verify_sell_trade(symbol):
    print(f"\n🔍 Verifying SELL trade for {symbol}...")
    async with get_db_connection() as client:
        # Check Trade
        trade = await client.trade.find_first(
            where={
                "symbol": symbol,
                "side": "SELL", # Or SHORT_SELL if it was a short
                "status": "executed"
            },
            order={"created_at": "desc"}
        )
        
        if not trade:
            print("❌ No executed SELL trade found!")
            return False
            
        print(f"✅ Found SELL trade: {trade.id} | Qty: {trade.quantity} | Price: {trade.executed_price}")
        
        # Check Position Closed
        position = await client.position.find_first(
            where={
                "symbol": symbol,
                "status": "closed"
            },
            order={"updated_at": "desc"}
        )
        
        if not position:
            print("❌ No closed position found!")
            return False
            
        print(f"✅ Found Closed Position: {position.id} | Realized PnL: {position.realized_pnl}")
        
        if float(position.realized_pnl or 0) != 0:
             print(f"✅ Realized PnL is non-zero: {position.realized_pnl}")
        else:
             print("⚠️ Realized PnL is zero (might be expected if price didn't change)")

        return True

async def main():
    print("🚀 Starting End-to-End Audit Test")
    
    # 1. Reset DB
    # We need to pass 'y' to the prompt
    print("\nStep 1: Resetting DB...")
    p = subprocess.Popen(
        [sys.executable, os.path.join(script_dir, "reset_and_audit.py"), "--reset"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = p.communicate(input="y\n")
    print(stdout)
    if p.returncode != 0:
        print("❌ Reset failed")
        print(stderr)
        return

    # 2. Ensure Agent
    print("\nStep 2: Ensuring Agent...")
    if not run_script("ensure_agent.py"):
        return

    # 3. Push BUY Signal
    symbol = "RELIANCE"
    print(f"\nStep 3: Pushing BUY Signal for {symbol}...")
    # push_fake_signal.py is in pipelines/nse/
    push_script = os.path.join(parent_dir, "pipelines/nse/push_fake_signal.py")
    cmd = [sys.executable, push_script, "--symbol", symbol, "--signal", "1", "--confidence", "0.9", "--price", "2500"]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("❌ Failed to push signal")
        print(result.stderr)
        return

    print("⏳ Waiting 15s for execution...")
    time.sleep(15)

    # 4. Verify BUY
    if not await verify_buy_trade(symbol):
        print("❌ BUY Verification Failed")
        return

    # 5. Push SELL Signal (to close)
    print(f"\nStep 5: Pushing SELL Signal for {symbol}...")
    # Use a slightly higher price to generate PnL
    cmd = [sys.executable, push_script, "--symbol", symbol, "--signal", "-1", "--confidence", "0.9", "--price", "2550"]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    
    print("⏳ Waiting 15s for execution...")
    time.sleep(15)

    # 6. Verify SELL
    if not await verify_sell_trade(symbol):
        print("❌ SELL Verification Failed")
        return

    print("\n✅ End-to-End Audit Test Completed Successfully!")

if __name__ == "__main__":
    asyncio.run(main())
