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
