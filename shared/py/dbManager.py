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
import atexit
from contextlib import asynccontextmanager
from typing import Optional, Any

from prisma import Prisma
from prisma.errors import PrismaError


class DBManager:
    """
    Singleton wrapper around Prisma Client Python.
    
    Provides robust connection management with event loop awareness.
    Automatically handles event loop changes and reconnection.
    
    For Celery workers and long-running processes:
    - Use get_instance() to get the shared singleton
    - Use async with db_manager.session() as client: for task-scoped usage
    - Connection is kept alive and reused across tasks in the same worker
    """

    _instance: Optional["DBManager"] = None
    _lock: asyncio.Lock = None  # Will be created when needed
    _pid: Optional[int] = None  # Track process ID to detect forks
    _active_sessions: int = 0  # Track number of active sessions using the connection

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
        
        # Set connection pool limit to prevent exhaustion
        # IMPORTANT: Reduced from 5 to 3 for production safety
        # Calculation: 3 connections × 4 workers = 12 per process
        # Total system: 4 processes × 12 = ~48 connections (safe for PostgreSQL max 100)
        self.connection_limit = int(os.getenv("PRISMA_CONNECTION_LIMIT", "3"))
        self.pool_timeout = int(os.getenv("PRISMA_POOL_TIMEOUT", "10"))

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

        # Add connection pool parameters to database URL if not present
        if "connection_limit" not in self.database_url:
            separator = "&" if "?" in self.database_url else "?"
            self.database_url = f"{self.database_url}{separator}connection_limit={self.connection_limit}&pool_timeout={self.pool_timeout}"
        
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
        # Detect process fork - reset instance if PID changed
        current_pid = os.getpid()
        
        # If instance exists but PID is different, we forked
        if cls._instance is not None and cls._pid is not None and cls._pid != current_pid:
            logging.getLogger(__name__).info(
                "🔄 Process fork detected (PID %s → %s), resetting DBManager instance",
                cls._pid, current_pid
            )
            cls.reset_instance()
        
        # If instance exists but PID was never set (old code path), set it now
        if cls._instance is not None and cls._pid is None:
            cls._pid = current_pid
        
        if cls._instance is None:
            cls._instance = cls(database_url=database_url, log_queries=log_queries)
            cls._pid = current_pid
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
            cls._pid = None  # Clear PID tracking

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

        # If already connected to the same event loop, verify connection is still healthy
        if self._connected and self._loop is loop:
            # Verify connection is still alive with a quick health check
            try:
                if self.client and self.client.is_connected():
                    # Quick ping to verify connection is responsive
                    await asyncio.wait_for(self.client.query_raw("SELECT 1"), timeout=2.0)
                    self.logger.debug("Already connected to database (same event loop, connection healthy)")
                    return
                else:
                    # Connection appears dead, force reconnection
                    self.logger.warning("⚠️ Connection marked as connected but Prisma client is not connected - forcing reconnect")
                    self._connected = False
            except (asyncio.TimeoutError, Exception) as e:
                # Health check failed - connection is stale, force reconnection
                self.logger.warning("⚠️ Connection health check failed: %s - forcing reconnect", e)
                self._connected = False
                # Fall through to reconnection logic below

        # If already connecting, wait for it to complete
        if self._connecting:
            self.logger.debug("Connection in progress, waiting...")
            while self._connecting:
                await asyncio.sleep(0.1)
            return

        self._connecting = True
        
        try:
            # Always clear Prisma registry first to avoid ClientAlreadyRegisteredError
            try:
                from prisma._registry import get_client as get_registered_client, _registered_client
                # Force clear the registry
                if _registered_client is not None:
                    self.logger.debug("Clearing Prisma registry before creating new client")
                    import prisma._registry
                    prisma._registry._registered_client = None
            except Exception as clear_exc:
                self.logger.debug("Registry clear failed (may be already empty): %s", clear_exc)
            
            # If loop changed or not connected, always create fresh client (faster than reusing)
            if self._loop is not None and self._loop is not loop:
                self.logger.info("Event loop changed, creating fresh Prisma client")
                # CRITICAL: Disconnect old client first to clean up event loop-bound objects
                if self.client is not None:
                    try:
                        # Force disconnect even if not connected (cleanup engine)
                        if self.client.is_connected():
                            await asyncio.wait_for(self.client.disconnect(), timeout=3.0)
                            self.logger.debug("✅ Disconnected old Prisma client")
                        
                        # Force cleanup of Prisma engine to close DB connections
                        if hasattr(self.client, '_engine') and self.client._engine:
                            try:
                                await self.client._engine.stop()
                                self.logger.debug("✅ Stopped Prisma engine")
                            except Exception as engine_exc:
                                self.logger.debug("Engine stop failed: %s", engine_exc)
                                
                    except asyncio.TimeoutError:
                        self.logger.warning("⚠️ Old client disconnect timed out, forcing cleanup")
                        # Force stop engine even on timeout
                        try:
                            if hasattr(self.client, '_engine') and self.client._engine:
                                await self.client._engine.stop()
                        except Exception:
                            pass
                    except Exception as disc_exc:
                        self.logger.debug("Old client disconnect failed: %s", disc_exc)
                    finally:
                        # Always unregister from Prisma registry
                        try:
                            from prisma._registry import unregister
                            unregister(self.client)
                        except Exception:
                            pass
                
                # Create new client for new event loop
                self.client = Prisma(auto_register=True, log_queries=self._client_options.get("log_queries", False))
                self._connected = False
                self._loop = None
            elif self.client is None:
                # First time connection
                self.client = Prisma(auto_register=True, log_queries=self._client_options.get("log_queries", False))

            # Connect to database with timeout to prevent hangs
            try:
                # Ensure client is disconnected before connecting to avoid AlreadyConnectedError
                if self.client.is_connected():
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass  # Best effort disconnect
                
                await asyncio.wait_for(self.client.connect(), timeout=10.0)
            except asyncio.TimeoutError:
                self.logger.error("❌ Prisma connection timed out after 10 seconds")
                self._connecting = False
                raise PrismaError("Database connection timeout")
            
            self._connected = True
            self._loop = loop
            self.logger.info("✅ Connected to database via Prisma (loop_id=%s)", id(loop))
            
        except Exception as exc:
            # Log the error
            if isinstance(exc, PrismaError):
                self.logger.error("❌ Failed to connect to database via Prisma", exc_info=exc)
            else:
                self.logger.error("❌ Unexpected error during Prisma connection: %s", exc, exc_info=True)
            
            self._connected = False
            self._loop = None
            raise
        finally:
            self._connecting = False

    async def disconnect(self, force: bool = False, timeout: float = 5.0) -> None:
        """
        Close the Prisma connection if it is active.
        
        Args:
            force: If True, disconnect even if there are active sessions.
                   If False (default), only disconnect if no active sessions.
            timeout: Maximum time to wait for disconnect operations (default 5s).
        
        Safe to call multiple times. Cleans up connection state.
        Handles SoftTimeLimitExceeded gracefully in Celery environments.
        """
        # Don't disconnect if there are active sessions (unless forced)
        if not force and DBManager._active_sessions > 0:
            self.logger.debug(
                "Skipping disconnect, %d active sessions remaining",
                DBManager._active_sessions
            )
            return
            
        if not self._connected and self.client is None:
            self.logger.debug("Already disconnected")
            return

        try:
            if self.client:
                # Disconnect client with timeout to prevent blocking on soft time limit
                if self.client.is_connected():
                    try:
                        await asyncio.wait_for(self.client.disconnect(), timeout=timeout)
                        self.logger.info("🔌 Disconnected Prisma client")
                    except asyncio.TimeoutError:
                        self.logger.warning("⚠️ Prisma disconnect timed out after %.1fs, forcing cleanup", timeout)
                    except Exception as disc_exc:
                        # Handle Celery SoftTimeLimitExceeded gracefully - silently
                        exc_name = type(disc_exc).__name__
                        if exc_name != "SoftTimeLimitExceeded":
                            self.logger.debug("Prisma disconnect error: %s", disc_exc)
                else:
                    # Client exists but is not connected - skip disconnect, just cleanup
                    self.logger.debug("Prisma client already disconnected, skipping disconnect call")
                
                # Force stop engine to ensure DB connections are closed (with timeout)
                if hasattr(self.client, '_engine') and self.client._engine:
                    try:
                        await asyncio.wait_for(self.client._engine.stop(), timeout=2.0)
                        self.logger.debug("🔌 Stopped Prisma engine")
                    except asyncio.TimeoutError:
                        self.logger.debug("Engine stop timed out, continuing cleanup")
                    except Exception as engine_exc:
                        exc_name = type(engine_exc).__name__
                        if exc_name != "SoftTimeLimitExceeded":
                            self.logger.debug("Engine stop failed: %s", engine_exc)
                
                # Unregister from global registry
                try:
                    from prisma._registry import unregister
                    unregister(self.client)
                except Exception:
                    pass
                    
        except Exception as e:
            # Handle any exception including SoftTimeLimitExceeded - silently
            exc_name = type(e).__name__
            if exc_name != "SoftTimeLimitExceeded":
                self.logger.debug("Error during disconnect cleanup: %s", e)
        finally:
            self._connected = False
            self._loop = None
            self.client = None

    @asynccontextmanager
    async def session(self):
        """
        Context manager for database sessions.
        
        Use this for Celery tasks to properly manage connection lifecycle.
        The connection is kept alive and reused across tasks in the same worker.
        
        Usage:
            async with db_manager.session() as client:
                users = await client.user.find_many()
        
        Yields:
            Connected Prisma client instance.
        """
        # Ensure we're connected
        await self.connect()
        
        # Track active sessions
        DBManager._active_sessions += 1
        self.logger.debug("Session started, active sessions: %d", DBManager._active_sessions)
        
        try:
            yield self.client
        finally:
            DBManager._active_sessions -= 1
            self.logger.debug("Session ended, active sessions: %d", DBManager._active_sessions)
            # Don't disconnect here - keep connection alive for reuse
            # Connection will be cleaned up when worker is recycled

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
