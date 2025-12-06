"""
Database connection manager - re-export from shared module.

This file maintains backward compatibility for existing imports.
All new code should import directly from dbManager.
"""

import sys
import os
from fastapi import HTTPException

# Add shared/py to path if not already there
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
shared_py_path = os.path.join(project_root, "shared/py")
if shared_py_path not in sys.path:
    sys.path.insert(0, shared_py_path)

from dbManager import DBManager

# Backward compatibility aliases
DatabaseClient = DBManager
get_db_client = DBManager.get_instance
get_db_manager = DBManager.get_instance  # Legacy alias from old implementation
disconnect = lambda: DBManager.get_instance().disconnect()

# prisma_client function for routes that need direct Prisma access
async def get_prisma_client():
    """
    Get the Prisma client from DBManager with auto-reconnection.

    This dependency ensures database connections are automatically restored
    if they become stale or disconnected during long-running server operation.

    Returns:
        Connected Prisma client instance.

    Raises:
        HTTPException: 503 if connection cannot be established.
    """
    db_manager = DBManager.get_instance()

    # Check if connected - if not, attempt to reconnect
    if not db_manager.is_connected():
        try:
            # Attempt to reconnect
            await db_manager.connect()
        except Exception as e:
            # Connection failed - return 503
            raise HTTPException(
                status_code=503,
                detail=f"Database connection failed: {str(e)}. Please retry in a moment."
            )

    try:
        return db_manager.get_client()
    except RuntimeError as e:
        # This should not happen after successful connect(), but handle defensively
        raise HTTPException(
            status_code=503,
            detail="Database connection not ready. Server is starting up, please retry in a moment."
        )

# For backward compatibility with direct prisma_client import
prisma_client = get_prisma_client

__all__ = ["DBManager", "DatabaseClient", "get_db_client", "get_db_manager", "disconnect", "prisma_client", "get_prisma_client"]