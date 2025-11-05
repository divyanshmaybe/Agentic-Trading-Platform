"""
Pipeline Controller - Request handlers for pipeline endpoints
"""

from fastapi import Request
from typing import Dict, Any
from services.pipeline_service import PipelineService
from utils.pipeline_utils import get_pipeline_status


class PipelineController:
    """Controller for pipeline-related endpoints"""
    
    def __init__(self, pipeline_service: PipelineService, server_dir: str):
        self.pipeline_service = pipeline_service
        self.server_dir = server_dir
    
    async def get_status(self, request: Request) -> Dict[str, Any]:
        """Get pipeline status"""
        pipeline_thread = getattr(request.app.state, "pipeline_thread", None)
        status = get_pipeline_status(self.server_dir, pipeline_thread)
        
        return {
            "status": "success",
            "data": status,
        }
    
    async def get_health(self, request: Request) -> Dict[str, Any]:
        """Get health check with pipeline status"""
        pipeline_thread = getattr(request.app.state, "pipeline_thread", None)
        pipeline_running = (
            pipeline_thread is not None
            and pipeline_thread.is_alive()
        )
        
        return {
            "status": "healthy",
            "service": "pipeline-server",
            "version": "1.0.0",
            "pipeline": {
                "running": pipeline_running,
                "status": "active" if pipeline_running else "stopped",
            },
        }

