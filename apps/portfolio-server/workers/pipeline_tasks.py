from __future__ import annotations

import os
import sys
from pathlib import Path

from celery.utils.log import get_task_logger

from celery_app import celery_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

from services.pipeline_service import PipelineService  # type: ignore  # noqa: E402

task_logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="pipeline.start",
    autoretry_for=(Exception,),
    retry_backoff=True,
    # Prevent concurrent execution
    acks_late=True,
    reject_on_worker_lost=True,
)
def start_nse_pipeline(self) -> None:
    """Celery task that runs the NSE pipeline indefinitely."""
    import os
    import psutil
    from redis import Redis
    from celery_app import BROKER_URL
    
    # Redis-based lock to prevent concurrent execution
    redis_client = Redis.from_url(BROKER_URL)
    lock_key = "pipeline:nse:lock"
    pid_key = "pipeline:nse:pid"
    current_pid = os.getpid()
    
    # Check if lock exists and if the process is still alive
    lock_value = redis_client.get(lock_key)
    if lock_value:
        stored_pid = redis_client.get(pid_key)
        if stored_pid:
            try:
                stored_pid = int(stored_pid.decode())
                # Check if the process is actually running
                if psutil.pid_exists(stored_pid):
                    try:
                        process = psutil.Process(stored_pid)
                        # Check if it's actually the NSE pipeline (heuristic: check cmdline)
                        cmdline = ' '.join(process.cmdline()) if process.cmdline() else ''
                        if 'pipeline' in cmdline.lower() or 'celery' in cmdline.lower():
                            ttl = redis_client.ttl(lock_key)
                            task_logger.warning(
                                "NSE pipeline already running (PID: %s, lock TTL: %s seconds), aborting this instance. "
                                "To clear stale lock, run: python scripts/check_nse_lock.py --clear",
                                stored_pid, ttl
                            )
                            return
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        # Process doesn't exist or can't access - stale lock
                        task_logger.warning(
                            "Stale NSE pipeline lock detected (PID %s not running). Clearing lock...",
                            stored_pid
                        )
                        redis_client.delete(lock_key)
                        redis_client.delete(pid_key)
                else:
                    # PID doesn't exist - stale lock
                    task_logger.warning(
                        "Stale NSE pipeline lock detected (PID %s not found). Clearing lock...",
                        stored_pid
                    )
                    redis_client.delete(lock_key)
                    redis_client.delete(pid_key)
            except (ValueError, AttributeError):
                # Invalid PID format - clear stale lock
                task_logger.warning("Invalid PID in lock, clearing stale lock...")
                redis_client.delete(lock_key)
                redis_client.delete(pid_key)
        else:
            # Lock exists but no PID - might be stale, but check TTL first
            ttl = redis_client.ttl(lock_key)
            if ttl and ttl > 3600:  # If lock is very new (< 1 hour), don't auto-clear
                task_logger.warning(
                    "NSE pipeline lock exists without PID (TTL: %s seconds). Clearing if stale...",
                    ttl
                )
                # Only clear if lock is old (likely stale)
                if ttl < 86400 - 300:  # Less than 24 hours - 5 minutes = likely stale
                    redis_client.delete(lock_key)
    
    # Try to acquire lock
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=86400)  # 24 hour TTL
    
    if not lock_acquired:
        ttl = redis_client.ttl(lock_key)
        task_logger.warning(
            "NSE pipeline lock still exists (TTL: %s seconds), aborting this instance. "
            "To clear stale lock, run: python scripts/check_nse_lock.py --clear",
            ttl
        )
        return
    
    # Store PID with lock
    redis_client.set(pid_key, str(current_pid), ex=86400)
    task_logger.info("✅ NSE pipeline lock acquired (PID: %s) - starting pipeline...", current_pid)
    
    try:
        server_dir = Path(__file__).resolve().parents[1]
        service = PipelineService(str(server_dir), logger=task_logger)
        task_logger.info("🚀 Launching NSE pipeline (polling, downloading PDFs, generating signals)...")
        service.run_nse_pipeline_forever()
    except KeyboardInterrupt:
        task_logger.info("🛑 NSE pipeline stopped by user (KeyboardInterrupt)")
        raise
    except Exception as e:
        task_logger.error("❌ NSE pipeline crashed: %s", e, exc_info=True)
        raise
    finally:
        # Release lock when pipeline stops
        redis_client.delete(lock_key)
        redis_client.delete(pid_key)
        task_logger.info("🔒 NSE pipeline lock released (PID: %s)", current_pid)


@celery_app.task(
    bind=True,
    name="pipeline.news_sentiment.run",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    # Prevent concurrent execution - only one instance can run at a time
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_news_sentiment_pipeline(self, top_k: int | None = None) -> dict:
    """Celery task that runs the News sentiment pipeline once."""
    import os
    import psutil
    from redis import Redis
    from celery_app import BROKER_URL
    
    # Redis-based lock to prevent concurrent execution
    redis_client = Redis.from_url(BROKER_URL)
    lock_key = "pipeline:news_sentiment:lock"
    pid_key = "pipeline:news_sentiment:pid"
    current_pid = os.getpid()
    
    # Check if lock exists and if the process is still alive
    lock_value = redis_client.get(lock_key)
    if lock_value:
        stored_pid = redis_client.get(pid_key)
        if stored_pid:
            try:
                stored_pid = int(stored_pid.decode())
                # Check if the process is actually running
                if psutil.pid_exists(stored_pid):
                    try:
                        process = psutil.Process(stored_pid)
                        # Check if it's actually the news pipeline (heuristic: check cmdline)
                        cmdline = ' '.join(process.cmdline()) if process.cmdline() else ''
                        if 'pipeline' in cmdline.lower() or 'celery' in cmdline.lower():
                            ttl = redis_client.ttl(lock_key)
                            task_logger.warning(
                                "News sentiment pipeline already running (PID: %s, lock TTL: %s seconds), skipping this execution. "
                                "To clear stale lock, run: redis-cli DEL %s %s",
                                stored_pid, ttl, lock_key, pid_key
                            )
                            return {"status": "skipped", "reason": "already_running"}
                    except (psutil.NoProcess, psutil.AccessDenied):
                        # Process doesn't exist or can't access - stale lock
                        task_logger.warning(
                            "Stale news sentiment pipeline lock detected (PID %s not accessible). Clearing lock...",
                            stored_pid
                        )
                        redis_client.delete(lock_key)
                        redis_client.delete(pid_key)
                else:
                    # PID doesn't exist - stale lock
                    task_logger.warning(
                        "Stale news sentiment pipeline lock detected (PID %s not found). Clearing lock...",
                        stored_pid
                    )
                    redis_client.delete(lock_key)
                    redis_client.delete(pid_key)
            except (ValueError, AttributeError):
                # Invalid PID format - clear stale lock
                task_logger.warning("Invalid PID in news sentiment pipeline lock, clearing stale lock...")
                redis_client.delete(lock_key)
                redis_client.delete(pid_key)
        else:
            # Lock exists but no PID - might be stale, but check TTL first
            ttl = redis_client.ttl(lock_key)
            if ttl and ttl > 3600:  # If lock is very new (< 1 hour), don't auto-clear
                task_logger.warning(
                    "News sentiment pipeline lock exists without PID (TTL: %s seconds). Clearing if stale...",
                    ttl
                )
                # Only clear if lock is old (likely stale)
                if ttl < 7200 - 300:  # Less than 2 hours - 5 minutes = likely stale
                    redis_client.delete(lock_key)
    
    # Try to acquire lock
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=7200)  # 2 hour TTL
    
    if not lock_acquired:
        task_logger.warning("News sentiment pipeline lock acquisition failed, skipping this execution")
        return {"status": "skipped", "reason": "lock_acquisition_failed"}
    
    # Store PID with lock
    redis_client.set(pid_key, str(current_pid), ex=7200)
    task_logger.info("✅ News sentiment pipeline lock acquired (PID: %s) - starting pipeline...", current_pid)
    
    try:
        server_dir = Path(__file__).resolve().parents[1]
        service = PipelineService(str(server_dir), logger=task_logger)
        top_k_value = top_k or int(os.getenv("NEWS_TOP_K", "3"))
        metadata = service.run_news_sentiment_pipeline(top_k=top_k_value)
        task_logger.info("✅ News sentiment pipeline completed: %s", metadata)
        return metadata
    finally:
        # Always release the lock and PID
        redis_client.delete(lock_key)
        redis_client.delete(pid_key)
        task_logger.info("News sentiment pipeline lock released")


@celery_app.task(
    bind=True,
    name="pipeline.rebalance.scheduled",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_scheduled_rebalance(self) -> dict:
    """Celery task that performs the scheduled portfolio rebalancing sweep."""

    server_dir = Path(__file__).resolve().parents[1]
    service = PipelineService(str(server_dir), logger=task_logger)
    audit_path = os.getenv("PORTFOLIO_REBALANCE_AUDIT_PATH")
    summary = service.run_scheduled_rebalance(audit_path=audit_path)
    task_logger.info("Scheduled portfolio rebalance completed: %s", summary)
    return summary


@celery_app.task(
    bind=True,
    name="pipeline.risk_monitor.run",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_risk_monitor(self) -> dict:
    """Celery task that runs the risk monitoring pipeline once."""

    server_dir = Path(__file__).resolve().parents[1]
    service = PipelineService(str(server_dir), logger=task_logger)
    summary = service.run_risk_monitoring()
    task_logger.info("Risk monitoring sweep completed: %s", summary)
    return summary


@celery_app.task(
    bind=True,
    name="pipeline.trade_execution.process_signal",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_trade_signal(self, signal_payload: dict) -> dict:
    """Process a single NSE trading signal and enqueue automated trades."""

    server_dir = Path(__file__).resolve().parents[1]
    service = PipelineService(str(server_dir), logger=task_logger)
    summary = service.process_nse_trade_signals([signal_payload])
    task_logger.info("Trade signal processed: %s", summary)
    return summary
