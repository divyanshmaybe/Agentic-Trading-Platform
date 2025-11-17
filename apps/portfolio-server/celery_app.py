from __future__ import annotations

import logging
import os
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

from celery import Celery
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
        "workers.order_monitor_worker",
        "workers.trade_execution_tasks",
        "workers.pipeline_tasks",
        "workers.snapshot_tasks",
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

celery_app.conf.task_queues = _queue_set(QUEUE_NAMES.values())

celery_app.conf.task_routes = {
    # Allocation + trading queues
    "portfolio.allocate_new_portfolio": {"queue": QUEUE_NAMES["allocations"]},
    "portfolio.allocate_for_objective": {"queue": QUEUE_NAMES["allocations"]},
    "portfolio.daily_rebalancing_sweep": {"queue": QUEUE_NAMES["allocations"]},
    "pipeline.rebalance.scheduled": {"queue": QUEUE_NAMES["allocations"]},
    "trading.execute_trade_job": {"queue": QUEUE_NAMES["trading"]},
    "trading.process_pending_trade": {"queue": QUEUE_NAMES["trading"]},
    "pipeline.trade_execution.process_signal": {"queue": QUEUE_NAMES["trading"]},
    # Pipelines + data
    "pipeline.start": {"queue": QUEUE_NAMES["pipelines"]},
    "pipeline.news_sentiment.run": {"queue": QUEUE_NAMES["pipelines"]},
    "pipeline.risk_monitor.run": {"queue": QUEUE_NAMES["pipelines"]},
    "market_data.fetch_via_api": {"queue": QUEUE_NAMES["market"]},
    "market_data.batch_fetch_via_api": {"queue": QUEUE_NAMES["market"]},
    "market_data.health_check_api": {"queue": QUEUE_NAMES["market"]},
    "market_data.generate_angelone_tokens": {"queue": QUEUE_NAMES["tokens"]},
    # Risk + alerts
    "risk.alerts.send_email": {"queue": QUEUE_NAMES["risk"]},
    # Order monitoring
    "order_monitor.start_continuous_monitoring": {"queue": QUEUE_NAMES["orders"]},
    "order_monitor.check_pending_orders_once": {"queue": QUEUE_NAMES["orders"]},
}

ANNOTATED_TASKS = [
    "portfolio.allocate_new_portfolio",
    "portfolio.allocate_for_objective",
    "portfolio.daily_rebalancing_sweep",
    "pipeline.rebalance.scheduled",
    "pipeline.risk_monitor.run",
    "pipeline.news_sentiment.run",
    "pipeline.trade_execution.process_signal",
    "trading.execute_trade_job",
    "trading.process_pending_trade",
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

NEWS_PIPELINE_ENABLED = os.getenv("NEWS_PIPELINE_ENABLED", "false").lower() in {"1", "true", "yes"}
NEWS_FETCH_RATE = int(os.getenv("NEWS_FETCH_RATE", "3600"))
NEWS_PIPELINE_QUEUE = os.getenv("NEWS_PIPELINE_QUEUE", QUEUE_NAMES["pipelines"])

REBALANCE_ENABLED = os.getenv("PORTFOLIO_REBALANCE_ENABLED", "true").lower() in {"1", "true", "yes"}
REBALANCE_HOUR = int(os.getenv("PORTFOLIO_REBALANCE_HOUR", "5"))
REBALANCE_MINUTE = int(os.getenv("PORTFOLIO_REBALANCE_MINUTE", "0"))
REBALANCE_DAY_OF_WEEK = os.getenv("PORTFOLIO_REBALANCE_DAY_OF_WEEK", "mon-fri")
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

# Only enable news pipeline via Beat if explicitly configured
if NEWS_PIPELINE_ENABLED:
    celery_app.conf.beat_schedule["news-sentiment-pipeline"] = {
        "task": "pipeline.news_sentiment.run",
        "schedule": timedelta(seconds=NEWS_FETCH_RATE),
        "options": {"queue": NEWS_PIPELINE_QUEUE},
    }

if REBALANCE_ENABLED:
    celery_app.conf.beat_schedule["portfolio-daily-rebalance"] = {
        "task": "portfolio.daily_rebalancing_sweep",
        "schedule": crontab(hour=REBALANCE_HOUR, minute=REBALANCE_MINUTE, day_of_week=REBALANCE_DAY_OF_WEEK),
        "options": {"queue": REBALANCE_QUEUE},
    }

if RISK_MONITOR_ENABLED:
    celery_app.conf.beat_schedule["portfolio-risk-monitor"] = {
        "task": "pipeline.risk_monitor.run",
        "schedule": timedelta(seconds=RISK_MONITOR_INTERVAL),
        "options": {"queue": RISK_MONITOR_QUEUE},
    }

# Order Monitor - Continuous checking of pending limit/stop/take-profit orders
if ORDER_MONITOR_ENABLED:
    celery_app.conf.beat_schedule["order-monitor-check"] = {
        "task": "order_monitor.check_pending_orders_once",
        "schedule": timedelta(seconds=ORDER_MONITOR_INTERVAL),
        "options": {"queue": ORDER_MONITOR_QUEUE},
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

__all__ = ["celery_app"]
