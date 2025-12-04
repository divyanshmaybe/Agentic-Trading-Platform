"""Celery application configuration."""

from celery import Celery
from quant_stream.mcp_server.config import get_config

# Get configuration
config = get_config()

# Create Celery app
celery_app = Celery(
    "quant_stream.mcp_server",
    broker=config.redis.url,
    backend=config.redis.url,
    include=["quant_stream.mcp_server.core.tasks"],
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # 55 minutes soft limit
    result_expires=86400,  # Results expire after 24 hours
    worker_prefetch_multiplier=1,  # Process one task at a time per worker
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks
    task_acks_late=True,  # Acknowledge task after completion
    task_reject_on_worker_lost=True,  # Requeue task if worker dies
    worker_redirect_stdouts=False,  # Don't redirect stdout - let print statements show
    worker_redirect_stdouts_level="INFO",  # Redirect stderr to logger at INFO level
)

# Task routing
celery_app.conf.task_routes = {
    "quant_stream.mcp_server.core.tasks.run_workflow_task": {"queue": "workflow"},
}

# Monitoring configuration
celery_app.conf.update(
    worker_send_task_events=True,
    task_send_sent_event=True,
)

