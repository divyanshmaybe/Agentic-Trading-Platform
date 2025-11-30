from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Dict, Iterable

from dotenv import load_dotenv
from kombu import Queue

# Suppress verbose Pathway sink logging globally for Celery workers
os.environ.setdefault("PATHWAY_LOG_LEVEL", "WARNING")
os.environ.setdefault("PATHWAY_DISABLE_PROGRESS", "1")
os.environ.setdefault("PATHWAY_MONITORING_LEVEL", "none")
# Suppress all Pathway loggers before any Pathway imports
logging.getLogger("pathway").setLevel(logging.ERROR)
logging.getLogger("pathway.io").setLevel(logging.ERROR)
logging.getLogger("pathway.io.kafka").setLevel(logging.ERROR)
logging.getLogger("pathway.io.filesystem").setLevel(logging.ERROR)
logging.getLogger("pathway.io.jsonlines").setLevel(logging.ERROR)
logging.getLogger("pathway.io.csv").setLevel(logging.ERROR)
# Suppress Pathway publisher/sink verbose messages
logging.getLogger("pathway.io.publisher").setLevel(logging.ERROR)
logging.getLogger("pathway.io.sink").setLevel(logging.ERROR)
# Suppress "Done writing" messages
logging.getLogger("pathway.io.filesystem").setLevel(logging.ERROR)
logging.getLogger("pathway.io.kafka").setLevel(logging.ERROR)

# Suppress verbose HTTP and network logging from Prisma/httpx
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpcore.http11").setLevel(logging.ERROR)
logging.getLogger("httpcore.connection").setLevel(logging.ERROR)
logging.getLogger("hpack").setLevel(logging.ERROR)
logging.getLogger("anyio").setLevel(logging.ERROR)

# Add filter to suppress verbose Pathway sink messages
class PathwaySinkFilter(logging.Filter):
    """Filter out verbose Pathway sink/publisher log messages"""
    def filter(self, record):
        msg = record.getMessage()
        # Suppress "Done writing", "Current batch writes", HTTP requests, position refresh, etc.
        suppress_patterns = [
            "Done writing",
            "Current batch writes took",
            "All writes so far took",
            "entries have been sent to the engine",
            "minibatch(es)",
            "HTTP Request: POST",
            "Position refresh:",
            "Risk monitor stream",
        ]
        return not any(pattern in msg for pattern in suppress_patterns)

# Apply filter to root logger and Celery worker logger
pathway_filter = PathwaySinkFilter()
logging.getLogger().addFilter(pathway_filter)
logging.getLogger("celery").addFilter(pathway_filter)
logging.getLogger("celery.worker").addFilter(pathway_filter)

# Load environment variables from portfolio-server .env and project root .env
# (same logic as PipelineService._load_environment)
_celery_file = Path(__file__).resolve()
_server_dir = _celery_file.parent
_project_root = _server_dir.parent.parent

# Load root .env first (lower priority)
_root_env = _project_root / ".env"
if _root_env.exists():
    load_dotenv(_root_env, override=False)

# Load server .env (higher priority, overrides root)
_server_env = _server_dir / ".env"
if _server_env.exists():
    load_dotenv(_server_env, override=True)
else:
    # Fallback: try to load from current directory
    load_dotenv(override=False)

from celery import Celery, signals
from celery.schedules import crontab
from datetime import datetime
import pytz

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
DEFAULT_QUEUE = os.getenv("CELERY_DEFAULT_QUEUE", "general")

QUEUE_NAMES: Dict[str, str] = {
    "allocations": os.getenv("CELERY_QUEUE_ALLOCATIONS", "allocations"),
    "trading": os.getenv("CELERY_QUEUE_TRADING", "trading"),
    "pipelines": os.getenv("CELERY_QUEUE_PIPELINES", "pipelines"),
    "risk": os.getenv("CELERY_QUEUE_RISK", "risk"),
    "orders": os.getenv("CELERY_QUEUE_ORDERS", "orders"),
    "market": os.getenv("CELERY_QUEUE_MARKET", "market"),
    "tokens": os.getenv("CELERY_QUEUE_TOKENS", "tokens"),
    "streaming": os.getenv("CELERY_QUEUE_STREAMING", "streaming"),  # Dedicated queue for long-running streaming tasks
}


def _queue_set(values: Iterable[str]) -> list[Queue]:
    seen = {DEFAULT_QUEUE}
    queue_objects = [Queue(DEFAULT_QUEUE)]
    for name in values:
        if name and name not in seen:
            queue_objects.append(Queue(name))
            seen.add(name)
    return queue_objects


celery_app = Celery(
    "portfolio-server",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=[
        "workers.trade_tasks",
        "workers.market_data_tasks",
        "workers.angelone_token_task",
        "workers.allocation_tasks",
        "workers.risk_alert_tasks",
        "workers.trade_execution_tasks",
        "workers.pipeline_tasks",
        "workers.snapshot_tasks",
        "workers.auto_sell_worker",
        "workers.streaming_risk_tasks",
        "workers.economic_indicators_tasks",
        "workers.low_risk_tasks",  # Low-risk pipeline worker
    ],
)

VISIBILITY_TIMEOUT = int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "900"))
RESULT_TTL = int(os.getenv("CELERY_RESULT_TTL", "86400"))
# Reduce default timeouts - most tasks should complete in <60s
# Tasks holding connections for 10 minutes (600s) cause connection exhaustion!
SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "120"))  # 2 minutes default
HARD_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", str(SOFT_TIME_LIMIT + 60)))  # +1 min for cleanup

# Worker concurrency settings
# IMPORTANT: Reduced from 8 to 4 to prevent connection pool exhaustion
# Calculation: 3 connections × 4 workers = 12 per process (safe for PostgreSQL max 100)
WORKER_CONCURRENCY = int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_track_started=True,
    task_default_queue=DEFAULT_QUEUE,
    task_default_exchange="portfolio-celery",
    task_default_exchange_type="direct",
    task_default_routing_key=DEFAULT_QUEUE,
    task_default_delivery_mode="persistent",
    task_queue_max_priority=10,
    # Worker settings - prevent task starvation and connection leaks
    worker_concurrency=WORKER_CONCURRENCY,
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "50")),  # Recycle workers aggressively to prevent leaks
    worker_prefetch_multiplier=1,  # Only prefetch 1 task per worker (prevents blocking)
    worker_redirect_stdouts=False,
    worker_send_task_events=True,
    worker_hijack_root_logger=False,
    worker_disable_rate_limits=False,
    worker_lost_wait=10,  # Seconds to wait for worker to exit gracefully
    # Task settings
    task_reject_on_worker_lost=True,
    task_time_limit=HARD_TIME_LIMIT,  # Global hard limit
    task_soft_time_limit=SOFT_TIME_LIMIT,  # Global soft limit
    task_always_eager=False,  # Never run tasks synchronously in production
    task_store_eager_result=False,
    task_ignore_result=False,  # Store results for debugging
    task_compression="gzip",  # Compress task payloads
    # Broker settings - robust connection handling
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    broker_pool_limit=20,  # Increased connection pool size for better concurrency
    broker_heartbeat=30,  # Keep connections alive
    broker_transport_options={
        "visibility_timeout": VISIBILITY_TIMEOUT,
        "fanout_prefix": True,
        "fanout_patterns": True,
        "max_retries": 5,
        "interval_start": 0,
        "interval_step": 0.1,  # Faster retry (reduced from 0.2)
        "interval_max": 0.3,  # Lower max interval (reduced from 0.5)
        "socket_keepalive": True,  # Keep sockets alive
        "socket_connect_timeout": 5,  # Fast connection timeout
    },
    # Result backend settings
    result_expires=RESULT_TTL,
    result_persistent=True,
    result_extended=True,  # Store additional task metadata
    # Event settings for monitoring (worker_send_task_events already set above)
    task_send_sent_event=True,
)

# Ensure all queues are registered explicitly with proper routing keys and priority support
_all_queues = [Queue(DEFAULT_QUEUE, routing_key=DEFAULT_QUEUE)]
for queue_name in ["allocations", "trading", "pipelines", "risk", "orders", "market", "tokens", "streaming"]:
    if not any(q.name == queue_name for q in _all_queues):
        # Trading queue gets priority support for real-time signal execution
        if queue_name == "trading":
            _all_queues.append(Queue(
                queue_name, 
                routing_key=queue_name,
                queue_arguments={"x-max-priority": 10}  # Enable priority 0-10
            ))
        else:
            _all_queues.append(Queue(queue_name, routing_key=queue_name))
celery_app.conf.task_queues = _all_queues

celery_app.conf.task_routes = {
    # Allocation + trading queues
    "portfolio.allocate_for_objective": {"queue": QUEUE_NAMES["allocations"], "routing_key": "allocations"},
    "portfolio.check_regime_and_rebalance": {"queue": QUEUE_NAMES["allocations"], "routing_key": "allocations"},
    "trading.execute_trade_job": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    # Signal processing goes to trading queue (not pipelines - that's blocked by streaming pipeline)
    "pipeline.trade_execution.process_signal": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    "pipeline.start": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "pipeline.news_sentiment.run": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "pipeline.risk_monitor.run": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "pipeline.low_risk.run": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "pipeline.low_risk.get_status": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "market_data.fetch_via_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.batch_fetch_via_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.health_check_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.generate_angelone_tokens": {"queue": QUEUE_NAMES["tokens"], "routing_key": "tokens"},
    # Risk + alerts
    "risk.alerts.send_email": {"queue": QUEUE_NAMES["risk"], "routing_key": "risk"},
    # Streaming monitor gets its own dedicated queue to not block other tasks
    "risk.streaming_monitor.start": {"queue": QUEUE_NAMES["streaming"], "routing_key": "streaming"},
    # Auto-sell worker
    "trades.auto_sell_expired_trades": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    "pipeline.sell_high_risk_before_close": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
}

# Task categories with different resource requirements
STANDARD_TASKS = [
    "portfolio.allocate_for_objective",
    "portfolio.check_regime_and_rebalance",
]

# Pipeline tasks - may take longer, rate limited
PIPELINE_TASKS = [
    "pipeline.risk_monitor.run",
    "pipeline.news_sentiment.run",
    "pipeline.start",
    "pipeline.low_risk.run",  # Low-risk stock selection (25-30 min limit)
    "pipeline.low_risk.get_status",  # Status check for low-risk pipeline
]

# Signal processing tasks - HIGHEST PRIORITY, NO RATE LIMITS for minimal latency
# These are the core real-time trading tasks that must execute immediately
SIGNAL_PROCESSING_TASKS = [
    "pipeline.trade_execution.process_signal",
]

# Trade execution - high priority, fast execution
TRADE_EXECUTION_TASKS = [
    "trading.execute_trade_job",
    "trading.process_pending_trade",
    "trades.execute_auto_close",  # Auto-close individual trades
]

# Tasks that should run indefinitely (no time limits) - isolated queue
LONG_RUNNING_TASKS = [
    "risk.streaming_monitor.start",
]

# Quick tasks - should complete fast, higher rate limit
QUICK_TASKS = [
    "market_data.fetch_via_api",
    "market_data.batch_fetch_via_api",
    "market_data.health_check_api",
    "risk.alerts.send_email",
    "snapshot.capture_agent_snapshots",
    "snapshot.capture_portfolio_snapshots",
]

# Auto-sell task - needs its own limits
AUTO_SELL_TASKS = [
    "trades.auto_sell_expired_trades",
    "pipeline.sell_high_risk_before_close",
]

celery_app.conf.task_annotations = {
    # Standard tasks - reasonable limits for DB operations
    **{
        task_name: {
            "soft_time_limit": 180,  # 3 min soft (allocation can take time for LLM calls)
            "time_limit": 240,  # 4 min hard
            "rate_limit": "30/m",  # Max 30 per minute (increased from 10)
        }
        for task_name in STANDARD_TASKS
    },
    # Signal processing - CRITICAL: NO RATE LIMIT for real-time trading
    # These must execute immediately when signals come in
    **{
        task_name: {
            "soft_time_limit": 120,  # 2 min soft limit (trade execution can take time)
            "time_limit": 180,  # 3 min hard limit
            "rate_limit": None,  # NO RATE LIMIT - execute immediately!
            "priority": 9,  # HIGH PRIORITY (0-9, 9 is highest)
        }
        for task_name in SIGNAL_PROCESSING_TASKS
    },
    # Trade execution - CRITICAL: NO RATE LIMIT
    **{
        task_name: {
            "soft_time_limit": 120,  # 2 min soft limit
            "time_limit": 180,  # 3 min hard limit
            "rate_limit": None,  # NO RATE LIMIT - execute immediately!
            "priority": 9,  # HIGH PRIORITY
        }
        for task_name in TRADE_EXECUTION_TASKS
    },
    # Pipeline tasks - longer limits, lower rate
    **{
        task_name: {
            "soft_time_limit": SOFT_TIME_LIMIT + 300,  # 15 min soft
            "time_limit": HARD_TIME_LIMIT + 300,  # 17 min hard
            "rate_limit": "2/m",  # Max 2 per minute (pipelines are heavy)
        }
        for task_name in PIPELINE_TASKS
    },
    # Long-running tasks - no limits, single instance
    # NOTE: Must explicitly set very high limits (not None) to override global config
    **{
        task_name: {
            "soft_time_limit": 86400,  # 24 hours (effectively unlimited)
            "time_limit": 86400,  # 24 hours (effectively unlimited)
            "rate_limit": "1/h",  # Only 1 per hour (singleton)
            "acks_late": False,  # Acknowledge immediately
            "max_retries": 0,  # Don't retry long-running tasks
        }
        for task_name in LONG_RUNNING_TASKS
    },
    # Quick tasks - short limits, high rate
    **{
        task_name: {
            "soft_time_limit": 60,
            "time_limit": 90,
            "rate_limit": "120/m",  # 2 per second (increased from 1/s)
        }
        for task_name in QUICK_TASKS
    },
    # Auto-sell tasks - reasonable limits (DB operations take time)
    **{
        task_name: {
            "soft_time_limit": 60,  # 60 second soft limit (increased from 30)
            "time_limit": 90,  # 90 second hard limit (increased from 45)
            "rate_limit": "10/m",  # Max 10 per minute (increased from 4)
        }
        for task_name in AUTO_SELL_TASKS
    },
}

celery_app.conf.beat_scheduler = "redbeat.RedBeatScheduler"
celery_app.conf.redbeat_redis_url = os.getenv("REDBEAT_REDIS_URL", BROKER_URL)
celery_app.conf.redbeat_lock_timeout = int(os.getenv("CELERY_REDBEAT_LOCK_TIMEOUT", "600"))
celery_app.conf.redbeat_lock_key = os.getenv("CELERY_REDBEAT_LOCK_KEY", "redbeat::lock")

NEWS_PIPELINE_ENABLED = os.getenv("NEWS_PIPELINE_ENABLED", "true").lower() in {"1", "true", "yes"}
NEWS_FETCH_RATE = int(os.getenv("NEWS_FETCH_RATE", "1800"))  # Default 30 minutes (1800 seconds)
NEWS_PIPELINE_QUEUE = os.getenv("NEWS_PIPELINE_QUEUE", QUEUE_NAMES["pipelines"])

NSE_PIPELINE_ENABLED = os.getenv("NSE_PIPELINE_ENABLED", "true").lower() in {"1", "true", "yes"}
NSE_PIPELINE_QUEUE = os.getenv("NSE_PIPELINE_QUEUE", QUEUE_NAMES["pipelines"])

# Regime monitoring (runs 1h before market open to detect regime changes)
REGIME_MONITOR_ENABLED = os.getenv("REGIME_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
REGIME_MONITOR_HOUR = int(os.getenv("REGIME_MONITOR_HOUR", "8"))  # 8:15 AM = 1h before 9:15 AM market open
REGIME_MONITOR_MINUTE = int(os.getenv("REGIME_MONITOR_MINUTE", "15"))
REGIME_MONITOR_DAY_OF_WEEK = os.getenv("REGIME_MONITOR_DAY_OF_WEEK", "mon-fri")
REGIME_MONITOR_QUEUE = os.getenv("REGIME_MONITOR_QUEUE", QUEUE_NAMES["allocations"])

# Portfolio rebalancing (only rebalances when rebalancing_date reached or regime changed)
REBALANCE_ENABLED = os.getenv("PORTFOLIO_REBALANCE_ENABLED", "true").lower() in {"1", "true", "yes"}
REBALANCE_QUEUE = os.getenv("PORTFOLIO_REBALANCE_QUEUE", QUEUE_NAMES["allocations"])

RISK_MONITOR_ENABLED = os.getenv("PORTFOLIO_RISK_MONITOR_ENABLED", "false").lower() in {"1", "true", "yes"}
RISK_MONITOR_INTERVAL = int(os.getenv("PORTFOLIO_RISK_MONITOR_INTERVAL", "900"))
RISK_MONITOR_QUEUE = os.getenv("PORTFOLIO_RISK_MONITOR_QUEUE", QUEUE_NAMES["pipelines"])

# Order Monitor Configuration (for limit/stop/take-profit orders)
ORDER_MONITOR_ENABLED = os.getenv("ORDER_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
ORDER_MONITOR_INTERVAL = int(os.getenv("ORDER_MONITOR_INTERVAL", "5"))  # Check every 5 seconds
ORDER_MONITOR_QUEUE = os.getenv("ORDER_MONITOR_QUEUE", QUEUE_NAMES["orders"])

# Initialize empty beat schedule
celery_app.conf.beat_schedule = {}

# NSE Pipeline - runs once on startup (long-running task)
if NSE_PIPELINE_ENABLED:
    celery_app.conf.beat_schedule["nse-filings-pipeline"] = {
        "task": "pipeline.start",
        "schedule": timedelta(seconds=300),  # Check every 5 minutes (task has internal lock)
        "options": {
            "queue": NSE_PIPELINE_QUEUE,
            "expires": 240,  # Expire after 4 minutes if not picked up
        },
    }

# Only enable news pipeline via Beat if explicitly configured
if NEWS_PIPELINE_ENABLED:
    celery_app.conf.beat_schedule["news-sentiment-pipeline"] = {
        "task": "pipeline.news_sentiment.run",
        "schedule": timedelta(seconds=NEWS_FETCH_RATE),
        "options": {"queue": NEWS_PIPELINE_QUEUE},
    }

# Regime monitor - runs daily 1h before market open (8:15 AM for 9:15 AM market)
if REGIME_MONITOR_ENABLED:
    celery_app.conf.beat_schedule["regime-monitor-check"] = {
        "task": "portfolio.check_regime_and_rebalance",
        "schedule": crontab(hour=REGIME_MONITOR_HOUR, minute=REGIME_MONITOR_MINUTE, day_of_week=REGIME_MONITOR_DAY_OF_WEEK),
        "options": {"queue": REGIME_MONITOR_QUEUE},
    }

if RISK_MONITOR_ENABLED:
    celery_app.conf.beat_schedule["portfolio-risk-monitor"] = {
        "task": "pipeline.risk_monitor.run",
        "schedule": timedelta(seconds=RISK_MONITOR_INTERVAL),
        "options": {
            "queue": RISK_MONITOR_QUEUE,
            "expires": RISK_MONITOR_INTERVAL - 10,  # Expire before next schedule
        },
    }

# Snapshot capture - Every 3 hours (0:00, 3:00, 6:00, 9:00, 12:00, 15:00, 18:00, 21:00 UTC)
SNAPSHOT_ENABLED = os.getenv("SNAPSHOT_CAPTURE_ENABLED", "true").lower() in {"1", "true", "yes"}
SNAPSHOT_QUEUE = os.getenv("SNAPSHOT_QUEUE", DEFAULT_QUEUE)

if SNAPSHOT_ENABLED:
    # Trading agent snapshots - every 3 hours
    celery_app.conf.beat_schedule["trading-agent-snapshots"] = {
        "task": "snapshot.capture_agent_snapshots",
        "schedule": crontab(hour="*/3", minute=0),  # Every 3 hours
        "options": {"queue": SNAPSHOT_QUEUE},
    }
    
    # Portfolio snapshots - every 3 hours
    celery_app.conf.beat_schedule["portfolio-snapshots"] = {
        "task": "snapshot.capture_portfolio_snapshots",
        "schedule": crontab(hour="*/3", minute=5),  # Every 3 hours (offset by 5 minutes)
        "options": {"queue": SNAPSHOT_QUEUE},
    }

# Auto-sell worker - runs every minute to sell trades past their 15-minute window
AUTO_SELL_ENABLED = os.getenv("AUTO_SELL_ENABLED", "true").lower() in {"1", "true", "yes"}
AUTO_SELL_QUEUE = os.getenv("AUTO_SELL_QUEUE", QUEUE_NAMES["trading"])

if AUTO_SELL_ENABLED:
    celery_app.conf.beat_schedule["auto-sell-expired-trades"] = {
        "task": "trades.auto_sell_expired_trades",
        "schedule": timedelta(minutes=1),  # Every minute
        "options": {
            "queue": AUTO_SELL_QUEUE,
            "expires": 50,  # Task expires after 50 seconds if not picked up
        },
    }

# Market closing task - sells all high_risk positions at 3:15 PM IST (9:45 AM UTC)
# IST is UTC+5:30, so 3:15 PM IST = 9:45 AM UTC
MARKET_CLOSE_SELL_ENABLED = os.getenv("MARKET_CLOSE_SELL_ENABLED", "true").lower() in {"1", "true", "yes"}
MARKET_CLOSE_SELL_QUEUE = os.getenv("MARKET_CLOSE_SELL_QUEUE", QUEUE_NAMES["trading"])

if MARKET_CLOSE_SELL_ENABLED:
    celery_app.conf.beat_schedule["sell-high-risk-before-close"] = {
        "task": "pipeline.sell_high_risk_before_close",
        "schedule": crontab(hour=9, minute=45, day_of_week="mon-fri"),  # 3:15 PM IST = 9:45 AM UTC
        "options": {"queue": MARKET_CLOSE_SELL_QUEUE},
    }

# Economic Indicators - runs on 21st of each month (configurable, in IST)
ECONOMIC_INDICATORS_ENABLED = os.getenv("ECONOMIC_INDICATORS_ENABLED", "true").lower() in {"1", "true", "yes"}
ECONOMIC_INDICATORS_UPDATE_DAY = int(os.getenv("ECONOMIC_INDICATORS_UPDATE_DAY", "21"))
ECONOMIC_INDICATORS_UPDATE_HOUR = int(os.getenv("ECONOMIC_INDICATORS_UPDATE_HOUR", "2"))  # IST time
ECONOMIC_INDICATORS_UPDATE_MINUTE = int(os.getenv("ECONOMIC_INDICATORS_UPDATE_MINUTE", "0"))  # IST time
ECONOMIC_INDICATORS_QUEUE = os.getenv("ECONOMIC_INDICATORS_QUEUE", QUEUE_NAMES["market"])

if ECONOMIC_INDICATORS_ENABLED:
    # Convert IST time to UTC for Celery schedule
    # IST is UTC+5:30
    ist = pytz.timezone("Asia/Kolkata")
    utc = pytz.UTC
    
    # Create a datetime in IST for the specified day/hour/minute
    # Use a reference month (e.g., January 2024) to calculate the offset
    ist_datetime = ist.localize(
        datetime(2024, 1, ECONOMIC_INDICATORS_UPDATE_DAY, ECONOMIC_INDICATORS_UPDATE_HOUR, ECONOMIC_INDICATORS_UPDATE_MINUTE)
    )
    utc_datetime = ist_datetime.astimezone(utc)
    
    # Calculate UTC hour and minute
    utc_hour = utc_datetime.hour
    utc_minute = utc_datetime.minute
    
    # Determine UTC day - use the actual UTC day from conversion
    # Example: 2:00 AM IST on 21st = 8:30 PM UTC on 20th
    # Example: 10:00 AM IST on 21st = 4:30 AM UTC on 21st
    utc_day = utc_datetime.day
    
    # Trading Economics indicators - scheduled in IST, converted to UTC
    celery_app.conf.beat_schedule["economic-indicators-trading-economics"] = {
        "task": "economic_indicators.update_trading_economics",
        "schedule": crontab(
            day_of_month=utc_day,
            hour=utc_hour,
            minute=utc_minute,
        ),
        "options": {
            "queue": ECONOMIC_INDICATORS_QUEUE,  # Only market worker should process these
            "routing_key": ECONOMIC_INDICATORS_QUEUE,
        },
    }
    
    # CPI indicators - scheduled in IST, converted to UTC
    celery_app.conf.beat_schedule["economic-indicators-cpi"] = {
        "task": "economic_indicators.update_cpi",
        "schedule": crontab(
            day_of_month=utc_day,
            hour=utc_hour,
            minute=utc_minute,
        ),
        "options": {
            "queue": ECONOMIC_INDICATORS_QUEUE,  # Only market worker should process these
            "routing_key": ECONOMIC_INDICATORS_QUEUE,
        },
    }
    
    logging.info(
        f"📅 Economic indicators scheduled: {ECONOMIC_INDICATORS_UPDATE_DAY}th at "
        f"{ECONOMIC_INDICATORS_UPDATE_HOUR:02d}:{ECONOMIC_INDICATORS_UPDATE_MINUTE:02d} IST "
        f"(UTC: {utc_day}th at {utc_hour:02d}:{utc_minute:02d})"
    )

# Industry Indicators - runs daily (configurable, in IST)
INDUSTRY_INDICATORS_ENABLED = os.getenv("INDUSTRY_INDICATORS_ENABLED", "true").lower() in {"1", "true", "yes"}
INDUSTRY_INDICATORS_UPDATE_HOUR = int(os.getenv("INDUSTRY_INDICATORS_UPDATE_HOUR", "3"))  # IST time
INDUSTRY_INDICATORS_UPDATE_MINUTE = int(os.getenv("INDUSTRY_INDICATORS_UPDATE_MINUTE", "0"))  # IST time
INDUSTRY_INDICATORS_QUEUE = os.getenv("INDUSTRY_INDICATORS_QUEUE", QUEUE_NAMES["market"])

if INDUSTRY_INDICATORS_ENABLED:
    # Convert IST to UTC for Celery's crontab
    ist = pytz.timezone('Asia/Kolkata')
    ist_time = ist.localize(datetime(
        datetime.now().year, datetime.now().month, datetime.now().day,
        INDUSTRY_INDICATORS_UPDATE_HOUR, INDUSTRY_INDICATORS_UPDATE_MINUTE
    ))
    utc_time = ist_time.astimezone(pytz.utc)

    utc_hour = utc_time.hour
    utc_minute = utc_time.minute

    # Schedule daily (every day at specified hour)
    celery_app.conf.beat_schedule["industry-indicators-update"] = {
        "task": "economic_indicators.update_industry_indicators",
        "schedule": crontab(
            hour=utc_hour,
            minute=utc_minute,
        ),
        "options": {
            "queue": INDUSTRY_INDICATORS_QUEUE,
            "routing_key": INDUSTRY_INDICATORS_QUEUE,
        },
    }

    logging.info(
        f"📅 Industry indicators scheduled: Daily at "
        f"{INDUSTRY_INDICATORS_UPDATE_HOUR:02d}:{INDUSTRY_INDICATORS_UPDATE_MINUTE:02d} IST "
        f"(UTC: {utc_hour:02d}:{utc_minute:02d})"
    )


# Lazy import worker modules to avoid circular imports
# These imports happen when celery worker starts, not when this module is imported
def _import_tasks():
    """Import all worker task modules so Celery discovers them."""
    # Import statement must be inside function to avoid circular imports
    # since some workers import services which import celery_app
    from workers import (
        allocation_tasks,
        pipeline_tasks,
        trade_tasks,
        trade_execution_tasks,
        auto_sell_worker,
        market_data_tasks,
        risk_alert_tasks,
        snapshot_tasks,
        angelone_token_task,
        economic_indicators_tasks,
    )


# Only import tasks when running as Celery worker (not when imported by other modules)
if os.environ.get("CELERY_WORKER_RUNNING") or "celery" in sys.argv[0]:
    _import_tasks()
    
    # Check and update economic indicators on startup if needed
    if ECONOMIC_INDICATORS_ENABLED:
        try:
            from workers.economic_indicators_tasks import check_and_update_on_startup
            check_and_update_on_startup()
        except Exception as e:
            logging.warning("Failed to run economic indicators startup check: %s", e)
    
    # Note: Prometheus exporter is initialized via worker_ready signal below


# Worker process initialization - reset Prisma client on fork
@signals.worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Reset Prisma client when worker process is forked.
    
    This is critical because Prisma clients cannot be shared across process forks.
    Each forked worker needs its own Prisma client instance.
    """
    try:
        # Add shared/py to path for DBManager import
        project_root = Path(__file__).resolve().parents[2]
        shared_py = project_root / "shared" / "py"
        if str(shared_py) not in sys.path:
            sys.path.insert(0, str(shared_py))
        
        from dbManager import DBManager
        
        # Reset the singleton instance - this forces recreation on next connect()
        DBManager.reset_instance()
        
        logger = logging.getLogger(__name__)
        logger.info("🔄 Worker process initialized - Prisma client reset for PID %s", os.getpid())
    except Exception as e:
        logging.error("❌ Failed to reset Prisma client in worker init: %s", e, exc_info=True)


# Worker process shutdown - force disconnect to release connections
@signals.worker_process_shutdown.connect
def shutdown_worker_process(**kwargs):
    """
    Force disconnect Prisma client when worker process shuts down.
    
    This ensures database connections are properly released to the pool.
    Critical for preventing connection leaks on worker restart/timeout.
    """
    try:
        project_root = Path(__file__).resolve().parents[2]
        shared_py = project_root / "shared" / "py"
        if str(shared_py) not in sys.path:
            sys.path.insert(0, str(shared_py))
        
        from dbManager import DBManager
        
        # Force disconnect - use asyncio.run to ensure it completes
        db_manager = DBManager._instance
        if db_manager and db_manager.is_connected():
            try:
                asyncio.run(db_manager.disconnect())
                logging.info("🔌 Worker process shutdown - Prisma disconnected for PID %s", os.getpid())
            except Exception as disc_exc:
                logging.warning("⚠️ Failed to disconnect on shutdown: %s", disc_exc)
            finally:
                # Force reset even if disconnect fails
                DBManager.reset_instance()
    except Exception as e:
        logging.error("❌ Failed to cleanup Prisma on worker shutdown: %s", e)


# Task-level connection management
@signals.task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, **kwargs):
    """Log task start and ensure clean DB state."""
    logging.debug("🚀 Task starting: %s [%s]", task.name if task else sender, task_id)


@signals.task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, retval=None, state=None, **kwargs):
    """
    Force disconnect after each task to prevent connection leaks.
    
    This is critical for long-running workers that execute many tasks.
    Each task gets a fresh connection from the pool.
    """
    try:
        project_root = Path(__file__).resolve().parents[2]
        shared_py = project_root / "shared" / "py"
        if str(shared_py) not in sys.path:
            sys.path.insert(0, str(shared_py))
        
        from dbManager import DBManager
        
        # Get instance without creating new one
        db_manager = DBManager._instance
        if db_manager and db_manager.is_connected():
            try:
                # Force disconnect to release connection back to pool
                asyncio.run(db_manager.disconnect())
                logging.debug("🔌 Task complete - DB disconnected: %s [%s]", task.name if task else sender, task_id)
            except Exception as disc_exc:
                logging.warning("⚠️ Failed to disconnect after task %s: %s", task_id, disc_exc)
    except Exception as e:
        logging.debug("Task postrun cleanup error: %s", e)


# Handle soft time limit exceeded - force disconnect
@signals.task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
    """Handle task failures and force cleanup on timeout."""
    from celery.exceptions import SoftTimeLimitExceeded
    
    if isinstance(exception, SoftTimeLimitExceeded):
        logging.warning("⏱️ Task %s exceeded soft time limit - forcing DB cleanup", task_id)
        try:
            project_root = Path(__file__).resolve().parents[2]
            shared_py = project_root / "shared" / "py"
            if str(shared_py) not in sys.path:
                sys.path.insert(0, str(shared_py))
            
            from dbManager import DBManager
            
            # Force disconnect on timeout
            db_manager = DBManager._instance
            if db_manager:
                try:
                    asyncio.run(db_manager.disconnect())
                    logging.info("🔌 Forced DB disconnect on soft timeout: %s", task_id)
                except Exception:
                    pass
                finally:
                    # Always reset to ensure next task gets fresh connection
                    DBManager.reset_instance()
        except Exception as e:
            logging.error("Failed to cleanup DB on timeout: %s", e)


# Initialize Prometheus exporter when worker is ready
@signals.worker_ready.connect
def setup_prometheus(**kwargs):
    """Set up Prometheus exporter when worker is ready."""
    logging.info("🔄 WORKER_READY signal fired - setting up Prometheus exporter")
    prometheus_enabled = os.getenv("PROMETHEUS_ENABLED", "true").lower() in ("true", "1", "yes")
    
    if not prometheus_enabled:
        logging.info("🔄 Prometheus disabled via environment variable")
        return
    
    try:
        logging.info("🔄 Importing prometheus_exporter module")
        from monitoring.prometheus_exporter import setup_prometheus_exporter
        
        logging.info("🔄 Calling setup_prometheus_exporter()")
        # Port is auto-determined based on worker name
        setup_prometheus_exporter()
        logging.info("✅ Prometheus exporter setup completed successfully")
        
    except Exception as e:
        logging.error("❌ Failed to initialize Prometheus exporter: %s", e, exc_info=True)


__all__ = ["celery_app"]
