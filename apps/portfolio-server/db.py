"""
Database connection manager - re-export from shared module.

This file maintains backward compatibility for existing imports.
All new code should import directly from dbManager.
"""

import sys
import os

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
def get_prisma_client():
    """Get the Prisma client from DBManager. Must be called after DB is connected."""
    return DBManager.get_instance().get_client()

# For backward compatibility with direct prisma_client import
prisma_client = get_prisma_client

__all__ = ["DBManager", "DatabaseClient", "get_db_client", "get_db_manager", "disconnect", "prisma_client", "get_prisma_client"]