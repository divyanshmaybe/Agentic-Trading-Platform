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

            task_logger.info("✅ Startup update tasks queued")
        else:
            task_logger.info("✅ All economic indicators are up to date")

    except Exception as exc:
        task_logger.error(
            "❌ Failed to check economic indicators on startup: %s", exc, exc_info=True
        )
        # Don't raise - startup check failure shouldn't prevent app from starting

