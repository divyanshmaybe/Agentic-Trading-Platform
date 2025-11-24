"""
Kafka consumer for NSE trading signals - backup execution path.

This worker continuously polls the Kafka topic for NSE signals and executes
any trades that weren't already processed by the immediate execution path.

USAGE:
    # Run as Celery beat task (every 10 seconds)
    celery -A celery_app beat
    
    # Or run standalone
    python -m workers.kafka_signal_consumer

ENVIRONMENT:
    KAFKA_SIGNAL_CONSUMER_ENABLED - Enable Kafka consumer (default: false)
    KAFKA_CONSUMER_POLL_INTERVAL - Polling interval in seconds (default: 10)
    KAFKA_CONSUMER_BATCH_SIZE - Max signals to process per batch (default: 10)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from celery_app import celery_app
from services.trade_sizing_service import calculate_trade_execution_jobs
from services.trade_execution_service import TradeExecutionService
from db import get_db_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration
ENABLED = os.getenv("KAFKA_SIGNAL_CONSUMER_ENABLED", "false").lower() in {"1", "true", "yes"}
POLL_INTERVAL = int(os.getenv("KAFKA_CONSUMER_POLL_INTERVAL", "10"))
BATCH_SIZE = int(os.getenv("KAFKA_CONSUMER_BATCH_SIZE", "10"))


async def check_signal_already_executed(signal_id: str) -> bool:
    """Check if a signal has already been executed."""
    try:
        db = get_db_client()
        
        # Check TradeExecutionLog for this signal
        trade = await db.tradeexecutionlog.find_first(
            where={
                "metadata": {
                    "path": ["signal_id"],
                    "equals": signal_id,
                }
            }
        )
        
        return trade is not None
        
    except Exception as e:
        logger.error(f"Failed to check signal execution status: {e}")
        return False  # Assume not executed to be safe


async def process_kafka_signals_batch(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process a batch of signals from Kafka.
    
    Only executes signals that haven't been processed by the immediate path.
    """
    if not signals:
        return {"processed": 0, "skipped": 0, "failed": 0}
    
    logger.info(f"📊 Processing batch of {len(signals)} signals from Kafka")
    
    processed = 0
    skipped = 0
    failed = 0
    
    for signal in signals:
        try:
            signal_id = signal.get("signal_id") or signal.get("filing_time", "unknown")
            
            # Check if already executed
            already_executed = await check_signal_already_executed(signal_id)
            if already_executed:
                logger.debug(f"⏭️ Signal {signal_id} already executed, skipping")
                skipped += 1
                continue
            
            # Execute using direct Python (same as immediate path)
            logger.info(f"🔄 Executing missed signal: {signal_id}")
            
            # Convert signal to request format
            request = {
                "request_id": signal_id,
                "payload": signal,
            }
            
            jobs = calculate_trade_execution_jobs([request], logger=logger)
            
            if not jobs:
                logger.warning(f"⚠️ No actionable jobs for signal {signal_id}")
                skipped += 1
                continue
            
            # Execute trade
            db = get_db_client()
            trade_service = TradeExecutionService(db, logger=logger)
            
            for job in jobs:
                result = await trade_service.execute_trade_direct(job)
                logger.info(f"✅ Executed trade from Kafka backup: {result}")
            
            processed += 1
            
        except Exception as e:
            logger.error(f"❌ Failed to process signal: {e}", exc_info=True)
            failed += 1
    
    summary = {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "total": len(signals),
    }
    
    logger.info(f"📊 Kafka batch summary: {summary}")
    return summary


@celery_app.task(
    bind=True,
    name="kafka.consume_nse_signals",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def consume_kafka_signals_task(self) -> Dict[str, Any]:
    """
    Celery task to poll Kafka and execute missed signals.
    
    This runs periodically (via Celery Beat) to catch any signals
    that weren't processed by the immediate execution path.
    """
    if not ENABLED:
        logger.debug("Kafka signal consumer disabled")
        return {"enabled": False}
    
    try:
        from kafka_service import default_kafka_bus
        
        # Get consumer (create if doesn't exist)
        topic = os.getenv("KAFKA_SIGNAL_TOPIC", "nse_trading_signals")
        consumer_group = "nse_trade_execution_backup"
        
        # Poll for messages
        logger.debug(f"Polling Kafka topic '{topic}' for up to {BATCH_SIZE} messages")
        
        # TODO: Implement actual Kafka polling
        # For now, return empty result
        # In production, you'd use:
        # messages = consumer.poll(timeout_ms=1000, max_records=BATCH_SIZE)
        
        messages = []  # Placeholder
        
        if not messages:
            logger.debug("No new messages from Kafka")
            return {"processed": 0, "skipped": 0, "failed": 0}
        
        # Process messages
        result = asyncio.run(process_kafka_signals_batch(messages))
        return result
        
    except Exception as e:
        logger.error(f"Kafka consumer task failed: {e}", exc_info=True)
        raise


# Add to Celery Beat schedule in celery_app.py:
# if KAFKA_SIGNAL_CONSUMER_ENABLED:
#     celery_app.conf.beat_schedule["kafka-nse-signals-consumer"] = {
#         "task": "kafka.consume_nse_signals",
#         "schedule": POLL_INTERVAL,
#         "options": {"queue": "default"},
#     }
