"""
Internal API Client for FastAPI applications
Provides communication with other internal services
"""

import httpx
import logging
from typing import Optional, Dict, Any
import os
import json


class InternalApiClient:
    """Client for communicating with internal services"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.timeout = httpx.Timeout(30.0)  # Longer timeout for internal calls
        self.internal_secret = os.getenv("INTERNAL_SERVICE_SECRET", "agentinvest-secret")

        # Service URLs
        self.services = {
            "auth": os.getenv("AUTH_SERVER_URL", "http://localhost:4000"),
            "portfolio": os.getenv("PORTFOLIO_SERVICE_URL", "http://localhost:8000"),
        }

    async def call_service(
        self,
        service_name: str,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make a call to an internal service"""
        if service_name not in self.services:
            self.logger.error(f"Unknown service: {service_name}")
            return None

        base_url = self.services[service_name]
        url = f"{base_url}{endpoint}"

        default_headers = {
            "Content-Type": "application/json",
            "X-Internal-Service": "true",
            "X-Service-Secret": self.internal_secret,
        }
        if headers:
            default_headers.update(headers)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method.upper() == "GET":
                    response = await client.get(url, headers=default_headers)
                elif method.upper() == "POST":
                    response = await client.post(
                        url, json=data, headers=default_headers
                    )
                elif method.upper() == "PUT":
                    response = await client.put(url, json=data, headers=default_headers)
                elif method.upper() == "DELETE":
                    response = await client.delete(url, headers=default_headers)
                else:
                    self.logger.error(f"Unsupported HTTP method: {method}")
                    return None

                if response.status_code >= 200 and response.status_code < 300:
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        return {"message": response.text}
                else:
                    self.logger.error(
                        f"Service call failed: {response.status_code} - {response.text}"
                    )
                    return None

        except httpx.TimeoutException:
            self.logger.error(f"Timeout calling {service_name}{endpoint}")
            return None
        except Exception as e:
            self.logger.error(f"Error calling {service_name}{endpoint}: {e}")
            return None

    # Auth service methods
    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user from auth service"""
        return await self.call_service("auth", "GET", f"/api/users/{user_id}")

    async def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Validate API key with auth service"""
        return await self.call_service(
            "auth", "POST", "/api/auth/validate-key", {"api_key": api_key}
        )

    async def health_check_service(self, service_name: str) -> bool:
        """Check if a service is healthy"""
        try:
            result = await self.call_service(service_name, "GET", "/health")
            return result is not None and result.get("status") == "healthy"
        except Exception:
            return False

    async def get_service_health(self) -> Dict[str, bool]:
        """Get health status of all services"""
        health = {}
        for service_name in self.services.keys():
            health[service_name] = await self.health_check_service(service_name)
        return health

    async def get(self, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[httpx.Response]:
        """Make a GET request (similar to axios.get for compatibility)"""
        try:
            default_headers = {
                "Content-Type": "application/json",
                "X-Internal-Service": "true",
                "X-Service-Secret": self.internal_secret,
            }
            if headers:
                default_headers.update(headers)

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=default_headers)
                return response
        except Exception as e:
            self.logger.error(f"Error in GET request to {url}: {e}")
            return None
