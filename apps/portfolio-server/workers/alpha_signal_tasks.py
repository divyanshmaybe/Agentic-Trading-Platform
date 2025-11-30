"""Celery tasks for alpha signal generation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from celery.utils.log import get_task_logger

from celery_app import celery_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"

if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))
if str(QUANT_STREAM_PATH) not in sys.path:
    sys.path.insert(0, str(QUANT_STREAM_PATH))

task_logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="alpha.generate_daily_signals",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    acks_late=True,
    reject_on_worker_lost=True,
)
def generate_daily_alpha_signals(self) -> Dict[str, Any]:
    """
    Generate daily alpha signals for all active LiveAlphas.
    
    This task runs daily before market open (8:00 AM IST by default).
    
    Process:
    1. Load all active LiveAlpha configurations (status='running')
    2. For each alpha:
       a. Fetch latest market data for configured symbols
       b. Evaluate factor expressions using quant-stream's AlphaEvaluator
       c. Run ML model inference (if configured)
       d. Generate buy/sell signals based on strategy
    3. Publish signals to trade execution pipeline
    """
    import asyncio
    from redis import Redis
    from celery_app import BROKER_URL
    
    # Redis-based lock to prevent concurrent execution
    redis_client = Redis.from_url(BROKER_URL)
    lock_key = "pipeline:alpha_signals:lock"
    pid_key = "pipeline:alpha_signals:pid"
    current_pid = os.getpid()
    
    # Try to acquire lock
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=3600)  # 1 hour TTL
    
    if not lock_acquired:
        task_logger.warning("Alpha signals pipeline lock acquisition failed, skipping this execution")
        return {"status": "skipped", "reason": "lock_acquisition_failed"}
    
    redis_client.set(pid_key, str(current_pid), ex=3600)
    task_logger.info("✅ Alpha signals pipeline lock acquired (PID: %s)", current_pid)
    
    try:
        result = asyncio.run(_generate_signals_async())
        task_logger.info("✅ Alpha signals generation completed: %s", result)
        return result
    except Exception as exc:
        task_logger.error("❌ Alpha signals generation failed: %s", exc, exc_info=True)
        raise
    finally:
        redis_client.delete(lock_key)
        redis_client.delete(pid_key)
        task_logger.info("Alpha signals pipeline lock released")


async def _generate_signals_async() -> Dict[str, Any]:
    """Async implementation of signal generation."""
    from dbManager import DBManager
    from services.alpha_signal_service import AlphaSignalService
    
    # Initialize database
    db_manager = DBManager.get_instance()
    await db_manager.connect()
    
    try:
        client = db_manager.get_client()
        
        # Get all running live alphas
        live_alphas = await client.livealpha.find_many(
            where={"status": "running"}
        )
        
        if not live_alphas:
            task_logger.info("No active live alphas found")
            return {"status": "success", "alphas_processed": 0, "signals_generated": 0}
        
        task_logger.info("Found %d active live alphas to process", len(live_alphas))
        
        # Initialize signal service
        signal_service = AlphaSignalService(client, task_logger)
        
        total_signals = 0
        processed = 0
        errors = []
        
        for alpha in live_alphas:
            try:
                task_logger.info("Processing alpha: %s (%s)", alpha.name, alpha.id)
                
                signals = await signal_service.generate_signals_for_alpha(alpha)
                signal_count = len(signals) if signals else 0
                total_signals += signal_count
                processed += 1
                
                # Update last_signal_at
                if signal_count > 0:
                    await client.livealpha.update(
                        where={"id": alpha.id},
                        data={
                            "last_signal_at": datetime.utcnow(),
                            "total_signals": alpha.total_signals + signal_count,
                        }
                    )
                
                task_logger.info(
                    "Alpha %s generated %d signals",
                    alpha.name, signal_count
                )
                
            except Exception as exc:
                task_logger.error(
                    "Failed to process alpha %s: %s",
                    alpha.id, exc, exc_info=True
                )
                errors.append({"alpha_id": alpha.id, "error": str(exc)})
                
                # Update alpha status to error
                await client.livealpha.update(
                    where={"id": alpha.id},
                    data={"status": "error"}
                )
        
        return {
            "status": "success",
            "alphas_processed": processed,
            "signals_generated": total_signals,
            "errors": errors if errors else None,
        }
        
    finally:
        await db_manager.disconnect()


@celery_app.task(
    bind=True,
    name="alpha.generate_signals_for_alpha",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def generate_signals_for_single_alpha(self, alpha_id: str) -> Dict[str, Any]:
    """
    Generate signals for a specific live alpha.
    
    This can be triggered manually or on-demand.
    """
    import asyncio
    
    try:
        result = asyncio.run(_generate_signals_for_alpha_async(alpha_id))
        return result
    except Exception as exc:
        task_logger.error("Failed to generate signals for alpha %s: %s", alpha_id, exc, exc_info=True)
        raise


async def _generate_signals_for_alpha_async(alpha_id: str) -> Dict[str, Any]:
    """Async implementation for single alpha signal generation."""
    from dbManager import DBManager
    from services.alpha_signal_service import AlphaSignalService
    
    db_manager = DBManager.get_instance()
    await db_manager.connect()
    
    try:
        client = db_manager.get_client()
        
        alpha = await client.livealpha.find_unique(where={"id": alpha_id})
        if not alpha:
            return {"status": "error", "error": "Alpha not found"}
        
        if alpha.status != "running":
            return {"status": "skipped", "reason": f"Alpha status is {alpha.status}"}
        
        signal_service = AlphaSignalService(client, task_logger)
        signals = await signal_service.generate_signals_for_alpha(alpha)
        signal_count = len(signals) if signals else 0
        
        # Update tracking
        if signal_count > 0:
            await client.livealpha.update(
                where={"id": alpha.id},
                data={
                    "last_signal_at": datetime.utcnow(),
                    "total_signals": alpha.total_signals + signal_count,
                }
            )
        
        return {
            "status": "success",
            "alpha_id": alpha_id,
            "signals_generated": signal_count,
        }
        
    finally:
        await db_manager.disconnect()


@celery_app.task(
    bind=True,
    name="alpha.process_signal_batch",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_alpha_signal_batch(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process a batch of alpha signals and convert them to trade execution jobs.
    
    Args:
        signals: List of signal dictionaries with:
            - alpha_id: ID of the live alpha
            - symbol: Stock symbol
            - signal_type: 'buy' or 'sell'
            - quantity: Number of shares
            - confidence: Signal confidence (0-1)
    """
    import asyncio
    
    try:
        result = asyncio.run(_process_signal_batch_async(signals))
        return result
    except Exception as exc:
        task_logger.error("Failed to process signal batch: %s", exc, exc_info=True)
        raise


async def _process_signal_batch_async(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Async implementation for signal batch processing."""
    from dbManager import DBManager
    from services.trade_execution_service import TradeExecutionService
    
    db_manager = DBManager.get_instance()
    await db_manager.connect()
    
    try:
        client = db_manager.get_client()
        trade_service = TradeExecutionService(client, task_logger)
        
        processed = 0
        errors = []
        
        for signal in signals:
            try:
                # Get alpha and its portfolio
                alpha = await client.livealpha.find_unique(
                    where={"id": signal["alpha_id"]}
                )
                if not alpha:
                    errors.append({"signal": signal, "error": "Alpha not found"})
                    continue
                
                # Create trade execution job
                await trade_service.create_alpha_trade(
                    alpha=alpha,
                    symbol=signal["symbol"],
                    signal_type=signal["signal_type"],
                    quantity=signal.get("quantity"),
                    confidence=signal.get("confidence", 1.0),
                )
                processed += 1
                
            except Exception as exc:
                task_logger.error(
                    "Failed to process signal: %s - %s",
                    signal, exc
                )
                errors.append({"signal": signal, "error": str(exc)})
        
        return {
            "status": "success",
            "processed": processed,
            "errors": errors if errors else None,
        }
        
    finally:
        await db_manager.disconnect()



