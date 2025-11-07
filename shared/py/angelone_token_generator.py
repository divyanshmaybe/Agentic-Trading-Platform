"""
Angel One token map generator - Celery task for async generation.
Downloads the Angel One scrip master file and generates a token mapping
for all NSE stocks to enable real-time market data subscriptions.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Default cache location
DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../apps/portfolio-server/docs/angelone_tokens.json"
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
            
            if not symbol or not token:
                continue
            
            # NSE Cash Market
            if exch_seg == 'NSE':
                nse_stocks[symbol] = {
                    "exchangeType": 1,
                    "token": token,
                    "name": name,
                    "segment": "NSE"
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
        popular_symbols = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK']
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
        return generate_angelone_token_map(cache_path)
    
    # Load from cache
    try:
        return load_angelone_token_map(cache_path)
    except Exception as e:
        logger.warning(f"Failed to load cache ({e}), regenerating...")
        return generate_angelone_token_map(cache_path)


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
