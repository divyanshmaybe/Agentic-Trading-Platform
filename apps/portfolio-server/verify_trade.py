#!/usr/bin/env python3
"""
Verify Trade Execution - Check all fields and workflows

Usage:
    python3 verify_trade.py [SYMBOL]
    
Example:
    python3 verify_trade.py INFY
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add paths
SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "shared" / "py"))

from dbManager import DBManager


async def verify_trade(symbol: str = "INFY"):
    db = DBManager.get_instance()
    try:
        await db.connect()
        
        # Get most recent trade for symbol
        trade = await db.client.trade.find_first(
            where={'symbol': symbol},
            order={'created_at': 'desc'},
            include={
                'tp_order': True,
                'sl_order': True,
                'position': True,
                'trade_execution_logs': True
            }
        )
        
        if not trade:
            print(f'❌ No {symbol} trade found')
            return False
            
        print('═══════════════════════════════════════════════════')
        print('📊 TRADE RECORD VERIFICATION')
        print('═══════════════════════════════════════════════════')
        print(f'Trade ID: {trade.id}')
        print(f'Symbol: {trade.symbol}')
        print(f'Side: {trade.side}')
        print(f'Quantity: {trade.quantity}')
        print(f'Price: ₹{trade.price}')
        print(f'Executed Price: ₹{trade.executed_price or "N/A"}')
        status_ok = trade.status == "simulated_executed"
        print(f'Status: {trade.status} {"✅" if status_ok else "❌"}')
        print(f'Net Amount: ₹{trade.net_amount or "N/A"}')
        print(f'Realized PnL: ₹{trade.realized_pnl or 0}')
        print(f'Execution Time: {trade.execution_time or "N/A"}')
        print(f'Auto-Sell Time: {trade.auto_sell_at or "N/A"}')
        
        # Check if auto-sell time is 15 minutes from execution
        auto_sell_ok = False
        if trade.auto_sell_at and trade.execution_time:
            exec_time = trade.execution_time
            sell_time = trade.auto_sell_at
            # Calculate difference in minutes
            diff = (sell_time - exec_time).total_seconds() / 60
            print(f'Auto-Sell Window: {diff:.1f} minutes after execution {"✅" if 14 < diff < 16 else "❌"}')
            auto_sell_ok = 14 < diff < 16
        elif trade.auto_sell_at:
            # Check relative to now
            now = datetime.now(timezone.utc)
            sell_time = trade.auto_sell_at
            diff = (sell_time - now).total_seconds() / 60
            print(f'Auto-Sell In: {diff:.1f} minutes {"✅" if 0 < diff < 16 else "❌"}')
            auto_sell_ok = 0 < diff < 16
        
        print(f'\n📋 TP/SL ORDERS:')
        tp_ok = trade.tp_order is not None
        print(f'TP Order: {"✅ YES" if tp_ok else "❌ NO"}')
        if trade.tp_order:
            tp = trade.tp_order
            # TP should be 3% above price for BUY, 3% below for SELL
            expected_tp = float(trade.price) * 1.03 if trade.side == "BUY" else float(trade.price) * 0.97
            tp_price_ok = abs(float(tp.limit_price) - expected_tp) < 1
            print(f'  └─ ID: {tp.id[:8]}... | {tp.side} {tp.quantity} @ ₹{tp.limit_price}')
            print(f'     Status: {tp.status} | Price Check: {"✅" if tp_price_ok else "❌"}')
            
        sl_ok = trade.sl_order is not None
        print(f'SL Order: {"✅ YES" if sl_ok else "❌ NO"}')
        if trade.sl_order:
            sl = trade.sl_order
            # SL should be 1% below price for BUY, 1% above for SELL
            expected_sl = float(trade.price) * 0.99 if trade.side == "BUY" else float(trade.price) * 1.01
            sl_price_ok = abs(float(sl.limit_price) - expected_sl) < 1
            print(f'  └─ ID: {sl.id[:8]}... | {sl.side} {sl.quantity} @ ₹{sl.limit_price}')
            print(f'     Status: {sl.status} | Price Check: {"✅" if sl_price_ok else "❌"}')
        
        print(f'\n📍 POSITION:')
        pos_ok = trade.position is not None
        print(f'Position Created: {"✅ YES" if pos_ok else "❌ NO"}')
        if trade.position:
            pos = trade.position
            qty_ok = pos.quantity == trade.quantity or pos.quantity > 0
            print(f'  └─ {pos.symbol} x {pos.quantity} @ avg ₹{pos.average_price}')
            print(f'     Unrealized PnL: ₹{pos.unrealized_pnl or 0} | Qty Check: {"✅" if qty_ok else "❌"}')
        
        print(f'\n📝 EXECUTION LOG:')
        log_ok = False
        if trade.trade_execution_logs:
            for log in trade.trade_execution_logs:
                log_status_ok = log.status == "simulated_executed"
                print(f'Log ID: {log.id[:8]}... | Status: {log.status} {"✅" if log_status_ok else "❌"}')
                print(f'  └─ Exec Price: ₹{log.executed_price or "N/A"} | Exec Qty: {log.executed_quantity or "N/A"}')
                log_ok = log_status_ok
        else:
            print('❌ No execution logs found')
            
        print('\n═══════════════════════════════════════════════════')
        print('📊 VERIFICATION SUMMARY')
        print('═══════════════════════════════════════════════════')
        
        checks = {
            'Trade Status': status_ok,
            'TP Order Created': tp_ok,
            'SL Order Created': sl_ok,
            'Position Created': pos_ok,
            'Execution Log': log_ok,
            'Auto-Sell Set': auto_sell_ok,
        }
        
        for check, result in checks.items():
            print(f'{check}: {"✅ PASS" if result else "❌ FAIL"}')
        
        all_passed = all(checks.values())
        print('═══════════════════════════════════════════════════')
        if all_passed:
            print('✅ ALL CHECKS PASSED - Trade execution is working correctly!')
        else:
            print('❌ SOME CHECKS FAILED - Review the issues above')
        print('═══════════════════════════════════════════════════')
        
        return all_passed
        
    finally:
        await db.disconnect()


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "INFY"
    try:
        result = asyncio.run(verify_trade(symbol))
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f'\n❌ Verification failed: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)
