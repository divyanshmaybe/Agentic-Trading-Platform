"""
Trade Converter

Converts final portfolio recommendations into executable trade records
with share quantities and investment amounts.
"""

import logging
import yfinance as yf
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def trade_converter(final_portfolio: List[Dict[str, Any]], fund_allocated: float) -> List[Dict[str, Any]]:
    """
    Convert portfolio recommendations into trade records with share quantities.
    
    Args:
        final_portfolio: List of ticker dictionaries with 'ticker', 'percentage', 'reasoning'
        fund_allocated: Total fund amount to be allocated across tickers
        
    Returns:
        List of trade records with ticker, amount_invested, no_of_shares_bought, reasoning, percentage
        
    Example:
        >>> final_portfolio = [
        ...     {'ticker': 'RELIANCE.NS', 'percentage': 0.3, 'reasoning': 'Strong fundamentals'},
        ...     {'ticker': 'TCS.NS', 'percentage': 0.25, 'reasoning': 'IT sector leader'}
        ... ]
        >>> trades = trade_converter(final_portfolio, fund_allocated=100000)
    """
    trade_list = []

    for ticker_dict in final_portfolio:
        trade_record = {}
        ticker = ticker_dict['ticker']
        
        # Add .NS suffix for NSE tickers if not already present
        yf_ticker = ticker if ticker.endswith('.NS') else f"{ticker}.NS"
        
        try:
            current_price = yf.Ticker(yf_ticker).history(period='1d')['Close'].iloc[-1]
        except Exception as e:
            logger.error(f"Error fetching price for {ticker}: {e}")
            current_price = 0
            continue

        amount_to_invest = fund_allocated * ticker_dict['percentage']
        n_shares = amount_to_invest // current_price

        trade_record['ticker'] = ticker
        trade_record['amount_invested'] = current_price * n_shares
        trade_record['no_of_shares_bought'] = n_shares
        trade_record['reasoning'] = ticker_dict['reasoning']
        trade_record['percentage'] = ticker_dict['percentage']
        trade_list.append(trade_record)
        
    return trade_list
