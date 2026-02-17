"""Application context and lifespan management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from celery import Celery

from quant_stream.mcp_server.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Application context with typed dependencies."""
    
    celery_app: Optional["Celery"]  # Optional - only if celery is installed
    config: Any  # Config object


@asynccontextmanager
async def app_lifespan(server: "FastMCP") -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context.
    
    This handles:
    - Loading configuration
    - Initializing Celery connection (if available)
    - Cleanup on shutdown
    """
    logger.info("Starting MCP server initialization...")
    
    # Load configuration
    config = get_config()
    
    # Try to initialize Celery app (optional)
    celery_app = None
    try:
        from quant_stream.mcp_server.core.celery_config import celery_app as _celery_app
        celery_app = _celery_app
        logger.info(f"✓ Celery connected to Redis at {config.redis.host}:{config.redis.port}")
        logger.info("  Async job execution enabled")
    except ImportError as e:
        logger.warning("⚠ Celery not available - workflows will run synchronously")
        logger.warning(f"  Install with: uv sync --group mcp")
        logger.warning(f"  Error: {e}")
    
    logger.info(f"Data path: {config.quantstream.data_path}")
    
    try:
        yield AppContext(
            celery_app=celery_app,
            config=config
        )
    finally:
        logger.info("Shutting down MCP server...")

