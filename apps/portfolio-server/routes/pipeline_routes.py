"""
Pipeline Routes
"""

from fastapi import APIRouter, Depends, Request
from controllers.pipeline_controller import PipelineController
from services.pipeline_service import PipelineService
from utils.auth import get_authenticated_user


def create_pipeline_routes(
    pipeline_service: PipelineService,
    server_dir: str
) -> APIRouter:
    """Create pipeline routes"""
    router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
    
    controller = PipelineController(pipeline_service, server_dir)
    
    @router.get("/status")
    async def get_pipeline_status(
        request: Request,
        _: dict = Depends(get_authenticated_user),
    ):
        """Get pipeline status (requires authentication)"""
        return await controller.get_status(request)

    from pydantic import BaseModel
    class DemoModeRequest(BaseModel):
        enabled: bool

    @router.get("/demo-mode")
    async def get_demo_mode(
        _: dict = Depends(get_authenticated_user),
    ):
        """Get dynamic demo mode status (requires authentication)"""
        return await controller.get_demo_mode()

    @router.post("/demo-mode")
    async def set_demo_mode(
        body: DemoModeRequest,
        _: dict = Depends(get_authenticated_user),
    ):
        """Set dynamic demo mode status (requires authentication)"""
        return await controller.set_demo_mode(body.enabled)
    
    return router


def create_health_routes(
    pipeline_service: PipelineService,
    server_dir: str
) -> APIRouter:
    """Create health check routes"""
    router = APIRouter(tags=["health"])
    
    controller = PipelineController(pipeline_service, server_dir)
    
    @router.get("/health")
    async def health_check(request: Request):
        """Health check endpoint"""
        return await controller.get_health(request)
    
    return router

