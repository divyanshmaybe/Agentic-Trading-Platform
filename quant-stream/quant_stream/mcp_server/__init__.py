"""MCP Server for quant-stream backtesting engine.

This package exposes quant-stream functionality as Model Context Protocol (MCP) tools
that can be called by AI agents.

Built with FastMCP and Celery for async background processing.

Usage:
    # Run MCP server
    mcp dev quant_stream/mcp_server/app.py

    # Run Celery worker
    celery -A quant_stream.mcp_server.core.celery_app worker --loglevel=info -Q backtest
"""

__version__ = "0.2.0"

# Don't import app by default to avoid circular imports with celery
# from quant_stream.mcp_server.app import mcp
from quant_stream.mcp_server import tools
from quant_stream.mcp_server import schemas
from quant_stream.mcp_server import config
from quant_stream.mcp_server import core

__all__ = ["tools", "schemas", "config", "core", "__version__"]

