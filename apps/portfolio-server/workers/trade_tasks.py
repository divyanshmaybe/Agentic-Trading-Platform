from __future__ import annotations

import asyncio
import logging
import os
import sys

from celery_app import celery_app

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
SHARED_PY_PATH = os.path.join(PROJECT_ROOT, "shared/py")
if SHARED_PY_PATH not in sys.path:
    sys.path.insert(0, SHARED_PY_PATH)

PORTFOLIO_SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PORTFOLIO_SERVER_ROOT not in sys.path:
    sys.path.insert(0, PORTFOLIO_SERVER_ROOT)

from db_context import get_db_connection

from services.trade_engine import TradeEngine

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="trading.process_pending_trade",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def process_pending_trade(self, trade_id: str) -> bool:
    """Process a pending trade using asyncio.run for proper event loop management."""
    return asyncio.run(_process_pending_trade_async(trade_id))


async def _process_pending_trade_async(trade_id: str) -> bool:
    async with get_db_connection() as client:
        engine = TradeEngine(client)

        try:
            executed = await engine.process_pending_trade(trade_id)
            if executed:
                logger.info("✅ Executed pending trade %s", trade_id)
            else:
                logger.debug("⌛ Trade %s not ready for execution", trade_id)
            return executed
        except Exception:
            logger.exception("Failed to process pending trade %s", trade_id)
            raise
