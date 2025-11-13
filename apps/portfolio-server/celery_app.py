from __future__ import annotations

import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from celery import Celery
from celery.schedules import crontab

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "portfolio-server",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=[
        "workers.trade_tasks",
        # "workers.pipeline_tasks",
        "workers.market_data_tasks",  # REST-based market data helpers
        "workers.angelone_token_task",  # Angel One token map generation
        "workers.allocation_tasks",  # Portfolio allocation and rebalancing
        "workers.risk_alert_tasks",  # Email notifications for risk monitor
        "workers.order_monitor_worker",  # Continuous order monitoring for limit/stop/TP orders
        "workers.trade_execution_tasks",  # Automated trade execution
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_max_tasks_per_child=100,
    worker_redirect_stdouts=False,
)

NEWS_FETCH_RATE = int(os.getenv("NEWS_FETCH_RATE", "3600"))

REBALANCE_ENABLED = os.getenv("PORTFOLIO_REBALANCE_ENABLED", "true").lower() in {"1", "true", "yes"}
REBALANCE_HOUR = int(os.getenv("PORTFOLIO_REBALANCE_HOUR", "5"))
REBALANCE_MINUTE = int(os.getenv("PORTFOLIO_REBALANCE_MINUTE", "0"))
REBALANCE_DAY_OF_WEEK = os.getenv("PORTFOLIO_REBALANCE_DAY_OF_WEEK", "mon-fri")
REBALANCE_QUEUE = os.getenv("PORTFOLIO_REBALANCE_QUEUE", "default")

RISK_MONITOR_ENABLED = os.getenv("PORTFOLIO_RISK_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
RISK_MONITOR_INTERVAL = int(os.getenv("PORTFOLIO_RISK_MONITOR_INTERVAL", "900"))
RISK_MONITOR_QUEUE = os.getenv("PORTFOLIO_RISK_MONITOR_QUEUE", "default")

# Order Monitor Configuration (for limit/stop/take-profit orders)
ORDER_MONITOR_ENABLED = os.getenv("ORDER_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
ORDER_MONITOR_INTERVAL = int(os.getenv("ORDER_MONITOR_INTERVAL", "5"))  # Check every 5 seconds
ORDER_MONITOR_QUEUE = os.getenv("ORDER_MONITOR_QUEUE", "default")

celery_app.conf.beat_schedule = {
    "news-sentiment-pipeline": {
        "task": "pipeline.news_sentiment.run",
        "schedule": timedelta(seconds=NEWS_FETCH_RATE),
        "options": {"queue": os.getenv("NEWS_PIPELINE_QUEUE", "default")},
    }
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

__all__ = ["celery_app"]
