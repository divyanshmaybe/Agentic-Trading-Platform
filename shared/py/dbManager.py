"""Prisma-powered database manager for FastAPI services."""

from __future__ import annotations

import logging
import os
from typing import Optional, Any

from prisma import Prisma
from prisma.errors import PrismaError


class DBManager:
    """Singleton wrapper around Prisma Client Python."""

    _instance: Optional["DBManager"] = None

    def __init__(self, database_url: Optional[str] = None, log_queries: bool = False):
        if DBManager._instance is not None:
            raise RuntimeError("Use DBManager.get_instance() to access the database manager")

        self.logger = logging.getLogger(__name__)
        self.database_url = database_url or os.getenv("DATABASE_URL") or os.getenv("DB_URL")

        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is not set")

        # Ensure Prisma can discover the database connection string
        os.environ.setdefault("DATABASE_URL", self.database_url)

        self.client: Prisma = Prisma(auto_register=True, log_queries=log_queries)
        self._connected: bool = False

    @classmethod
    def get_instance(cls, database_url: Optional[str] = None, log_queries: bool = False) -> "DBManager":
        """Return (or create) the shared DB manager instance."""

        if cls._instance is None:
            cls._instance = cls(database_url=database_url, log_queries=log_queries)
        return cls._instance

    async def connect(self) -> None:
        """Establish a connection to the database via Prisma."""

        if self._connected:
            return

        try:
            await self.client.connect()
            self._connected = True
            self.logger.info("✅ Connected to database via Prisma")
        except PrismaError as exc:
            self.logger.error("❌ Failed to connect to database via Prisma", exc_info=exc)
            raise

    async def disconnect(self) -> None:
        """Close the Prisma connection if it is active."""

        if not self._connected:
            return

        try:
            await self.client.disconnect()
            self.logger.info("🔌 Disconnected Prisma client")
        finally:
            self._connected = False

    def get_client(self) -> Prisma:
        """Return the underlying Prisma client (requires active connection)."""

        if not self._connected:
            raise RuntimeError("Database not connected. Call connect() before accessing the client.")
        return self.client

    def is_connected(self) -> bool:
        """Return True if the Prisma client is connected."""

        return self._connected

    async def health_check(self) -> bool:
        """Perform a basic health check against the database."""

        if not self._connected:
            return False

        try:
            # Lightweight query to verify connectivity
            await self.client.query_raw("SELECT 1")
            return True
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Database health check failed", exc_info=exc)
            return False

    async def execute_raw(self, query: str, parameters: Optional[Any] = None) -> Any:
        """Execute a raw query using the Prisma client."""

        if not self._connected:
            raise RuntimeError("Database not connected. Call connect() before executing queries.")

        if parameters is None:
            return await self.client.execute_raw(query)
        return await self.client.execute_raw(query, parameters)


__all__ = ["DBManager"]
