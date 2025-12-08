"""
Company Report Update Celery Tasks

Tasks for updating company reports based on:
1. NSE Filings - Triggered by NSE scraper (general queue)
2. News Articles - Scheduled at market close 3:30 PM IST (news_pipeline queue)

Original Research: Qualitative Database Updation - NSE & News (Colab)
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from celery.utils.log import get_task_logger

# Add paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from celery_app import celery_app, QUEUE_NAMES

task_logger = get_task_logger(__name__)


def _run_async(coro):
    """Helper to run async code in Celery tasks."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a new loop if one is already running
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _download_pdf_as_base64(url: str) -> Optional[str]:
    """Download a PDF from URL and return as base64 string."""
    import requests
    
    if not url or not url.strip():
        return None
    
    try:
        # Ensure URL is complete
        if not url.startswith('http'):
            url = f"https://www.nseindia.com{url}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        
        # Encode to base64
        pdf_base64 = base64.b64encode(response.content).decode('utf-8')
        task_logger.debug(f"Downloaded PDF ({len(response.content)} bytes) from {url[:80]}...")
        return pdf_base64
        
    except Exception as e:
        task_logger.error(f"Failed to download PDF from {url}: {e}")
        return None


# =============================================================================
# NSE Filing Update Task (Triggered by NSE Scraper)
# =============================================================================

@celery_app.task(
    bind=True,
    name="company_report.update_from_nse_filing",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    # acks_late=False by default - safe for auto-retry (prevents duplicate executions on worker crash)
)
def update_company_report_from_nse_filing(
    self,
    ticker: str,
    pdf_base64: str,
    filing_category: str,
    filing_subject: str = "",
    filing_date: str = "",
) -> Dict[str, Any]:
    """
    Celery task to update company report from NSE filing.
    
    This task is triggered by the NSE scraper when a relevant filing is detected.
    Runs on the 'general' queue.
    
    Args:
        ticker: Stock ticker symbol (e.g., "RELIANCE")
        pdf_base64: Base64 encoded PDF content
        filing_category: Category of the filing
        filing_subject: Subject of the announcement
        filing_date: Date of the filing
        
    Returns:
        Dict with update status
    """
    from services.company_report_update_service import (
        get_company_report_update_service,
        RELEVANT_NSE_FILING_CATEGORIES,
    )
    
    task_logger.info(f"📄 Processing NSE filing update for {ticker}: {filing_category}")
    
    try:
        service = get_company_report_update_service()
        
        # Check if filing is relevant
        if not service.is_relevant_nse_filing(filing_category):
            task_logger.info(f"⏭️ Skipping non-relevant filing category: {filing_category}")
            return {
                "status": "skipped",
                "reason": "irrelevant_category",
                "ticker": ticker,
                "filing_category": filing_category,
            }
        
        # Run async update
        result = _run_async(
            service.update_from_nse_filing(
                ticker=ticker,
                pdf_base64=pdf_base64,
                filing_category=filing_category,
                filing_subject=filing_subject,
                filing_date=filing_date,
            )
        )
        
        task_logger.info(f"✅ NSE filing update complete for {ticker}: {result.get('status')}")
        return result
        
    except Exception as e:
        task_logger.error(f"❌ Failed to update {ticker} from NSE filing: {e}", exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="company_report.update_from_nse_filing_url",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    # acks_late=False by default - safe for auto-retry (prevents duplicate executions on worker crash)
    soft_time_limit=300,  # 5 minutes
    time_limit=360,  # 6 minutes
)
def update_company_report_from_nse_filing_url(
    self,
    ticker: str,
    pdf_url: str,
    filing_category: str,
    filing_subject: str = "",
    filing_date: str = "",
) -> Dict[str, Any]:
    """
    Celery task to update company report from NSE filing URL.
    
    This task downloads the PDF from the URL, then processes it.
    Triggered by the NSE pipeline after processing a relevant filing.
    Runs on the 'general' queue.
    
    Args:
        ticker: Stock ticker symbol (e.g., "RELIANCE")
        pdf_url: URL to download the PDF from
        filing_category: Category of the filing
        filing_subject: Subject of the announcement
        filing_date: Date of the filing
        
    Returns:
        Dict with update status
    """
    from services.company_report_update_service import (
        get_company_report_update_service,
        RELEVANT_NSE_FILING_CATEGORIES,
    )
    
    task_logger.info(f"📄 Processing NSE filing update for {ticker} from URL: {filing_category}")
    
    try:
        service = get_company_report_update_service()
        
        # Check if ticker exists in our database first
        ticker_exists = _run_async(service.ticker_exists_in_db(ticker))
        if not ticker_exists:
            task_logger.info(f"⏭️ Skipping {ticker} - ticker not found in database")
            return {
                "status": "skipped",
                "reason": "ticker_not_in_db",
                "ticker": ticker,
                "filing_category": filing_category,
            }
        
        # Check if filing is relevant
        if not service.is_relevant_nse_filing(filing_category):
            task_logger.info(f"⏭️ Skipping non-relevant filing category: {filing_category}")
            return {
                "status": "skipped",
                "reason": "irrelevant_category",
                "ticker": ticker,
                "filing_category": filing_category,
            }
        
        # Download PDF
        task_logger.info(f"📥 Downloading PDF for {ticker} from {pdf_url[:80]}...")
        pdf_base64 = _download_pdf_as_base64(pdf_url)
        
        if not pdf_base64:
            task_logger.warning(f"⚠️ Could not download PDF for {ticker}, skipping update")
            return {
                "status": "skipped",
                "reason": "pdf_download_failed",
                "ticker": ticker,
                "filing_category": filing_category,
            }
        
        # Run async update
        result = _run_async(
            service.update_from_nse_filing(
                ticker=ticker,
                pdf_base64=pdf_base64,
                filing_category=filing_category,
                filing_subject=filing_subject,
                filing_date=filing_date,
            )
        )
        
        task_logger.info(f"✅ NSE filing update complete for {ticker}: {result.get('status')}")
        return result
        
    except Exception as e:
        task_logger.error(f"❌ Failed to update {ticker} from NSE filing URL: {e}", exc_info=True)
        raise


# =============================================================================
# News Update Task (Scheduled at Market Close)
# =============================================================================

@celery_app.task(
    bind=True,
    name="company_report.update_from_news",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    # acks_late=False by default - safe for auto-retry (prevents duplicate executions on worker crash)
)
def update_company_report_from_news(
    self,
    ticker: str,
    news_articles: List[Dict[str, Any]],
    overall_sentiment: float = 0.5,
) -> Dict[str, Any]:
    """
    Celery task to update company report from news articles.
    
    This task is typically called from the batch news update task.
    Runs on the 'news_pipeline' queue.
    
    Args:
        ticker: Stock ticker symbol
        news_articles: List of news article dicts
        overall_sentiment: Aggregated sentiment score
        
    Returns:
        Dict with update status
    """
    from services.company_report_update_service import get_company_report_update_service
    
    task_logger.info(f"📰 Processing news update for {ticker} ({len(news_articles)} articles)")
    
    try:
        service = get_company_report_update_service()
        
        result = _run_async(
            service.update_from_news(
                ticker=ticker,
                news_articles=news_articles,
                overall_sentiment=overall_sentiment,
            )
        )
        
        task_logger.info(f"✅ News update complete for {ticker}: {result.get('status')}")
        return result
        
    except Exception as e:
        task_logger.error(f"❌ Failed to update {ticker} from news: {e}", exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="company_report.batch_update_from_news",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    # acks_late=False by default - safe for auto-retry (prevents duplicate executions on worker crash)
    # Extended time limit for batch processing
    soft_time_limit=3600,  # 1 hour
    time_limit=3900,  # 1 hour 5 min
)
def batch_update_company_reports_from_news(
    self,
    news_by_ticker: Dict[str, List[Dict[str, Any]]],
    sentiments_by_ticker: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Celery task to batch update company reports from daily news.
    
    This task is scheduled to run at market close (3:30 PM IST).
    Runs on the 'news_pipeline' queue.
    
    Args:
        news_by_ticker: Dict mapping ticker to list of news articles
        sentiments_by_ticker: Optional dict mapping ticker to sentiment
        
    Returns:
        Summary of all updates
    """
    from services.company_report_update_service import get_company_report_update_service
    
    task_logger.info(f"📰 Starting batch news update for {len(news_by_ticker)} tickers")
    
    try:
        service = get_company_report_update_service()
        
        result = _run_async(
            service.batch_update_from_news(
                news_by_ticker=news_by_ticker,
                sentiments_by_ticker=sentiments_by_ticker,
            )
        )
        
        task_logger.info(
            f"✅ Batch news update complete: "
            f"{result.get('updated', 0)} updated, "
            f"{result.get('no_update', 0)} unchanged, "
            f"{result.get('errors', 0)} errors"
        )
        return result
        
    except Exception as e:
        task_logger.error(f"❌ Batch news update failed: {e}", exc_info=True)
        raise


# =============================================================================
# Scheduled Task: Daily News-Based Report Update
# =============================================================================

@celery_app.task(
    bind=True,
    name="company_report.daily_news_update",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
    # acks_late=False by default - safe for auto-retry (prevents duplicate executions on worker crash)
    soft_time_limit=7200,  # 2 hours
    time_limit=7500,  # 2 hours 5 min
)
def run_daily_news_report_update(self) -> Dict[str, Any]:
    """
    Scheduled task to run daily news-based company report updates.
    
    This task:
    1. Fetches today's news for all NIFTY 500 stocks
    2. Analyzes and updates reports where material changes detected
    
    Scheduled to run at 3:30 PM IST (market close).
    Runs on the 'news_pipeline' queue.
    
    Returns:
        Summary of updates performed
    """
    import requests
    from datetime import datetime, timedelta
    
    task_logger.info("🕞 Starting daily news-based company report update")
    
    try:
        # Get API keys
        market_api_key = os.getenv("MARKET_API_KEY")
        if not market_api_key:
            task_logger.error("MARKET_API_KEY not found")
            return {"status": "error", "reason": "missing_api_key"}
        
        # Load NIFTY 500 tickers (or use a subset)
        # For now, we'll process tickers that have news from the news pipeline
        # In production, this would integrate with the existing news pipeline
        
        # Get today's date range
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now
        
        # Fetch news for stocks (integrate with existing news pipeline)
        # This is a placeholder - in production, this would get news
        # from the existing news sentiment pipeline or cache
        
        news_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
        sentiments_by_ticker: Dict[str, float] = {}
        
        # Check if we have cached news from the news pipeline
        from pathlib import Path
        news_cache_file = Path(__file__).parent.parent / "data" / "pipeline" / "daily_news_cache.json"
        
        if news_cache_file.exists():
            import json
            try:
                with open(news_cache_file, "r") as f:
                    cached_data = json.load(f)
                    news_by_ticker = cached_data.get("news_by_ticker", {})
                    sentiments_by_ticker = cached_data.get("sentiments", {})
                    task_logger.info(f"📁 Loaded {len(news_by_ticker)} tickers from news cache")
            except Exception as e:
                task_logger.warning(f"Failed to load news cache: {e}")
        
        if not news_by_ticker:
            task_logger.info("📭 No news data available for update")
            return {
                "status": "skipped",
                "reason": "no_news_data",
                "timestamp": now.isoformat(),
            }
        
        # Run batch update
        from services.company_report_update_service import get_company_report_update_service
        
        service = get_company_report_update_service()
        result = _run_async(
            service.batch_update_from_news(
                news_by_ticker=news_by_ticker,
                sentiments_by_ticker=sentiments_by_ticker,
            )
        )
        
        result["timestamp"] = now.isoformat()
        task_logger.info(f"✅ Daily news update complete: {result}")
        return result
        
    except Exception as e:
        task_logger.error(f"❌ Daily news update failed: {e}", exc_info=True)
        raise


# =============================================================================
# Helper function to trigger NSE filing update from scraper
# =============================================================================

def trigger_nse_filing_update(
    ticker: str,
    pdf_base64: str,
    filing_category: str,
    filing_subject: str = "",
    filing_date: str = "",
    async_mode: bool = True,
) -> Optional[str]:
    """
    Helper function to trigger NSE filing update task.
    
    Called by the NSE scraper when a relevant filing is detected.
    
    Args:
        ticker: Stock ticker symbol
        pdf_base64: Base64 encoded PDF content
        filing_category: Category of the filing
        filing_subject: Subject of the announcement
        filing_date: Date of the filing
        async_mode: If True, queue task; if False, run synchronously
        
    Returns:
        Task ID if async, or result dict if sync
    """
    from services.company_report_update_service import RELEVANT_NSE_FILING_CATEGORIES
    
    # Quick check if category is relevant
    category_lower = filing_category.lower().strip()
    is_relevant = any(
        rel.lower() in category_lower or category_lower in rel.lower()
        for rel in RELEVANT_NSE_FILING_CATEGORIES
    )
    
    if not is_relevant:
        task_logger.debug(f"Skipping non-relevant filing: {filing_category}")
        return None
    
    if async_mode:
        # Queue the task
        result = update_company_report_from_nse_filing.apply_async(
            args=[ticker, pdf_base64, filing_category, filing_subject, filing_date],
            queue=QUEUE_NAMES.get("general", "general"),
        )
        task_logger.info(f"📤 Queued NSE filing update for {ticker} (task_id: {result.id})")
        return result.id
    else:
        # Run synchronously
        return update_company_report_from_nse_filing(
            ticker, pdf_base64, filing_category, filing_subject, filing_date
        )


def trigger_nse_filing_update_url(
    ticker: str,
    filing_subject: str,
    attachment_url: str,
    filing_date: Optional[str] = None,
    async_mode: bool = True
) -> Optional[str]:
    """
    Helper to trigger NSE filing update from URL.
    This is used by the NSE pipeline when attachment URL is available.
    
    Args:
        ticker: Stock ticker symbol
        filing_subject: Subject/category of the filing
        attachment_url: URL to download the filing PDF
        filing_date: Date of filing (optional)
        async_mode: Whether to queue async (True) or run sync (False)
        
    Returns:
        Task ID if async, or result dict if sync
    """
    from services.company_report_update_service import RELEVANT_NSE_FILING_CATEGORIES
    
    # Quick check if filing subject is relevant
    subject_lower = filing_subject.lower().strip()
    is_relevant = any(
        rel.lower() in subject_lower or subject_lower in rel.lower()
        for rel in RELEVANT_NSE_FILING_CATEGORIES
    )
    
    if not is_relevant:
        task_logger.debug(f"Skipping non-relevant filing: {filing_subject}")
        return None
    
    if async_mode:
        # Queue the task
        result = update_company_report_from_nse_filing_url.apply_async(
            args=[ticker, filing_subject, attachment_url, filing_date],
            queue=QUEUE_NAMES.get("general", "general"),
        )
        task_logger.info(f"📤 Queued NSE filing URL update for {ticker} (task_id: {result.id})")
        return result.id
    else:
        # Run synchronously
        return update_company_report_from_nse_filing_url(
            ticker, filing_subject, attachment_url, filing_date
        )
