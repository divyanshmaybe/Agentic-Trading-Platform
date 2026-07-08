import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Locate the config file in the shared mounted server directory
# Standard path is /app/apps/portfolio-server/demo_mode_override.json
SERVER_DIR = Path(__file__).resolve().parents[1]
OVERRIDE_FILE = SERVER_DIR / "demo_mode_override.json"

def is_demo_mode_enabled() -> bool:
    """
    Check if DEMO_MODE is enabled dynamically.
    1. Checks for demo_mode_override.json file
    2. Falls back to DEMO_MODE env variable
    """
    try:
        if OVERRIDE_FILE.exists():
            with open(OVERRIDE_FILE, "r") as f:
                data = json.load(f)
                override = data.get("demo_mode")
                if override is not None:
                    return bool(override)
    except Exception as e:
        logger.debug(f"Failed to read demo_mode_override.json: {e}")
        
    # Fallback to env var
    return os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}

def set_demo_mode(enabled: bool) -> None:
    """
    Set DEMO_MODE override status in the shared JSON file.
    """
    try:
        with open(OVERRIDE_FILE, "w") as f:
            json.dump({"demo_mode": enabled}, f)
        logger.info(f"💾 Dynamic DEMO_MODE set to: {enabled}")
    except Exception as e:
        logger.error(f"Failed to write demo_mode_override.json: {e}")
        raise
