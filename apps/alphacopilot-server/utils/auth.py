"""Authentication utilities for AlphaCopilot server."""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

from fastapi import Request, HTTPException, status

# Add middleware to path
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
MIDDLEWARE_PATH = os.path.join(PROJECT_ROOT, "middleware/py")
if MIDDLEWARE_PATH not in sys.path:
    sys.path.insert(0, MIDDLEWARE_PATH)

from auth_middleware import get_auth_client


def normalize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize user dict to a consistent format."""
    return {
        "id": user.get("id") or user.get("_id"),
        "organization_id": user.get("organization_id") or user.get("organizationId"),
        "customer_id": user.get("customer_id") or user.get("customerId"),
        "role": user.get("role"),
        "email": user.get("email"),
        "raw": user,
    }


async def get_authenticated_user(request: Request) -> Dict[str, Any]:
    """Resolve the authenticated user via auth middleware.
    
    Returns:
        Dict with user info including customer_id
        
    Raises:
        HTTPException: If authentication fails
    """
    # Allow internal service calls to bypass auth
    internal_service = request.headers.get("X-Internal-Service")
    service_secret = request.headers.get("X-Service-Secret")
    expected_secret = os.getenv("INTERNAL_SERVICE_SECRET", "agentinvest-secret")
    
    if internal_service == "true" and service_secret == expected_secret:
        # Return a dummy user for internal service calls
        return {"id": "internal-service", "role": "service", "email": "internal@service"}
    
    # Check if user already resolved
    raw_user = getattr(request.state, "user", None)
    if raw_user:
        normalized = normalize_user(raw_user)
        request.state.user = normalized
        return normalized

    # Get token from Authorization header
    token = None
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    # Get token from cookies
    if not token:
        cookies = request.cookies
        if cookies and "token" in cookies:
            token = cookies["token"]
        elif cookies and "access_token" in cookies:
            token = cookies["access_token"]

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
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_msg,
        )

    raw_user = validation.get("user", {})
    normalized = normalize_user(raw_user)
    request.state.user = normalized
    return normalized
