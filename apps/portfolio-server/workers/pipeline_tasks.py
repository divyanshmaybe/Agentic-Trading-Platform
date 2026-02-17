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
    # acks_late=False by default - safe for auto-retry (prevents duplicate executions on worker crash)
    # Prevent concurrent execution - only one instance can run at a time (Redis lock protects this)
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
    
    # Check last run time to avoid re-fetching on restart. We prefer Redis but fall back to a persisted file
    last_run_key = "pipeline:news_sentiment:last_run"
    # Build a persistent file path inside the server directory so this survives restarts
    from pathlib import Path
    from datetime import datetime, timedelta

    server_dir = Path(__file__).resolve().parents[1]
    # Keep persistent data under server_dir/data/pipeline
    persisted_dir = server_dir / "data" / "pipeline"
    persisted_dir.mkdir(parents=True, exist_ok=True)
    last_run_file = persisted_dir / "news_last_run.txt"

    def _parse_iso_or_none(value: str | bytes | None):
        if not value:
            return None
        if isinstance(value, bytes):
            try:
                value = value.decode()
            except Exception:
                return None
        try:
            # strip the literal Z if present since fromisoformat() doesn't accept 'Z'
            if value.endswith("Z"):
                value = value[:-1]
            return datetime.fromisoformat(value)
        except Exception:
            return None

    last_run_time = redis_client.get(last_run_key)
    last_run = _parse_iso_or_none(last_run_time)

    if not last_run and last_run_file.exists():
        # Fall back to file-based timestamp if Redis missed it
        try:
            last_run = _parse_iso_or_none(last_run_file.read_text())
        except Exception:
            last_run = None

    if last_run:
        time_since_last_run = datetime.utcnow() - last_run
        # If last run was less than 30 minutes ago, skip
        if time_since_last_run < timedelta(minutes=30):
            task_logger.info(
                "News sentiment pipeline last ran %s ago (less than 30 minutes), skipping fetch",
                time_since_last_run,
            )
            redis_client.delete(lock_key)
            redis_client.delete(pid_key)
            return {"status": "skipped", "reason": "too_soon", "last_run": last_run.isoformat()}
    
    try:
        server_dir = Path(__file__).resolve().parents[1]
        service = PipelineService(str(server_dir), logger=task_logger)
        top_k_value = top_k or int(os.getenv("NEWS_TOP_K", "3"))
        metadata = service.run_news_sentiment_pipeline(top_k=top_k_value)
        
        # Store last run time (persist to both Redis and local file so restart won't lose it)
        from datetime import datetime
        now_iso = datetime.utcnow().isoformat()
        redis_client.set(last_run_key, now_iso, ex=86400)  # 24 hour TTL
        try:
            # Persist to local file so the timestamp survives Redis restarts
            last_run_file.write_text(now_iso)
        except Exception:
            task_logger.warning("Failed to persist news pipeline last-run timestamp to file: %s", last_run_file, exc_info=True)
        
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
    retry_backoff_max=30,  # Max backoff 30 seconds
    retry_kwargs={"max_retries": 3},
    # CRITICAL: No rate limit - signals must process immediately for minimal latency
    rate_limit=None,
    # High priority for real-time signal processing
    priority=9,
    # NO TIME LIMITS - trade execution can take time
    soft_time_limit=None,
    time_limit=None,
)
def process_trade_signal(self, signal_payload: dict) -> dict:
    """
    Process NSE trading signal - simplified direct execution.
    
    Flow:
    1. Use PipelineService to calculate jobs (it has all the agent logic)
    2. Jobs are persisted and executed via existing flow
    
    This is simpler and reuses existing tested code.
    """
    from pathlib import Path
    from services.pipeline_service import PipelineService
    
    try:
        task_logger.info("📊 Processing trade signal for: %s", signal_payload.get('symbol'))
        
        server_dir = Path(__file__).resolve().parents[1]
        service = PipelineService(str(server_dir), logger=task_logger)
        
        # Use existing method - it handles everything correctly
        summary = service.process_nse_trade_signals([signal_payload])
        
        task_logger.info("✅ Trade signal processed: %s", summary)
        return summary
        
    except Exception as exc:
        task_logger.error("❌ Failed to process trade signal: %s", exc, exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="pipeline.sell_high_risk_before_close",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,  # Max backoff 60 seconds
    retry_kwargs={"max_retries": 3},
    # Higher priority for market close operations
    priority=8,
)
def sell_high_risk_before_close(self) -> dict:
    """Sell all high_risk agent positions before market close (3:15 PM IST)."""
    import asyncio
    
    server_dir = Path(__file__).resolve().parents[1]
    service = PipelineService(str(server_dir), logger=task_logger)
    
    try:
        result = asyncio.run(service.sell_all_high_risk_positions())
        task_logger.info("High-risk positions sold before market close: %s", result)
        return result
    except Exception as exc:
        task_logger.error("Failed to sell high-risk positions: %s", exc, exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="pipeline.sell_alpha_before_close",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,  # Max backoff 60 seconds
    retry_kwargs={"max_retries": 3},
    # Higher priority for market close operations
    priority=8,
)
def sell_alpha_before_close(self) -> dict:
    """Sell all alpha agent positions before market close (3:20 PM IST).
    
    This runs 5 minutes after high_risk positions are closed to avoid
    overwhelming the trade execution system.
    """
    import asyncio
    
    server_dir = Path(__file__).resolve().parents[1]
    service = PipelineService(str(server_dir), logger=task_logger)
    
    try:
        result = asyncio.run(service.sell_all_alpha_positions())
        task_logger.info("Alpha positions sold before market close: %s", result)
        return result
    except Exception as exc:
        task_logger.error("Failed to sell alpha positions: %s", exc, exc_info=True)
        raise
