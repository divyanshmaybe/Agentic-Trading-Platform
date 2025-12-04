"""Celery worker entry point.

Run this to start a Celery worker for processing background tasks:

    python -m quant_stream.mcp_server.worker

Or using the celery command directly (from project root):

    celery -A quant_stream.mcp_server.core.celery_config:celery_app worker --loglevel=info
"""

from quant_stream.mcp_server.core import celery_app

if __name__ == "__main__":
    celery_app.start()

