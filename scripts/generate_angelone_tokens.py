#!/usr/bin/env python3
"""
Generate Angel One token mapping for NSE stocks.
Extracts all NSE Cash Market (NSE_CM) symbols from Angel One's master scrip file.
"""

import json
import sys
from pathlib import Path

def generate_token_map(scrip_file: str, output_file: str):
    """Generate token mapping from Angel One scrip master file."""
    
    print(f"📥 Loading scrip data from {scrip_file}...")
    with open(scrip_file, 'r') as f:
        scrips = json.load(f)
    
    print(f"✓ Loaded {len(scrips)} total scrips")
    
    # Filter for NSE Cash Market (exch_seg='NSE')
    nse_stocks = {}
    
    for scrip in scrips:
        if scrip.get('exch_seg') == 'NSE':
            symbol = scrip.get('symbol', '').upper()
            token = scrip.get('token')
            name = scrip.get('name', '')
            
            if symbol and token:
                # Exchange type 1 = NSE Cash Market
                nse_stocks[symbol] = {
                    "exchangeType": 1,
                    "token": token,
                    "name": name
                }
    
    print(f"✓ Extracted {len(nse_stocks)} NSE stocks")
    
    # Save full mapping
    with open(output_file, 'w') as f:
        json.dump(nse_stocks, f, indent=2)
    
    print(f"✅ Saved token mapping to {output_file}")
    print(f"\n📊 Sample stocks:")
    for i, (symbol, data) in enumerate(list(nse_stocks.items())[:10]):
        print(f"  {symbol}: token={data['token']}, name={data['name']}")
        if i >= 9:
            break
    
    # Create compact version for .env (top 100 stocks by common usage)
    top_symbols = [
        'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'ITC',
        'SBIN', 'BHARTIARTL', 'KOTAKBANK', 'LT', 'AXISBANK', 'ASIANPAINT', 
        'MARUTI', 'TITAN', 'WIPRO', 'BAJFINANCE', 'HCLTECH', 'SUNPHARMA', 'ULTRACEMCO',
        'NESTLEIND', 'BAJAJFINSV', 'ONGC', 'TECHM', 'TATAMOTORS', 'POWERGRID',
        'NTPC', 'M&M', 'TATASTEEL', 'ADANIENT', 'HINDALCO', 'COALINDIA', 'JSWSTEEL',
        'INDUSINDBK', 'DRREDDY', 'GRASIM', 'CIPLA', 'DIVISLAB', 'EICHERMOT',
        'APOLLOHOSP', 'SHREECEM', 'ADANIPORTS', 'BRITANNIA', 'HEROMOTOCO', 'VEDL',
        'TATACONSUM', 'UPL', 'BAJAJ-AUTO', 'PIDILITIND', 'SBILIFE', 'DABUR'
    ]
    
    compact_map = {
        sym: nse_stocks[sym] 
        for sym in top_symbols 
        if sym in nse_stocks
    }
    
    print(f"\n📦 Compact map (top {len(compact_map)} stocks):")
    print(json.dumps(compact_map, separators=(',', ':')))

if __name__ == "__main__":
    scrip_file = sys.argv[1] if len(sys.argv) > 1 else "/tmp/angel_scrip_master.json"
    output_file = sys.argv[2] if len(sys.argv) > 2 else "shared/data/angelone_nse_tokens.json"
    
    # Create data directory if needed
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    
    generate_token_map(scrip_file, output_file)
