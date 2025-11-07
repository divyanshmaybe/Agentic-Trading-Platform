"""Database utilities for the portfolio server."""

from __future__ import annotations

import os
import sys
from typing import AsyncIterator

from prisma import Prisma

# Ensure shared Python utilities are importable
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../..")
SHARED_PY_PATH = os.path.join(PROJECT_ROOT, "shared/py")

if SHARED_PY_PATH not in sys.path:
    sys.path.insert(0, SHARED_PY_PATH)

from dbManager import DBManager  # pylint: disable=wrong-import-position


def get_db_manager() -> DBManager:
    """Return the shared Prisma-backed database manager."""

    return DBManager.get_instance()


async def prisma_client() -> AsyncIterator[Prisma]:
    """FastAPI dependency that yields a connected Prisma client."""

    manager = get_db_manager()

    if not manager.is_connected():
        await manager.connect()

    try:
        yield manager.get_client()
    finally:
        # Connection stays open for reuse; lifecycle managed by BaseApp
        pass
