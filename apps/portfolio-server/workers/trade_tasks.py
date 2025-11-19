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

from dbManager import DBManager  # type: ignore

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
    # Fix event loop issue in Celery fork pool workers
    # Create a new event loop for each task execution
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        return loop.run_until_complete(_process_pending_trade_async(trade_id))
    finally:
        # Clean up the event loop
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
        except Exception:
            pass


async def _process_pending_trade_async(trade_id: str) -> bool:
    db = DBManager.get_instance()
    if not db.is_connected():
        await db.connect()

    prisma = db.get_client()
    engine = TradeEngine(prisma)

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
