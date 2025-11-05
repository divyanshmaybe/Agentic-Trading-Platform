"""
Cache Middleware for FastAPI applications
Provides response caching using Redis
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from typing import Optional, Dict, Any, List
import json
import hashlib
import logging
import sys
import os
import time

# Add shared directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../shared/py"))

from redisManager import RedisManager

logger = logging.getLogger(__name__)


class CacheOptions:
    """Options for cache middleware configuration"""

    def __init__(
        self,
        ttl: int = 300,
        key_prefix: str = "cache",
        include_user: bool = False,
        include_query: bool = True,
        include_body: bool = False,
        exclude_params: Optional[List[str]] = None,
    ):
        self.ttl = ttl
        self.key_prefix = key_prefix
        self.include_user = include_user
        self.include_query = include_query
        self.include_body = include_body
        self.exclude_params = exclude_params or []


class CachedResponse:
    """Cached response data structure"""

    def __init__(self, data: Any, timestamp: int, status_code: int):
        self.data = data
        self.timestamp = timestamp
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "data": self.data,
            "timestamp": self.timestamp,
            "statusCode": self.status_code,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedResponse":
        """Create from dictionary"""
        return cls(
            data=data.get("data"),
            timestamp=data.get("timestamp", 0),
            status_code=data.get("statusCode", 200),
        )


class CacheManager:
    """Manager for cache operations"""

    def __init__(self):
        self.redis_manager: Optional[RedisManager] = None
        self._initialize_redis()

    def _initialize_redis(self):
        """Initialize Redis connection"""
        try:
            self.redis_manager = RedisManager()
        except Exception as e:
            logger.warning(f"Redis not available: {e}")
            self.redis_manager = None

    def _generate_cache_key(self, request: Request, options: CacheOptions) -> str:
        """Generate cache key from request"""
        parts: List[str] = [options.key_prefix]

        # Add base path
        path = request.url.path
        parts.append(path)

        # Add method
        parts.append(request.method.lower())

        # Add user ID if needed
        if options.include_user and hasattr(request.state, "user"):
            user = request.state.user
            if isinstance(user, dict) and user.get("_id"):
                parts.append(f"user:{user['_id']}")

        # Add path parameters
        if request.path_params:
            param_string = ",".join(
                f"{key}:{value}" for key, value in sorted(request.path_params.items())
            )
            if param_string:
                parts.append(f"params:{param_string}")

        # Add query parameters
        if options.include_query and request.query_params:
            filtered_query = [
                f"{key}:{value}"
                for key, value in sorted(request.query_params.items())
                if key not in options.exclude_params
            ]
            if filtered_query:
                parts.append(f"query:{','.join(filtered_query)}")

        # Add request body
        if options.include_body and hasattr(request, "_body"):
            try:
                body = request._body
                if body:
                    body_hash = hashlib.md5(body).hexdigest()
                    parts.append(f"body:{body_hash}")
            except Exception:
                pass

        return ":".join(parts)

    async def get(self, key: str) -> Optional[CachedResponse]:
        """Get data from cache"""
        if not self.redis_manager or not self.redis_manager.client:
            return None

        try:
            cached = await self.redis_manager.get(key)
            if not cached:
                return None

            parsed = json.loads(cached)
            return CachedResponse.from_dict(parsed)
        except Exception as error:
            logger.error(f"❌ Cache get error: {error}")
            return None

    async def set(
        self, key: str, data: Any, status_code: int = 200, ttl: int = 300
    ) -> None:
        """Set data in cache"""
        if not self.redis_manager or not self.redis_manager.client:
            return

        try:
            cache_data = CachedResponse(
                data=data, timestamp=int(time.time() * 1000), status_code=status_code
            )
            await self.redis_manager.set(key, json.dumps(cache_data.to_dict()), ex=ttl)
        except Exception as error:
            logger.error(f"❌ Cache set error: {error}")

    async def delete_pattern(self, pattern: str) -> int:
        """Delete cache entries by pattern"""
        if not self.redis_manager or not self.redis_manager.client:
            return 0

        try:
            # Redis doesn't have direct pattern delete, need to scan and delete
            keys = []
            async for key in self.redis_manager.client.scan_iter(match=pattern):
                keys.append(key)

            if not keys:
                return 0

            deleted = await self.redis_manager.client.delete(*keys)
            logger.info(f"🗑️ Deleted {deleted} cache entries matching pattern: {pattern}")
            return deleted
        except Exception as error:
            logger.error(f"❌ Cache delete pattern error: {error}")
            return 0

    async def delete(self, key: str) -> bool:
        """Delete specific cache key"""
        if not self.redis_manager or not self.redis_manager.client:
            return False

        try:
            deleted = await self.redis_manager.delete(key)
            return deleted > 0
        except Exception as error:
            logger.error(f"❌ Cache delete error: {error}")
            return False

    async def clear(self) -> None:
        """Clear all cache"""
        if not self.redis_manager or not self.redis_manager.client:
            return

        try:
            await self.redis_manager.client.flushdb()
            logger.info("🗑️ Cache cleared successfully")
        except Exception as error:
            logger.error(f"❌ Cache clear error: {error}")

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.redis_manager or not self.redis_manager.client:
            return {"connected": False, "keyCount": 0}

        try:
            key_count = await self.redis_manager.client.dbsize()
            info = await self.redis_manager.client.info("memory")
            memory_match = None
            if isinstance(info, str):
                import re
                memory_match = re.search(r"used_memory_human:(.+)", info)

            memory_usage = memory_match.group(1).strip() if memory_match else None

            return {
                "connected": True,
                "keyCount": key_count,
                "memoryUsage": memory_usage,
            }
        except Exception as error:
            logger.error(f"❌ Cache stats error: {error}")
            return {"connected": False, "keyCount": 0}


# Global cache manager instance
cache_manager = CacheManager()


def cache_middleware(options: CacheOptions = CacheOptions()):
    """Create cache middleware with options"""

    class CacheMiddlewareInstance(BaseHTTPMiddleware):
        """Cache middleware instance"""

        async def dispatch(self, request: Request, call_next):
            """Process request with caching"""
            # Skip caching for non-GET requests
            if request.method != "GET":
                return await call_next(request)

            cache_key = cache_manager._generate_cache_key(request, options)

            try:
                # Try to get from cache
                cached = await cache_manager.get(cache_key)

                if cached:
                    logger.info(f"🎯 Cache HIT: {cache_key}")

                    response = JSONResponse(
                        content=cached.data, status_code=cached.status_code
                    )
                    response.headers["X-Cache"] = "HIT"
                    response.headers["X-Cache-Key"] = cache_key
                    response.headers["X-Cache-Timestamp"] = (
                        str(cached.timestamp)
                    )
                    return response

                logger.info(f"💨 Cache MISS: {cache_key}")

                # Cache miss - process request
                response = await call_next(request)

                # Cache the response if it's successful
                if response.status_code >= 200 and response.status_code < 300:
                    try:
                        # Read response body
                        body = b""
                        async for chunk in response.body_iterator:
                            body += chunk

                        # Parse JSON response if available
                        try:
                            data = json.loads(body.decode()) if body else {}
                            await cache_manager.set(
                                cache_key, data, response.status_code, options.ttl
                            )
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            # Not JSON, skip caching
                            pass

                        # Recreate response with body
                        response = JSONResponse(
                            content=json.loads(body.decode()) if body else {},
                            status_code=response.status_code,
                            headers=dict(response.headers),
                        )

                        response.headers["X-Cache"] = "MISS"
                        response.headers["X-Cache-Key"] = cache_key
                    except Exception as error:
                        logger.error(f"❌ Failed to cache response: {error}")
                        # Return original response if caching fails
                        response.headers["X-Cache"] = "MISS"
                        response.headers["X-Cache-Key"] = cache_key

                return response
            except Exception as error:
                logger.error(f"❌ Cache middleware error: {error}")
                return await call_next(request)

    return CacheMiddlewareInstance


# Predefined cache middleware configurations
def portfolio_cache():
    """Portfolio cache middleware"""
    return cache_middleware(
        CacheOptions(
            key_prefix="portfolio", ttl=180, include_user=True, include_query=True
        )
    )


def market_cache():
    """Market cache middleware"""
    return cache_middleware(
        CacheOptions(
            key_prefix="market",
            ttl=60,
            include_query=True,
            exclude_params=["timestamp", "_t"],
        )
    )


def history_cache():
    """History cache middleware"""
    return cache_middleware(
        CacheOptions(
            key_prefix="history", ttl=300, include_user=True, include_query=True
        )
    )


def company_cache():
    """Company cache middleware"""
    return cache_middleware(
        CacheOptions(key_prefix="company", ttl=1800, include_query=True)
    )


async def clear_trade_related_cache(user_id: str, symbol: Optional[str] = None) -> None:
    """Clear cache after trade execution"""
    try:
        logger.info(
            f"🧹 Clearing trade-related cache for user {user_id}{f' and symbol {symbol}' if symbol else ''}"
        )

        patterns = [
            f"portfolio:*user:{user_id}*",
            f"history:*user:{user_id}*",
        ]

        if symbol:
            patterns.append(f"market:*{symbol}*")

        total_deleted = 0
        for pattern in patterns:
            deleted = await cache_manager.delete_pattern(pattern)
            total_deleted += deleted

        logger.info(f"✅ Cleared {total_deleted} cache entries after trade execution")
    except Exception as error:
        logger.error(f"❌ Error clearing trade-related cache: {error}")


async def clear_market_cache() -> None:
    """Clear all market data cache"""
    try:
        logger.info("🧹 Clearing all market cache")
        deleted = await cache_manager.delete_pattern("market:*")
        logger.info(f"✅ Cleared {deleted} market cache entries")
    except Exception as error:
        logger.error(f"❌ Error clearing market cache: {error}")


async def clear_user_cache(user_id: str) -> None:
    """Clear cache for a specific user"""
    try:
        logger.info(f"🧹 Clearing cache for user {user_id}")
        patterns = [
            f"portfolio:*user:{user_id}*",
            f"history:*user:{user_id}*",
        ]

        total_deleted = 0
        for pattern in patterns:
            deleted = await cache_manager.delete_pattern(pattern)
            total_deleted += deleted

        logger.info(f"✅ Cleared {total_deleted} cache entries for user {user_id}")
    except Exception as error:
        logger.error(f"❌ Error clearing user cache: {error}")

