"""Entry point for running MCP server as a module."""

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    from quant_stream.mcp_server.app import mcp
    
    logger.info("Starting Quant-Stream MCP Server v0.2.0...")
    logger.info("For background jobs, ensure Redis and Celery worker are running")
    logger.info("Run worker: celery -A quant_stream.mcp_server.core.celery_config:celery_app worker --loglevel=info")
    logger.info("=" * 80)
    logger.info("MCP Server starting on HTTP transport")
    logger.info("=" * 80)
    
    # Run the FastMCP server on HTTP transport
    # Clients can connect via: http://127.0.0.1:6969/mcp
    mcp.run(transport="streamable-http")

