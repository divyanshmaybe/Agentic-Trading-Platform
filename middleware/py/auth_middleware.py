"""
Authentication Middleware for FastAPI applications
Provides route protection and user authentication
"""

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import sys
import os

# Add shared directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../shared/py"))

from authService.client import AuthServiceClient

logger = logging.getLogger(__name__)

# Singleton instance
_auth_client_instance = None


def get_auth_client() -> AuthServiceClient:
    """Get singleton auth client instance"""
    global _auth_client_instance
    if _auth_client_instance is None:
        _auth_client_instance = AuthServiceClient()
    return _auth_client_instance


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware for protecting routes with authentication"""

    async def dispatch(self, request: Request, call_next):
        """Process request and validate authentication"""
        # Allow CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Check if route requires authentication
        if not hasattr(request.state, "require_auth") or not request.state.require_auth:
            return await call_next(request)

        token = None

        # Get token from Authorization header
        authorization = request.headers.get("authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ")[1]

        # Get token from cookies
        if not token:
            cookies = request.cookies
            if cookies and "token" in cookies:
                token = cookies["token"]

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authorized, no token",
            )

        # Validate token
        client = get_auth_client()
        validation = await client.validate_token(token)

        if not validation.get("valid"):
            error_msg = validation.get("error") or "Invalid token"
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=error_msg
            )

        user = validation.get("user")
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )

        # Attach user to request state
        request.state.user = user

        response = await call_next(request)
        return response


async def protect_route(request: Request) -> dict:
    """Dependency function for protecting routes"""
    # Allow CORS preflight requests
    if request.method == "OPTIONS":
        return {}

    token = None

    # Get token from Authorization header
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    # Get token from cookies
    if not token:
        cookies = request.cookies
        if cookies and "token" in cookies:
            token = cookies["token"]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorized, no token",
        )

    # Validate token
    client = get_auth_client()
    validation = await client.validate_token(token)

    if not validation.get("valid"):
        error_msg = validation.get("error") or "Invalid token"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=error_msg
        )

    user = validation.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    # Return user for dependency injection
    return user

