"""Prisma-powered database manager for FastAPI services."""

from __future__ import annotations

import asyncio
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

        # Default to localhost PostgreSQL if not set (for development)
        if not self.database_url:
            db_host = os.getenv("DB_HOST", "localhost")
            db_port = os.getenv("DB_PORT", "5432")
            db_user = os.getenv("DB_USER", "postgres")
            db_password = os.getenv("DB_PASSWORD", "postgres")
            db_name = os.getenv("DB_NAME", "portfolio_db")
            self.database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            self.logger.info(
                "DATABASE_URL not set, using default localhost config: postgresql://%s:***@%s:%s/%s",
                db_user, db_host, db_port, db_name
            )

        # Ensure Prisma can discover the database connection string
        os.environ.setdefault("DATABASE_URL", self.database_url)

        self._client_options = {"auto_register": True, "log_queries": log_queries}
        self.client: Prisma = Prisma(**self._client_options)
        self._connected: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def get_instance(cls, database_url: Optional[str] = None, log_queries: bool = False) -> "DBManager":
        """Return (or create) the shared DB manager instance."""

        if cls._instance is None:
            cls._instance = cls(database_url=database_url, log_queries=log_queries)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Useful for event loop changes in async contexts."""
        if cls._instance is not None:
            # Disconnect and unregister the Prisma client
            try:
                # Try to disconnect synchronously if possible
                if cls._instance.client and cls._instance._connected:
                    try:
                        # Force disconnect by closing internal httpx client
                        if hasattr(cls._instance.client, '_engine') and cls._instance.client._engine:
                            if hasattr(cls._instance.client._engine, '_client'):
                                try:
                                    import asyncio
                                    loop = asyncio.get_event_loop()
                                    if loop.is_running():
                                        # Can't await in running loop, force close
                                        pass
                                    else:
                                        asyncio.run(cls._instance.client.disconnect())
                                except:
                                    pass
                    except Exception:
                        pass  # Best effort cleanup
                
                # Unregister from Prisma's global registry
                from prisma._registry import unregister
                if cls._instance.client:
                    unregister(cls._instance.client)
            except Exception:
                pass  # Best effort cleanup
            
            cls._instance = None

    async def connect(self) -> None:
        """Establish a connection to the database via Prisma."""

        loop = asyncio.get_running_loop()

        if self._connected:
            if self._loop is loop:
                return

            # Recreate the Prisma client for the new event loop
            try:
                await self.client.disconnect()
            except Exception:  # pragma: no cover - best effort cleanup
                self.logger.debug("Failed to disconnect existing Prisma client during loop switch", exc_info=True)

            self.client = Prisma(**self._client_options)
            self._connected = False
            self._loop = None

        try:
            await self.client.connect()
            self._connected = True
            self._loop = loop
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
            self._loop = None

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
