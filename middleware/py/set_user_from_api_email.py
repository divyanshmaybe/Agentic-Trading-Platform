"""
Set User from API Email Middleware for FastAPI applications
Extracts user information from X-API-Email header
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import sys
import os
import logging

# Add shared directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../shared/py"))

from internalApi.client import InternalApiClient

logger = logging.getLogger(__name__)

# Singleton instance
_internal_api_instance = None


def get_internal_api() -> InternalApiClient:
    """Get singleton internal API client instance"""
    global _internal_api_instance
    if _internal_api_instance is None:
        _internal_api_instance = InternalApiClient()
    return _internal_api_instance


async def set_user_from_api_email(request: Request) -> None:
    """Dependency function to set user from X-API-Email header"""
    email = request.headers.get("x-api-email")
    if email:
        try:
            auth_server_url = os.getenv("AUTH_SERVER_URL", "http://localhost:4000")
            internal_api = get_internal_api()
            
            try:
                # Use internal API to get user by email
                response = await internal_api.get(
                    f"{auth_server_url}/api/internal/user-by-email/{email}"
                )
                
                if response and response.status_code == 200:
                    data = response.json()
                    if data and data.get("user"):
                        request.state.user = data["user"]
            except Exception as err:
                logger.error(f"Error fetching user from internal API: {err}")
        except Exception as err:
            logger.error(f"Error setting req.user from X-API-Email: {err}")


class SetUserFromApiEmailMiddleware(BaseHTTPMiddleware):
    """Middleware to set user from X-API-Email header"""

    async def dispatch(self, request: Request, call_next):
        """Process request and set user from email header"""
        email = request.headers.get("x-api-email")
        if email:
            try:
                auth_server_url = os.getenv("AUTH_SERVER_URL", "http://localhost:4000")
                internal_api = get_internal_api()
                
                try:
                    response = await internal_api.get(
                        f"{auth_server_url}/api/internal/user-by-email/{email}"
                    )
                    
                    if response and response.status_code == 200:
                        data = response.json()
                        if data and data.get("user"):
                            request.state.user = data["user"]
                except Exception as err:
                    logger.error(f"Error fetching user from internal API: {err}")
            except Exception as err:
                logger.error(f"Error setting req.user from X-API-Email: {err}")

        response = await call_next(request)
        return response

