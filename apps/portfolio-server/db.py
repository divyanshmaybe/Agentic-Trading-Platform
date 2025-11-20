"""
Database utilities for the portfolio server.

This module provides database access utilities for the portfolio server.
It wraps the new db_client module for compatibility with existing code.
"""

from __future__ import annotations

from typing import AsyncIterator
from prisma import Prisma

# Import from new robust db_client module
from db_client import (
    DBManager,
    get_db_client,
    get_db,
    ensure_disconnected,
    DatabaseClient,
    health_check,
)


def get_db_manager() -> DBManager:
    """
    Return the database manager instance.
    
    Legacy compatibility function. For new code, prefer using
    get_db_client() or DatabaseClient context manager directly.
    """
    return DBManager.get_instance()


async def prisma_client() -> AsyncIterator[Prisma]:
    """
    FastAPI dependency that yields a connected Prisma client.
    
    Usage:
        ```python
        from db import prisma_client
        
        @router.get("/users")
        async def get_users(db: Prisma = Depends(prisma_client)):
            return await db.user.find_many()
        ```
    
    For new code, prefer using get_db from db_client:
        ```python
        from db_client import get_db
        
        @router.get("/users")
        async def get_users(db: Prisma = Depends(get_db)):
            return await db.user.find_many()
        ```
    """
    db = await get_db_client()
    try:
        yield db
    finally:
        # Connection stays open for reuse
        pass


# Re-export for convenience
__all__ = [
    "get_db_manager",
    "prisma_client",
    "get_db_client",
    "get_db",
    "ensure_disconnected",
    "DatabaseClient",
    "health_check",
    "DBManager",
]
