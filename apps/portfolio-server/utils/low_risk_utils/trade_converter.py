"""
Trade Converter

Converts final portfolio recommendations into executable trade records
with share quantities and investment amounts.
"""

import logging
import asyncio
import sys
from pathlib import Path
from typing import List, Dict, Any
from decimal import Decimal

# Add shared/py to sys.path
shared_dir = Path(__file__).resolve().parent.parent.parent.parent.parent / "shared" / "py"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))

from market_data import get_market_data_service

logger = logging.getLogger(__name__)


async def _fetch_price_from_market_service(ticker: str) -> Decimal:
    """
    Fetch current price using market service.
    
    Args:
        ticker: NSE ticker symbol
        
    Returns:
        Current price as Decimal
        
    Raises:
        ValueError: If price not available
    """
    try:
        market_service = get_market_data_service()
        
        # Check if symbol exists in Angel One token map first
        if not market_service.has_symbol(ticker):
            similar = market_service.search_similar_symbols(ticker, limit=3)
            similar_msg = f" Similar: {', '.join(similar)}" if similar else ""
            logger.warning(f"⚠️ Symbol {ticker} not found in Angel One token map.{similar_msg}")
            raise ValueError(f"Symbol '{ticker}' not available in Angel One.{similar_msg}")
        
        # Use await_price() with longer timeout for WebSocket data
        logger.debug(f"📡 Fetching price for {ticker}...")
        price = await market_service.await_price(ticker, timeout=10.0)
        logger.debug(f"✅ Got price for {ticker}: ₹{price}")
        return price
        
    except Exception as e:
        logger.error(f"Error fetching price for {ticker} from market service: {e}")
        raise ValueError(f"Failed to fetch price for {ticker}: {e}")


def trade_converter(final_portfolio: List[Dict[str, Any]], fund_allocated: float) -> List[Dict[str, Any]]:
    """
    Convert portfolio recommendations into trade records with share quantities.
    Uses market service for live price data.
    
    Args:
        final_portfolio: List of ticker dictionaries with 'ticker', 'percentage', 'reasoning'
        fund_allocated: Total fund amount to be allocated across tickers
        
    Returns:
        List of trade records with ticker, amount_invested, no_of_shares_bought, reasoning, percentage
        
    Example:
        >>> final_portfolio = [
        ...     {'ticker': 'RELIANCE', 'percentage': 0.3, 'reasoning': 'Strong fundamentals'},
        ...     {'ticker': 'TCS', 'percentage': 0.25, 'reasoning': 'IT sector leader'}
        ... ]
        >>> trades = trade_converter(final_portfolio, fund_allocated=100000)
    """
    
    async def _convert_async():
        trade_list = []
        
        for ticker_dict in final_portfolio:
            ticker = ticker_dict['ticker']
            
            try:
                # Fetch price from market service
                current_price = await _fetch_price_from_market_service(ticker)
                
                # percentage is like 30.0 meaning 30%, so divide by 100 to get ratio
                percentage_ratio = Decimal(str(ticker_dict['percentage'])) / Decimal('100')
                amount_to_invest = Decimal(str(fund_allocated)) * percentage_ratio
                n_shares = int(amount_to_invest // current_price)
                
                if n_shares > 0:
                    trade_record = {
                        'ticker': ticker,
                        'amount_invested': float(current_price * n_shares),
                        'no_of_shares_bought': n_shares,
                        'price_bought': float(current_price),
                        'reasoning': ticker_dict['reasoning'],
                        'percentage': ticker_dict['percentage']
                    }
                    trade_list.append(trade_record)
                    logger.info(f"✓ Trade created for {ticker}: {n_shares} shares @ ₹{current_price}")
                else:
                    logger.warning(f"⚠ Insufficient funds to buy {ticker} at ₹{current_price}")
                    
            except Exception as e:
                logger.error(f"❌ Failed to create trade for {ticker}: {e}")
                continue
        
        return trade_list
    
    # Run async function in event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, create a new task
            import nest_asyncio
            nest_asyncio.apply()
        return loop.run_until_complete(_convert_async())
    except RuntimeError:
        # Create new event loop if none exists
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_convert_async())
        finally:
            loop.close()
