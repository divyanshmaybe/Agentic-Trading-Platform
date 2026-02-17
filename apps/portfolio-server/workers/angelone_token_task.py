"""
Celery task for Angel One token map and Nifty-500 list generation.
Runs asynchronously at server startup to:
1. Download and cache NSE stock tokens from Angel One scrip master
2. Generate Nifty-500 constituent list for market data pre-fetching
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="market_data.generate_angelone_tokens",
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def generate_angelone_tokens_task(self, force_refresh: bool = False):
    """
    Celery task to generate Angel One token map and Nifty-500 list asynchronously.
    
    This task:
    1. Downloads Angel One scrip master (8000+ NSE stocks)
    2. Generates token map for real-time market data subscriptions
    3. Auto-generates Nifty-500 constituent list for pre-fetching optimization
    
    Args:
        force_refresh: If True, regenerate even if cache exists.
        
    Returns:
        dict: Status and count of generated tokens and symbols
    """
    try:
        from angelone_token_generator import ensure_angelone_token_map
        
        logger.info(f"🚀 Starting Angel One token map + Nifty-500 generation (force_refresh={force_refresh})")
        
        token_map = ensure_angelone_token_map(force_refresh=force_refresh)
        
        result = {
            "status": "success",
            "count": len(token_map),
            "message": f"✅ Generated token map ({len(token_map):,} symbols) + Nifty-500 list"
        }
        
        logger.info(f"{result['message']}")
        return result
        
    except Exception as exc:
        logger.error(f"❌ Angel One data generation failed: {exc}", exc_info=True)
        
        # Retry on failure
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "status": "failed",
                "error": str(exc),
                "message": "Max retries exceeded for token/Nifty-500 generation"
            }
