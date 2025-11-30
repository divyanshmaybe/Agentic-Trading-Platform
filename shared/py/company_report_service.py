"""
Company Report Service with MongoDB + Redis Cache

Provides high-performance access to company reports with Redis caching layer.
Implements read-through cache pattern: Redis → MongoDB → Return.

Usage:
    ```python
    from company_report_service import CompanyReportService
    
    # Get service instance
    service = CompanyReportService.get_instance()
    
    # Initialize (connects to MongoDB and Redis)
    await service.initialize()
    
    # Get report (checks Redis first, then MongoDB)
    report = await service.get_report_by_ticker("RELIANCE")
    
    # Upsert report (writes to MongoDB, updates cache)
    await service.upsert_report({
        "ticker": "RELIANCE",
        "company_name": "Reliance Industries",
        ...
    })
    
    # Clear cache for a ticker
    await service.clear_cache("RELIANCE")
    
    # Clear all cache
    await service.clear_all_cache()
    ```
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional, Dict, Any, List
from datetime import datetime

from pymongo.errors import DuplicateKeyError

try:
    from .mongodb_provider import MongoDBProvider
    from .redisManager import RedisManager
except ImportError:
    from mongodb_provider import MongoDBProvider
    from redisManager import RedisManager


class CompanyReportService:
    """
    Service for managing company reports with MongoDB storage and Redis caching.
    
    Implements read-through cache pattern:
    - Read: Redis → MongoDB → Cache → Return
    - Write: MongoDB → Invalidate/Update Cache
    """

    _instance: Optional["CompanyReportService"] = None
    COLLECTION_NAME = "company_reports"
    CACHE_PREFIX = "company_report:"
    DEFAULT_CACHE_TTL = 3600*24  # 24 hours

    def __init__(
        self,
        mongodb_provider: Optional[MongoDBProvider] = None,
        redis_manager: Optional[RedisManager] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """
        Initialize CompanyReportService.
        
        Args:
            mongodb_provider: MongoDBProvider instance (if None, uses get_instance())
            redis_manager: RedisManager instance (if None, creates new one)
            cache_ttl: Cache TTL in seconds (default: 86400 seconds)
            
        Note: Use get_instance() instead of direct instantiation.
        """
        if CompanyReportService._instance is not None:
            raise RuntimeError(
                "CompanyReportService is a singleton. Use CompanyReportService.get_instance() to access it."
            )

        self.logger = logging.getLogger(__name__)
        self.mongodb_provider = mongodb_provider or MongoDBProvider.get_instance()
        self.redis_manager = redis_manager or RedisManager()
        self.cache_ttl = cache_ttl
        self._initialized = False
        self._loop = None  # Track which event loop we're initialized in

    @classmethod
    def get_instance(
        cls,
        mongodb_provider: Optional[MongoDBProvider] = None,
        redis_manager: Optional[RedisManager] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ) -> "CompanyReportService":
        """
        Get or create the shared CompanyReportService singleton instance.
        
        Args:
            mongodb_provider: MongoDBProvider instance (only used on first call)
            redis_manager: RedisManager instance (only used on first call)
            cache_ttl: Cache TTL in seconds (only used on first call)
            
        Returns:
            The singleton CompanyReportService instance.
        """
        if cls._instance is None:
            cls._instance = cls(
                mongodb_provider=mongodb_provider,
                redis_manager=redis_manager,
                cache_ttl=cache_ttl,
            )
        return cls._instance

    async def initialize(self) -> None:
        """
        Initialize service (connect to MongoDB and Redis).
        
        Handles event loop changes by re-initializing when loop changes.
        Should be called before using the service.
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError(
                "initialize() must be called from within an async context. "
                "Use asyncio.run() or ensure you're in an async function."
            )
        
        # If event loop changed, reset initialization
        if self._loop is not None and self._loop is not current_loop:
            self.logger.debug("Event loop changed, re-initializing CompanyReportService")
            self._initialized = False
            self._loop = None
        
        # If already initialized for this loop, skip
        if self._initialized and self._loop is current_loop:
            self.logger.debug("Service already initialized for this event loop")
            return

        try:
            # Connect to MongoDB (handles event loop changes internally)
            await self.mongodb_provider.connect()
            
            # Connect to Redis
            if not self.redis_manager.client:
                await self.redis_manager.connect()
            
            # Create indexes on MongoDB collection
            await self._create_indexes()
            
            self._initialized = True
            self._loop = current_loop
            self.logger.info("✅ CompanyReportService initialized")
        except Exception as e:
            self.logger.error("❌ Failed to initialize CompanyReportService: %s", e, exc_info=True)
            raise

    async def _create_indexes(self) -> None:
        """Create necessary indexes on MongoDB collection."""
        try:
            db = self.mongodb_provider.get_database()
            collection = db[self.COLLECTION_NAME]
            
            # Create unique index on ticker
            await collection.create_index("ticker", unique=True)
            
            # Create index on company_name for search
            await collection.create_index("company_name")
            
            # Create index on updated_at for sorting
            await collection.create_index("updated_at")
            
            self.logger.debug("✅ Created indexes on company_reports collection")
        except Exception as e:
            self.logger.warning("Failed to create indexes (may already exist): %s", e)

    def _get_cache_key(self, ticker: str) -> str:
        """Generate Redis cache key for a ticker."""
        return f"{self.CACHE_PREFIX}{ticker.upper()}"

    async def get_report_by_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get company report by ticker (with Redis cache).
        
        Read path: Redis → MongoDB → Cache → Return
        
        Args:
            ticker: Stock ticker symbol (e.g., "RELIANCE")
            
        Returns:
            Company report dictionary or None if not found
        """
        if not self._initialized:
            await self.initialize()

        ticker_upper = ticker.upper()
        cache_key = self._get_cache_key(ticker_upper)

        try:
            # Try Redis cache first
            cached_data = await self.redis_manager.get(cache_key)
            if cached_data:
                self.logger.debug(f"✅ Cache hit for ticker: {ticker_upper}")
                return json.loads(cached_data)
        except Exception as e:
            self.logger.warning(f"Redis cache read failed for {ticker_upper}: {e}")

        # Cache miss - fetch from MongoDB
        try:
            db = self.mongodb_provider.get_database()
            collection = db[self.COLLECTION_NAME]
            
            report = await collection.find_one({"ticker": ticker_upper})
            
            if report:
                # Convert ObjectId to string for JSON serialization
                if "_id" in report:
                    report["_id"] = str(report["_id"])
                
                # Cache in Redis for next time
                try:
                    await self.redis_manager.set(
                        cache_key,
                        json.dumps(report),
                        expire=self.cache_ttl,
                    )
                    self.logger.debug(f"✅ Cached report for ticker: {ticker_upper}")
                except Exception as e:
                    self.logger.warning(f"Failed to cache report for {ticker_upper}: {e}")
                
                return report
            
            self.logger.debug(f"Report not found for ticker: {ticker_upper}")
            return None

        except Exception as e:
            self.logger.error(f"❌ Failed to fetch report from MongoDB for {ticker_upper}: {e}", exc_info=True)
            raise

    async def get_reports_by_tickers(self, tickers: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Get multiple company reports by tickers (batch operation with caching).
        
        Args:
            tickers: List of ticker symbols
            
        Returns:
            Dictionary mapping ticker -> report (or None if not found)
        """
        if not self._initialized:
            await self.initialize()

        results = {}
        tickers_to_fetch = []

        # Check cache for each ticker
        for ticker in tickers:
            ticker_upper = ticker.upper()
            cache_key = self._get_cache_key(ticker_upper)
            
            try:
                cached_data = await self.redis_manager.get(cache_key)
                if cached_data:
                    results[ticker_upper] = json.loads(cached_data)
                    self.logger.debug(f"✅ Cache hit for ticker: {ticker_upper}")
                else:
                    tickers_to_fetch.append(ticker_upper)
            except Exception as e:
                self.logger.warning(f"Redis cache read failed for {ticker_upper}: {e}")
                tickers_to_fetch.append(ticker_upper)

        # Fetch missing reports from MongoDB
        if tickers_to_fetch:
            try:
                db = self.mongodb_provider.get_database()
                collection = db[self.COLLECTION_NAME]
                
                # Query MongoDB for missing tickers
                cursor = collection.find({"ticker": {"$in": tickers_to_fetch}})
                async for report in cursor:
                    ticker_upper = report["ticker"].upper()
                    
                    # Convert ObjectId to string
                    if "_id" in report:
                        report["_id"] = str(report["_id"])
                    
                    results[ticker_upper] = report
                    
                    # Cache in Redis
                    try:
                        cache_key = self._get_cache_key(ticker_upper)
                        await self.redis_manager.set(
                            cache_key,
                            json.dumps(report),
                            expire=self.cache_ttl,
                        )
                    except Exception as e:
                        self.logger.warning(f"Failed to cache report for {ticker_upper}: {e}")
                
                # Mark missing tickers as None
                for ticker_upper in tickers_to_fetch:
                    if ticker_upper not in results:
                        results[ticker_upper] = None
                        
            except Exception as e:
                self.logger.error(f"❌ Failed to fetch reports from MongoDB: {e}", exc_info=True)
                # Mark all missing as None on error
                for ticker_upper in tickers_to_fetch:
                    if ticker_upper not in results:
                        results[ticker_upper] = None

        return results

    async def upsert_report(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upsert company report (insert or update).
        
        Write path: MongoDB → Invalidate/Update Cache
        
        Args:
            report_data: Company report dictionary (must include "ticker")
            
        Returns:
            Upserted report dictionary
        """
        if not self._initialized:
            await self.initialize()

        if "ticker" not in report_data:
            raise ValueError("report_data must include 'ticker' field")

        ticker_upper = report_data["ticker"].upper()
        report_data["ticker"] = ticker_upper

        # Add/update timestamps
        now = datetime.utcnow()
        if "_id" not in report_data:
            report_data["created_at"] = now
        report_data["updated_at"] = now

        try:
            db = self.mongodb_provider.get_database()
            collection = db[self.COLLECTION_NAME]
            
            # Upsert (insert or update)
            result = await collection.update_one(
                {"ticker": ticker_upper},
                {"$set": report_data},
                upsert=True,
            )
            
            # Fetch the updated document
            updated_report = await collection.find_one({"ticker": ticker_upper})
            
            if updated_report and "_id" in updated_report:
                updated_report["_id"] = str(updated_report["_id"])
            
            # Update cache
            try:
                cache_key = self._get_cache_key(ticker_upper)
                await self.redis_manager.set(
                    cache_key,
                    json.dumps(updated_report),
                    expire=self.cache_ttl,
                )
                self.logger.debug(f"✅ Updated cache for ticker: {ticker_upper}")
            except Exception as e:
                self.logger.warning(f"Failed to update cache for {ticker_upper}: {e}")
            
            self.logger.info(
                f"✅ Upserted report for ticker: {ticker_upper} "
                f"(matched: {result.matched_count}, modified: {result.modified_count})"
            )
            
            return updated_report

        except DuplicateKeyError as e:
            self.logger.error(f"❌ Duplicate key error for ticker {ticker_upper}: {e}")
            raise ValueError(f"Report with ticker {ticker_upper} already exists") from e
        except Exception as e:
            self.logger.error(f"❌ Failed to upsert report for {ticker_upper}: {e}", exc_info=True)
            raise

    async def delete_report(self, ticker: str) -> bool:
        """
        Delete company report by ticker.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            True if deleted, False if not found
        """
        if not self._initialized:
            await self.initialize()

        ticker_upper = ticker.upper()

        try:
            db = self.mongodb_provider.get_database()
            collection = db[self.COLLECTION_NAME]
            
            result = await collection.delete_one({"ticker": ticker_upper})
            
            # Clear cache
            await self.clear_cache(ticker_upper)
            
            deleted = result.deleted_count > 0
            if deleted:
                self.logger.info(f"✅ Deleted report for ticker: {ticker_upper}")
            else:
                self.logger.debug(f"Report not found for deletion: {ticker_upper}")
            
            return deleted

        except Exception as e:
            self.logger.error(f"❌ Failed to delete report for {ticker_upper}: {e}", exc_info=True)
            raise

    async def clear_cache(self, ticker: str) -> bool:
        """
        Clear Redis cache for a specific ticker.
        
        Args:
            ticker: Stock ticker symbol
            
        Returns:
            True if cache was cleared, False otherwise
        """
        ticker_upper = ticker.upper()
        cache_key = self._get_cache_key(ticker_upper)

        try:
            deleted = await self.redis_manager.delete(cache_key)
            if deleted:
                self.logger.debug(f"✅ Cleared cache for ticker: {ticker_upper}")
            return deleted > 0
        except Exception as e:
            self.logger.warning(f"Failed to clear cache for {ticker_upper}: {e}")
            return False

    async def clear_all_cache(self) -> int:
        """
        Clear all company report caches from Redis.
        
        Returns:
            Number of keys deleted
        """
        try:
            if not self.redis_manager.client:
                self.logger.warning("Redis client not available for cache clearing")
                return 0

            # Get all keys matching the prefix
            pattern = f"{self.CACHE_PREFIX}*"
            keys = await self.redis_manager.scan_keys(pattern)
            
            if keys:
                deleted = await self.redis_manager.client.delete(*keys)
                self.logger.info(f"✅ Cleared {deleted} cache keys")
                return deleted
            else:
                self.logger.debug("No cache keys found to clear")
                return 0

        except Exception as e:
            self.logger.error(f"❌ Failed to clear all cache: {e}", exc_info=True)
            return 0

    async def health_check(self) -> Dict[str, bool]:
        """
        Perform health check on MongoDB and Redis.
        
        Returns:
            Dictionary with health status for MongoDB and Redis
        """
        health = {
            "mongodb": False,
            "redis": False,
        }

        try:
            health["mongodb"] = await self.mongodb_provider.health_check()
        except Exception as e:
            self.logger.warning(f"MongoDB health check failed: {e}")

        try:
            health["redis"] = await self.redis_manager.health_check()
        except Exception as e:
            self.logger.warning(f"Redis health check failed: {e}")

        return health


__all__ = ["CompanyReportService"]

