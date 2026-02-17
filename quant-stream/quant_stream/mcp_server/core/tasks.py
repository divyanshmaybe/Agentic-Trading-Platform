"""Celery tasks for background processing."""

from typing import Dict, Any
import traceback

from celery import Task
from celery.utils.log import get_task_logger

from quant_stream.mcp_server.core.celery_config import celery_app

logger = get_task_logger(__name__)


class CallbackTask(Task):
    """Base task class with callbacks for status updates."""
    
    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        logger.info(f"Task {task_id} completed successfully")
        return super().on_success(retval, task_id, args, kwargs)
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails."""
        logger.error(f"Task {task_id} failed: {exc}")
        return super().on_failure(exc, task_id, args, kwargs, einfo)
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is retried."""
        logger.warning(f"Task {task_id} retrying: {exc}")
        return super().on_retry(exc, task_id, args, kwargs, einfo)


@celery_app.task(
    bind=True,
    base=CallbackTask,
    name="quant_stream.mcp_server.core.tasks.run_workflow_task",
    max_retries=3,
    default_retry_delay=60,
)
def run_workflow_task(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Background task for running workflow.
    
    Args:
        request_data: RunWorkflowRequest as dict
        
    Returns:
        RunWorkflowResponse as dict
    """
    try:
        from quant_stream.mcp_server.tools.workflow import run_ml_workflow_sync
        
        # Execute tool - print statements will show progress
        result = run_ml_workflow_sync(request_data)
        
        # Update progress
        self.update_state(
            state="PROCESSING",
            meta={"status": "Workflow complete", "progress": 100}
        )
        
        logger.info("Workflow completed successfully")
        
        # Return result as dict
        return result
        
    except Exception as e:
        logger.exception(f"Workflow failed: {e}")
        # Return error response
        return {
            "success": False,
            "metrics": {},
            "run_info": {},
            "error": f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}",
        }

