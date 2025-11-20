"""
Database Client - Professional Prisma Connection Management
============================================================

This module provides a robust, thread-safe database client for the portfolio server.
It handles connection lifecycle, event loop management, and ensures proper cleanup.

Key Features:
- Singleton pattern per event loop to avoid connection conflicts
- Automatic event loop detection and client recreation
- Context manager support for safe connection handling
- Proper error handling and logging
- Compatible with both FastAPI and Celery workers

Usage Patterns:
---------------

1. FastAPI Dependency (Recommended for API endpoints):
    ```python
    from db_client import get_db
    
    @router.get("/endpoint")
    async def endpoint(db: Prisma = Depends(get_db)):
        users = await db.user.find_many()
        return users
    ```

2. Direct Usage (For workers and services):
    ```python
    from db_client import get_db_client, ensure_disconnected
    
    async def my_worker():
        db = await get_db_client()
        try:
            # Use db
            users = await db.user.find_many()
        finally:
            await ensure_disconnected()
    ```

3. Context Manager (Safest for workers):
    ```python
    from db_client import DatabaseClient
    
    async def my_worker():
        async with DatabaseClient() as db:
            users = await db.user.find_many()
        # Automatically cleaned up
    ```

4. Synchronous Workers (Celery):
    ```python
    from db_client import run_with_db
    
    @celery_app.task
    def my_task():
        def task_logic(db):
            # Synchronous logic here
            users = await db.user.find_many()
            return users
        
        return run_with_db(task_logic)
    ```
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict

from prisma import Prisma
from prisma.errors import PrismaError

# Setup logging
logger = logging.getLogger(__name__)

# Thread-safe storage for Prisma clients per event loop
# Note: Using regular Dict instead of WeakValueDictionary because Prisma objects
# don't support weak references
_clients: Dict[int, Prisma] = {}
_client_lock = asyncio.Lock()


class DatabaseClient:
    """
    Database client wrapper with context manager support.
    
    Ensures proper connection lifecycle and cleanup.
    Safe to use in both API endpoints and background workers.
    """
    
    def __init__(self, auto_connect: bool = True):
        """
        Initialize database client.
        
        Args:
            auto_connect: If True, connects automatically when entering context.
        """
        self.auto_connect = auto_connect
        self._client: Optional[Prisma] = None
        self._should_disconnect = False
    
    async def __aenter__(self) -> Prisma:
        """Enter async context - returns connected Prisma client."""
        if self.auto_connect:
            self._client = await get_db_client()
            self._should_disconnect = True
        else:
            self._client = await get_db_client()
        return self._client
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context - disconnects if needed."""
        if self._should_disconnect and self._client:
            try:
                await ensure_disconnected()
            except Exception as e:
                logger.warning(f"Failed to disconnect database client: {e}")
        self._client = None


async def get_db_client() -> Prisma:
    """
    Get or create a Prisma client for the current event loop.
    
    This function ensures that:
    1. Each event loop gets its own Prisma client instance
    2. Clients are reused within the same event loop
    3. Clients are automatically recreated when event loops change
    
    Returns:
        Connected Prisma client instance
        
    Raises:
        PrismaError: If connection fails
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError(
            "get_db_client() must be called from within an async context. "
            "Use asyncio.run() or ensure you're in an async function."
        )
    
    loop_id = id(loop)
    
    async with _client_lock:
        # Check if we have a client for this event loop
        client = _clients.get(loop_id)
        
        if client is not None:
            # Check if client is still connected
            try:
                if client.is_connected():
                    return client
            except Exception:
                pass
            # Client is dead, clean it up
            logger.debug(f"Existing client for loop {loop_id} is disconnected, recreating")
            try:
                await client.disconnect()
            except Exception:
                pass
            _clients.pop(loop_id, None)
        
        # Create new client for this event loop WITHOUT auto_register
        # We'll manage the registry manually per event loop
        logger.debug(f"Creating new Prisma client for event loop {loop_id}")
        
        # Clear any existing registered client to avoid conflicts
        try:
            from prisma import get_client
            try:
                existing = get_client()
                if existing:
                    # Unregister it
                    from prisma._registry import _client_registry
                    _client_registry.clear()
            except Exception:
                pass
        except Exception:
            pass
        
        client = Prisma()
        
        try:
            await client.connect()
            logger.info(f"✅ Database connected for event loop {loop_id}")
            _clients[loop_id] = client
            return client
        except PrismaError as e:
            logger.error(f"❌ Failed to connect to database: {e}")
            raise


async def ensure_disconnected() -> None:
    """
    Disconnect the Prisma client for the current event loop.
    
    Safe to call multiple times. Only disconnects if client exists.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    
    loop_id = id(loop)
    
    async with _client_lock:
        client = _clients.pop(loop_id, None)
        if client:
            try:
                await client.disconnect()
                logger.info(f"🔌 Database disconnected for event loop {loop_id}")
            except Exception as e:
                logger.warning(f"Error disconnecting database client: {e}")


async def health_check() -> bool:
    """
    Check if database is accessible.
    
    Returns:
        True if database is healthy, False otherwise
    """
    try:
        db = await get_db_client()
        await db.query_raw("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


@asynccontextmanager
async def get_db() -> AsyncIterator[Prisma]:
    """
    FastAPI dependency for database access.
    
    Usage:
        ```python
        @router.get("/users")
        async def get_users(db: Prisma = Depends(get_db)):
            return await db.user.find_many()
        ```
    
    Yields:
        Connected Prisma client
    """
    db = await get_db_client()
    try:
        yield db
    finally:
        # Don't disconnect - keep connection alive for reuse
        pass


def run_with_db(async_func):
    """
    Run an async function with database connection in a new event loop.
    
    Useful for Celery workers that need to run async code.
    
    Args:
        async_func: Async function that takes a Prisma client as first argument
        
    Returns:
        Result of async_func
        
    Example:
        ```python
        @celery_app.task
        def my_task():
            async def task_logic(db):
                users = await db.user.find_many()
                return users
            
            return run_with_db(task_logic)
        ```
    """
    async def _run():
        async with DatabaseClient() as db:
            return await async_func(db)
    
    return asyncio.run(_run())


# Legacy compatibility - maintain DBManager interface
class DBManager:
    """
    Legacy DBManager interface for backward compatibility.
    
    This class maintains the old interface while using the new
    robust connection management underneath.
    """
    
    _instance: Optional[DBManager] = None
    
    def __init__(self):
        self._client: Optional[Prisma] = None
        self.logger = logger
    
    @classmethod
    def get_instance(cls) -> DBManager:
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance."""
        if cls._instance and cls._instance._client:
            try:
                # Best effort cleanup
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(ensure_disconnected())
                else:
                    asyncio.run(ensure_disconnected())
            except Exception:
                pass
        cls._instance = None
    
    async def connect(self) -> None:
        """Connect to database."""
        self._client = await get_db_client()
    
    async def disconnect(self) -> None:
        """Disconnect from database."""
        await ensure_disconnected()
        self._client = None
    
    def get_client(self) -> Prisma:
        """Get Prisma client."""
        if self._client is None:
            raise RuntimeError(
                "Database not connected. Call await connect() first."
            )
        return self._client
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._client is not None
    
    async def health_check(self) -> bool:
        """Health check."""
        return await health_check()


# Export commonly used functions
__all__ = [
    "DatabaseClient",
    "get_db_client",
    "get_db",
    "ensure_disconnected",
    "health_check",
    "run_with_db",
    "DBManager",  # Legacy compatibility
]
