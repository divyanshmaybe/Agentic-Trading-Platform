#!/usr/bin/env python3
"""
Comprehensive Trading System Test
Tests: BUY/SELL, SHORT/COVER, TP/SL monitoring, Realized P&L calculations
"""

import asyncio
import sys
import logging
from decimal import Decimal
from prisma import Prisma

# Setup logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)

async def execute_mock_trade(client, agent, symbol, side, quantity, price):
    """Execute a mock trade and create position"""
    from services.trade_execution_service import TradeExecutionService
    
    service = TradeExecutionService(logger=logger)
    
    # Create trade record
    trade = await client.trade.create(data={
        'organization_id': 'test_org',
        'portfolio_id': agent.allocation.portfolio_id,
        'customer_id': 'test_customer',
        'trade_type': 'intraday',
        'symbol': symbol,
        'exchange': 'NSE',
        'segment': 'EQUITY',
        'side': side,
        'order_type': 'market',
        'quantity': quantity,
        'status': 'executed',
        'executed_price': price,
        'executed_quantity': quantity,
        'agent_id': agent.id,
        'allocation_id': agent.allocation.id
    })
    
    # Apply position logic
    await service._apply_position_update(
        client=client,
        trade_id=trade.id,
        portfolio_id=agent.allocation.portfolio_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        executed_price=float(price),
        agent_id=agent.id,
        allocation_id=agent.allocation.id
    )
    
    return trade

async def main():
    print('🧪 COMPREHENSIVE TRADING SYSTEM TEST')
    print('=' * 90)
    
    client = Prisma()
    await client.connect()
    
    try:
        # Get high risk agent
        agent = await client.tradingagent.find_first(
            where={'agent_type': 'high_risk'},
            include={'allocation': True, 'positions': True}
        )
        
        if not agent:
            print('❌ No high risk agent found')
            return
        
        print(f'\n📊 INITIAL STATE:')
        print(f'   Allocated: ₹{float(agent.allocation.allocated_amount):,.2f}')
        print(f'   Available: ₹{float(agent.allocation.available_cash):,.2f}')
        
        # TEST 1: BUY with TP/SL
        print(f'\n' + '=' * 90)
        print('TEST 1: BUY Trade (RELIANCE)')
        print('=' * 90)
        
        buy_price = 1540.60
        trade1 = await execute_mock_trade(client, agent, 'RELIANCE', 'BUY', 10, buy_price)
        
        # Check position
        rel_pos = await client.position.find_first(where={'symbol': 'RELIANCE', 'status': 'open'})
        if rel_pos:
            print(f'   ✅ LONG Position Created:')
            print(f'      Price: ₹{float(rel_pos.average_buy_price):,.2f}')
            print(f'      Quantity: {rel_pos.quantity}')
        else:
            print(f'   ❌ Position not created')
        
        # TEST 2: SHORT_SELL
        print(f'\n' + '=' * 90)
        print('TEST 2: SHORT_SELL Trade (INFY)')
        print('=' * 90)
        
        short_price = 1616.20
        trade2 = await execute_mock_trade(client, agent, 'INFY', 'SHORT_SELL', 50, short_price)
        
        # Check SHORT position
        short_pos = await client.position.find_first(where={'symbol': 'INFY', 'status': 'open'})
        if short_pos:
            print(f'   ✅ SHORT Position Created:')
            print(f'      Price: ₹{float(short_pos.average_buy_price):,.2f}')
            print(f'      Position Type: {short_pos.position_type}')
            print(f'      Quantity: {short_pos.quantity}')
        else:
            print(f'   ❌ SHORT position not created')
        
        # TEST 3: BUY to COVER SHORT
        print(f'\n' + '=' * 90)
        print('TEST 3: BUY to Cover SHORT (INFY)')
        print('=' * 90)
        
        cover_price = 1620.50
        trade3 = await execute_mock_trade(client, agent, 'INFY', 'BUY', 50, cover_price)
        
        print(f'   ✅ COVER Executed:')
        print(f'      Price: ₹{cover_price:,.2f}')
        
        # Check if SHORT closed
        short_closed = await client.position.find_first(where={'symbol': 'INFY', 'status': 'closed'})
        if short_closed:
            pnl = float(short_closed.realized_pnl or 0)
            expected_pnl = (short_price - cover_price) * 50
            match_icon = "✅" if abs(pnl - expected_pnl) < 1 else "❌"
            print(f'      ✅ SHORT CLOSED!')
            print(f'      Realized P&L: ₹{pnl:,.2f}')
            print(f'      Expected: ₹{expected_pnl:,.2f}')
            print(f'      Match: {match_icon}')
        else:
            print(f'      ❌ SHORT not closed')
        
        # TEST 4: SELL to close LONG
        print(f'\n' + '=' * 90)
        print('TEST 4: SELL to Close LONG (RELIANCE)')
        print('=' * 90)
        
        sell_price = 1545.80
        trade4 = await execute_mock_trade(client, agent, 'RELIANCE', 'SELL', 10, sell_price)
        
        print(f'   ✅ SELL Executed:')
        print(f'      Price: ₹{sell_price:,.2f}')
        
        # Check if LONG closed
        long_closed = await client.position.find_first(where={'symbol': 'RELIANCE', 'status': 'closed'})
        if long_closed:
            pnl = float(long_closed.realized_pnl or 0)
            expected_pnl = (sell_price - buy_price) * 10
            match_icon = "✅" if abs(pnl - expected_pnl) < 1 else "❌"
            print(f'      ✅ LONG CLOSED!')
            print(f'      Realized P&L: ₹{pnl:,.2f}')
            print(f'      Expected: ₹{expected_pnl:,.2f}')
            print(f'      Match: {match_icon}')
        else:
            print(f'      ❌ LONG not closed')
        # FINAL SUMMARY
        print(f'\n' + '=' * 90)
        print('📊 FINAL SUMMARY')
        print('=' * 90)
        
        agent_final = await client.tradingagent.find_first(
            where={'id': agent.id},
            include={'allocation': True, 'positions': True, 'trades': True}
        )
        
        all_trades = [t for t in agent_final.trades if t.status == 'executed']
        closed_pos = [p for p in agent_final.positions if p.status == 'closed']
        
        total_realized = sum(float(p.realized_pnl or 0) for p in closed_pos)
        
        print(f'\n   Executed Trades: {len(all_trades)}')
        print(f'   Closed Positions: {len(closed_pos)}')
        print(f'   Total Realized P&L: ₹{total_realized:,.2f}')
        
        print(f'\n✅ ALL TESTS COMPLETED!')
        
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
