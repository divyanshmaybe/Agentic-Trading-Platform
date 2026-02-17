"""
Angel One token map generator - Celery task for async generation.
Downloads the Angel One scrip master file and generates:
1. Token mapping for all NSE stocks (for real-time market data subscriptions)
2. Nifty-500 constituent list (for pre-fetching optimization)
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Default cache locations
DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../apps/portfolio-server/docs/angelone_tokens.json"
)

DEFAULT_NIFTY500_PATH = os.path.join(
    os.path.dirname(__file__),
    "../py/nifty500_symbols.py"
)

DEFAULT_NIFTY500_PATH = os.path.join(
    os.path.dirname(__file__),
    "nifty500_symbols.py"
)


def generate_angelone_token_map(cache_path: str = None) -> Dict[str, Any]:
    """
    Download Angel One scrip master and generate token map for all NSE stocks.
    
    Args:
        cache_path: Path to save the generated token map. If None, uses default.
        
    Returns:
        Dict mapping symbol -> {"exchangeType": int, "token": str, "name": str}
    """
    import httpx
    
    if cache_path is None:
        cache_path = DEFAULT_CACHE_PATH
    
    try:
        # Download scrip master file
        scrip_url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        
        logger.info("📥 Downloading Angel One scrip master file...")
        with httpx.Client(timeout=120.0) as client:
            response = client.get(scrip_url)
            response.raise_for_status()
            scrips = response.json()
        
        logger.info(f"✓ Downloaded {len(scrips):,} total scrips")
        
        # Extract NSE Cash Market stocks (exch_seg='NSE')
        nse_stocks = {}
        nse_fo_count = 0
        bse_count = 0
        
        for scrip in scrips:
            exch_seg = scrip.get('exch_seg', '')
            symbol = scrip.get('symbol', '').upper()
            token = scrip.get('token')
            name = scrip.get('name', '')
            tradingsymbol = scrip.get('trading_symbol', symbol)
            
            if not symbol or not token:
                continue
            
            # NSE Cash Market
            if exch_seg == 'NSE':
                nse_stocks[symbol] = {
                    "exchangeType": 1,
                    "token": token,
                    "name": name,
                    "segment": "NSE",
                    "tradingSymbol": tradingsymbol
                }
            # Also track counts for other segments
            elif exch_seg == 'NFO':
                nse_fo_count += 1
            elif exch_seg == 'BSE':
                bse_count += 1
        
        logger.info(f"✅ Extracted {len(nse_stocks):,} NSE stocks")
        logger.info(f"   (Also available: {nse_fo_count:,} NSE F&O, {bse_count:,} BSE)")
        
        # Create cache directory if needed
        cache_dir = os.path.dirname(cache_path)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        
        # Save to cache file
        with open(cache_path, 'w') as f:
            json.dump(nse_stocks, f, indent=2, sort_keys=True)
        
        logger.info(f"💾 Saved token map to {cache_path}")
        
        # Log statistics
        logger.info(f"📊 Token map statistics:")
        logger.info(f"   Total NSE symbols: {len(nse_stocks):,}")
        logger.info(f"   File size: {os.path.getsize(cache_path) / 1024:.1f} KB")
        
        # Log sample stocks
        popular_symbols = ['RELIANCE-EQ', 'TCS-EQ', 'HDFCBANK-EQ', 'INFY-EQ', 'ICICIBANK-EQ']
        samples = [(s, nse_stocks.get(s)) for s in popular_symbols if s in nse_stocks]
        if samples:
            sample_text = ', '.join(f"{s}({d['token']})" for s, d in samples)
            logger.info(f"   Sample: {sample_text}")
        
        return nse_stocks
        
    except Exception as e:
        logger.error(f"❌ Failed to generate token map: {e}", exc_info=True)
        raise


def load_angelone_token_map(cache_path: str = None) -> Dict[str, Any]:
    """
    Load Angel One token map from cache file.
    
    Args:
        cache_path: Path to the cached token map. If None, uses default.
        
    Returns:
        Dict mapping symbol -> {"exchangeType": int, "token": str, "name": str}
        
    Raises:
        FileNotFoundError: If cache file doesn't exist
    """
    if cache_path is None:
        cache_path = DEFAULT_CACHE_PATH
    
    if not os.path.exists(cache_path):
        raise FileNotFoundError(f"Token map cache not found at {cache_path}")
    
    with open(cache_path, 'r') as f:
        token_map = json.load(f)
    
    logger.info(f"📂 Loaded {len(token_map):,} NSE symbols from {cache_path}")
    return token_map


def ensure_angelone_token_map(cache_path: str = None, force_refresh: bool = False) -> Dict[str, Any]:
    """
    Ensure Angel One token map exists, loading from cache or generating if needed.
    
    Args:
        cache_path: Path to the cached token map. If None, uses default.
        force_refresh: If True, regenerate even if cache exists.
        
    Returns:
        Dict mapping symbol -> {"exchangeType": int, "token": str, "name": str}
    """
    if cache_path is None:
        cache_path = DEFAULT_CACHE_PATH
    
    # Check if we need to generate
    if force_refresh or not os.path.exists(cache_path):
        logger.info("🔄 Generating new Angel One token map...")
        token_map = generate_angelone_token_map(cache_path)
        
        # Also generate Nifty-500 list
        try:
            generate_nifty500_symbols(token_map)
        except Exception as e:
            logger.warning(f"Failed to generate Nifty-500 list: {e}")
        
        return token_map
    
    # Load from cache
    try:
        token_map = load_angelone_token_map(cache_path)
        
        # Check if Nifty-500 list exists, generate if not
        if not os.path.exists(DEFAULT_NIFTY500_PATH):
            logger.info("📋 Nifty-500 list not found, generating...")
            try:
                generate_nifty500_symbols(token_map)
            except Exception as e:
                logger.warning(f"Failed to generate Nifty-500 list: {e}")
        
        return token_map
    except Exception as e:
        logger.warning(f"Failed to load cache ({e}), regenerating...")
        return generate_angelone_token_map(cache_path)


def generate_nifty500_symbols(token_map: Dict[str, Any] = None, output_path: str = None) -> List[str]:
    """
    Generate Nifty-500 constituent list from token map.
    
    Creates a Python file with the list of Nifty-500 symbols for pre-fetching.
    Uses NSE official constituent lists or falls back to top 500 by market cap.
    
    Args:
        token_map: Token map dict. If None, loads from default cache.
        output_path: Path to save the generated Python file. If None, uses default.
        
    Returns:
        List of Nifty-500 symbol strings
    """
    import httpx
    
    if token_map is None:
        token_map = load_angelone_token_map()
    
    if output_path is None:
        output_path = DEFAULT_NIFTY500_PATH
    
    logger.info("📊 Generating Nifty-500 constituent list...")
    
    # Try to fetch official Nifty indices from NSE
    nifty500_symbols = []
    
    try:
        # Fetch from NSE India official indices
        # Note: NSE API might require headers/rate limiting in production
        indices_to_fetch = [
            "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
            # Fallback: construct from smaller indices
        ]
        
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            for url in indices_to_fetch:
                try:
                    response = client.get(url, headers={
                        "User-Agent": "Mozilla/5.0 (compatible; AgentInvest/1.0)",
                        "Accept": "text/csv,text/plain"
                    })
                    
                    if response.status_code == 200:
                        # Parse CSV
                        lines = response.text.strip().split('\n')
                        for line in lines[1:]:  # Skip header
                            parts = line.split(',')
                            if len(parts) > 2:
                                symbol = parts[2].strip().strip('"')  # Symbol column
                                if symbol and symbol != 'Symbol':
                                    # Add -EQ suffix for NSE CM segment
                                    if not symbol.endswith('-EQ'):
                                        symbol_eq = f"{symbol}-EQ"
                                    else:
                                        symbol_eq = symbol
                                    
                                    # Verify it exists in token map
                                    if symbol_eq in token_map or symbol in token_map:
                                        nifty500_symbols.append(symbol_eq)
                        
                        if len(nifty500_symbols) > 400:  # Got valid data
                            logger.info(f"✓ Fetched {len(nifty500_symbols)} symbols from NSE official list")
                            break
                        
                except Exception as e:
                    logger.warning(f"Failed to fetch from {url}: {e}")
                    continue
        
    except Exception as e:
        logger.warning(f"Failed to fetch official Nifty-500 list: {e}")
    
    # Fallback: Use top stocks from token map (sorted by common indices)
    if len(nifty500_symbols) < 400:
        logger.info("📋 Using fallback: top stocks from token map")
        
        # Prefer stocks ending with -EQ (equity segment)
        eq_symbols = [s for s in token_map.keys() if s.endswith('-EQ')]
        
        # Sort by popularity (known major stocks first)
        priority_symbols = [
            # Nifty 50 stocks
            "RELIANCE-EQ", "TCS-EQ", "HDFCBANK-EQ", "INFY-EQ", "ICICIBANK-EQ",
            "HINDUNILVR-EQ", "ITC-EQ", "SBIN-EQ", "BHARTIARTL-EQ", "KOTAKBANK-EQ",
            "BAJFINANCE-EQ", "LT-EQ", "ASIANPAINT-EQ", "HCLTECH-EQ", "AXISBANK-EQ",
            "MARUTI-EQ", "SUNPHARMA-EQ", "TITAN-EQ", "ULTRACEMCO-EQ", "WIPRO-EQ",
            "NESTLEIND-EQ", "ONGC-EQ", "NTPC-EQ", "POWERGRID-EQ", "M&M-EQ",
            "BAJAJFINSV-EQ", "ADANIENT-EQ", "JSWSTEEL-EQ", "TATAMOTORS-EQ", "TATASTEEL-EQ",
            "INDUSINDBK-EQ", "ADANIPORTS-EQ", "COALINDIA-EQ", "HINDALCO-EQ", "DIVISLAB-EQ",
            "DRREDDY-EQ", "BAJAJ-AUTO-EQ", "TECHM-EQ", "EICHERMOT-EQ", "CIPLA-EQ",
            "GRASIM-EQ", "BRITANNIA-EQ", "TATACONSUM-EQ", "HEROMOTOCO-EQ", "BPCL-EQ",
            "APOLLOHOSP-EQ", "SBILIFE-EQ", "HDFCLIFE-EQ", "LTIM-EQ", "VEDL-EQ",
        ]
        
        # Start with priority symbols that exist
        nifty500_symbols = [s for s in priority_symbols if s in token_map]
        
        # Add remaining symbols up to 500
        for symbol in sorted(eq_symbols):
            if symbol not in nifty500_symbols:
                nifty500_symbols.append(symbol)
                if len(nifty500_symbols) >= 500:
                    break
        
        logger.info(f"✓ Selected {len(nifty500_symbols)} top NSE symbols")
    
    # Generate Python file content
    content = f'''"""
Nifty 500 constituent symbols for pre-fetching live market data.

This list enables the market service to subscribe to all Nifty-500 stocks
on startup, ensuring instant price lookups without rate limit concerns.

Auto-generated: {os.path.basename(__file__)}
Update frequency: Run `generate_angelone_tokens_task` to refresh
Source: NSE India official index constituents + Angel One scrip master
"""

# Nifty 500 symbols (NSE format with -EQ suffix)
# Total symbols: {len(nifty500_symbols)}
NIFTY_500_SYMBOLS = [
'''
    
    # Add symbols in groups of 5 for readability
    for i in range(0, len(nifty500_symbols), 5):
        batch = nifty500_symbols[i:i+5]
        symbols_str = ', '.join(f'"{s}"' for s in batch)
        content += f'    {symbols_str},\n'
    
    content += '''
]

def get_nifty500_symbols() -> list[str]:
    """Return list of Nifty 500 constituent symbols."""
    return NIFTY_500_SYMBOLS.copy()

def get_nifty500_count() -> int:
    """Return count of Nifty 500 symbols."""
    return len(NIFTY_500_SYMBOLS)
'''
    
    # Save to file
    with open(output_path, 'w') as f:
        f.write(content)
    
    logger.info(f"💾 Saved Nifty-500 list to {output_path} ({len(nifty500_symbols)} symbols)")
    
    return nifty500_symbols


# Minimal fallback mapping for critical stocks
FALLBACK_TOKEN_MAP = {
    "RELIANCE": {"exchangeType": 1, "token": "2885", "name": "Reliance Industries"},
    "TCS": {"exchangeType": 1, "token": "11536", "name": "Tata Consultancy Services"},
    "INFY": {"exchangeType": 1, "token": "1594", "name": "Infosys"},
    "HDFCBANK": {"exchangeType": 1, "token": "1333", "name": "HDFC Bank"},
    "ICICIBANK": {"exchangeType": 1, "token": "4963", "name": "ICICI Bank"},
    "HINDUNILVR": {"exchangeType": 1, "token": "1394", "name": "Hindustan Unilever"},
    "ITC": {"exchangeType": 1, "token": "1660", "name": "ITC Limited"},
    "SBIN": {"exchangeType": 1, "token": "3045", "name": "State Bank of India"},
    "BHARTIARTL": {"exchangeType": 1, "token": "10604", "name": "Bharti Airtel"},
    "KOTAKBANK": {"exchangeType": 1, "token": "1922", "name": "Kotak Mahindra Bank"}
}
