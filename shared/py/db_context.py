"""
Database connection context manager for proper cleanup in Celery workers.

Ensures Prisma connections are always closed after use, preventing connection pool exhaustion.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from prisma import Prisma

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db_connection(
    database_url: str | None = None,
    timeout: float = 10.0
) -> AsyncGenerator[Prisma, None]:
    """
    Context manager for database connections that guarantees cleanup.
    
    Usage:
        async with get_db_connection() as db:
            users = await db.user.find_many()
    
    Args:
        database_url: Optional database URL override
        timeout: Connection timeout in seconds
        
    Yields:
        Connected Prisma client
        
    Raises:
        TimeoutError: If connection times out
        PrismaError: If connection fails
    """
    client = None
    try:
        # Create fresh client
        if database_url:
            client = Prisma(datasource={"url": database_url})
        else:
            client = Prisma()
        
        # Connect with timeout
        await asyncio.wait_for(client.connect(), timeout=timeout)
        logger.debug("✅ DB connection established (id=%s)", id(client))
        
        yield client
        
    finally:
        # Always disconnect
        if client and client.is_connected():
            try:
                await asyncio.wait_for(client.disconnect(), timeout=3.0)
                logger.debug("🔌 DB connection closed (id=%s)", id(client))
            except asyncio.TimeoutError:
                logger.warning("⚠️ DB disconnect timeout (id=%s)", id(client))
            except Exception as e:
                logger.debug("DB disconnect error (id=%s): %s", id(client), e)
            
            # Force engine stop
            try:
                if hasattr(client, '_engine') and client._engine:
                    await client._engine.stop()
            except Exception:
                pass


__all__ = ["get_db_connection"]
