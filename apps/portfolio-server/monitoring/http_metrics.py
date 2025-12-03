"""
Prometheus HTTP Metrics Middleware for FastAPI

Exposes HTTP request metrics for the Portfolio Server API.
"""

import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse


# HTTP Request Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total number of HTTP requests',
    ['method', 'endpoint', 'status_code']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

http_requests_in_progress = Gauge(
    'http_requests_in_progress',
    'Number of HTTP requests currently being processed',
    ['method', 'endpoint']
)

http_request_size_bytes = Histogram(
    'http_request_size_bytes',
    'HTTP request size in bytes',
    ['method', 'endpoint'],
    buckets=(100, 1000, 10000, 100000, 1000000, 10000000)
)

http_response_size_bytes = Histogram(
    'http_response_size_bytes',
    'HTTP response size in bytes',
    ['method', 'endpoint'],
    buckets=(100, 1000, 10000, 100000, 1000000, 10000000)
)


def normalize_path(path: str) -> str:
    """
    Normalize path to reduce cardinality.
    Replace dynamic path segments (UUIDs, IDs) with placeholders.
    """
    import re
    
    # Replace UUIDs
    path = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '{uuid}',
        path,
        flags=re.IGNORECASE
    )
    
    # Replace numeric IDs (standalone numbers in path)
    path = re.sub(r'/\d+(?=/|$)', '/{id}', path)
    
    # Replace timestamps
    path = re.sub(r'/\d{10,13}(?=/|$)', '/{timestamp}', path)
    
    return path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect HTTP metrics for Prometheus.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        method = request.method
        path = normalize_path(request.url.path)
        
        # Skip metrics endpoint to avoid recursion
        if path == '/metrics':
            return await call_next(request)
        
        # Track request in progress
        http_requests_in_progress.labels(method=method, endpoint=path).inc()
        
        # Track request size
        content_length = request.headers.get('content-length')
        if content_length:
            http_request_size_bytes.labels(method=method, endpoint=path).observe(int(content_length))
        
        # Time the request
        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration = time.time() - start_time
            
            # Record metrics
            http_requests_total.labels(
                method=method,
                endpoint=path,
                status_code=response.status_code
            ).inc()
            
            http_request_duration_seconds.labels(
                method=method,
                endpoint=path
            ).observe(duration)
            
            # Track response size
            response_size = response.headers.get('content-length')
            if response_size:
                http_response_size_bytes.labels(method=method, endpoint=path).observe(int(response_size))
            
            return response
            
        except Exception as e:
            # Record failed request
            duration = time.time() - start_time
            http_requests_total.labels(
                method=method,
                endpoint=path,
                status_code=500
            ).inc()
            http_request_duration_seconds.labels(
                method=method,
                endpoint=path
            ).observe(duration)
            raise
            
        finally:
            # Decrease in-progress counter
            http_requests_in_progress.labels(method=method, endpoint=path).dec()


def metrics_endpoint():
    """
    Endpoint to expose Prometheus metrics.
    Returns metrics in Prometheus text format.
    """
    from fastapi.responses import Response
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
