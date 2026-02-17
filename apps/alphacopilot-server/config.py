"""Configuration for alphacopilot server."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from this directory
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # Try root .env as fallback
    _root_env = Path(__file__).resolve().parents[2] / ".env"
    if _root_env.exists():
        load_dotenv(_root_env)

# Server configuration
HOST = os.getenv("ALPHACOPILOT_HOST", "0.0.0.0")
PORT = int(os.getenv("ALPHACOPILOT_PORT", "8069"))

# Database configuration (uses shared Prisma DB via portfolio-server)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://portfolio_user:portfolio_password@localhost:5434/portfolio_db")

# LLM Configuration
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4")

# MCP Server Configuration
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:6969/mcp")

# Long polling configuration
DEFAULT_POLL_TIMEOUT = int(os.getenv("ALPHACOPILOT_POLL_TIMEOUT", "30"))
MAX_POLL_TIMEOUT = int(os.getenv("ALPHACOPILOT_MAX_POLL_TIMEOUT", "300"))

# CORS Configuration
CORS_ORIGINS = os.getenv("ALPHACOPILOT_CORS_ORIGINS", "http://localhost:3000").split(",")

# Redis Configuration (for caching/queues)
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6381"))

# Quant-stream path (symlinked at project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"



