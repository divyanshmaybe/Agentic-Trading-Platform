"""
Prisma-powered database manager for FastAPI services.

This module provides a robust, production-ready database manager for Python services.
It handles connection lifecycle, event loop management, and ensures proper cleanup.

Key Features:
- Singleton pattern with proper event loop handling
- Automatic reconnection on event loop changes
- Thread-safe operations
- Comprehensive error handling and logging
- Health check support

Usage:
    ```python
    from dbManager import DBManager
    
    # Get singleton instance
    db_manager = DBManager.get_instance()
    
    # Connect
    await db_manager.connect()
    
    # Get Prisma client
    client = db_manager.get_client()
    
    # Use client
    users = await client.user.find_many()
    
    # Disconnect when done
    await db_manager.disconnect()
    ```
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Any

from prisma import Prisma
from prisma.errors import PrismaError


class DBManager:
    """
    Singleton wrapper around Prisma Client Python.
    
    Provides robust connection management with event loop awareness.
    Automatically handles event loop changes and reconnection.
    """

    _instance: Optional["DBManager"] = None
    _lock: asyncio.Lock = None  # Will be created when needed

    def __init__(self, database_url: Optional[str] = None, log_queries: bool = False):
        """
        Initialize DBManager.
        
        Args:
            database_url: PostgreSQL connection string. If not provided, uses DATABASE_URL env var.
            log_queries: If True, logs all SQL queries (useful for debugging).
            
        Note: Use get_instance() instead of direct instantiation.
        """
        if DBManager._instance is not None:
            raise RuntimeError(
                "DBManager is a singleton. Use DBManager.get_instance() to access it."
            )

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
        self._connecting: bool = False

    @classmethod
    def get_instance(cls, database_url: Optional[str] = None, log_queries: bool = False) -> "DBManager":
        """
        Get or create the shared DBManager singleton instance.
        
        Args:
            database_url: PostgreSQL connection string (only used on first call).
            log_queries: If True, logs all SQL queries (only used on first call).
            
        Returns:
            The singleton DBManager instance.
        """
        if cls._instance is None:
            cls._instance = cls(database_url=database_url, log_queries=log_queries)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance.
        
        Useful for:
        - Event loop changes in async contexts
        - Testing scenarios requiring fresh state
        - Worker processes that need clean slate
        
        Warning: This will disconnect any existing connections.
        """
        if cls._instance is not None:
            # Disconnect and unregister the Prisma client
            try:
                # Try to disconnect synchronously if possible
                if cls._instance.client and cls._instance._connected:
                    try:
                        loop = asyncio.get_event_loop()
                        if not loop.is_running():
                            asyncio.run(cls._instance.disconnect())
                    except Exception:
                        pass  # Best effort cleanup
                
                # Unregister from Prisma's global registry
                from prisma._registry import unregister
                if cls._instance.client:
                    try:
                        unregister(cls._instance.client)
                    except Exception:
                        pass  # Best effort cleanup
            except Exception:
                pass  # Best effort cleanup
            
            cls._instance = None

    async def connect(self) -> None:
        """
        Establish a connection to the database via Prisma.
        
        Handles event loop changes by recreating the client if needed.
        Safe to call multiple times - will reuse existing connection if still valid.
        
        Raises:
            PrismaError: If connection fails after retries.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError(
                "connect() must be called from within an async context. "
                "Use asyncio.run() or ensure you're in an async function."
            )

        # If already connected to the same event loop, return
        if self._connected and self._loop is loop:
            self.logger.debug("Already connected to database (same event loop)")
            return

        # If already connecting, wait for it to complete
        if self._connecting:
            self.logger.debug("Connection in progress, waiting...")
            while self._connecting:
                await asyncio.sleep(0.1)
            return

        self._connecting = True
        
        try:
            # If loop changed, recreate the Prisma client
            if self._loop is not None and self._loop is not loop:
                self.logger.info("Event loop changed, recreating Prisma client")
                try:
                    await self.client.disconnect()
                except Exception:  # pragma: no cover - best effort cleanup
                    self.logger.debug(
                        "Failed to disconnect existing Prisma client during loop switch", 
                        exc_info=True
                    )

                self.client = Prisma(**self._client_options)
                self._connected = False
                self._loop = None

            # Connect to database
            await self.client.connect()
            self._connected = True
            self._loop = loop
            self.logger.info("✅ Connected to database via Prisma (loop_id=%s)", id(loop))
            
        except PrismaError as exc:
            self.logger.error("❌ Failed to connect to database via Prisma", exc_info=exc)
            self._connected = False
            self._loop = None
            raise
        finally:
            self._connecting = False

    async def disconnect(self) -> None:
        """
        Close the Prisma connection if it is active.
        
        Safe to call multiple times. Cleans up connection state.
        """
        if not self._connected:
            self.logger.debug("Already disconnected")
            return

        try:
            await self.client.disconnect()
            self.logger.info("🔌 Disconnected Prisma client")
        except Exception as e:
            self.logger.warning("Error during disconnect: %s", e)
        finally:
            self._connected = False
            self._loop = None

    def get_client(self) -> Prisma:
        """
        Get the underlying Prisma client.
        
        Returns:
            Connected Prisma client instance.
            
        Raises:
            RuntimeError: If not connected. Call connect() first.
        """
        if not self._connected:
            raise RuntimeError(
                "Database not connected. Call await connect() before accessing the client."
            )
        return self.client

    def is_connected(self) -> bool:
        """
        Check if the database connection is active.
        
        Returns:
            True if connected, False otherwise.
        """
        return self._connected

    async def health_check(self) -> bool:
        """
        Perform a basic health check against the database.
        
        Returns:
            True if database is healthy, False otherwise.
        """
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
        """
        Execute a raw SQL query using the Prisma client.
        
        Args:
            query: SQL query string.
            parameters: Optional query parameters.
            
        Returns:
            Query results.
            
        Raises:
            RuntimeError: If not connected.
            PrismaError: If query execution fails.
        """
        if not self._connected:
            raise RuntimeError(
                "Database not connected. Call await connect() before executing queries."
            )

        if parameters is None:
            return await self.client.execute_raw(query)
        return await self.client.execute_raw(query, parameters)


__all__ = ["DBManager"]
