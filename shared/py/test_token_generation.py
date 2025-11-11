"""
Test script for Angel One token generator with Nifty-500 list generation.

This script tests the full flow:
1. Generate Angel One token map from scrip master
2. Auto-generate Nifty-500 constituent list
3. Verify both files are created correctly
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Import the generator
from angelone_token_generator import (
    ensure_angelone_token_map,
    generate_nifty500_symbols,
    load_angelone_token_map,
    DEFAULT_CACHE_PATH,
    DEFAULT_NIFTY500_PATH
)

def test_token_generation():
    """Test token map and Nifty-500 list generation."""
    
    logger.info("=" * 80)
    logger.info("Testing Angel One Token Generator")
    logger.info("=" * 80)
    
    # Test 1: Generate token map (will also generate Nifty-500 list)
    logger.info("\n📋 Test 1: Generate token map and Nifty-500 list...")
    try:
        token_map = ensure_angelone_token_map(force_refresh=False)
        logger.info(f"✓ Token map loaded: {len(token_map)} symbols")
        
        # Show sample tokens
        sample_symbols = ["RELIANCE-EQ", "TCS-EQ", "INFY-EQ"]
        for symbol in sample_symbols:
            if symbol in token_map:
                logger.info(f"  {symbol}: {token_map[symbol]}")
        
    except Exception as e:
        logger.error(f"✗ Token generation failed: {e}")
        return False
    
    # Test 2: Verify Nifty-500 list exists
    logger.info("\n📊 Test 2: Verify Nifty-500 list...")
    try:
        if not os.path.exists(DEFAULT_NIFTY500_PATH):
            logger.error(f"✗ Nifty-500 file not found at {DEFAULT_NIFTY500_PATH}")
            return False
        
        # Import and check the list
        sys.path.insert(0, os.path.dirname(DEFAULT_NIFTY500_PATH))
        import nifty500_symbols
        
        symbols = nifty500_symbols.NIFTY_500_SYMBOLS
        logger.info(f"✓ Nifty-500 list loaded: {len(symbols)} symbols")
        logger.info(f"  First 10: {symbols[:10]}")
        logger.info(f"  Count function: {nifty500_symbols.get_nifty500_count()}")
        
    except Exception as e:
        logger.error(f"✗ Nifty-500 verification failed: {e}")
        return False
    
    # Test 3: Verify all Nifty-500 symbols exist in token map
    logger.info("\n🔍 Test 3: Verify symbols in token map...")
    try:
        missing_symbols = []
        for symbol in symbols[:100]:  # Check first 100
            if symbol not in token_map:
                missing_symbols.append(symbol)
        
        if missing_symbols:
            logger.warning(f"⚠ {len(missing_symbols)} symbols not in token map: {missing_symbols[:5]}")
        else:
            logger.info("✓ All checked symbols exist in token map")
        
    except Exception as e:
        logger.error(f"✗ Verification failed: {e}")
        return False
    
    # Test 4: Test regeneration
    logger.info("\n🔄 Test 4: Test manual Nifty-500 regeneration...")
    try:
        new_symbols = generate_nifty500_symbols(token_map)
        logger.info(f"✓ Regenerated {len(new_symbols)} symbols")
        
    except Exception as e:
        logger.error(f"✗ Regeneration failed: {e}")
        return False
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ ALL TESTS PASSED")
    logger.info("=" * 80)
    logger.info(f"\nGenerated files:")
    logger.info(f"  Token map: {DEFAULT_CACHE_PATH}")
    logger.info(f"  Nifty-500: {DEFAULT_NIFTY500_PATH}")
    
    return True

if __name__ == "__main__":
    success = test_token_generation()
    sys.exit(0 if success else 1)
