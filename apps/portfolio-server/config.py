"""
Portfolio Server Configuration
"""

import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "../.."))

# Load environment variables from repo root first, then app-specific overrides
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=False)
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

load_dotenv()  # Fallback to default resolution in case a different cwd supplies vars

# Server Configuration
PORT = int(os.getenv("PORT", "8000"))
SERVICE_NAME = "Portfolio Server"

# Allowed Origins for CORS
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001"
).split(",")

# Pipeline Configuration
NSE_PIPELINE_DIR = os.path.join(
    os.path.dirname(__file__), "pipelines/nse"
)
NSE_REFRESH_INTERVAL = int(os.getenv("NSE_REFRESH_INTERVAL", "60"))
NEWS_FETCH_RATE = int(os.getenv("NEWS_FETCH_RATE", "3600"))
NEWS_TOP_K = int(os.getenv("NEWS_TOP_K", "3"))

# Environment
NODE_ENV = os.getenv("NODE_ENV", "development")

# Portfolio Constraints
DEFAULT_PORTFOLIO_CASH = os.getenv("DEFAULT_PORTFOLIO_CASH", "100000")
MAX_TRADE_VALUE = os.getenv("MAX_TRADE_VALUE", "50000")
MAX_POSITION_VALUE = os.getenv("MAX_POSITION_VALUE", "100000")

# Production Trading Settings
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}
ANGELONE_TRADING_ENABLED = os.getenv("ANGELONE_TRADING_ENABLED", "false").lower() in {"1", "true", "yes"}

# Short Selling Configuration
SHORT_SELL_AUTO_CLOSE_MINUTES = int(os.getenv("SHORT_SELL_AUTO_CLOSE_MINUTES", "15"))
MARKET_CLOSE_SELL_ENABLED = os.getenv("MARKET_CLOSE_SELL_ENABLED", "true").lower() in {"1", "true", "yes"}

