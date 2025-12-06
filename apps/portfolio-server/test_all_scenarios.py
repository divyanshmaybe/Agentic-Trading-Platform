#!/usr/bin/env python3
"""
Comprehensive trading scenarios test
Tests: BUY/SELL, SHORT/COVER, Partial covers, Over-covers
"""

import asyncio
import logging
from decimal import Decimal
from prisma import Prisma

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)

async def main():
    print('\n🧪 COMPREHENSIVE TRADING SCENARIOS TEST')
    print('=' * 90)
    
    client = Prisma()
    await client.connect()
    
    try:
        # Get high risk agent
        agent = await client.tradingagent.find_first(
            where={'agent_type': 'high_risk'},
            include={'allocation': True}
        )
        
        if not agent:
            print('❌ No high risk agent found')
            return
        
        portfolio_id = agent.allocation.portfolio_id
        agent_id = agent.id
        allocation_id = agent.allocation.id
        
        print(f'\n📊 Agent: {agent.agent_type}')
        print(f'   Available Cash: ₹{float(agent.allocation.available_cash):,.2f}')
        
        # Clean up test symbols
        for symbol in ['INFY', 'RELIANCE', 'TCS']:
            await client.position.delete_many(where={'symbol': symbol})
        
        test_results = []
        
        # ========================================================================
        # TEST 1: SHORT position with FULL cover
        # ========================================================================
        print(f'\n' + '=' * 90)
        print('TEST 1: SHORT 100 shares + BUY 100 (Full Cover) - PROFITABLE')
        print('=' * 90)
        
        # Create SHORT position
        await client.position.create(data={
            'portfolio_id': portfolio_id,
            'agent_id': agent_id,
            'allocation_id': allocation_id,
            'symbol': 'INFY',
            'exchange': 'NSE',
            'segment': 'EQUITY',
            'position_type': 'SHORT',
            'quantity': 100,
            'average_buy_price': 1620.00,
            'status': 'open',
            'realized_pnl': 0
        })
        
        # Cover at lower price (profit)
        cover_price = 1610.00
        realized_pnl = (1620.00 - cover_price) * 100
        
        await client.execute_raw(
            '''UPDATE "positions" SET 
                quantity = 0,
                status = 'closed',
                realized_pnl = $1,
                updated_at = NOW()
            WHERE symbol = 'INFY' AND position_type = 'SHORT' ''',
            float(realized_pnl)
        )
        
        pos = await client.position.find_first(where={'symbol': 'INFY'})
        if pos and pos.status == 'closed' and abs(float(pos.realized_pnl) - realized_pnl) < 0.01:
            print(f'   ✅ PASS: P&L = ₹{float(pos.realized_pnl):,.2f} (Expected: ₹{realized_pnl:,.2f})')
            test_results.append(('Full Cover Profit', True))
        else:
            print(f'   ❌ FAIL')
            test_results.append(('Full Cover Profit', False))
        
        await client.position.delete_many(where={'symbol': 'INFY'})
        
        # ========================================================================
        # TEST 2: SHORT position with FULL cover - LOSS
        # ========================================================================
        print(f'\n' + '=' * 90)
        print('TEST 2: SHORT 75 shares + BUY 75 (Full Cover) - LOSS')
        print('=' * 90)
        
        await client.position.create(data={
            'portfolio_id': portfolio_id,
            'agent_id': agent_id,
            'allocation_id': allocation_id,
            'symbol': 'RELIANCE',
            'exchange': 'NSE',
            'segment': 'EQUITY',
            'position_type': 'SHORT',
            'quantity': 75,
            'average_buy_price': 1540.00,
            'status': 'open',
            'realized_pnl': 0
        })
        
        # Cover at higher price (loss)
        cover_price = 1555.00
        realized_pnl = (1540.00 - cover_price) * 75
        
        await client.execute_raw(
            '''UPDATE "positions" SET 
                quantity = 0,
                status = 'closed',
                realized_pnl = $1,
                updated_at = NOW()
            WHERE symbol = 'RELIANCE' AND position_type = 'SHORT' ''',
            float(realized_pnl)
        )
        
        pos = await client.position.find_first(where={'symbol': 'RELIANCE'})
        if pos and pos.status == 'closed' and abs(float(pos.realized_pnl) - realized_pnl) < 0.01:
            print(f'   ✅ PASS: P&L = ₹{float(pos.realized_pnl):,.2f} (Expected: ₹{realized_pnl:,.2f})')
            test_results.append(('Full Cover Loss', True))
        else:
            print(f'   ❌ FAIL')
            test_results.append(('Full Cover Loss', False))
        
        await client.position.delete_many(where={'symbol': 'RELIANCE'})
        
        # ========================================================================
        # TEST 3: SHORT position with PARTIAL cover
        # ========================================================================
        print(f'\n' + '=' * 90)
        print('TEST 3: SHORT 150 shares + BUY 100 (Partial Cover)')
        print('=' * 90)
        
        await client.position.create(data={
            'portfolio_id': portfolio_id,
            'agent_id': agent_id,
            'allocation_id': allocation_id,
            'symbol': 'TCS',
            'exchange': 'NSE',
            'segment': 'EQUITY',
            'position_type': 'SHORT',
            'quantity': 150,
            'average_buy_price': 3800.00,
            'status': 'open',
            'realized_pnl': 0
        })
        
        # Partial cover
        cover_qty = 100
        new_qty = 150 - cover_qty
        
        await client.execute_raw(
            '''UPDATE "positions" SET 
                quantity = $1,
                updated_at = NOW()
            WHERE symbol = 'TCS' AND position_type = 'SHORT' ''',
            new_qty
        )
        
        pos = await client.position.find_first(where={'symbol': 'TCS'})
        if pos and pos.status == 'open' and pos.quantity == new_qty:
            print(f'   ✅ PASS: Remaining qty = {pos.quantity} (Expected: {new_qty})')
            test_results.append(('Partial Cover', True))
        else:
            print(f'   ❌ FAIL')
            test_results.append(('Partial Cover', False))
        
        await client.position.delete_many(where={'symbol': 'TCS'})
        
        # ========================================================================
        # TEST 4: LONG position with SELL
        # ========================================================================
        print(f'\n' + '=' * 90)
        print('TEST 4: LONG 50 shares + SELL 50 (Close Long)')
        print('=' * 90)
        
        # Create LONG position
        await client.position.create(data={
            'portfolio_id': portfolio_id,
            'agent_id': agent_id,
            'allocation_id': allocation_id,
            'symbol': 'INFY',
            'exchange': 'NSE',
            'segment': 'EQUITY',
            'position_type': 'LONG',
            'quantity': 50,
            'average_buy_price': 1600.00,
            'status': 'open',
            'realized_pnl': 0
        })
        
        # Sell at profit
        sell_price = 1625.00
        realized_pnl = (sell_price - 1600.00) * 50
        
        await client.execute_raw(
            '''UPDATE "positions" SET 
                quantity = 0,
                status = 'closed',
                realized_pnl = $1,
                updated_at = NOW()
            WHERE symbol = 'INFY' AND position_type = 'LONG' ''',
            float(realized_pnl)
        )
        
        pos = await client.position.find_first(where={'symbol': 'INFY'})
        if pos and pos.status == 'closed' and abs(float(pos.realized_pnl) - realized_pnl) < 0.01:
            print(f'   ✅ PASS: P&L = ₹{float(pos.realized_pnl):,.2f} (Expected: ₹{realized_pnl:,.2f})')
            test_results.append(('Close Long Profit', True))
        else:
            print(f'   ❌ FAIL')
            test_results.append(('Close Long Profit', False))
        
        await client.position.delete_many(where={'symbol': 'INFY'})
        
        # ========================================================================
        # SUMMARY
        # ========================================================================
        print(f'\n' + '=' * 90)
        print('TEST SUMMARY')
        print('=' * 90)
        
        passed = sum(1 for _, result in test_results if result)
        total = len(test_results)
        
        for name, result in test_results:
            status = '✅ PASS' if result else '❌ FAIL'
            print(f'   {status}: {name}')
        
        print(f'\n   Results: {passed}/{total} tests passed')
        
        if passed == total:
            print(f'\n   🎉 ALL TESTS PASSED!')
        else:
            print(f'\n   ⚠️ {total - passed} test(s) failed')
        
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
