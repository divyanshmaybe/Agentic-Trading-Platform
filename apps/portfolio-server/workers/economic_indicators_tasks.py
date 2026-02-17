"""
Celery tasks for updating economic indicators

Runs scrapers for Trading Economics and CPI data on scheduled basis (21st of month).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any

# Add server directory to path
server_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(server_dir))

from celery_app import celery_app
from utils.economic_indicators_storage import get_storage
import asyncio

task_logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="economic_indicators.update_trading_economics",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def update_trading_economics_indicators(self) -> Dict[str, Any]:
    """
    Celery task that updates Trading Economics indicator data.
    
    This task is scheduled to run on the 21st of each month via Celery Beat.
    It scrapes Indian economic indicators from Trading Economics website.
    
    Returns:
        Dict with update results
    """
    from redis import Redis
    from celery_app import BROKER_URL
    
    # Acquire lock to prevent concurrent execution
    redis_client = Redis.from_url(BROKER_URL)
    lock_key = "task:trading_economics:lock"
    
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=600)  # 10 min TTL
    
    if not lock_acquired:
        task_logger.warning("⚠️ Trading Economics update already running, skipping")
        return {"success": False, "skipped": True, "reason": "Task already running"}
    
    try:
        task_logger.info("📊 Starting Trading Economics indicators update...")

        # Import scraper
        from pipelines.low_risk.india_economic_scraper import IndiaEconomicScraper

        # Initialize scraper and run
        scraper = IndiaEconomicScraper()
        df = scraper.scrape()

        if df.empty:
            task_logger.warning("⚠️ Trading Economics scraper returned empty data")
            return {
                "success": False,
                "scraper": "trading_economics",
                "rows": 0,
                "error": "Empty data returned",
            }

        # Store data with write lock
        storage = get_storage()
        storage.write_indicators("trading_economics", df)

        task_logger.info(
            f"✅ Trading Economics indicators updated: {len(df)} rows"
        )

        return {
            "success": True,
            "scraper": "trading_economics",
            "rows": len(df),
            "columns": list(df.columns),
        }

    except Exception as exc:
        task_logger.error(
            "❌ Failed to update Trading Economics indicators: %s", exc, exc_info=True
        )
        raise
    
    finally:
        redis_client.delete(lock_key)
        task_logger.info("🔓 Trading Economics lock released")


@celery_app.task(
    bind=True,
    name="economic_indicators.update_cpi",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def update_cpi_indicators(self) -> Dict[str, Any]:
    """
    Celery task that updates CPI (Consumer Price Index) data.
    
    This task is scheduled to run on the 21st of each month via Celery Beat.
    It scrapes CPI data for all Indian states from MOSPI website.
    
    Returns:
        Dict with update results
    """
    from redis import Redis
    from celery_app import BROKER_URL
    
    # Acquire lock to prevent concurrent execution
    redis_client = Redis.from_url(BROKER_URL)
    lock_key = "task:cpi:lock"
    
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=600)  # 10 min TTL
    
    if not lock_acquired:
        task_logger.warning("⚠️ CPI update already running, skipping")
        return {"success": False, "skipped": True, "reason": "Task already running"}
    
    try:
        task_logger.info("📊 Starting CPI indicators update...")

        # Import scraper
        from pipelines.low_risk.cpi_scraper import CPIScraperFixed

        # Initialize scraper and run
        scraper = CPIScraperFixed()
        df = scraper.scrape()

        if df.empty:
            task_logger.warning("⚠️ CPI scraper returned empty data")
            return {
                "success": False,
                "scraper": "cpi",
                "rows": 0,
                "error": "Empty data returned",
            }

        # Store data with write lock
        storage = get_storage()
        storage.write_indicators("cpi", df)

        task_logger.info(f"✅ CPI indicators updated: {len(df)} rows")

        return {
            "success": True,
            "scraper": "cpi",
            "rows": len(df),
            "columns": list(df.columns),
        }

    except Exception as exc:
        task_logger.error(
            "❌ Failed to update CPI indicators: %s", exc, exc_info=True
        )
        raise
    
    finally:
        redis_client.delete(lock_key)
        task_logger.info("🔓 CPI lock released")


@celery_app.task(
    bind=True,
    name="economic_indicators.update_industry_indicators",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def update_industry_indicators(self) -> Dict[str, Any]:
    """
    Celery task that updates industry indicators data.
    
    This task is scheduled to run daily/weekly via Celery Beat.
    It fetches historical market data from Angel One API and computes
    technical indicators aggregated by industry.
    
    Returns:
        Dict with update results
    """
    import time
    from redis import Redis
    from celery_app import BROKER_URL
    
    start_time = time.time()
    
    # Acquire lock to prevent concurrent execution
    redis_client = Redis.from_url(BROKER_URL)
    lock_key = "task:industry_indicators:lock"
    
    # Try to acquire lock (10 minute TTL)
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=600)
    
    if not lock_acquired:
        task_logger.warning("⚠️ Industry indicators update already running, skipping this execution")
        return {
            "success": False,
            "skipped": True,
            "reason": "Task already running"
        }
    
    try:
        task_logger.info("📊 Starting industry indicators update...")

        # Get configuration from environment
        stocks_csv_path = os.getenv(
            "INDUSTRY_INDICATORS_STOCKS_CSV",
            "scripts/nifty_500_stats.csv"
        )
        period = os.getenv("INDUSTRY_INDICATORS_PERIOD", "1y")
        interval = os.getenv("INDUSTRY_INDICATORS_INTERVAL", "1d")
        benchmark_ticker = os.getenv("INDUSTRY_INDICATORS_BENCHMARK", "^CRSLDX")

        # Check if stocks CSV exists
        stocks_path = Path(stocks_csv_path)
        if not stocks_path.is_absolute():
            # Try relative to server directory first
            stocks_path = server_dir / stocks_csv_path
            if not stocks_path.exists():
                # Try relative to project root
                project_root = server_dir.parent.parent
                stocks_path = project_root / stocks_csv_path
        
        if not stocks_path.exists():
            task_logger.error(f"❌ Stocks CSV file not found: {stocks_path}")
            return {
                "success": False,
                "error": f"Stocks CSV file not found: {stocks_path}",
            }

        # Import required modules
        from pipelines.low_risk.industry_indicators_pipeline import IndustryIndicatorsPipeline
        from pipelines.low_risk.angelone_batch_fetcher import create_fetcher_from_market_service
        from shared.py.market_data import get_market_data_service

        # Initialize MarketDataService and create batch fetcher
        task_logger.info("🔧 Initializing Angel One API connection...")
        market_service = get_market_data_service()
        fetcher = create_fetcher_from_market_service(market_service)

        # Initialize pipeline
        task_logger.info(f"📈 Initializing Industry Indicators Pipeline (period={period}, interval={interval})...")
        pipeline = IndustryIndicatorsPipeline(
            stocks_csv_path=str(stocks_path),
            angel_one_fetcher=fetcher,
            period=period,
            interval=interval,
            benchmark_ticker=benchmark_ticker,
            rsi_length=14
        )

        # Run computation (async)
        task_logger.info("🚀 Computing industry indicators...")
        per_ticker_df, industry_summary_df = pipeline.compute()

        if per_ticker_df.is_empty() or industry_summary_df.is_empty():
            task_logger.warning("⚠️ Pipeline returned empty data")
            return {
                "success": False,
                "error": "Empty data returned from pipeline",
                "per_ticker_rows": 0,
                "industry_rows": 0,
            }

        # Store data with write lock
        storage = get_storage()
        storage.write_industry_indicators(
            per_ticker_df=per_ticker_df,
            industry_summary_df=industry_summary_df,
            metadata={
                "period": period,
                "interval": interval,
                "benchmark_ticker": benchmark_ticker,
                "stocks_csv": str(stocks_path),
            }
        )

        execution_time = time.time() - start_time
        per_ticker_count = len(per_ticker_df)
        industry_count = len(industry_summary_df)

        task_logger.info(
            f"✅ Industry indicators updated: {per_ticker_count} per-ticker rows, "
            f"{industry_count} industry rows (took {execution_time:.2f}s)"
        )

        return {
            "success": True,
            "per_ticker_rows": per_ticker_count,
            "industry_rows": industry_count,
            "execution_time_seconds": round(execution_time, 2),
            "period": period,
            "interval": interval,
        }

    except Exception as exc:
        execution_time = time.time() - start_time
        task_logger.error(
            f"❌ Failed to update industry indicators (took {execution_time:.2f}s): %s",
            exc,
            exc_info=True
        )
        raise
    
    finally:
        # Release lock
        redis_client.delete(lock_key)
        task_logger.info("🔓 Industry indicators lock released")


def check_and_update_on_startup():
    """
    Check if data needs updating on startup and trigger updates if needed.
    
    This function is called from celery_app.py during initialization.
    It checks if data files exist or are older than 30 days, and if so,
    queues immediate updates for both scrapers.
    """
    try:
        task_logger.info("🔍 Checking economic indicators on startup...")

        storage = get_storage()

        # Check both scrapers
        scrapers_to_update = []

        for scraper_name in ["trading_economics", "cpi"]:
            if storage.check_if_update_needed(scraper_name, max_age_days=30):
                scrapers_to_update.append(scraper_name)
                task_logger.info(
                    f"  → {scraper_name} needs update (missing or >30 days old)"
                )
            else:
                last_update = storage.get_last_update_time(scraper_name)
                if last_update:
                    task_logger.info(
                        f"  ✓ {scraper_name} is up to date (last updated: {last_update})"
                    )

        # Check industry indicators (DISABLED by default)
        industry_indicators_enabled = os.getenv(
            "INDUSTRY_INDICATORS_ENABLED", "false"
        ).lower() in {"1", "true", "yes"}

        if industry_indicators_enabled:
            if storage.check_industry_indicators_update_needed(max_age_days=7):
                scrapers_to_update.append("industry_indicators")
                task_logger.info(
                    "  → industry_indicators needs update (missing or >7 days old)"
                )
            else:
                last_update = storage.get_last_update_time("industry_indicators_summary")
                if last_update:
                    task_logger.info(
                        f"  ✓ industry_indicators is up to date (last updated: {last_update})"
                    )

        # Queue updates for scrapers that need it
        if scrapers_to_update:
            task_logger.info(
                f"🚀 Queueing immediate updates for: {', '.join(scrapers_to_update)}"
            )

            if "trading_economics" in scrapers_to_update:
                celery_app.send_task(
                    "economic_indicators.update_trading_economics",
                    queue=os.getenv("ECONOMIC_INDICATORS_QUEUE", "market"),
                )

            if "cpi" in scrapers_to_update:
                celery_app.send_task(
                    "economic_indicators.update_cpi",
                    queue=os.getenv("ECONOMIC_INDICATORS_QUEUE", "market"),
                )

            if "industry_indicators" in scrapers_to_update:
                celery_app.send_task(
                    "economic_indicators.update_industry_indicators",
                    queue=os.getenv("INDUSTRY_INDICATORS_QUEUE", "market"),
                )

            task_logger.info("✅ Startup update tasks queued")
        else:
            task_logger.info("✅ All economic indicators are up to date")

    except Exception as exc:
        task_logger.error(
            "❌ Failed to check economic indicators on startup: %s", exc, exc_info=True
        )
        # Don't raise - startup check failure shouldn't prevent app from starting

