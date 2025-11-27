"""
Fix realized P&L for existing SELL trades that have 0 P&L.
This script recalculates P&L using the position's average_buy_price.
"""
from prisma import Prisma
import asyncio
from decimal import Decimal

async def fix_realized_pnl():
    db = Prisma()
    await db.connect()
    
    # Find SELL trades with realized_pnl = 0
    sell_trades = await db.trade.find_many(
        where={'side': 'SELL', 'status': 'executed'},
        order={'created_at': 'desc'}
    )
    
    print(f'Found {len(sell_trades)} SELL trades to check\n')
    
    fixed_count = 0
    for sell_trade in sell_trades:
        # Find position (open or closed) for this symbol
        position = await db.position.find_first(
            where={
                'portfolio_id': sell_trade.portfolio_id,
                'symbol': {'equals': sell_trade.symbol, 'mode': 'insensitive'}
            },
            order={'updated_at': 'desc'}
        )
        
        if not position:
            print(f'⚠️  {sell_trade.symbol}: No position found, skipping')
            continue
        
        avg_buy_price = float(position.average_buy_price)
        sell_price = float(sell_trade.price)
        quantity = int(sell_trade.quantity)
        
        # Calculate P&L
        realized_pnl = (sell_price - avg_buy_price) * quantity
        
        current_pnl = float(sell_trade.realized_pnl or 0)
        
        # Only update if different
        if abs(realized_pnl - current_pnl) > 0.01:
            await db.trade.update(
                where={'id': sell_trade.id},
                data={'realized_pnl': Decimal(str(realized_pnl))}
            )
            
            print(f'✅ {sell_trade.symbol}: Buy @ ₹{avg_buy_price:.2f}, Sell @ ₹{sell_price:.2f}')
            print(f'   Quantity: {quantity}')
            print(f'   OLD P&L: ₹{current_pnl:.2f} → NEW P&L: ₹{realized_pnl:.2f}')
            print()
            fixed_count += 1
        else:
            print(f'✓  {sell_trade.symbol}: P&L already correct (₹{realized_pnl:.2f})')
    
    print(f'\n🎯 Fixed {fixed_count} trades')
    
    await db.disconnect()

if __name__ == '__main__':
    asyncio.run(fix_realized_pnl())
