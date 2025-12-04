"""
Business-Level Prometheus Metrics for Trading Platform

Tracks trading-domain KPIs including trade execution, risk alerts, and pipeline health.
These custom metrics complement the core Celery metrics from celery-exporter.
"""

from __future__ import annotations

import logging
import os
import time
from functools import wraps
from typing import Any, Callable, Optional

from prometheus_client import Counter, Gauge, Histogram, Info

logger = logging.getLogger(__name__)

# Environment flag to enable/disable custom business metrics
BUSINESS_METRICS_ENABLED = os.getenv("BUSINESS_METRICS_ENABLED", "true").lower() in ("true", "1", "yes")

# ============================================================================
# Trade Execution Metrics
# ============================================================================

# Total trade executions by strategy, status, and queue
portfolio_trade_executions_total = Counter(
    'portfolio_trade_executions_total',
    'Total number of trade executions',
    ['strategy', 'status', 'queue', 'symbol']
)

# Trade execution latency (signal-to-execution time)
portfolio_trade_execution_latency_seconds = Histogram(
    'portfolio_trade_execution_latency_seconds',
    'Trade execution latency from signal to order placement',
    ['strategy', 'queue'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)
)

# Trade signal processing time
portfolio_signal_processing_seconds = Histogram(
    'portfolio_signal_processing_seconds',
    'Time to process trading signals',
    ['signal_type', 'source'],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

# Currently active trades being processed
portfolio_active_trades = Gauge(
    'portfolio_active_trades',
    'Number of trades currently being processed',
    ['queue']
)

# Trade execution errors by type
portfolio_trade_errors_total = Counter(
    'portfolio_trade_errors_total',
    'Total trade execution errors',
    ['error_type', 'strategy', 'symbol']
)

# ============================================================================
# Risk Management Metrics
# ============================================================================

# Pending risk alerts by type and severity
portfolio_risk_alerts_pending = Gauge(
    'portfolio_risk_alerts_pending',
    'Number of pending risk alerts',
    ['alert_type', 'severity']
)

# Risk alert processing time
portfolio_risk_alert_processing_seconds = Histogram(
    'portfolio_risk_alert_processing_seconds',
    'Time to process risk alerts',
    ['alert_type'],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0)
)

# Risk alerts sent by type and channel
portfolio_risk_alerts_sent_total = Counter(
    'portfolio_risk_alerts_sent_total',
    'Total risk alerts sent',
    ['alert_type', 'channel']
)

# Risk check failures
portfolio_risk_check_failures_total = Counter(
    'portfolio_risk_check_failures_total',
    'Total risk check failures',
    ['check_type']
)

# ============================================================================
# Pipeline Metrics
# ============================================================================

# Pipeline errors by type
portfolio_pipeline_errors_total = Counter(
    'portfolio_pipeline_errors_total',
    'Total pipeline processing errors',
    ['pipeline_type', 'error_type']
)

# Pipeline processing duration
portfolio_pipeline_duration_seconds = Histogram(
    'portfolio_pipeline_duration_seconds',
    'Pipeline execution duration',
    ['pipeline_type'],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0, 1800.0, 3600.0)
)

# Pipeline runs total
portfolio_pipeline_runs_total = Counter(
    'portfolio_pipeline_runs_total',
    'Total pipeline executions',
    ['pipeline_type', 'status']
)

# Pipeline queue depths (manually tracked)
portfolio_queue_depth = Gauge(
    'portfolio_queue_depth',
    'Current depth of critical queues',
    ['queue_name']
)

# ============================================================================
# Allocation & Rebalancing Metrics
# ============================================================================

# Portfolio allocations performed
portfolio_allocations_total = Counter(
    'portfolio_allocations_total',
    'Total portfolio allocations',
    ['objective', 'status']
)

# Allocation processing time
portfolio_allocation_duration_seconds = Histogram(
    'portfolio_allocation_duration_seconds',
    'Portfolio allocation duration',
    ['objective'],
    buckets=(1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
)

# Regime changes detected
portfolio_regime_changes_total = Counter(
    'portfolio_regime_changes_total',
    'Total regime changes detected',
    ['from_regime', 'to_regime']
)

# Rebalancing operations
portfolio_rebalances_total = Counter(
    'portfolio_rebalances_total',
    'Total portfolio rebalancing operations',
    ['trigger', 'status']
)

# ============================================================================
# Alpha Signal Metrics
# ============================================================================

# Alpha signals generated
portfolio_alpha_signals_total = Counter(
    'portfolio_alpha_signals_total',
    'Total alpha signals generated',
    ['alpha_type', 'direction']
)

# Alpha signal strength distribution
portfolio_alpha_signal_strength = Histogram(
    'portfolio_alpha_signal_strength',
    'Distribution of alpha signal strengths',
    ['alpha_type'],
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
)

# ============================================================================
# Market Data Metrics
# ============================================================================

# Market data fetch latency
portfolio_market_data_latency_seconds = Histogram(
    'portfolio_market_data_latency_seconds',
    'Market data fetch latency',
    ['source', 'data_type'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)
)

# Market data fetch errors
portfolio_market_data_errors_total = Counter(
    'portfolio_market_data_errors_total',
    'Total market data fetch errors',
    ['source', 'error_type']
)

# ============================================================================
# System Health Metrics
# ============================================================================

# Worker info (supplementary to celery-exporter)
portfolio_worker_info = Info(
    'portfolio_worker',
    'Portfolio server worker information'
)

# Database connection pool status
portfolio_db_connections_active = Gauge(
    'portfolio_db_connections_active',
    'Active database connections',
    ['database']
)

# External API health
portfolio_external_api_health = Gauge(
    'portfolio_external_api_health',
    'External API health status (1=healthy, 0=unhealthy)',
    ['api_name']
)

# ============================================================================
# Tracking State for Duration Calculations
# ============================================================================

_trade_start_times: dict[str, float] = {}
_signal_start_times: dict[str, tuple[float, str, str]] = {}
_pipeline_start_times: dict[str, tuple[float, str]] = {}
_allocation_start_times: dict[str, tuple[float, str]] = {}


# ============================================================================
# Helper Functions for Recording Metrics
# ============================================================================

def record_trade_start(trade_id: str, queue: str = "trading") -> None:
    """Record the start of a trade execution for latency tracking."""
    if not BUSINESS_METRICS_ENABLED:
        return
    _trade_start_times[trade_id] = time.time()
    portfolio_active_trades.labels(queue=queue).inc()


def record_trade_completion(
    trade_id: str,
    strategy: str,
    status: str,
    symbol: str = "unknown",
    queue: str = "trading"
) -> None:
    """Record trade completion and calculate latency."""
    if not BUSINESS_METRICS_ENABLED:
        return
    
    portfolio_trade_executions_total.labels(
        strategy=strategy,
        status=status,
        queue=queue,
        symbol=symbol
    ).inc()
    
    portfolio_active_trades.labels(queue=queue).dec()
    
    start_time = _trade_start_times.pop(trade_id, None)
    if start_time:
        latency = time.time() - start_time
        portfolio_trade_execution_latency_seconds.labels(
            strategy=strategy,
            queue=queue
        ).observe(latency)


def record_trade_error(
    error_type: str,
    strategy: str = "unknown",
    symbol: str = "unknown"
) -> None:
    """Record a trade execution error."""
    if not BUSINESS_METRICS_ENABLED:
        return
    portfolio_trade_errors_total.labels(
        error_type=error_type,
        strategy=strategy,
        symbol=symbol
    ).inc()


def record_signal_start(signal_id: str, signal_type: str, source: str) -> None:
    """Record the start of signal processing."""
    if not BUSINESS_METRICS_ENABLED:
        return
    _signal_start_times[signal_id] = (time.time(), signal_type, source)


def record_signal_completion(signal_id: str) -> None:
    """Record signal processing completion."""
    if not BUSINESS_METRICS_ENABLED:
        return
    
    start_info = _signal_start_times.pop(signal_id, None)
    if start_info:
        start_time, signal_type, source = start_info
        duration = time.time() - start_time
        portfolio_signal_processing_seconds.labels(
            signal_type=signal_type,
            source=source
        ).observe(duration)


def record_pipeline_start(pipeline_id: str, pipeline_type: str) -> None:
    """Record the start of a pipeline execution."""
    if not BUSINESS_METRICS_ENABLED:
        return
    _pipeline_start_times[pipeline_id] = (time.time(), pipeline_type)


def record_pipeline_completion(pipeline_id: str, status: str) -> None:
    """Record pipeline completion."""
    if not BUSINESS_METRICS_ENABLED:
        return
    
    start_info = _pipeline_start_times.pop(pipeline_id, None)
    if start_info:
        start_time, pipeline_type = start_info
        duration = time.time() - start_time
        portfolio_pipeline_duration_seconds.labels(
            pipeline_type=pipeline_type
        ).observe(duration)
        portfolio_pipeline_runs_total.labels(
            pipeline_type=pipeline_type,
            status=status
        ).inc()


def record_pipeline_error(pipeline_type: str, error_type: str) -> None:
    """Record a pipeline error."""
    if not BUSINESS_METRICS_ENABLED:
        return
    portfolio_pipeline_errors_total.labels(
        pipeline_type=pipeline_type,
        error_type=error_type
    ).inc()


def record_risk_alert(
    alert_type: str,
    channel: str,
    processing_time: Optional[float] = None
) -> None:
    """Record a risk alert being sent."""
    if not BUSINESS_METRICS_ENABLED:
        return
    
    portfolio_risk_alerts_sent_total.labels(
        alert_type=alert_type,
        channel=channel
    ).inc()
    
    if processing_time is not None:
        portfolio_risk_alert_processing_seconds.labels(
            alert_type=alert_type
        ).observe(processing_time)


def set_risk_alerts_pending(alert_type: str, severity: str, count: int) -> None:
    """Set the current number of pending risk alerts."""
    if not BUSINESS_METRICS_ENABLED:
        return
    portfolio_risk_alerts_pending.labels(
        alert_type=alert_type,
        severity=severity
    ).set(count)


def record_allocation(
    objective: str,
    status: str,
    duration: Optional[float] = None
) -> None:
    """Record a portfolio allocation."""
    if not BUSINESS_METRICS_ENABLED:
        return
    
    portfolio_allocations_total.labels(
        objective=objective,
        status=status
    ).inc()
    
    if duration is not None:
        portfolio_allocation_duration_seconds.labels(
            objective=objective
        ).observe(duration)


def record_regime_change(from_regime: str, to_regime: str) -> None:
    """Record a regime change detection."""
    if not BUSINESS_METRICS_ENABLED:
        return
    portfolio_regime_changes_total.labels(
        from_regime=from_regime,
        to_regime=to_regime
    ).inc()


def record_rebalance(trigger: str, status: str) -> None:
    """Record a portfolio rebalancing operation."""
    if not BUSINESS_METRICS_ENABLED:
        return
    portfolio_rebalances_total.labels(
        trigger=trigger,
        status=status
    ).inc()


def record_alpha_signal(alpha_type: str, direction: str, strength: float) -> None:
    """Record an alpha signal generation."""
    if not BUSINESS_METRICS_ENABLED:
        return
    
    portfolio_alpha_signals_total.labels(
        alpha_type=alpha_type,
        direction=direction
    ).inc()
    
    portfolio_alpha_signal_strength.labels(
        alpha_type=alpha_type
    ).observe(abs(strength))


def record_market_data_fetch(
    source: str,
    data_type: str,
    latency: float,
    success: bool = True,
    error_type: Optional[str] = None
) -> None:
    """Record market data fetch metrics."""
    if not BUSINESS_METRICS_ENABLED:
        return
    
    if success:
        portfolio_market_data_latency_seconds.labels(
            source=source,
            data_type=data_type
        ).observe(latency)
    elif error_type:
        portfolio_market_data_errors_total.labels(
            source=source,
            error_type=error_type
        ).inc()


def set_queue_depth(queue_name: str, depth: int) -> None:
    """Set the current depth of a queue."""
    if not BUSINESS_METRICS_ENABLED:
        return
    portfolio_queue_depth.labels(queue_name=queue_name).set(depth)


# ============================================================================
# Decorator for Monitored Tasks
# ============================================================================

def monitored_trade_task(
    strategy: str = "unknown",
    queue: str = "trading"
) -> Callable:
    """
    Decorator to automatically track trade task metrics.
    
    Usage:
        @monitored_trade_task(strategy="nse_filings", queue="trading")
        def execute_trade(symbol: str, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not BUSINESS_METRICS_ENABLED:
                return func(*args, **kwargs)
            
            # Generate a unique trade ID
            trade_id = f"{func.__name__}_{time.time()}"
            symbol = kwargs.get("symbol", args[0] if args else "unknown")
            
            record_trade_start(trade_id, queue)
            
            try:
                result = func(*args, **kwargs)
                record_trade_completion(
                    trade_id,
                    strategy=strategy,
                    status="success",
                    symbol=str(symbol),
                    queue=queue
                )
                return result
            except Exception as e:
                record_trade_completion(
                    trade_id,
                    strategy=strategy,
                    status="failure",
                    symbol=str(symbol),
                    queue=queue
                )
                record_trade_error(
                    error_type=type(e).__name__,
                    strategy=strategy,
                    symbol=str(symbol)
                )
                raise
        
        return wrapper
    return decorator


def monitored_pipeline_task(pipeline_type: str) -> Callable:
    """
    Decorator to automatically track pipeline task metrics.
    
    Usage:
        @monitored_pipeline_task(pipeline_type="nse_filings")
        def run_nse_pipeline():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not BUSINESS_METRICS_ENABLED:
                return func(*args, **kwargs)
            
            pipeline_id = f"{func.__name__}_{time.time()}"
            record_pipeline_start(pipeline_id, pipeline_type)
            
            try:
                result = func(*args, **kwargs)
                record_pipeline_completion(pipeline_id, status="success")
                return result
            except Exception as e:
                record_pipeline_completion(pipeline_id, status="failure")
                record_pipeline_error(
                    pipeline_type=pipeline_type,
                    error_type=type(e).__name__
                )
                raise
        
        return wrapper
    return decorator


def monitored_signal_task(signal_type: str, source: str) -> Callable:
    """
    Decorator to automatically track signal processing metrics.
    
    Usage:
        @monitored_signal_task(signal_type="alpha", source="lstm_model")
        def process_alpha_signal(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not BUSINESS_METRICS_ENABLED:
                return func(*args, **kwargs)
            
            signal_id = f"{func.__name__}_{time.time()}"
            record_signal_start(signal_id, signal_type, source)
            
            try:
                result = func(*args, **kwargs)
                record_signal_completion(signal_id)
                return result
            except Exception:
                record_signal_completion(signal_id)
                raise
        
        return wrapper
    return decorator


# ============================================================================
# Initialization
# ============================================================================

def init_business_metrics(worker_name: str, worker_pool: str) -> None:
    """Initialize business metrics with worker information."""
    if not BUSINESS_METRICS_ENABLED:
        logger.info("Business metrics disabled via BUSINESS_METRICS_ENABLED=false")
        return
    
    portfolio_worker_info.info({
        'worker_name': worker_name,
        'worker_pool': worker_pool,
        'pid': str(os.getpid())
    })
    
    logger.info(
        "📊 Business metrics initialized for worker %s (pool: %s)",
        worker_name,
        worker_pool
    )


__all__ = [
    # Metric recording functions
    'record_trade_start',
    'record_trade_completion',
    'record_trade_error',
    'record_signal_start',
    'record_signal_completion',
    'record_pipeline_start',
    'record_pipeline_completion',
    'record_pipeline_error',
    'record_risk_alert',
    'set_risk_alerts_pending',
    'record_allocation',
    'record_regime_change',
    'record_rebalance',
    'record_alpha_signal',
    'record_market_data_fetch',
    'set_queue_depth',
    # Decorators
    'monitored_trade_task',
    'monitored_pipeline_task',
    'monitored_signal_task',
    # Initialization
    'init_business_metrics',
    # Raw metrics for advanced usage
    'portfolio_trade_executions_total',
    'portfolio_trade_execution_latency_seconds',
    'portfolio_risk_alerts_pending',
    'portfolio_pipeline_errors_total',
    'portfolio_queue_depth',
    'BUSINESS_METRICS_ENABLED',
]
