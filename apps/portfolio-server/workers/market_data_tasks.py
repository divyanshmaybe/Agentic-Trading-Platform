"""
Celery tasks for market data price fetching with HTTP API fallback.
DO NOT use WebSocket/Pathway in Celery workers - it creates duplicate connections!
"""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
from decimal import Decimal
import requests

from celery import shared_task

logger = logging.getLogger(__name__)

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY") or "d46u2mpr01qgc9euka70d46u2mpr01qgc9euka7g"
FINNHUB_API_URL = "https://finnhub.io/api/v1/quote"


@shared_task(
    name="market_data.fetch_via_api",
    bind=True,
    max_retries=3,
    default_retry_delay=1,
)
def fetch_price_via_api(self, symbol: str) -> Optional[float]:
    """
    Fetch price via Finnhub REST API (fallback, not WebSocket).
    
    Args:
        symbol: Stock symbol
        
    Returns:
        Current price or None
    """
    normalized = symbol.upper().strip()
    logger.info(f"📊 Fetching {normalized} via Finnhub API")
    
    try:
        response = requests.get(
            FINNHUB_API_URL,
            params={"symbol": normalized, "token": FINNHUB_API_KEY},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            price = data.get("c")  # Current price
            
            if price and price > 0:
                logger.info(f"✅ {normalized}: ${price}")
                return float(price)
            else:
                logger.warning(f"⚠️ {normalized}: No price data in response")
                return None
        else:
            logger.error(f"❌ {normalized}: API returned {response.status_code}")
            return None
            
    except Exception as exc:
        logger.error(f"❌ Error fetching {normalized}: {exc}")
        raise self.retry(exc=exc)


@shared_task(name="market_data.batch_fetch_via_api")
def batch_fetch_via_api(symbols: List[str]) -> Dict[str, Optional[float]]:
    """
    Batch fetch prices via REST API (not WebSocket).
    
    Args:
        symbols: List of stock symbols
        
    Returns:
        Dict mapping symbol to price
    """
    logger.info(f"� Batch fetching {len(symbols)} symbols via API")
    
    results = {}
    for symbol in symbols:
        normalized = symbol.upper().strip()
        if normalized:
            price = fetch_price_via_api(normalized)
            results[normalized] = price
    
    return results


@shared_task(name="market_data.health_check_api")
def check_api_health() -> Dict[str, any]:
    """
    Check Finnhub API health.
    
    Returns:
        Health status dict
    """
    try:
        response = requests.get(
            FINNHUB_API_URL,
            params={"symbol": "AAPL", "token": FINNHUB_API_KEY},
            timeout=5
        )
        
        return {
            "status": "healthy" if response.status_code == 200 else "unhealthy",
            "provider": "finnhub-api",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error(f"❌ API health check failed: {exc}")
        return {
            "status": "unhealthy",
            "error": str(exc),
            "timestamp": datetime.utcnow().isoformat(),
        }

