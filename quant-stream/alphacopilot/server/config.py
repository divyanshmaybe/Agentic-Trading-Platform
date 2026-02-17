"""Configuration for alphacopilot server."""

import os
from pathlib import Path

# Database configuration
DATABASE_DIR = Path(os.getenv("ALPHACOPILOT_DB_DIR", ".data"))
DATABASE_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_PATH = DATABASE_DIR / "alphacopilot.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Server configuration
HOST = os.getenv("ALPHACOPILOT_HOST", "0.0.0.0")
PORT = int(os.getenv("ALPHACOPILOT_PORT", "8069"))

# Long polling configuration
DEFAULT_POLL_TIMEOUT = int(os.getenv("ALPHACOPILOT_POLL_TIMEOUT", "30"))
MAX_POLL_TIMEOUT = int(os.getenv("ALPHACOPILOT_MAX_POLL_TIMEOUT", "300"))

