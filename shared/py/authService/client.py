"""Auth Service Client for Python services."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
import jwt
from dotenv import load_dotenv


class AuthServiceClient:
    """Client for communicating with the auth service."""

    def __init__(self) -> None:
        # Load environment from shared locations if not already loaded
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        repo_root = os.path.abspath(os.path.join(base_dir, ".."))
        load_dotenv(os.path.join(repo_root, ".env"), override=False)
        load_dotenv(os.path.join(base_dir, ".env"), override=False)

        self.logger = logging.getLogger(__name__)
        self.base_url = os.getenv("AUTH_SERVER_URL", "http://localhost:4000")
        self.jwt_secret = (
            os.getenv("JWT_SECRET_ACCESS")
            or os.getenv("JWT_SECRET")
            or "default-secret"
        )
        self.timeout = httpx.Timeout(10.0)
        self.internal_secret = os.getenv("INTERNAL_SERVICE_SECRET")
        if not self.internal_secret:
            raise RuntimeError(
                "INTERNAL_SERVICE_SECRET is not set; cannot call internal auth endpoints"
            )

    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            exp = payload.get("exp")
            if exp and datetime.utcnow().timestamp() > exp:
                return None
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    async def validate_token(self, token: str) -> Dict[str, Any]:
        if not token or token.strip() == "":
            return {"valid": False, "error": "Token is empty"}

        payload = await self.verify_token(token)
        if payload:
            user_payload = {
                "id": payload.get("id") or payload.get("_id"),
                "email": payload.get("email"),
                "role": payload.get("role"),
                "organization_id": payload.get("organization_id")
                or payload.get("organizationId"),
                "customer_id": payload.get("customer_id")
                or payload.get("customerId"),
            }
            return {"valid": True, "user": user_payload, "source": "local"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/internal/validate-token",
                    json={"token": token},
                    headers={
                        "X-Internal-Service": "true",
                        "X-Service-Secret": self.internal_secret,
                        "Content-Type": "application/json",
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    if data and data.get("user"):
                        return {"valid": True, "user": data["user"], "source": "remote"}
                    return {"valid": False, "error": "Invalid token response"}

                error_detail = None
                try:
                    error_detail = response.json().get("error") or response.json().get("message")
                except Exception:  # pragma: no cover - defensive
                    error_detail = response.text

                if response.status_code == 401:
                    return {"valid": False, "error": error_detail or "Invalid token"}

                if response.status_code == 403:
                    return {"valid": False, "error": error_detail or "Internal access denied"}

                return {
                    "valid": False,
                    "error": error_detail or f"Token validation failed ({response.status_code})",
                }

        except httpx.ConnectError:
            self.logger.warning("⚠️ Auth service unavailable")
            return {"valid": False, "error": "Auth service unavailable"}
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("❌ Token validation error: %s", exc)
            return {"valid": False, "error": "Token validation failed"}

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/users/{user_id}",
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    return response.json()
                self.logger.error(
                    "Failed to get user %s: %s", user_id, response.status_code
                )
                return None
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Error getting user %s: %s", user_id, exc)
            return None

    async def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/auth/validate-key",
                    json={"api_key": api_key},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    return response.json()
                return None
        except Exception as exc:
            self.logger.error("Error validating API key: %s", exc)
            return None

    async def create_api_key(self, user_id: str, name: str) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/users/{user_id}/api-keys",
                    json={"name": name},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 201:
                    data = response.json()
                    return data.get("api_key")
                self.logger.error(
                    "Failed to create API key: %s", response.status_code
                )
                return None
        except Exception as exc:
            self.logger.error("Error creating API key: %s", exc)
            return None

    async def revoke_api_key(self, user_id: str, api_key_id: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.delete(
                    f"{self.base_url}/api/users/{user_id}/api-keys/{api_key_id}"
                )
                return response.status_code == 204
        except Exception as exc:
            self.logger.error("Error revoking API key: %s", exc)
            return False

    async def authenticate_user(
        self, email: str, password: str
    ) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/auth/login",
                    json={"email": email, "password": password},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 200:
                    return response.json()
                return None
        except Exception as exc:
            self.logger.error("Error authenticating user: %s", exc)
            return None

    async def register_user(
        self, email: str, password: str, username: str
    ) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/auth/register",
                    json={"email": email, "password": password, "username": username},
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 201:
                    return response.json()
                return None
        except Exception as exc:
            self.logger.error("Error registering user: %s", exc)
            return None

    def generate_token(
        self, user_data: Dict[str, Any], expires_delta: Optional[timedelta] = None
    ) -> str:
        expire = datetime.utcnow() + (expires_delta or timedelta(hours=24))
        to_encode = user_data.copy()
        to_encode.update({"exp": expire.timestamp()})
        encoded_jwt = jwt.encode(to_encode, self.jwt_secret, algorithm="HS256")
        return encoded_jwt

    def health_check(self) -> bool:
        try:
            import requests

            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:  # pragma: no cover - defensive
            return False
