"""
Prometheus Metrics for AlphaCopilot Server

Exposes workflow execution, LLM usage, and backtest metrics.
"""

import time
import logging
from functools import wraps
from typing import Optional, Callable, Any

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

logger = logging.getLogger(__name__)

# ============================================================================
# Run Metrics
# ============================================================================

alphacopilot_runs_total = Counter(
    'alphacopilot_runs_total',
    'Total AlphaCopilot workflow runs',
    ['status']  # "created", "running", "completed", "failed", "cancelled"
)

alphacopilot_run_duration_seconds = Histogram(
    'alphacopilot_run_duration_seconds',
    'Workflow run duration',
    ['workflow_type'],  # "full", "validation_only", "backtest_only"
    buckets=(10, 30, 60, 120, 300, 600, 1200, 1800, 3600)
)

alphacopilot_concurrent_runs = Gauge(
    'alphacopilot_concurrent_runs',
    'Number of concurrent workflow runs'
)

# ============================================================================
# Iteration Metrics
# ============================================================================

alphacopilot_iterations_total = Counter(
    'alphacopilot_iterations_total',
    'Total workflow iterations',
    ['iteration_type', 'status']  # iteration_type: "factor_gen", "validation", "refinement"
)

alphacopilot_iteration_duration_seconds = Histogram(
    'alphacopilot_iteration_duration_seconds',
    'Duration of each iteration',
    ['iteration_type'],
    buckets=(5, 10, 30, 60, 120, 300, 600)
)

# ============================================================================
# LLM Metrics
# ============================================================================

alphacopilot_llm_requests_total = Counter(
    'alphacopilot_llm_requests_total',
    'Total LLM API requests',
    ['model', 'endpoint', 'status']  # status: "success", "error", "timeout"
)

alphacopilot_llm_latency_seconds = Histogram(
    'alphacopilot_llm_latency_seconds',
    'LLM API response latency',
    ['model', 'endpoint'],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60)
)

alphacopilot_llm_tokens_total = Counter(
    'alphacopilot_llm_tokens_total',
    'Total LLM tokens used',
    ['model', 'token_type']  # token_type: "input", "output"
)

# ============================================================================
# Factor Validation Metrics
# ============================================================================

alphacopilot_factor_validations_total = Counter(
    'alphacopilot_factor_validations_total',
    'Total factor expression validations',
    ['status']  # "valid", "invalid", "error"
)

alphacopilot_factors_generated_total = Counter(
    'alphacopilot_factors_generated_total',
    'Total alpha factors generated',
    ['factor_type']
)

# ============================================================================
# Backtest Metrics (if Celery queue enabled)
# ============================================================================

alphacopilot_backtest_jobs_total = Counter(
    'alphacopilot_backtest_jobs_total',
    'Total backtest jobs',
    ['status']  # "queued", "running", "completed", "failed"
)

alphacopilot_backtest_duration_seconds = Histogram(
    'alphacopilot_backtest_duration_seconds',
    'Backtest execution duration',
    buckets=(30, 60, 120, 300, 600, 1200, 1800)
)

# ============================================================================
# System Metrics
# ============================================================================

alphacopilot_db_queries_total = Counter(
    'alphacopilot_db_queries_total',
    'Total database queries',
    ['operation', 'table']  # operation: "select", "insert", "update"
)

alphacopilot_service_info = Info(
    'alphacopilot_service',
    'AlphaCopilot service information'
)

# ============================================================================
# Tracking State for Duration Calculations
# ============================================================================

_run_start_times: dict[str, float] = {}
_iteration_start_times: dict[str, tuple[float, str]] = {}
_llm_start_times: dict[str, tuple[float, str, str]] = {}


# ============================================================================
# Helper Functions
# ============================================================================

def record_run_created(run_id: str) -> None:
    """Record a new run being created."""
    alphacopilot_runs_total.labels(status="created").inc()
    _run_start_times[run_id] = time.time()
    alphacopilot_concurrent_runs.inc()


def record_run_completed(run_id: str, status: str, workflow_type: str = "full") -> None:
    """Record a run completion (success or failure)."""
    alphacopilot_runs_total.labels(status=status).inc()
    alphacopilot_concurrent_runs.dec()
    
    if run_id in _run_start_times:
        duration = time.time() - _run_start_times.pop(run_id)
        alphacopilot_run_duration_seconds.labels(workflow_type=workflow_type).observe(duration)


def record_iteration_start(iteration_id: str, iteration_type: str) -> None:
    """Record the start of an iteration."""
    _iteration_start_times[iteration_id] = (time.time(), iteration_type)


def record_iteration_complete(iteration_id: str, status: str) -> None:
    """Record iteration completion."""
    if iteration_id in _iteration_start_times:
        start_time, iteration_type = _iteration_start_times.pop(iteration_id)
        duration = time.time() - start_time
        alphacopilot_iterations_total.labels(iteration_type=iteration_type, status=status).inc()
        alphacopilot_iteration_duration_seconds.labels(iteration_type=iteration_type).observe(duration)
    else:
        # No start time recorded, just increment counter
        alphacopilot_iterations_total.labels(iteration_type="unknown", status=status).inc()


def record_llm_request_start(request_id: str, model: str, endpoint: str) -> None:
    """Record the start of an LLM request."""
    _llm_start_times[request_id] = (time.time(), model, endpoint)


def record_llm_request_complete(
    request_id: str,
    status: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None
) -> None:
    """Record LLM request completion."""
    if request_id in _llm_start_times:
        start_time, model, endpoint = _llm_start_times.pop(request_id)
        duration = time.time() - start_time
        alphacopilot_llm_requests_total.labels(model=model, endpoint=endpoint, status=status).inc()
        alphacopilot_llm_latency_seconds.labels(model=model, endpoint=endpoint).observe(duration)
        
        if input_tokens is not None:
            alphacopilot_llm_tokens_total.labels(model=model, token_type="input").inc(input_tokens)
        if output_tokens is not None:
            alphacopilot_llm_tokens_total.labels(model=model, token_type="output").inc(output_tokens)


def record_factor_validation(status: str) -> None:
    """Record a factor validation result."""
    alphacopilot_factor_validations_total.labels(status=status).inc()


def record_factor_generated(factor_type: str) -> None:
    """Record a factor being generated."""
    alphacopilot_factors_generated_total.labels(factor_type=factor_type).inc()


def record_backtest_job(status: str) -> None:
    """Record backtest job status."""
    alphacopilot_backtest_jobs_total.labels(status=status).inc()


def record_db_query(operation: str, table: str) -> None:
    """Record a database query."""
    alphacopilot_db_queries_total.labels(operation=operation, table=table).inc()


# ============================================================================
# Decorators
# ============================================================================

def track_llm_call(model: str, endpoint: str):
    """Decorator to track LLM API calls."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            request_id = f"{func.__name__}_{time.time()}"
            record_llm_request_start(request_id, model, endpoint)
            try:
                result = await func(*args, **kwargs)
                # Try to extract token counts from result if available
                input_tokens = getattr(result, 'input_tokens', None)
                output_tokens = getattr(result, 'output_tokens', None)
                record_llm_request_complete(request_id, "success", input_tokens, output_tokens)
                return result
            except TimeoutError:
                record_llm_request_complete(request_id, "timeout")
                raise
            except Exception:
                record_llm_request_complete(request_id, "error")
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            request_id = f"{func.__name__}_{time.time()}"
            record_llm_request_start(request_id, model, endpoint)
            try:
                result = func(*args, **kwargs)
                record_llm_request_complete(request_id, "success")
                return result
            except TimeoutError:
                record_llm_request_complete(request_id, "timeout")
                raise
            except Exception:
                record_llm_request_complete(request_id, "error")
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


# ============================================================================
# Metrics Endpoint
# ============================================================================

def metrics_endpoint() -> Response:
    """
    FastAPI endpoint to expose Prometheus metrics.
    Returns metrics in Prometheus text format.
    
    Usage:
        app.add_api_route("/metrics", metrics_endpoint)
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


def set_service_info(version: str, environment: str) -> None:
    """Set service information."""
    alphacopilot_service_info.info({
        'version': version,
        'environment': environment,
    })
