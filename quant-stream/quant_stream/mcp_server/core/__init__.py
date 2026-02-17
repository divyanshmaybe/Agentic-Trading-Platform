"""Core functionality for MCP server."""

# Lazy imports to make celery optional
def __getattr__(name):
    if name == "AppContext":
        from quant_stream.mcp_server.core.context import AppContext
        return AppContext
    elif name == "app_lifespan":
        from quant_stream.mcp_server.core.context import app_lifespan
        return app_lifespan
    elif name == "celery_app":
        try:
            from quant_stream.mcp_server.core.celery_config import celery_app
            return celery_app
        except ImportError:
            raise ImportError(
                "Celery is not installed. Install with: pip install celery redis\n"
                "Celery is optional - MCP server can run workflows synchronously without it."
            )
    elif name == "get_celery_app":
        def _get_celery():
            try:
                from quant_stream.mcp_server.core.celery_config import celery_app
                return celery_app
            except ImportError:
                raise ImportError("Celery not available")
        return _get_celery
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["AppContext", "app_lifespan", "get_celery_app"]
