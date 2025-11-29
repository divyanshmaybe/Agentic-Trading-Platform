"""
MongoDB Provider for FastAPI applications

Provides MongoDB connection management with singleton pattern.
Uses motor (async MongoDB driver) for async operations.

Usage:
    ```python
    from mongodb_provider import MongoDBProvider
    
    # Get singleton instance
    provider = MongoDBProvider.get_instance()
    
    # Connect
    await provider.connect()
    
    # Get database
    db = provider.get_database()
    
    # Use database
    collection = db["company_reports"]
    result = await collection.find_one({"ticker": "RELIANCE"})
    
    # Disconnect when done
    await provider.disconnect()
    ```
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError


class MongoDBProvider:
    """
    Singleton MongoDB connection manager using Motor (async driver).
    
    Provides robust connection management with automatic reconnection.
    Thread-safe and event loop aware.
    """

    _instance: Optional["MongoDBProvider"] = None
    _lock: asyncio.Lock = None
    _pid: Optional[int] = None

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize MongoDBProvider.
        
        Args:
            connection_string: MongoDB connection string. If not provided, uses MONGODB_URI env var.
            
        Note: Use get_instance() instead of direct instantiation.
        """
        if MongoDBProvider._instance is not None:
            raise RuntimeError(
                "MongoDBProvider is a singleton. Use MongoDBProvider.get_instance() to access it."
            )

        self.logger = logging.getLogger(__name__)
        
        # Get connection string from parameter or environment
        self.connection_string = connection_string or os.getenv(
            "MONGODB_URI"
        ) or os.getenv("MONGODB_URL") or os.getenv("MONGO_URL")
        
        # Build connection string from components if not provided
        if not self.connection_string:
            mongo_host = os.getenv("MONGODB_HOST", "localhost")
            mongo_port = int(os.getenv("MONGODB_PORT", "27017"))
            mongo_user = os.getenv("MONGODB_USER")
            mongo_password = os.getenv("MONGODB_PASSWORD")
            mongo_db = os.getenv("MONGODB_DB", "portfolio_db")
            
            if mongo_user and mongo_password:
                self.connection_string = (
                    f"mongodb://{mongo_user}:{mongo_password}@{mongo_host}:{mongo_port}/{mongo_db}"
                )
            else:
                self.connection_string = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
            
            self.logger.info(
                "MONGODB_URI not set, using default config: mongodb://%s:***@%s:%s/%s",
                mongo_user or "no-auth", mongo_host, mongo_port, mongo_db
            )

        self.client: Optional[AsyncIOMotorClient] = None
        self.database_name: str = os.getenv("MONGODB_DB", "portfolio_db")
        self._connected: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connecting: bool = False

    @classmethod
    def get_instance(cls, connection_string: Optional[str] = None) -> "MongoDBProvider":
        """
        Get or create the shared MongoDBProvider singleton instance.
        
        Args:
            connection_string: MongoDB connection string (only used on first call).
            
        Returns:
            The singleton MongoDBProvider instance.
        """
        # Detect process fork - reset instance if PID changed
        current_pid = os.getpid()
        
        if cls._instance is not None and cls._pid is not None and cls._pid != current_pid:
            logging.getLogger(__name__).info(
                "🔄 Process fork detected (PID %s → %s), resetting MongoDBProvider instance",
                cls._pid, current_pid
            )
            cls.reset_instance()
        
        if cls._instance is not None and cls._pid is None:
            cls._pid = current_pid
        
        if cls._instance is None:
            cls._instance = cls(connection_string=connection_string)
            cls._pid = current_pid
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance."""
        if cls._instance is not None:
            try:
                if cls._instance.client and cls._instance._connected:
                    try:
                        loop = asyncio.get_event_loop()
                        if not loop.is_running():
                            asyncio.run(cls._instance.disconnect())
                    except Exception:
                        pass
            except Exception:
                pass
            
            cls._instance = None
            cls._pid = None

    async def connect(self) -> None:
        """
        Establish connection to MongoDB.
        
        Handles event loop changes by recreating the client if needed.
        Safe to call multiple times.
        
        Raises:
            ConnectionFailure: If connection fails.
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
            self.logger.debug("Already connected to MongoDB (same event loop)")
            return

        # If already connecting, wait for it to complete
        if self._connecting:
            self.logger.debug("Connection in progress, waiting...")
            while self._connecting:
                await asyncio.sleep(0.1)
            return

        self._connecting = True

        try:
            # If loop changed or not connected, create fresh client
            if self._loop is not None and self._loop is not loop:
                self.logger.info("Event loop changed, creating fresh MongoDB client")
                if self.client:
                    try:
                        self.client.close()
                    except Exception:
                        pass
                self.client = None
                self._connected = False
                self._loop = None

            # Create client if needed
            if self.client is None:
                self.client = AsyncIOMotorClient(
                    self.connection_string,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    socketTimeoutMS=5000,
                )

            # Test connection
            await asyncio.wait_for(
                self.client.admin.command("ping"),
                timeout=5.0
            )

            self._connected = True
            self._loop = loop
            self.logger.info(
                "✅ Connected to MongoDB (database: %s, loop_id=%s)",
                self.database_name, id(loop)
            )

        except asyncio.TimeoutError:
            self.logger.error("❌ MongoDB connection timed out after 5 seconds")
            self._connecting = False
            raise ConnectionFailure("MongoDB connection timeout")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            self.logger.error("❌ Failed to connect to MongoDB: %s", e)
            self._connected = False
            self._loop = None
            raise
        except Exception as e:
            self.logger.error("❌ Unexpected error during MongoDB connection: %s", e, exc_info=True)
            self._connected = False
            self._loop = None
            raise
        finally:
            self._connecting = False

    async def disconnect(self) -> None:
        """Close MongoDB connection if active."""
        if not self._connected and self.client is None:
            self.logger.debug("Already disconnected from MongoDB")
            return

        try:
            if self.client:
                self.client.close()
                self.logger.info("🔌 Disconnected from MongoDB")
        except Exception as e:
            self.logger.warning("Error during MongoDB disconnect: %s", e)
        finally:
            self._connected = False
            self._loop = None
            self.client = None

    def get_database(self, database_name: Optional[str] = None) -> AsyncIOMotorDatabase:
        """
        Get MongoDB database instance.
        
        Args:
            database_name: Database name. If not provided, uses default from config.
            
        Returns:
            AsyncIOMotorDatabase instance.
            
        Raises:
            RuntimeError: If not connected.
        """
        if not self._connected:
            raise RuntimeError(
                "MongoDB not connected. Call await connect() before accessing the database."
            )
        
        db_name = database_name or self.database_name
        return self.client[db_name]

    def is_connected(self) -> bool:
        """Check if MongoDB connection is active."""
        return self._connected

    async def health_check(self) -> bool:
        """
        Perform health check against MongoDB.
        
        Returns:
            True if MongoDB is healthy, False otherwise.
        """
        if not self._connected:
            return False

        try:
            await asyncio.wait_for(
                self.client.admin.command("ping"),
                timeout=2.0
            )
            return True
        except Exception as exc:
            self.logger.warning("MongoDB health check failed: %s", exc)
            return False


__all__ = ["MongoDBProvider"]

