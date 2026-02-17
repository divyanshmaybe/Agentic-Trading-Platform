"""
MCP client for loading tools from quant-stream MCP server.

This module uses fastmcp.Client to connect to the MCP server with support for:
- HTTP Transport (Streamable): Connect to HTTP server (default)
- Stdio transport: Connect to a local script
- Auto-detection based on server string format
"""

from dataclasses import asdict, is_dataclass
from typing import Optional, Any
import logging

from fastmcp import Client
logger = logging.getLogger(__name__)

DEFAULT_SERVER = "http://127.0.0.1:6969/mcp"

def _normalize_result(value: Any) -> Any:
    """Convert FastMCP responses (including dataclasses) into plain Python types."""
    if value is None:
        return None
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: _normalize_result(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_normalize_result(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_result(item) for item in value)
    return value


async def create_mcp_tools(server: Optional[str] = None):
    """Create and load MCP tools from quant-stream server.
    
    Auto-detects connection type based on server string:
    - HTTP/HTTPS URL: SSE transport (e.g., "http://localhost:8000/mcp")
    - File path: Stdio transport (e.g., "./server.py")
    - None: Default HTTP to quant_stream MCP server
    
    Args:
        server: Server specification - URL for SSE, path for stdio, or None for default
        
    Returns:
        List of LangChain tools loaded from MCP server
        
    Examples:
        # Default HTTP connection
        tools_info = await create_mcp_tools()

        # Custom SSE connection
        tools_info = await create_mcp_tools("http://localhost:8000/mcp")

        # Custom stdio script
        tools_info = await create_mcp_tools("./my_server.py")
    """
    if server is None:
        server = DEFAULT_SERVER

    async with Client(server) as client:
        await client.ping()
        tool_list = await client.list_tools()

        tool_names = [tool.name for tool in tool_list]
        logger.info(
            "Connected to MCP server %s. Available tools: %s",
            server,
            ", ".join(tool_names),
        )

        return {"server": server, "tools": tool_names}


async def call_mcp_tool(
    server: str,
    tool_name: str,
    arguments: Optional[dict] = None,
):
    """Invoke an MCP tool using a fresh client connection."""
    async with Client(server) as client:
        raw_result = await client.call_tool(tool_name, arguments or {})

        # Prefer rich data attribute if available and meaningful
        if hasattr(raw_result, "data") and getattr(raw_result, "data") is not None:
            normalized_data = _normalize_result(raw_result.data)
            # FastMCP often wraps outputs as dataclasses whose fields may be empty.
            if isinstance(normalized_data, dict) and "result" in normalized_data:
                inner = normalized_data["result"]
                if inner not in (None, {}, []):
                    return inner
                # Otherwise fall through to inspect structured/text content
            elif normalized_data not in (None, {}, []):
                return normalized_data

        # Structured content (dict/list) returned by FastMCP
        structured = getattr(raw_result, "structured_content", None)
        if structured:
            normalized_structured = _normalize_result(structured)
            if isinstance(normalized_structured, dict) and "result" in normalized_structured:
                inner = normalized_structured["result"]
                if inner not in (None, {}, []):
                    return inner
                normalized_structured = inner

            if normalized_structured not in (None, {}, []):
                return normalized_structured
            # If structured content is empty, continue to inspect raw text

        # Fallback to text content blocks (JSON or plain text)
        content_blocks = getattr(raw_result, "content", None)
        if content_blocks:
            text_blocks = [
                getattr(block, "text")
                for block in content_blocks
                if hasattr(block, "text") and getattr(block, "text")
            ]
            if text_blocks:
                try:
                    import json

                    return _normalize_result(json.loads(text_blocks[-1]))
                except Exception:
                    return text_blocks[-1]

        return _normalize_result(raw_result)
