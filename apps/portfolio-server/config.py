"""
Portfolio Server Configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()

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

# Environment
NODE_ENV = os.getenv("NODE_ENV", "development")

