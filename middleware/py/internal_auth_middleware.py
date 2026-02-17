"""
Internal Authentication Middleware for FastAPI applications
Provides authentication for internal service-to-service communication
"""

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import os
import logging
import secrets

logger = logging.getLogger(__name__)


async def internal_auth(request: Request) -> None:
    """Dependency function for internal service authentication"""
    service_secret = request.headers.get("x-service-secret")
    is_internal = request.headers.get("x-internal-service")
    expected_secret = os.getenv("INTERNAL_SERVICE_SECRET")

    if not is_internal or not service_secret or not expected_secret or not secrets.compare_digest(
        service_secret, expected_secret
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Internal access only",
        )


class InternalAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for protecting routes with internal service authentication"""

    async def dispatch(self, request: Request, call_next):
        """Process request and validate internal service authentication"""
        # Check if route requires internal auth
        if hasattr(request.state, "require_internal_auth") and request.state.require_internal_auth:
            service_secret = request.headers.get("x-service-secret")
            is_internal = request.headers.get("x-internal-service")
            expected_secret = os.getenv("INTERNAL_SERVICE_SECRET")

            if not is_internal or not service_secret or not expected_secret or not secrets.compare_digest(
                service_secret, expected_secret
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Internal access only",
                )

        response = await call_next(request)
        return response

