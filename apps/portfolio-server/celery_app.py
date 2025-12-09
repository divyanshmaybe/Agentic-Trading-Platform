from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Dict, Iterable

# CRITICAL: Disable NumPy/OpenBLAS threading before any imports
# This prevents SIGSEGV errors in HMM training with multiprocessing
# Must be set before NumPy/OpenBLAS are imported
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

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
# Suppress "Done writing" messages from pathway_engine
logging.getLogger("pathway_engine").setLevel(logging.ERROR)
logging.getLogger("pathway_engine.connectors").setLevel(logging.ERROR)
logging.getLogger("pathway_engine.connectors.monitoring").setLevel(logging.ERROR)

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
    "pipelines": os.getenv("CELERY_QUEUE_PIPELINES", "pipelines"),  # Deprecated - use specific queues below
    "nse_pipeline": os.getenv("CELERY_QUEUE_NSE_PIPELINE", "nse_pipeline"),  # NSE filings (1 worker)
    "news_pipeline": os.getenv("CELERY_QUEUE_NEWS_PIPELINE", "news_pipeline"),  # News sentiment (1 worker)
    "low_risk_pipeline": os.getenv("CELERY_QUEUE_LOW_RISK", "low_risk_pipeline"),  # Low-risk selection (1 worker)
    "general": os.getenv("CELERY_QUEUE_GENERAL", "general"),  # General tasks
    "risk": os.getenv("CELERY_QUEUE_RISK", "risk"),
    "orders": os.getenv("CELERY_QUEUE_ORDERS", "orders"),
    "market": os.getenv("CELERY_QUEUE_MARKET", "market"),
    "tokens": os.getenv("CELERY_QUEUE_TOKENS", "tokens"),
    "streaming": os.getenv("CELERY_QUEUE_STREAMING", "streaming"),  # Dedicated queue for long-running streaming tasks
    "auto_sell": os.getenv("CELERY_QUEUE_AUTO_SELL", "general"),  # Auto-sell uses general queue to not block trading
    "regime": os.getenv("CELERY_QUEUE_REGIME", "regime"),  # Dedicated queue for regime sweeps
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
        "workers.streaming_risk_tasks",
        "workers.economic_indicators_tasks",
        "workers.low_risk_tasks",  # Low-risk pipeline worker
        "workers.alpha_signal_tasks",
        "workers.observability_agent_tasks",  # NSE pipeline loss analysis
        "workers.low_risk_observability_tasks",  # Low risk drawdown analysis
        "workers.company_report_update_tasks",  # Company report update from NSE/News
    ],
)

VISIBILITY_TIMEOUT = int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "900"))
RESULT_TTL = int(os.getenv("CELERY_RESULT_TTL", "86400"))
# Generous default timeouts - pipeline operations can take several minutes
# Individual task categories override these with their own limits in task_annotations
SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "600"))  # 10 minutes default
HARD_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", str(SOFT_TIME_LIMIT + 120)))  # +2 min for cleanup

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
    worker_send_task_events=True,  # Enable Celery event stream for celery-exporter
    worker_hijack_root_logger=False,
    worker_disable_rate_limits=False,
    worker_lost_wait=10,  # Seconds to wait for worker to exit gracefully
    worker_heartbeat_interval=2,  # Heartbeat interval for worker health monitoring
    # Task settings
    task_reject_on_worker_lost=True,
    task_time_limit=HARD_TIME_LIMIT,  # Global hard limit
    task_soft_time_limit=SOFT_TIME_LIMIT,  # Global soft limit
    task_always_eager=False,  # Never run tasks synchronously in production
    task_store_eager_result=False,
    task_ignore_result=False,  # Store results for debugging
    task_compression="gzip",  # Compress task payloads
    task_send_sent_event=True,  # Track task 'sent' events for monitoring
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
)

# Ensure all queues are registered explicitly with proper routing keys and priority support
_all_queues = [Queue(DEFAULT_QUEUE, routing_key=DEFAULT_QUEUE)]
for queue_name in [
    "allocations",
    "trading",
    "nse_pipeline",
    "news_pipeline",
    "low_risk_pipeline",
    "risk",
    "orders",
    "market",
    "tokens",
    "streaming",
    "regime",
]:
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
    "portfolio.check_regime_and_rebalance": {"queue": QUEUE_NAMES["regime"], "routing_key": QUEUE_NAMES["regime"]},
    "trading.execute_trade_job": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    # Signal processing goes to trading queue (not pipelines - that's blocked by streaming pipeline)
    "pipeline.trade_execution.process_signal": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    # NSE pipeline gets dedicated queue (1 worker max)
    "pipeline.start": {"queue": QUEUE_NAMES["nse_pipeline"], "routing_key": "nse_pipeline"},
    # News pipeline gets dedicated queue (1 worker max)
    "pipeline.news_sentiment.run": {"queue": QUEUE_NAMES["news_pipeline"], "routing_key": "news_pipeline"},
    # Generic risk monitor can use general queue
    "pipeline.risk_monitor.run": {"queue": QUEUE_NAMES["general"], "routing_key": "general"},
    # Low-risk pipeline gets dedicated queue (1 worker, 25-30 min time limits)
    "pipeline.low_risk.run": {"queue": QUEUE_NAMES["low_risk_pipeline"], "routing_key": "low_risk_pipeline"},
    "pipeline.low_risk.get_status": {"queue": QUEUE_NAMES["low_risk_pipeline"], "routing_key": "low_risk_pipeline"},
    "market_data.fetch_via_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.batch_fetch_via_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.health_check_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.generate_angelone_tokens": {"queue": QUEUE_NAMES["tokens"], "routing_key": "tokens"},
    # Risk + alerts
    "risk.alerts.send_email": {"queue": QUEUE_NAMES["risk"], "routing_key": "risk"},
    # Streaming monitor gets its own dedicated queue to not block other tasks
    "risk.streaming_monitor.start": {"queue": QUEUE_NAMES["streaming"], "routing_key": "streaming"},
    # Market close sell - uses auto_sell queue
    "pipeline.sell_high_risk_before_close": {"queue": QUEUE_NAMES["auto_sell"], "routing_key": "general"},
    "pipeline.sell_alpha_before_close": {"queue": QUEUE_NAMES["auto_sell"], "routing_key": "general"},
    # Alpha signal tasks - trading queue for signal execution
    "alpha.generate_daily_signals": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "alpha.generate_signals_for_alpha": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    "alpha.process_signal_batch": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    # Observability agent - uses general queue for loss analysis
    "observability.analyze_losing_trade": {"queue": QUEUE_NAMES["general"], "routing_key": "general"},
    "observability.batch_analyze_losses": {"queue": QUEUE_NAMES["general"], "routing_key": "general"},
    # Company report update tasks
    "company_report.update_from_nse_filing": {"queue": QUEUE_NAMES["general"], "routing_key": "general"},
    "company_report.update_from_nse_filing_url": {"queue": QUEUE_NAMES["general"], "routing_key": "general"},
    "company_report.update_from_news": {"queue": QUEUE_NAMES["news_pipeline"], "routing_key": "news_pipeline"},
    "company_report.batch_update_from_news": {"queue": QUEUE_NAMES["news_pipeline"], "routing_key": "news_pipeline"},
    "company_report.daily_news_update": {"queue": QUEUE_NAMES["news_pipeline"], "routing_key": "news_pipeline"},
}

# Task categories with different resource requirements
STANDARD_TASKS = [
    "portfolio.allocate_for_objective",
]

# Allocation/Rebalancing tasks - no time limits (can take time for regime detection + LLM)
ALLOCATION_TASKS = [
    "portfolio.check_regime_and_rebalance",
]

# Pipeline tasks - may take longer, rate limited
PIPELINE_TASKS = [
    "pipeline.risk_monitor.run",
    "pipeline.news_sentiment.run",
    "pipeline.low_risk.run",  # Low-risk stock selection (25-30 min limit)
    "pipeline.low_risk.get_status",  # Status check for low-risk pipeline
    "alpha.generate_daily_signals",  # Daily alpha signal generation
]

# Signal processing tasks - HIGHEST PRIORITY, NO RATE LIMITS for minimal latency
# These are the core real-time trading tasks that must execute immediately
SIGNAL_PROCESSING_TASKS = [
    "pipeline.trade_execution.process_signal",
    "alpha.generate_signals_for_alpha",  # On-demand alpha signal generation
    "alpha.process_signal_batch",  # Process alpha signals
]

# Trade execution - high priority, fast execution
TRADE_EXECUTION_TASKS = [
    "trading.execute_trade_job",
    "trading.process_pending_trade",
]

# Tasks that should run indefinitely (no time limits) - isolated queue
# These are continuous streaming pipelines that run 24/7
LONG_RUNNING_TASKS = [
    "risk.streaming_monitor.start",
    "pipeline.start",  # NSE pipeline - runs continuously 24/7, monitors trading_signals.jsonl
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

# Auto-sell is handled by streaming_order_monitor - no Celery tasks needed
# Only market-close sell remains as a scheduled Celery task
AUTO_SELL_TASKS = [
    "pipeline.sell_high_risk_before_close",
    "pipeline.sell_alpha_before_close",
]

celery_app.conf.task_annotations = {
    # Standard tasks - reasonable limits for DB operations
    **{
        task_name: {
            "soft_time_limit": 300,  # 5 min soft
            "time_limit": 360,  # 6 min hard
            "rate_limit": "30/m",  # Max 30 per minute
        }
        for task_name in STANDARD_TASKS
    },
    # Allocation/Rebalancing tasks - Very high time limits (regime detection + LLM can take time)
    **{
        task_name: {
            "soft_time_limit": 86400,  # 24 hours (effectively unlimited)
            "time_limit": 86400,  # 24 hours (effectively unlimited)
            "rate_limit": "10/m",  # Max 10 per minute
        }
        for task_name in ALLOCATION_TASKS
    },
    # Signal processing - CRITICAL: NO RATE LIMIT, VERY HIGH TIME LIMITS for real-time trading
    # These must execute immediately when signals come in and run as long as needed
    # NOTE: Use very high limits instead of None - Celery doesn't handle None properly
    **{
        task_name: {
            "soft_time_limit": 86400,  # 24 hours (effectively unlimited)
            "time_limit": 86400,  # 24 hours (effectively unlimited)
            "rate_limit": None,  # NO RATE LIMIT - execute immediately!
            "priority": 9,  # HIGH PRIORITY (0-9, 9 is highest)
        }
        for task_name in SIGNAL_PROCESSING_TASKS
    },
    # Trade execution - CRITICAL: NO RATE LIMIT, VERY HIGH TIME LIMITS
    **{
        task_name: {
            "soft_time_limit": 86400,  # 24 hours (effectively unlimited)
            "time_limit": 86400,  # 24 hours (effectively unlimited)
            "rate_limit": None,  # NO RATE LIMIT - execute immediately!
            "priority": 9,  # HIGH PRIORITY
        }
        for task_name in TRADE_EXECUTION_TASKS
    },
    # Pipeline tasks - longer limits, lower rate
    **{
        task_name: {
            "soft_time_limit": 86400,  # 24 hours for pipelines (no interruption)
            "time_limit": 86400,  # 24 hours for pipelines
            "rate_limit": "2/m",  # Max 2 per minute (pipelines are heavy)
        }
        for task_name in PIPELINE_TASKS
        if task_name != "pipeline.low_risk.run"  # low_risk has no time limit
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
    # Low-risk pipeline - needs extended time limit (fetches ~500 symbols at 1 req/sec)
    # Typical runtime: 10-20 minutes, max 1 hour for safety
    "pipeline.low_risk.run": {
        "soft_time_limit": 3600*3,  # 2 hours soft limit (matches task decorator)
        "time_limit": 3600*3,  # 2 hours hard limit (matches task decorator)
        "rate_limit": "1/h",  # Only 1 per hour per user (has Redis lock too)
        "acks_late": False,  # Acknowledge immediately to prevent re-queuing (matches task decorator)
        "max_retries": 0,  # NO RETRIES - prevent duplicate executions (task has Redis lock)
        "reject_on_worker_lost": True,  # Don't re-queue if worker crashes
    },
    # Quick tasks - short limits, high rate
    **{
        task_name: {
            "soft_time_limit": 120,
            "time_limit": 180,
            "rate_limit": "120/m",  # 2 per second (increased from 1/s)
        }
        for task_name in QUICK_TASKS
    },
    # Market close sell - no limits
    "pipeline.sell_high_risk_before_close": {
        "rate_limit": "1/h",  # Once per hour max
    },
}

celery_app.conf.beat_scheduler = "redbeat.RedBeatScheduler"
celery_app.conf.redbeat_redis_url = os.getenv("REDBEAT_REDIS_URL", BROKER_URL)
celery_app.conf.redbeat_lock_timeout = int(os.getenv("CELERY_REDBEAT_LOCK_TIMEOUT", "600"))
celery_app.conf.redbeat_lock_key = os.getenv("CELERY_REDBEAT_LOCK_KEY", "redbeat::lock")

NEWS_PIPELINE_ENABLED = os.getenv("NEWS_PIPELINE_ENABLED", "true").lower() in {"1", "true", "yes"}
NEWS_FETCH_RATE = int(os.getenv("NEWS_FETCH_RATE", "1800"))  # Default 30 minutes (1800 seconds)
NEWS_PIPELINE_QUEUE = os.getenv("NEWS_PIPELINE_QUEUE", QUEUE_NAMES["news_pipeline"])  # Fixed: use news_pipeline queue

NSE_PIPELINE_ENABLED = os.getenv("NSE_PIPELINE_ENABLED", "true").lower() in {"1", "true", "yes"}
NSE_PIPELINE_QUEUE = os.getenv("NSE_PIPELINE_QUEUE", QUEUE_NAMES["nse_pipeline"])  # Fixed: use nse_pipeline queue

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
RISK_MONITOR_QUEUE = os.getenv("PORTFOLIO_RISK_MONITOR_QUEUE", QUEUE_NAMES["general"])  # Fixed: use general queue

# Order Monitor Configuration (for limit/stop/take-profit orders)
ORDER_MONITOR_ENABLED = os.getenv("ORDER_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
ORDER_MONITOR_INTERVAL = int(os.getenv("ORDER_MONITOR_INTERVAL", "5"))  # Check every 5 seconds
ORDER_MONITOR_QUEUE = os.getenv("ORDER_MONITOR_QUEUE", QUEUE_NAMES["orders"])

# Initialize empty beat schedule
celery_app.conf.beat_schedule = {}

# NSE Pipeline - runs continuously (started manually, NOT via beat scheduler)
# Disabled beat schedule to prevent task accumulation since pipeline.start runs 24/7
# To start: manually trigger pipeline.start task or let it start on worker boot
# if NSE_PIPELINE_ENABLED:
#     celery_app.conf.beat_schedule["nse-filings-pipeline"] = {
#         "task": "pipeline.start",
#         "schedule": timedelta(seconds=300),  # Check every 5 minutes (task has internal lock)
#         "options": {
#             "queue": NSE_PIPELINE_QUEUE,
#             "expires": 240,  # Expire after 4 minutes if not picked up
#         },
#     }

# Only enable news pipeline via Beat if explicitly configured
if NEWS_PIPELINE_ENABLED:
    celery_app.conf.beat_schedule["news-sentiment-pipeline"] = {
        "task": "pipeline.news_sentiment.run",
        "schedule": timedelta(seconds=NEWS_FETCH_RATE),
        "options": {"queue": NEWS_PIPELINE_QUEUE},
    }

# Regime model retraining - runs daily at 8:30 AM IST (3:00 AM UTC) before market opens
REGIME_RETRAIN_ENABLED = os.getenv("REGIME_RETRAIN_ENABLED", "true").lower() in {"1", "true", "yes"}
REGIME_RETRAIN_QUEUE = os.getenv("REGIME_RETRAIN_QUEUE", DEFAULT_QUEUE)

if REGIME_RETRAIN_ENABLED:
    celery_app.conf.beat_schedule["regime-model-retrain"] = {
        "task": "portfolio.retrain_regime_model",
        "schedule": crontab(hour=3, minute=0, day_of_week="mon-fri"),  # 8:30 AM IST = 3:00 AM UTC
        "options": {"queue": REGIME_RETRAIN_QUEUE},
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

# Snapshot capture - Every 1 hour
SNAPSHOT_ENABLED = os.getenv("SNAPSHOT_CAPTURE_ENABLED", "true").lower() in {"1", "true", "yes"}
SNAPSHOT_QUEUE = os.getenv("SNAPSHOT_QUEUE", DEFAULT_QUEUE)

if SNAPSHOT_ENABLED:
    # Trading agent snapshots - every 1 hour
    celery_app.conf.beat_schedule["trading-agent-snapshots"] = {
        "task": "snapshot.capture_agent_snapshots",
        "schedule": crontab(minute=0),  # Every hour on the hour
        "options": {"queue": SNAPSHOT_QUEUE},
    }
    
    # Portfolio snapshots - every 1 hour
    celery_app.conf.beat_schedule["portfolio-snapshots"] = {
        "task": "snapshot.capture_portfolio_snapshots",
        "schedule": crontab(minute=5),  # Every hour at 5 minutes past
        "options": {"queue": SNAPSHOT_QUEUE},
    }

# Auto-sell and order monitoring is now handled by the NEW Pathway order monitor (RECOMMENDED)
# The NEW PathwayOrderMonitor in pipelines/orders/pathway_order_monitor.py handles:
# 1. TP/SL orders - reactive monitoring via Redis pub/sub (sub-100ms latency)
# 2. Limit/stop orders - reactive monitoring via Redis pub/sub
# 3. Price-based triggers - instant reaction to price changes
#
# Run with: python -m workers.pathway_order_monitor
# Or via pnpm: pnpm pathway:orders
#
# The NEW Pathway monitor:
# - ✅ Zero database polling (Redis pub/sub only)
# - ✅ Sub-100ms latency (TradeEngine → Redis → Pathway → Execution)
# - ✅ True reactive architecture (event-driven, no loops)
# - ✅ Handles all order types: TP, SL, limit, stop, time-based
#
# LEGACY: The old streaming_order_monitor.py (polls DB every 10s) is DEPRECATED
# To use legacy: Set STREAMING_ORDER_MONITOR_ENABLED=true and run pnpm streaming:orders
# To use NEW Pathway: Set PATHWAY_ORDER_MONITOR_ENABLED=true and run pnpm pathway:orders
#
# No Celery beat schedule needed - Pathway monitor runs continuously in its own process

# Market closing task - sells all high_risk positions at 3:15 PM IST (9:45 AM UTC)
# IST is UTC+5:30, so 3:15 PM IST = 9:45 AM UTC
MARKET_CLOSE_SELL_ENABLED = os.getenv("MARKET_CLOSE_SELL_ENABLED", "true").lower() in {"1", "true", "yes"}
MARKET_CLOSE_SELL_QUEUE = os.getenv("MARKET_CLOSE_SELL_QUEUE", QUEUE_NAMES["auto_sell"])  # Uses general queue

if MARKET_CLOSE_SELL_ENABLED:
    celery_app.conf.beat_schedule["sell-high-risk-before-close"] = {
        "task": "pipeline.sell_high_risk_before_close",
        "schedule": crontab(hour=9, minute=45, day_of_week="mon-fri"),  # 3:15 PM IST = 9:45 AM UTC
        "options": {"queue": MARKET_CLOSE_SELL_QUEUE},
    }

# Alpha EOD close task - sells all alpha positions at 3:20 PM IST (9:50 AM UTC)
# Runs 5 minutes after high_risk to avoid overwhelming the execution system
ALPHA_EOD_CLOSE_ENABLED = os.getenv("ALPHA_EOD_CLOSE_ENABLED", "true").lower() in {"1", "true", "yes"}
ALPHA_EOD_CLOSE_QUEUE = os.getenv("ALPHA_EOD_CLOSE_QUEUE", QUEUE_NAMES["auto_sell"])

if ALPHA_EOD_CLOSE_ENABLED:
    celery_app.conf.beat_schedule["sell-alpha-before-close"] = {
        "task": "pipeline.sell_alpha_before_close",
        "schedule": crontab(hour=9, minute=50, day_of_week="mon-fri"),  # 3:20 PM IST = 9:50 AM UTC
        "options": {"queue": ALPHA_EOD_CLOSE_QUEUE},
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

# Industry Indicators - DISABLED by default (manually trigger if needed)
INDUSTRY_INDICATORS_ENABLED = os.getenv("INDUSTRY_INDICATORS_ENABLED", "false").lower() in {"1", "true", "yes"}
INDUSTRY_INDICATORS_UPDATE_HOUR = int(os.getenv("INDUSTRY_INDICATORS_UPDATE_HOUR", "3"))  # IST time
INDUSTRY_INDICATORS_UPDATE_MINUTE = int(os.getenv("INDUSTRY_INDICATORS_UPDATE_MINUTE", "0"))  # IST time
INDUSTRY_INDICATORS_QUEUE = os.getenv("INDUSTRY_INDICATORS_QUEUE", QUEUE_NAMES["market"])


# Alpha signal generation - runs daily before market open (8:30 AM IST = 3:00 AM UTC)
# IST is UTC+5:30, so 8:30 AM IST = 3:00 AM UTC
ALPHA_SIGNALS_ENABLED = os.getenv("ALPHA_SIGNALS_ENABLED", "true").lower() in {"1", "true", "yes"}
ALPHA_SIGNALS_HOUR = int(os.getenv("ALPHA_SIGNALS_HOUR", "3"))  # 3:00 AM UTC = 8:30 AM IST
ALPHA_SIGNALS_MINUTE = int(os.getenv("ALPHA_SIGNALS_MINUTE", "0"))
ALPHA_SIGNALS_QUEUE = os.getenv("ALPHA_SIGNALS_QUEUE", QUEUE_NAMES["pipelines"])

if ALPHA_SIGNALS_ENABLED:
    celery_app.conf.beat_schedule["alpha-daily-signals"] = {
        "task": "alpha.generate_daily_signals",
        "schedule": crontab(hour=ALPHA_SIGNALS_HOUR, minute=ALPHA_SIGNALS_MINUTE, day_of_week="mon-fri"),
        "options": {"queue": ALPHA_SIGNALS_QUEUE},
    }

# Company Report News Update - runs daily at market close (3:30 PM IST = 10:00 AM UTC)
# IST is UTC+5:30, so 3:30 PM IST = 10:00 AM UTC
COMPANY_REPORT_NEWS_UPDATE_ENABLED = os.getenv("COMPANY_REPORT_NEWS_UPDATE_ENABLED", "true").lower() in {"1", "true", "yes"}
COMPANY_REPORT_NEWS_UPDATE_HOUR = int(os.getenv("COMPANY_REPORT_NEWS_UPDATE_HOUR", "10"))  # 10:00 AM UTC = 3:30 PM IST
COMPANY_REPORT_NEWS_UPDATE_MINUTE = int(os.getenv("COMPANY_REPORT_NEWS_UPDATE_MINUTE", "0"))
COMPANY_REPORT_NEWS_UPDATE_QUEUE = os.getenv("COMPANY_REPORT_NEWS_UPDATE_QUEUE", QUEUE_NAMES["news_pipeline"])

if COMPANY_REPORT_NEWS_UPDATE_ENABLED:
    celery_app.conf.beat_schedule["company-report-daily-news-update"] = {
        "task": "company_report.daily_news_update",
        "schedule": crontab(
            hour=COMPANY_REPORT_NEWS_UPDATE_HOUR,
            minute=COMPANY_REPORT_NEWS_UPDATE_MINUTE,
            day_of_week="mon-fri",
        ),
        "options": {"queue": COMPANY_REPORT_NEWS_UPDATE_QUEUE},
    }

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
        market_data_tasks,
        risk_alert_tasks,
        snapshot_tasks,
        angelone_token_task,
        economic_indicators_tasks,
        alpha_signal_tasks,
        company_report_update_tasks,  # Company report update from NSE/News
    )


# Only import tasks when running as Celery worker (not when imported by other modules)
if os.environ.get("CELERY_WORKER_RUNNING") or "celery" in sys.argv[0]:
    _import_tasks()
    
    # Note: Prometheus exporter is initialized via worker_ready signal below


# Worker process initialization - reset Prisma client on fork
@signals.worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Reset Prisma client when worker process is forked.
    
    This is critical because Prisma clients cannot be shared across process forks.
    Each forked worker needs its own Prisma client instance.
    
    Also disables NumPy/OpenBLAS threading to prevent SIGSEGV in HMM training.
    """
    try:
        # CRITICAL: Disable NumPy/OpenBLAS threading before any NumPy imports
        # This prevents SIGSEGV errors in HMM training with multiprocessing
        os.environ["OPENBLAS_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"
        os.environ["NUMEXPR_NUM_THREADS"] = "1"
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
        
        # Set NumPy threading to single-threaded if NumPy is already imported
        try:
            import numpy as np
            # Force single-threaded mode for NumPy operations
            # This must be done before any BLAS operations
            np.seterr(all='ignore')  # Suppress warnings
        except ImportError:
            pass  # NumPy not imported yet, env vars will take effect
        
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
    
    Uses timeout to prevent blocking on soft time limit exceeded.
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
                # Use asyncio.wait_for with timeout to prevent blocking on soft time limit
                async def _disconnect_with_timeout():
                    await db_manager.disconnect(timeout=3.0)
                
                asyncio.run(_disconnect_with_timeout())
                logging.debug("🔌 Task complete - DB disconnected: %s [%s]", task.name if task else sender, task_id)
            except Exception as disc_exc:
                exc_name = type(disc_exc).__name__
                if exc_name == "SoftTimeLimitExceeded":
                    logging.warning("⚠️ SoftTimeLimitExceeded during postrun disconnect for task %s", task_id)
                    # Force reset to ensure clean state for next task
                    DBManager.reset_instance()
                else:
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
            
            # Force reset immediately - don't try to disconnect since we're in a timeout state
            # The disconnect could block or fail, better to just reset and let connection timeout
            db_manager = DBManager._instance
            if db_manager:
                # Force cleanup without async disconnect (which could block)
                try:
                    # Unregister from Prisma registry synchronously
                    if db_manager.client:
                        try:
                            from prisma._registry import unregister
                            unregister(db_manager.client)
                        except Exception:
                            pass
                except Exception:
                    pass
                finally:
                    # Always reset to ensure next task gets fresh connection
                    DBManager.reset_instance()
                    logging.info("🔌 Forced DB reset on soft timeout: %s", task_id)
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
    
    # Check and update economic indicators on startup (only market worker)
    if ECONOMIC_INDICATORS_ENABLED:
        worker_name = os.getenv("WORKER_NAME", "")
        if not worker_name and "sender" in kwargs:
            sender = kwargs.get("sender")
            worker_name = getattr(sender, "hostname", "")

        if worker_name.startswith("market@"):
            try:
                from workers.economic_indicators_tasks import check_and_update_on_startup
                check_and_update_on_startup()
            except Exception as e:
                logging.warning("Failed to run economic indicators startup check: %s", e)
        else:
            logging.info(
                "Skipping economic indicator startup check for worker %s (market worker only)",
                worker_name or "unknown",
            )


# Clean up database connections when worker process shuts down
@signals.worker_process_shutdown.connect
def cleanup_worker_process(**kwargs):
    """
    Clean up Prisma client when worker process is shutting down.
    
    This ensures database connections are properly released before the worker exits,
    preventing connection leaks.
    """
    import asyncio
    
    logger = logging.getLogger(__name__)
    logger.info("🔌 Worker process shutting down - cleaning up database connections (PID %s)", os.getpid())
    
    try:
        # Add shared/py to path for DBManager import
        project_root = Path(__file__).resolve().parents[2]
        shared_py = project_root / "shared" / "py"
        if str(shared_py) not in sys.path:
            sys.path.insert(0, str(shared_py))
        
        from dbManager import DBManager
        
        # Force disconnect and reset
        if DBManager._instance is not None:
            try:
                # Try to run disconnect in a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(DBManager._instance.disconnect(force=True))
                finally:
                    loop.close()
            except Exception as disc_exc:
                logger.debug("Async disconnect failed: %s", disc_exc)
            
            # Always reset the instance
            DBManager.reset_instance()
        
        logger.info("✅ Database connections cleaned up for PID %s", os.getpid())
    except Exception as e:
        logger.warning("⚠️ Error during database cleanup: %s", e)


__all__ = ["celery_app"]
