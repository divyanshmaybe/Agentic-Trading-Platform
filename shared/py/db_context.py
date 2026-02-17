"""
Database connection context manager for proper cleanup in Celery workers.

Ensures Prisma connections are always closed after use, preventing connection pool exhaustion.
Optimized for production with proper connection pooling and timeout handling.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from prisma import Prisma

logger = logging.getLogger(__name__)

# Connection pool settings
DEFAULT_CONNECTION_TIMEOUT = float(os.getenv("PRISMA_CONNECTION_TIMEOUT", "15"))
DEFAULT_DISCONNECT_TIMEOUT = float(os.getenv("PRISMA_DISCONNECT_TIMEOUT", "5"))


@asynccontextmanager
async def get_db_connection(
    database_url: str | None = None,
    timeout: float | None = None
) -> AsyncGenerator[Prisma, None]:
    """
    Context manager for database connections that guarantees cleanup.
    
    PRODUCTION OPTIMIZED:
    - Connection pooling via Prisma (10 connections default)
    - Fast timeout handling (15s connect, 5s disconnect)
    - Proper cleanup on error
    - Force engine stop to prevent connection leaks
    
    Usage:
        async with get_db_connection() as db:
            users = await db.user.find_many()
    
    Args:
        database_url: Optional database URL override
        timeout: Connection timeout in seconds (default: 15s)
        
    Yields:
        Connected Prisma client
        
    Raises:
        TimeoutError: If connection times out
        PrismaError: If connection fails
    """
    if timeout is None:
        timeout = DEFAULT_CONNECTION_TIMEOUT
        
    client = None
    try:
        # Create fresh client with auto_register=False to avoid registry conflicts
        if database_url:
            client = Prisma(datasource={"url": database_url}, auto_register=False)
        else:
            client = Prisma(auto_register=False)
        
        # Connect with timeout
        await asyncio.wait_for(client.connect(), timeout=timeout)
        logger.debug("✅ DB connection established (id=%s)", id(client))
        
        yield client
        
    finally:
        # Always disconnect - critical for connection pool health
        if client:
            try:
                if client.is_connected():
                    await asyncio.wait_for(client.disconnect(), timeout=DEFAULT_DISCONNECT_TIMEOUT)
                    logger.debug("🔌 DB connection closed (id=%s)", id(client))
            except asyncio.TimeoutError:
                logger.warning("⚠️ DB disconnect timeout (id=%s)", id(client))
            except Exception as e:
                logger.debug("DB disconnect error (id=%s): %s", id(client), e)
            
            # Force engine stop to ensure DB connections are returned to pool
            try:
                if hasattr(client, '_engine') and client._engine:
                    await asyncio.wait_for(client._engine.stop(), timeout=2.0)
            except Exception:
                pass


__all__ = ["get_db_connection"]
