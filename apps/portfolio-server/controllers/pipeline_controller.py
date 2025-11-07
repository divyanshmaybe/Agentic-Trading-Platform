"""
Pipeline Controller - Request handlers for pipeline endpoints
"""

from fastapi import Request
from typing import Any, Dict

from services.pipeline_service import PipelineService
from utils.pipeline_utils import get_pipeline_status


class PipelineController:
    """Controller for pipeline-related endpoints"""

    def __init__(self, pipeline_service: PipelineService, server_dir: str):
        self.pipeline_service = pipeline_service
        self.server_dir = server_dir

    async def get_status(self, request: Request) -> Dict[str, Any]:
        """Get pipeline status"""
        pipeline_state = getattr(request.app.state, "pipeline_status", None)
        pipeline_job_id = getattr(request.app.state, "pipeline_job_id", None)
        status = get_pipeline_status(self.server_dir, pipeline_state, pipeline_job_id)

        return {
            "status": "success",
            "data": status,
        }

    async def get_health(self, request: Request) -> Dict[str, Any]:
        """Get health check with pipeline status"""
        pipeline_state = getattr(request.app.state, "pipeline_status", None)
        pipeline_job_id = getattr(request.app.state, "pipeline_job_id", None)
        status = get_pipeline_status(self.server_dir, pipeline_state, pipeline_job_id)

        return {
            "status": "healthy",
            "service": "pipeline-server",
            "version": "1.0.0",
            "pipeline": status,
        }

