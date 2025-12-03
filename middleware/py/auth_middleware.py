"""
Authentication Middleware for FastAPI applications
Provides route protection and user authentication
"""

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import sys
import os
from typing import Iterable, Set

# Add shared directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../shared/py"))

from authService.client import AuthServiceClient

logger = logging.getLogger(__name__)

# Singleton instance
_auth_client_instance = None

_DEFAULT_PUBLIC_PATHS: Set[str] = {
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}
_DEFAULT_PUBLIC_PREFIXES: Iterable[str] = (
    "/docs",
    "/openapi",
    "/static",
    "/api/pipeline",
)

_extra_paths = {
    path.strip()
    for path in os.getenv("AUTH_PUBLIC_PATHS", "").split(",")
    if path.strip()
}
_extra_prefixes = tuple(
    prefix.strip()
    for prefix in os.getenv("AUTH_PUBLIC_PREFIXES", "").split(",")
    if prefix.strip()
)


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

        path = request.url.path

        require_auth_flag = getattr(request.state, "require_auth", None)

        if require_auth_flag is False or self._is_public_path(path):
            return await call_next(request)

        if getattr(request.state, "user", None):
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

    def _is_public_path(self, path: str) -> bool:
        if path in _DEFAULT_PUBLIC_PATHS or path in _extra_paths:
            return True
        prefixes = tuple(_DEFAULT_PUBLIC_PREFIXES) + _extra_prefixes
        return any(path.startswith(prefix) for prefix in prefixes)


async def require_admin_or_staff(request: Request) -> dict:
    """
    Dependency function for protecting admin/staff-only routes.
    Validates authentication and checks for admin or staff role.
    Returns the authenticated user with organization_id.
    
    Usage:
        @router.get("/admin-endpoint")
        async def admin_endpoint(user: dict = Depends(require_admin_or_staff)):
            org_id = user["organization_id"]
            ...
    """
    user = await protect_route(request)
    
    role = (user.get("role") or "").lower()
    if role not in ("admin", "staff"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Staff access required",
        )
    
    org_id = user.get("organization_id") or user.get("organizationId")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization ID not found in user context",
        )
    
    # Normalize organization_id in user dict
    user["organization_id"] = org_id
    return user


async def protect_route(request: Request) -> dict:
    """Dependency function for protecting routes"""
    # Allow CORS preflight requests
    if request.method == "OPTIONS":
        return {}

    if getattr(request.state, "user", None):
        return request.state.user

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
    request.state.user = user
    return user

