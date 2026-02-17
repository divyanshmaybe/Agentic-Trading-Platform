from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import Request

from auth_middleware import protect_route  # type: ignore


def normalize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": user.get("id") or user.get("_id"),
        "organization_id": user.get("organization_id") or user.get("organizationId"),
        "customer_id": user.get("customer_id") or user.get("customerId"),
        "role": user.get("role"),
        "email": user.get("email"),
        "raw": user,
    }


async def get_authenticated_user(request: Request) -> Dict[str, Any]:
    """Resolve the authenticated user via auth middleware, caching on request state."""
    # Allow internal service calls to bypass auth
    internal_service = request.headers.get("X-Internal-Service")
    service_secret = request.headers.get("X-Service-Secret")
    expected_secret = os.getenv("INTERNAL_SERVICE_SECRET", "agentinvest-secret")
    
    if internal_service == "true" and service_secret == expected_secret:
        # Return a dummy user for internal service calls
        return {"id": "internal-service", "role": "service", "email": "internal@service"}
    
    raw_user = getattr(request.state, "user", None)
    if raw_user:
        normalized = normalize_user(raw_user)
        request.state.user = normalized
        return normalized

    raw_user = await protect_route(request)
    normalized = normalize_user(raw_user)
    request.state.user = normalized
    return normalized
