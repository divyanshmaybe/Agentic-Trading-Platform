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


@celery_app.task(bind=True, name="pipeline.start", autoretry_for=(Exception,), retry_backoff=True)
def start_nse_pipeline(self) -> None:
    """Celery task that runs the NSE pipeline indefinitely."""
    server_dir = Path(__file__).resolve().parents[1]
    service = PipelineService(str(server_dir), logger=task_logger)
    service.run_nse_pipeline_forever()


@celery_app.task(
    bind=True,
    name="pipeline.news_sentiment.run",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_news_sentiment_pipeline(self, top_k: int | None = None) -> dict:
    """Celery task that runs the News sentiment pipeline once."""

    server_dir = Path(__file__).resolve().parents[1]
    service = PipelineService(str(server_dir), logger=task_logger)
    top_k_value = top_k or int(os.getenv("NEWS_TOP_K", "3"))
    metadata = service.run_news_sentiment_pipeline(top_k=top_k_value)
    task_logger.info("News sentiment pipeline completed: %s", metadata)
    return metadata


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
