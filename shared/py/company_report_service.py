"""
Company Report Service with MongoDB + Redis Cache

Provides high-performance access to company reports with Redis caching layer. 
Implements read-through cache pattern: Redis → MongoDB → Return. 
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from pymongo. errors import DuplicateKeyError

try:
    from . mongodb_provider import MongoDBProvider
    from .redisManager import RedisManager
except ImportError:
    from mongodb_provider import MongoDBProvider
    from redisManager import RedisManager


class CompanyReportService:
    """
    Service for managing company reports with MongoDB storage and Redis caching.
    
    Thread-safe for use with ThreadPoolExecutor.
    """

    _instance: Optional["CompanyReportService"] = None
    COLLECTION_NAME = "company_reports"
    CACHE_PREFIX = "company_report:"
    DEFAULT_CACHE_TTL = 3600 * 24  # 24 hours

    def __init__(
        self,
        mongodb_provider: Optional[MongoDBProvider] = None,
        redis_manager: Optional[RedisManager] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """Initialize CompanyReportService singleton."""
        if CompanyReportService._instance is not None:
            raise RuntimeError(
                "CompanyReportService is a singleton.  Use get_instance()."
            )

        self.logger = logging.getLogger(__name__)
        self.mongodb_provider = mongodb_provider or MongoDBProvider. get_instance()
        self. redis_manager = redis_manager or RedisManager()
        self.cache_ttl = cache_ttl
        self._initialized = False

    @classmethod
    def get_instance(
        cls,
        mongodb_provider: Optional[MongoDBProvider] = None,
        redis_manager: Optional[RedisManager] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ) -> "CompanyReportService":
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls(
                mongodb_provider=mongodb_provider,
                redis_manager=redis_manager,
                cache_ttl=cache_ttl,
            )
        return cls._instance

    async def initialize(self) -> None:
        """
        Initialize service - MUST be called in the same event loop where it will be used.
        This is thread-safe and can be called multiple times.
        """
        try:
            # Connect to MongoDB
            await self.mongodb_provider.connect()
            
            # Connect to Redis (always call to handle loop changes)
            await self.redis_manager.connect()
            
            # Create indexes
            await self._create_indexes()
            
            self._initialized = True
            self.logger.debug("✅ CompanyReportService initialized")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize: {e}", exc_info=True)
            raise

    async def _create_indexes(self) -> None:
        """Create MongoDB indexes."""
        try:
            db = self.mongodb_provider.get_database()
            collection = db[self.COLLECTION_NAME]
            
            # Create indexes (idempotent - won't fail if exists)
            await collection.create_index("ticker", unique=True)
            await collection.create_index("company_name")
            await collection.create_index("updated_at")
            
            self.logger.debug("✅ Indexes created/verified")
        except Exception as e:
            # Indexes might already exist - this is OK
            self.logger.debug(f"Index creation note: {e}")

    def _get_cache_key(self, ticker: str) -> str:
        """Generate Redis cache key."""
        return f"{self. CACHE_PREFIX}{ticker. upper()}"

    def _serialize_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Convert MongoDB document to JSON-serializable dict."""
        serialized = report.copy()
        
        # Convert ObjectId to string
        if "_id" in serialized:
            serialized["_id"] = str(serialized["_id"])
        
        # Convert datetime to ISO string
        for key in ["created_at", "updated_at"]:
            if key in serialized and isinstance(serialized[key], datetime):
                serialized[key] = serialized[key].isoformat()
        
        return serialized

    async def get_report_by_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get company report by ticker (with Redis cache).
        
        Thread-safe when called from separate event loops.
        """
        ticker_upper = ticker.upper()
        cache_key = self._get_cache_key(ticker_upper)

        # Try Redis cache first
        try:
            cached_data = await self.redis_manager. get(cache_key)
            if cached_data:
                self.logger.debug(f"✅ Cache hit: {ticker_upper}")
                return json.loads(cached_data)
        except Exception as e:
            self.logger.warning(f"Redis read failed for {ticker_upper}: {e}")

        # Fetch from MongoDB
        try:
            db = self.mongodb_provider.get_database()
            collection = db[self.COLLECTION_NAME]
            
            report = await collection.find_one({"ticker": ticker_upper})
            
            if report:
                # Serialize for JSON
                report = self._serialize_report(report)
                
                # Cache in Redis
                try:
                    await self.redis_manager.set(
                        cache_key,
                        json.dumps(report, default=str),
                        expire=self.cache_ttl,
                    )
                    self.logger.debug(f"✅ Cached: {ticker_upper}")
                except Exception as e:
                    self.logger.warning(f"Redis write failed for {ticker_upper}: {e}")
                
                return report
            
            self.logger.debug(f"Report not found: {ticker_upper}")
            return None

        except Exception as e:
            self.logger.error(f"❌ MongoDB fetch failed for {ticker_upper}: {e}", exc_info=True)
            raise

    async def upsert_report(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Upsert company report. 
        
        Thread-safe when called from separate event loops.
        """
        if "ticker" not in report_data:
            raise ValueError("report_data must include 'ticker' field")

        ticker_upper = report_data["ticker"]. upper()
        report_data["ticker"] = ticker_upper

        # Add timestamps
        now = datetime.utcnow()
        if "_id" not in report_data:
            report_data["created_at"] = now
        report_data["updated_at"] = now

        try:
            db = self.mongodb_provider.get_database()
            collection = db[self. COLLECTION_NAME]
            
            # Upsert
            result = await collection.update_one(
                {"ticker": ticker_upper},
                {"$set": report_data},
                upsert=True,
            )
            
            # Fetch updated document
            updated_report = await collection.find_one({"ticker": ticker_upper})
            
            # Serialize
            updated_report = self._serialize_report(updated_report)
            
            # Update cache
            try:
                cache_key = self._get_cache_key(ticker_upper)
                await self.redis_manager. set(
                    cache_key,
                    json.dumps(updated_report, default=str),
                    expire=self.cache_ttl,
                )
                self.logger.debug(f"✅ Cache updated: {ticker_upper}")
            except Exception as e:
                self.logger.warning(f"Redis update failed for {ticker_upper}: {e}")
            
            self.logger.info(
                f"✅ Upserted {ticker_upper} "
                f"(matched: {result.matched_count}, modified: {result.modified_count})"
            )
            
            return updated_report

        except DuplicateKeyError as e:
            self.logger. error(f"❌ Duplicate key: {ticker_upper}")
            raise ValueError(f"Report exists: {ticker_upper}") from e
        except Exception as e:
            self.logger.error(f"❌ Upsert failed for {ticker_upper}: {e}", exc_info=True)
            raise

    async def delete_report(self, ticker: str) -> bool:
        """Delete report by ticker."""
        ticker_upper = ticker.upper()

        try:
            db = self.mongodb_provider.get_database()
            collection = db[self.COLLECTION_NAME]
            
            result = await collection.delete_one({"ticker": ticker_upper})
            
            # Clear cache
            await self.clear_cache(ticker_upper)
            
            deleted = result.deleted_count > 0
            if deleted:
                self.logger. info(f"✅ Deleted: {ticker_upper}")
            
            return deleted

        except Exception as e:
            self.logger.error(f"❌ Delete failed for {ticker_upper}: {e}", exc_info=True)
            raise

    async def clear_cache(self, ticker: str) -> bool:
        """Clear Redis cache for ticker."""
        ticker_upper = ticker.upper()
        cache_key = self._get_cache_key(ticker_upper)

        try:
            deleted = await self.redis_manager. delete(cache_key)
            if deleted:
                self.logger. debug(f"✅ Cache cleared: {ticker_upper}")
            return deleted > 0
        except Exception as e:
            self.logger.warning(f"Cache clear failed for {ticker_upper}: {e}")
            return False

    async def clear_all_cache(self) -> int:
        """Clear all company report caches."""
        try:
            if not self.redis_manager.client:
                return 0

            pattern = f"{self.CACHE_PREFIX}*"
            keys = await self.redis_manager.scan_keys(pattern)
            
            if keys:
                deleted = await self. redis_manager.client.delete(*keys)
                self.logger.info(f"✅ Cleared {deleted} cache keys")
                return deleted
            
            return 0

        except Exception as e:
            self.logger.error(f"❌ Clear all cache failed: {e}", exc_info=True)
            return 0


__all__ = ["CompanyReportService"]