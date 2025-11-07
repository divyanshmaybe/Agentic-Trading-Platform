"""
Celery task for Angel One token map generation.
Runs asynchronously at server startup to download and cache NSE stock tokens.
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
    Celery task to generate Angel One token map asynchronously.
    
    Args:
        force_refresh: If True, regenerate even if cache exists.
        
    Returns:
        dict: Status and count of generated tokens
    """
    try:
        from angelone_token_generator import ensure_angelone_token_map
        
        logger.info(f"🚀 Starting Angel One token map generation (force_refresh={force_refresh})")
        
        token_map = ensure_angelone_token_map(force_refresh=force_refresh)
        
        result = {
            "status": "success",
            "count": len(token_map),
            "message": f"Generated token map for {len(token_map):,} NSE symbols"
        }
        
        logger.info(f"✅ {result['message']}")
        return result
        
    except Exception as exc:
        logger.error(f"❌ Angel One token generation failed: {exc}", exc_info=True)
        
        # Retry on failure
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "status": "failed",
                "error": str(exc),
                "message": "Max retries exceeded for token map generation"
            }
