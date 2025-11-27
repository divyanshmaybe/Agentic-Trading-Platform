"""Test live price fetching from Angel One"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../shared/py"))

import asyncio
from market_data import await_live_price

async def main():
    symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFC', 'JUNIPER']
    
    print("Testing live price fetching from Angel One...\n")
    
    for symbol in symbols:
        try:
            price = await await_live_price(symbol, timeout=10.0)
            print(f'✅ {symbol:15s}: ₹{float(price):>10.2f}')
        except Exception as e:
            print(f'❌ {symbol:15s}: {e}')

if __name__ == '__main__':
    asyncio.run(main())
