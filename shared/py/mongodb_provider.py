"""
MongoDB Provider for FastAPI applications

Provides MongoDB Atlas and local MongoDB connection management with singleton pattern.
Uses motor (async MongoDB driver) for async operations.

Supports both MongoDB Atlas (mongodb+srv://) and local MongoDB (mongodb://) connections.

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
    
    Supports both MongoDB Atlas (mongodb+srv://) and local MongoDB (mongodb://) connections.
    Provides robust connection management with automatic reconnection.
    Thread-safe and event loop aware.
    """

    _instance: Optional["MongoDBProvider"] = None
    _lock: asyncio.Lock = None
    _pid: Optional[int] = None

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize MongoDBProvider for MongoDB Atlas or local MongoDB.
        
        Args:
            connection_string: MongoDB connection string.
                              For Atlas: mongodb+srv://username:password@cluster.mongodb.net/database
                              For local: mongodb://localhost:27017/database
                              If not provided, uses MONGODB_URI or MONGODB_URL env var.
            
        Note: Use get_instance() instead of direct instantiation.
        Raises:
            ValueError: If connection string is not provided or not a valid MongoDB URI.
        """
        if MongoDBProvider._instance is not None:
            raise RuntimeError(
                "MongoDBProvider is a singleton. Use MongoDBProvider.get_instance() to access it."
            )

        self.logger = logging.getLogger(__name__)
        
        # Get MongoDB Atlas connection string (mongodb+srv:// only)
        self.connection_string = connection_string or os.getenv("MONGODB_URI") or os.getenv("MONGODB_URL")
        
        if not self.connection_string:
            raise ValueError(
                "MONGODB_URI environment variable is required. "
                "Please set your MongoDB Atlas connection string: "
                "mongodb+srv://username:password@cluster.mongodb.net/database"
            )
        
        # Validate that it's a MongoDB Atlas connection (mongodb+srv://) or local (mongodb://)
        if not (self.connection_string.startswith("mongodb+srv://") or self.connection_string.startswith("mongodb://")):
            raise ValueError(
                "Only MongoDB Atlas connections (mongodb+srv://) or local MongoDB (mongodb://) are supported. "
                f"Received: {self.connection_string[:30]}..."
            )
        
        if self.connection_string.startswith("mongodb+srv://"):
            self.logger.info("✅ Using MongoDB Atlas connection")
        else:
            self.logger.info("✅ Using local MongoDB connection")
        
        # Extract database name from Atlas connection string
        # Format: mongodb+srv://user:pass@cluster.mongodb.net/dbname?options
        try:
            after_at = self.connection_string.split("@")[-1]
            if "/" in after_at:
                db_part = after_at.split("/")[1].split("?")[0]
                if db_part:
                    self.database_name = db_part
                else:
                    self.database_name = os.getenv("MONGODB_DB", "portfolio_db")
            else:
                self.database_name = os.getenv("MONGODB_DB", "portfolio_db")
        except Exception:
            self.database_name = os.getenv("MONGODB_DB", "portfolio_db")

        self.client: Optional[AsyncIOMotorClient] = None
        self._connected: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connecting: bool = False

    @classmethod
    def get_instance(cls, connection_string: Optional[str] = None) -> "MongoDBProvider":
        """
        Get or create the shared MongoDBProvider singleton instance.
        
        Args:
            connection_string: MongoDB connection string (Atlas or local, only used on first call).
            
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
        Establish connection to MongoDB (Atlas or local).
        
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
            self.logger.debug("Already connected to MongoDB Atlas (same event loop)")
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
                # MongoDB connection parameters
                client_kwargs = {
                    "serverSelectionTimeoutMS": 10000,
                    "connectTimeoutMS": 10000,
                    "socketTimeoutMS": 30000,
                }
                
                # Add Atlas-specific parameters only for Atlas connections
                if self.connection_string.startswith("mongodb+srv://"):
                    client_kwargs.update({
                        "tls": True,
                        "tlsAllowInvalidCertificates": False,
                    })
                    
                    # Ensure standard Atlas parameters are present
                    if "?" not in self.connection_string:
                        self.connection_string = f"{self.connection_string}?retryWrites=true&w=majority"
                    elif "retryWrites" not in self.connection_string:
                        separator = "&" if "?" in self.connection_string else "?"
                        self.connection_string = f"{self.connection_string}{separator}retryWrites=true&w=majority"
                    
                    self.logger.debug("Configuring MongoDB Atlas connection with SSL/TLS")
                else:
                    # Local MongoDB - no TLS required
                    self.logger.debug("Configuring local MongoDB connection")
                
                self.client = AsyncIOMotorClient(
                    self.connection_string,
                    **client_kwargs
                )

            # Test connection (Atlas requires longer timeout due to network latency)
            await asyncio.wait_for(
                self.client.admin.command("ping"),
                timeout=15.0
            )

            self._connected = True
            self._loop = loop
            self.logger.info(
                "✅ Connected to MongoDB Atlas (database: %s, loop_id=%s)",
                self.database_name, id(loop)
            )

        except asyncio.TimeoutError:
            self.logger.error("❌ MongoDB Atlas connection timed out after 15 seconds")
            self._connecting = False
            raise ConnectionFailure("MongoDB Atlas connection timeout")
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            self.logger.error("❌ Failed to connect to MongoDB Atlas: %s", e)
            self._connected = False
            self._loop = None
            raise
        except Exception as e:
            self.logger.error("❌ Unexpected error during MongoDB Atlas connection: %s", e, exc_info=True)
            self._connected = False
            self._loop = None
            raise
        finally:
            self._connecting = False

    async def disconnect(self) -> None:
        """Close MongoDB connection if active."""
        if not self._connected and self.client is None:
            self.logger.debug("Already disconnected from MongoDB Atlas")
            return

        try:
            if self.client:
                self.client.close()
                self.logger.info("🔌 Disconnected from MongoDB Atlas")
        except Exception as e:
            self.logger.warning("Error during MongoDB Atlas disconnect: %s", e)
        finally:
            self._connected = False
            self._loop = None
            self.client = None

    def get_database(self, database_name: Optional[str] = None) -> AsyncIOMotorDatabase:
        """
        Get MongoDB database instance.
        
        Args:
            database_name: Database name. If not provided, uses default from connection string or config.
            
        Returns:
            AsyncIOMotorDatabase instance.
            
        Raises:
            RuntimeError: If not connected.
        """
        if not self._connected:
            raise RuntimeError(
                "MongoDB Atlas not connected. Call await connect() before accessing the database."
            )
        
        db_name = database_name or self.database_name
        return self.client[db_name]

    def is_connected(self) -> bool:
        """Check if MongoDB Atlas connection is active."""
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
                timeout=5.0
            )
            return True
        except Exception as exc:
            self.logger.warning("MongoDB Atlas health check failed: %s", exc)
            return False


__all__ = ["MongoDBProvider"]
