"""
Prometheus Exporter for Celery Workers

Exposes metrics about Celery task execution, worker health, and queue statistics.
Each worker pool runs its own Prometheus exporter on a different port.

Note: This exporter provides worker-local metrics. For cluster-wide Celery metrics,
use danihodovic/celery-exporter which connects to the Redis broker and provides
comprehensive task lifecycle metrics (sent, received, started, succeeded, failed, etc.)
"""

from __future__ import annotations

import logging
import os
import time
from threading import Thread
from typing import Optional

from celery import signals
from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server

logger = logging.getLogger(__name__)

# Metrics
celery_tasks_total = Counter(
    'celery_tasks_total',
    'Total number of tasks processed',
    ['worker', 'task_name', 'status']
)

celery_task_duration_seconds = Histogram(
    'celery_task_duration_seconds',
    'Task execution duration in seconds',
    ['worker', 'task_name'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0, 3600.0)
)

celery_task_runtime_seconds = Histogram(
    'celery_task_runtime_seconds',
    'Task runtime in seconds',
    ['worker', 'task_name'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0)
)

celery_worker_tasks_active = Gauge(
    'celery_worker_tasks_active',
    'Number of tasks currently being executed',
    ['worker']
)

celery_worker_pool_usage = Gauge(
    'celery_worker_pool_usage',
    'Worker pool utilization (active/total)',
    ['worker']
)

celery_task_received = Counter(
    'celery_task_received_total',
    'Total tasks received by worker',
    ['worker', 'task_name']
)

celery_task_started = Counter(
    'celery_task_started_total',
    'Total tasks started',
    ['worker', 'task_name']
)

celery_task_succeeded = Counter(
    'celery_task_succeeded_total',
    'Total tasks succeeded',
    ['worker', 'task_name']
)

celery_task_failed = Counter(
    'celery_task_failed_total',
    'Total tasks failed',
    ['worker', 'task_name']
)

celery_task_retried = Counter(
    'celery_task_retried_total',
    'Total tasks retried',
    ['worker', 'task_name']
)

celery_task_rejected = Counter(
    'celery_task_rejected_total',
    'Total tasks rejected',
    ['worker', 'task_name']
)

celery_worker_info = Info(
    'celery_worker',
    'Information about the Celery worker'
)

celery_worker_up = Gauge(
    'celery_worker_up',
    'Worker is up and running',
    ['worker']
)

# Track active tasks per worker
_active_tasks = {}


def get_worker_name() -> str:
    """Get the current worker hostname/name."""
    # Prefer environment variable (set by worker startup script)
    worker_name = os.getenv('WORKER_NAME')
    if worker_name:
        return worker_name
    
    # Fallback: try to get from Celery inspect (may fail if broker not ready)
    try:
        from celery import current_app
        hostname = current_app.control.inspect().active()
        if hostname:
            return list(hostname.keys())[0] if hostname else 'unknown'
    except Exception:
        pass
    
    return 'unknown'


class PrometheusExporter:
    """Prometheus metrics exporter for Celery workers."""
    
    def __init__(self, port: Optional[int] = None):
        """
        Initialize Prometheus exporter.
        
        Args:
            port: Port to expose metrics on. If None, determined from worker name.
        """
        self.worker_name = get_worker_name()
        self.port = port or self._get_port_for_worker()
        self.server_thread: Optional[Thread] = None
        
    def _get_port_for_worker(self) -> int:
        """Get Prometheus port based on worker name."""
        # Default ports per worker pool
        worker_ports = {
            'trading': 9101,
            'pipeline': 9102,
            'allocation': 9103,
            'market': 9104,
            'general': 9105,
        }
        
        for worker_type, port in worker_ports.items():
            if worker_type in self.worker_name.lower():
                return port
        
        # Fallback to environment variable or default
        return int(os.getenv('PROMETHEUS_PORT', '9100'))
    
    def start(self):
        """Start Prometheus HTTP server in background thread."""
        try:
            # Start HTTP server
            start_http_server(self.port)
            logger.info(
                "📊 Prometheus metrics server started on port %d for worker %s",
                self.port,
                self.worker_name
            )
            
            # Set worker info
            celery_worker_info.info({
                'worker_name': self.worker_name,
                'port': str(self.port),
                'pid': str(os.getpid())
            })
            
            # Mark worker as up
            celery_worker_up.labels(worker=self.worker_name).set(1)
            
        except OSError as e:
            logger.warning(
                "Failed to start Prometheus server on port %d: %s (port may be in use)",
                self.port,
                e
            )
        except Exception as e:
            logger.error("Failed to start Prometheus exporter: %s", e, exc_info=True)
    
    def stop(self):
        """Stop Prometheus exporter."""
        celery_worker_up.labels(worker=self.worker_name).set(0)
        logger.info("📊 Prometheus exporter stopped for worker %s", self.worker_name)


# Global exporter instance
_exporter: Optional[PrometheusExporter] = None


def setup_prometheus_exporter(port: Optional[int] = None):
    """
    Set up Prometheus exporter for Celery worker.
    
    Args:
        port: Port to expose metrics on
    """
    global _exporter
    
    logger.info("📊 Setting up Prometheus exporter (port=%s)", port)
    
    if _exporter is not None:
        logger.warning("Prometheus exporter already initialized")
        return
    
    _exporter = PrometheusExporter(port=port)
    _exporter.start()
    
    logger.info("📊 Prometheus exporter started, registering signal handlers")
    # Register Celery signal handlers
    _register_signal_handlers()
    logger.info("📊 Signal handlers registered successfully")
    
    # Initialize business metrics
    try:
        from monitoring.business_metrics import init_business_metrics, BUSINESS_METRICS_ENABLED
        if BUSINESS_METRICS_ENABLED:
            worker_name = _exporter.worker_name
            # Extract worker pool from name (e.g., "trading@docker" -> "trading")
            worker_pool = worker_name.split("@")[0] if "@" in worker_name else worker_name
            init_business_metrics(worker_name, worker_pool)
            logger.info("📊 Business metrics initialized for worker %s", worker_name)
    except Exception as e:
        logger.warning("Failed to initialize business metrics: %s", e)


def _register_signal_handlers():
    """Register Celery signal handlers for metrics collection."""
    logger.info("📊 Registering Celery signal handlers for metrics collection")
    
    @signals.task_received.connect
    def task_received_handler(sender=None, headers=None, body=None, **kwargs):
        """Track when task is received."""
        task_name = headers.get('task', 'unknown') if headers else 'unknown'
        worker_name = get_worker_name()
        logger.debug(f"📊 Task received: {task_name} on {worker_name}")
        celery_task_received.labels(worker=worker_name, task_name=task_name).inc()
    
    @signals.task_prerun.connect
    def task_prerun_handler(sender=None, task_id=None, task=None, **kwargs):
        """Track when task starts executing."""
        task_name = task.name if task else sender.name if sender else 'unknown'
        worker_name = get_worker_name()
        logger.debug(f"📊 Task started: {task_name} on {worker_name}")
        
        celery_task_started.labels(worker=worker_name, task_name=task_name).inc()
        
        # Track start time for duration calculation
        _active_tasks[task_id] = {
            'start_time': time.time(),
            'task_name': task_name,
            'worker': worker_name
        }
        
        # Update active tasks gauge
        celery_worker_tasks_active.labels(worker=worker_name).inc()
    
    @signals.task_postrun.connect
    def task_postrun_handler(sender=None, task_id=None, task=None, state=None, **kwargs):
        """Track when task finishes (success or failure)."""
        if task_id not in _active_tasks:
            return
        
        task_info = _active_tasks.pop(task_id)
        duration = time.time() - task_info['start_time']
        task_name = task_info['task_name']
        worker_name = task_info['worker']
        
        # Record duration
        celery_task_duration_seconds.labels(
            worker=worker_name,
            task_name=task_name
        ).observe(duration)
        
        # Update active tasks gauge
        celery_worker_tasks_active.labels(worker=worker_name).dec()
    
    @signals.task_success.connect
    def task_success_handler(sender=None, result=None, **kwargs):
        """Track successful task completion."""
        task_name = sender.name if sender else 'unknown'
        worker_name = get_worker_name()
        logger.debug(f"📊 Task succeeded: {task_name} on {worker_name}")
        
        celery_task_succeeded.labels(worker=worker_name, task_name=task_name).inc()
        celery_tasks_total.labels(worker=worker_name, task_name=task_name, status='success').inc()
    
    @signals.task_failure.connect
    def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
        """Track failed task."""
        task_name = sender.name if sender else 'unknown'
        worker_name = get_worker_name()
        
        celery_task_failed.labels(worker=worker_name, task_name=task_name).inc()
        celery_tasks_total.labels(worker=worker_name, task_name=task_name, status='failure').inc()
        
        # Clean up if task is still in active tasks
        if task_id in _active_tasks:
            _active_tasks.pop(task_id)
            celery_worker_tasks_active.labels(worker=worker_name).dec()
    
    @signals.task_retry.connect
    def task_retry_handler(sender=None, reason=None, **kwargs):
        """Track task retries."""
        task_name = sender.name if sender else 'unknown'
        worker_name = get_worker_name()
        
        celery_task_retried.labels(worker=worker_name, task_name=task_name).inc()
    
    @signals.task_rejected.connect
    def task_rejected_handler(sender=None, **kwargs):
        """Track rejected tasks."""
        task_name = sender.name if sender else 'unknown'
        worker_name = get_worker_name()
        
        celery_task_rejected.labels(worker=worker_name, task_name=task_name).inc()
    
    @signals.worker_ready.connect
    def worker_ready_handler(sender=None, **kwargs):
        """Track when worker is ready."""
        worker_name = get_worker_name()
        celery_worker_up.labels(worker=worker_name).set(1)
        logger.info("📊 Worker %s is ready and reporting metrics", worker_name)
    
    @signals.worker_shutdown.connect
    def worker_shutdown_handler(sender=None, **kwargs):
        """Track when worker shuts down."""
        worker_name = get_worker_name()
        celery_worker_up.labels(worker=worker_name).set(0)
        logger.info("📊 Worker %s shutting down", worker_name)