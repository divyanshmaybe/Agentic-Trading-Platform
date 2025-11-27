from __future__ import annotations

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
    ],
)

VISIBILITY_TIMEOUT = int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "900"))
RESULT_TTL = int(os.getenv("CELERY_RESULT_TTL", "86400"))
SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "600"))
HARD_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", str(SOFT_TIME_LIMIT + 120)))

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
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "200")),
    worker_prefetch_multiplier=int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1")),
    worker_redirect_stdouts=False,
    worker_send_task_events=True,
    worker_hijack_root_logger=False,
    worker_disable_rate_limits=False,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": VISIBILITY_TIMEOUT,
        "fanout_prefix": True,
        "fanout_patterns": True,
        "max_retries": 3,
    },
    result_expires=RESULT_TTL,
    result_persistent=True,
)

# Ensure all queues are registered explicitly with proper routing keys
_all_queues = [Queue(DEFAULT_QUEUE, routing_key=DEFAULT_QUEUE)]
for queue_name in ["allocations", "trading", "pipelines", "risk", "orders", "market", "tokens"]:
    if not any(q.name == queue_name for q in _all_queues):
        _all_queues.append(Queue(queue_name, routing_key=queue_name))
celery_app.conf.task_queues = _all_queues

celery_app.conf.task_routes = {
    # Allocation + trading queues
    "portfolio.allocate_for_objective": {"queue": QUEUE_NAMES["allocations"], "routing_key": "allocations"},
    "portfolio.check_regime_and_rebalance": {"queue": QUEUE_NAMES["allocations"], "routing_key": "allocations"},
    "trading.execute_trade_job": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    # Pipelines + data - Signal processing goes to pipelines queue (contains pathway streaming)
    "pipeline.trade_execution.process_signal": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "pipeline.start": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "pipeline.news_sentiment.run": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "pipeline.risk_monitor.run": {"queue": QUEUE_NAMES["pipelines"], "routing_key": "pipelines"},
    "market_data.fetch_via_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.batch_fetch_via_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.health_check_api": {"queue": QUEUE_NAMES["market"], "routing_key": "market"},
    "market_data.generate_angelone_tokens": {"queue": QUEUE_NAMES["tokens"], "routing_key": "tokens"},
    # Risk + alerts
    "risk.alerts.send_email": {"queue": QUEUE_NAMES["risk"], "routing_key": "risk"},
    "risk.streaming_monitor.start": {"queue": QUEUE_NAMES["risk"], "routing_key": "risk"},
    # Auto-sell worker
    "trades.auto_sell_expired_trades": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
    "pipeline.sell_high_risk_before_close": {"queue": QUEUE_NAMES["trading"], "routing_key": "trading"},
}

ANNOTATED_TASKS = [
    "portfolio.allocate_for_objective",
    "portfolio.check_regime_and_rebalance",
    "pipeline.risk_monitor.run",
    "pipeline.news_sentiment.run",
    "pipeline.trade_execution.process_signal",
    "trading.execute_trade_job",
]

celery_app.conf.task_annotations = {
    task_name: {
        "soft_time_limit": SOFT_TIME_LIMIT,
        "time_limit": HARD_TIME_LIMIT,
    }
    for task_name in ANNOTATED_TASKS
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
    )


# Only import tasks when running as Celery worker (not when imported by other modules)
if os.environ.get("CELERY_WORKER_RUNNING") or "celery" in sys.argv[0]:
    _import_tasks()
    
    # Initialize Prometheus monitoring if enabled
    if os.getenv("PROMETHEUS_ENABLED", "false").lower() in {"1", "true", "yes"}:
        try:
            from monitoring.prometheus_exporter import setup_prometheus_exporter
            setup_prometheus_exporter()
        except ImportError:
            logging.warning("prometheus-client not installed, skipping metrics export")
        except Exception as e:
            logging.error("Failed to initialize Prometheus exporter: %s", e)


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


# Initialize Prometheus exporter when worker is ready
@signals.worker_ready.connect
def setup_prometheus(**kwargs):
    """Set up Prometheus exporter when worker is ready."""
    prometheus_enabled = os.getenv("PROMETHEUS_ENABLED", "true").lower() in ("true", "1", "yes")
    
    if not prometheus_enabled:
        return
    
    try:
        from monitoring.prometheus_exporter import setup_prometheus_exporter
        
        # Port is auto-determined based on worker name
        setup_prometheus_exporter()
        
    except Exception as e:
        logging.error("❌ Failed to initialize Prometheus exporter: %s", e, exc_info=True)


__all__ = ["celery_app"]
