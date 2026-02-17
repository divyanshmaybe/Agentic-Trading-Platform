"""
Low Risk Pipeline Celery Tasks

Provides production-ready task execution for the low-risk stock selection pipeline
with comprehensive concurrency control, status tracking, error handling, and Kafka logging.
"""

from __future__ import annotations

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import time
from celery.utils.log import get_task_logger
from redis import Redis

# Add project paths
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

# Add portfolio-server to path
PORTFOLIO_SERVER_PATH = Path(__file__).resolve().parents[1]
if str(PORTFOLIO_SERVER_PATH) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_PATH))

from celery_app import celery_app, BROKER_URL
from utils.low_risk_utils import LowRiskKafkaPublisher, publish_to_kafka

task_logger = get_task_logger(__name__)


class PipelineStatus:
    """Pipeline status tracking via Redis"""

    def __init__(self, redis_client: Redis, user_id: str):
        self.redis = redis_client
        self.user_id = user_id
        self.status_key = f"pipeline:low_risk:{user_id}:status"
        self.lock_key = f"pipeline:low_risk:{user_id}:lock"
        self.start_time_key = f"pipeline:low_risk:{user_id}:start_time"

    def is_running(self) -> tuple[bool, Optional[float]]:
        """
        Check if pipeline is currently running for this user.

        Returns:
            Tuple of (is_running, start_timestamp_or_None)
        """
        lock_exists = self.redis.exists(self.lock_key)
        if lock_exists:
            start_time = self.redis.get(self.start_time_key)
            if start_time:
                return True, float(start_time.decode())
            return True, None
        return False, None

    def acquire_lock(self, ttl: int = 1800) -> bool:
        """
        Acquire pipeline lock (30 minute default TTL for safety).

        Args:
            ttl: Lock time-to-live in seconds (default: 1800 = 30 minutes)

        Returns:
            True if lock acquired, False if already locked
        """
        now = time.time()
        # Use SET with NX (only set if not exists) and EX (expiration)
        lock_acquired = self.redis.set(self.lock_key, "locked", nx=True, ex=ttl)

        if lock_acquired:
            # Store start time for duration tracking
            self.redis.set(self.start_time_key, str(now), ex=ttl)
            self.redis.set(self.status_key, "running", ex=ttl + 300)  # Status lives 5 min longer
            task_logger.info(f"✅ Low-risk pipeline lock acquired for user {self.user_id}")
            return True

        task_logger.warning(f"⚠️ Low-risk pipeline already running for user {self.user_id}")
        return False

    def release_lock(self):
        """Release pipeline lock and update status"""
        self.redis.delete(self.lock_key)
        self.redis.delete(self.start_time_key)
        self.redis.set(self.status_key, "completed", ex=3600)  # Keep status for 1 hour
        task_logger.info(f"🔓 Low-risk pipeline lock released for user {self.user_id}")

    def set_error(self, error_message: str):
        """Mark pipeline as failed with error message"""
        self.redis.delete(self.lock_key)
        self.redis.delete(self.start_time_key)
        error_data = json.dumps({
            "status": "failed",
            "error": error_message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self.redis.set(self.status_key, error_data, ex=3600)
        task_logger.error(f"❌ Low-risk pipeline failed for user {self.user_id}: {error_message}")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current pipeline status for user.

        Returns:
            Dictionary with status information
        """
        is_running, start_time = self.is_running()

        if is_running:
            elapsed_minutes = 0
            if start_time:
                elapsed_minutes = int((time.time() - start_time) / 60)

            return {
                "running": True,
                "status": "running",
                "start_time": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat() if start_time else None,
                "elapsed_minutes": elapsed_minutes
            }

        # Check stored status
        status_data = self.redis.get(self.status_key)
        if status_data:
            status_str = status_data.decode()
            try:
                # Try parsing as JSON (error status)
                status_obj = json.loads(status_str)
                return {
                    "running": False,
                    **status_obj
                }
            except json.JSONDecodeError:
                # Simple string status
                return {
                    "running": False,
                    "status": status_str
                }

        return {
            "running": False,
            "status": "not_started"
        }


@celery_app.task(
    bind=True,
    name="pipeline.low_risk.run",
    # DO NOT use autoretry_for - it causes task duplication on success
    acks_late=False,  # Acknowledge immediately to prevent re-queuing
    reject_on_worker_lost=True,
    soft_time_limit=3600*3,  # 3 hours (no SoftTimeLimitExceeded interruption)
    time_limit=3600*3,  # 3 hours hard limit
)
def run_low_risk_pipeline(
    self,
    user_id: str,
    fund_allocated: float = 100000.0,
    rebalance: bool = False,
    prev_summary: Dict[str, Any] = {},
    _skip_lock: bool = False,  # Internal flag: lock already acquired in route
) -> Dict[str, Any]:
    """
    Execute the low-risk stock selection pipeline for a specific user.

    This task:
    1. Acquires a user-specific lock to prevent concurrent executions (if not already acquired)
    2. Loads required data (company CSV, economic indicators)
    3. Runs industry selection → stock selection → trade generation
    4. Publishes progress updates via Kafka to frontend
    5. Returns summary of trades generated

    Args:
        user_id: User ID for pipeline execution and Kafka routing
        fund_allocated: Total fund amount to allocate (default: ₹100,000)
        rebalance: Whether this is a rebalance operation
        prev_summary: Previous summary for rebalancing
        _skip_lock: Internal flag - set to True if lock already acquired by caller

    Returns:
        Dictionary with pipeline results and summary

    Raises:
        Various exceptions if pipeline fails (logged and returned as error)
    """
    # Log parameters instead of print (print can cause serialization issues)
    task_logger.info(f"Starting pipeline: rebalance={rebalance}, prev_summary keys: {list(prev_summary.keys()) if prev_summary else 'None'}")
    
    import pandas as pd
    from dotenv import load_dotenv

    # Load environment
    load_dotenv()

    # Get task_id from Celery request for Kafka tracking
    task_id = self.request.id

    # Initialize Redis for status tracking
    redis_client = Redis.from_url(BROKER_URL)
    pipeline_status = PipelineStatus(redis_client, user_id)

    # Only check/acquire lock if not already acquired by caller
    if not _skip_lock:
        # Check if pipeline already running
        is_running, start_time = pipeline_status.is_running()
        if is_running:
            elapsed_minutes = int((time.time() - start_time) / 60) if start_time else 0
            msg = f"Low-risk pipeline already running (started {elapsed_minutes} minutes ago)"
            task_logger.warning(msg)
            return {
                "success": False,
                "error": "Pipeline already running",
                "elapsed_minutes": elapsed_minutes
            }

        # Acquire lock (2 hour TTL to match task time limit)
        if not pipeline_status.acquire_lock(ttl=7200):
            return {
                "success": False,
                "error": "Failed to acquire pipeline lock"
            }
    else:
        # Lock already acquired, just log it
        task_logger.info(f"✅ Using pre-acquired lock for user {user_id}")

    try:
        # === STAGE 1: Initialization ===
        publish_to_kafka(
            {"content": f"Starting low-risk pipeline with fund: ₹{fund_allocated:,.2f}", "stage": "init", "status": "start"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info(f"🚀 Starting low-risk pipeline for user {user_id} with fund: ₹{fund_allocated:,.2f}")

        # Import pipeline components
        from pipelines.low_risk.stock_selection_pipeline import StockSelectionPipeline
        from pipelines.low_risk.industry_pipeline import IndustrySelectionPipeline
        from pipelines.low_risk.industry_indicators_pipeline import IndustryIndicatorsPipeline
        from pipelines.low_risk.fundamental_analyzer_pipeline import FundamentalAnalyzerPipeline
        from utils.economic_indicators_storage import get_storage
        from market_data import get_market_data_service
        from pipelines.low_risk.angelone_batch_fetcher import create_fetcher_from_market_service

        nifty_500_path = PROJECT_ROOT / "scripts" / "ind_nifty500listbrief.csv"
        if not nifty_500_path.exists():
            raise FileNotFoundError(
                f"Company data not found at {nifty_500_path}. "
                f"Please ensure ind_nifty500listbrief.csv exists."
            )

        publish_to_kafka(
            {"content": f"Loading company data...", "stage": "init", "status": "progress"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info(f"📊 Loading company data from {nifty_500_path}")
        company_df = pd.read_csv(nifty_500_path)

        if "Company Name" not in company_df.columns or "Industry" not in company_df.columns:
            raise ValueError(
                f"CSV must contain 'Company Name' and 'Industry' columns. "
                f"Found: {company_df.columns.tolist()}"
            )

        # Get API keys
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        # Initialize storage
        storage = get_storage()
        publish_to_kafka(
            {"content": f"Initialization complete. Loaded {len(company_df)} companies.", "stage": "init", "status": "done"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info("🗄️ Economic indicators storage initialized")

        # === STAGE 2: Market Data Service ===
        publish_to_kafka(
            {"content": "Initializing market data service...", "stage": "market_data", "status": "start"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info("🔧 Initializing Angel One market data service...")
        market_service = get_market_data_service()
        angel_fetcher = create_fetcher_from_market_service(market_service)
        publish_to_kafka(
            {"content": "Market service initialized", "stage": "market_data", "status": "done"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )

        # === STAGE 3: Industry Indicators ===
        publish_to_kafka(
            {"content": "Computing industry indicators (fetching ~500 stocks)...", "stage": "industry_indicators", "status": "start"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info("📈 Computing industry indicators...")
        industry_indicators = IndustryIndicatorsPipeline(
            stocks_csv_path=str(nifty_500_path),
            angel_one_fetcher=angel_fetcher,
            Demo=False
        )
        industry_indicators.compute()
        publish_to_kafka(
            {"content": "Industry indicators computed successfully", "stage": "industry_indicators", "status": "done"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info("✅ Industry indicators computed")

        # === STAGE 4: Industry Selection ===
        publish_to_kafka(
            {"content": "Running LLM-based industry selection...", "stage": "industry_selection", "status": "start"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info("🏭 Running industry selection pipeline...")
        industry_pipeline = IndustrySelectionPipeline(
            industry_pipeline=industry_indicators,
            user_id=user_id,
            gemini_api_key=gemini_api_key,
            storage=storage,
            task_id=task_id,
        )
        industry_list = industry_pipeline.run(rebalance=rebalance, summary=prev_summary)
        publish_to_kafka(
            {
                "content": f"Selected {len(industry_list)} industries",
                "stage": "industry_selection",
                "status": "done",
                "result": {"industries": [i.get("name") for i in industry_list]}
            },
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info(f"✅ Selected {len(industry_list)} industries")

        # === STAGE 5: Fundamental Analyzer ===
        publish_to_kafka(
            {"content": "Running fundamental analyzer...", "stage": "fundamental", "status": "start"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info("📊 Running fundamental analyzer pipeline...")
        fundamental_pipeline = FundamentalAnalyzerPipeline()
        fundamental_result = fundamental_pipeline.run()
        publish_to_kafka(
            {
                "content": f"Fundamental metrics ready for {len(getattr(fundamental_result, 'dataframe', []))} tickers",
                "stage": "fundamental",
                "status": "done"
            },
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )

        # === STAGE 6: Stock Selection ===
        publish_to_kafka(
            {"content": f"Running stock selection for {len(industry_list)} industries...", "stage": "stock_selection", "status": "start"},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info("📈 Running stock selection pipeline...")
        stock_pipeline = StockSelectionPipeline(
            pipeline=fundamental_pipeline,
            company_df=company_df,
            industry_list=industry_list,
            gemini_api_key=gemini_api_key,
            user_id=user_id,
            task_id=task_id,
        )

        # Run pipeline and generate trades
        result = stock_pipeline.run(fund_allocated=fund_allocated)

        # Extract summary
        summary = result["summary"]
        publish_to_kafka(
            {
                "content": f"Stock selection complete: {summary['total_stocks']} stocks selected",
                "stage": "stock_selection",
                "status": "done",
                "result": summary
            },
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )
        task_logger.info(
            f"✅ Pipeline completed: {summary['total_stocks']} stocks, "
            f"{summary['total_trades']} trades, "
            f"₹{summary['total_invested']:,.2f} invested "
            f"({summary['utilization_rate']:.2f}% utilization)"
        )

        # === STAGE 7: Completion ===
        completion_msg = (
            f"Pipeline completed: {summary['total_stocks']} stocks, "
            f"{summary['total_trades']} trades, "
            f"₹{summary['total_invested']:,.2f} invested "
            f"({summary['utilization_rate']:.2f}% utilization)"
        )
        publish_to_kafka(
            {"content": completion_msg, "stage": "completion", "status": "done", "result": summary},
            user_id=user_id,
            message_type="stage",
            task_id=task_id,
        )

        # Release lock and mark success
        pipeline_status.release_lock()

        return {
            "success": True,
            "user_id": user_id,
            "fund_allocated": fund_allocated,
            "summary": summary,
            "trades_generated": len(result["trade_list"]),
            "industries_selected": len(industry_list),
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        # Log error and update status
        error_message = str(e)
        task_logger.error(f"❌ Low-risk pipeline failed for user {user_id}: {error_message}", exc_info=True)
        publish_to_kafka(
            {"content": f"Pipeline failed: {error_message}", "stage": "error", "status": "error", "error": error_message},
            user_id=user_id,
            message_type="error",
            task_id=task_id,
        )
        pipeline_status.set_error(error_message)
        
        # CRITICAL: Release lock on error to prevent deadlock
        pipeline_status.release_lock()

        # Return error instead of raising (no autoretry configured)
        return {
            "success": False,
            "error": error_message,
            "user_id": user_id,
            "fund_allocated": fund_allocated,
            "failed_at": datetime.now(timezone.utc).isoformat()
        }


@celery_app.task(name="pipeline.low_risk.get_status")
def get_low_risk_pipeline_status(user_id: str) -> Dict[str, Any]:
    """
    Get current status of low-risk pipeline for a user.

    Args:
        user_id: User ID to check status for

    Returns:
        Dictionary with status information
    """
    redis_client = Redis.from_url(BROKER_URL)
    pipeline_status = PipelineStatus(redis_client, user_id)
    return pipeline_status.get_status()


__all__ = [
    "run_low_risk_pipeline",
    "get_low_risk_pipeline_status",
    "PipelineStatus",
]
