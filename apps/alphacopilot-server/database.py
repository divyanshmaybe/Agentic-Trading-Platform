"""Database setup using Prisma client."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load .env file BEFORE importing DBManager
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    _root_env = Path(__file__).resolve().parents[2] / ".env"
    if _root_env.exists():
        load_dotenv(_root_env)

# Add shared/py to path for DBManager
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_PY = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY) not in sys.path:
    sys.path.insert(0, str(SHARED_PY))

from dbManager import DBManager


_db_manager: Optional[DBManager] = None


async def get_db_manager() -> DBManager:
    """Get the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DBManager.get_instance()
    if not _db_manager.is_connected():
        await _db_manager.connect()
    return _db_manager


async def get_prisma_client():
    """Get the Prisma client."""
    manager = await get_db_manager()
    return manager.get_client()


@asynccontextmanager
async def get_db_session():
    """Async context manager for database sessions."""
    client = await get_prisma_client()
    try:
        yield client
    finally:
        pass  # Connection pooling handled by DBManager


async def init_db():
    """Initialize database connection."""
    manager = await get_db_manager()
    await manager.connect()


async def close_db():
    """Close database connection."""
    global _db_manager
    if _db_manager is not None:
        await _db_manager.disconnect()
        _db_manager = None



