#!/usr/bin/env python
"""
Lightweight health check that validates Celery workers can talk to Redis (broker/result)
and PostgreSQL before reporting ready. The script intentionally keeps dependencies to
the standard library to avoid import overhead inside probes.
"""

from __future__ import annotations

import os
import socket
import sys
from contextlib import closing
from urllib.parse import urlparse


def _check_endpoint(url: str, default_port: int) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port

    with closing(socket.create_connection((host, port), timeout=3)):
        return


def main() -> int:
    redis_url = os.getenv("CELERY_BROKER_URL") or "redis://localhost:6379/0"
    result_url = os.getenv("CELERY_RESULT_BACKEND") or redis_url
    database_url = os.getenv("DATABASE_URL", "postgresql://localhost:5432/postgres")

    try:
        _check_endpoint(redis_url, 6379)
        _check_endpoint(result_url, 6379)
        _check_endpoint(database_url, 5432)
    except OSError as exc:  # pragma: no cover - probe script
        print(f"celery healthcheck failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

