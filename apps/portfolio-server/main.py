"""
Portfolio Server - FastAPI server with NSE pipeline integration
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add shared directory to path
project_root = os.path.join(os.path.dirname(__file__), "../..")
shared_py_path = os.path.join(project_root, "shared/py")
middleware_py_path = os.path.join(project_root, "middleware/py")

sys.path.insert(0, shared_py_path)
sys.path.insert(0, middleware_py_path)

from baseApp import BaseApp
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Add current directory to path for local imports
sys.path.insert(0, os.path.dirname(__file__))

from config import PORT, SERVICE_NAME, ALLOWED_ORIGINS
from services.pipeline_service import PipelineService
from routes.pipeline_routes import create_pipeline_routes, create_health_routes

# Get server directory for pipelines
server_dir = os.path.dirname(__file__)

# Initialize services
pipeline_service = PipelineService(server_dir, None)

# Create custom lifespan to start NSE pipeline
def create_lifespan(base_app_instance, pipeline_service_instance):
    """Create lifespan context manager with pipeline startup"""
    @asynccontextmanager
    async def lifespan_with_pipeline(app: FastAPI):
        """Application lifespan with NSE pipeline startup"""
        # Run base startup
        await base_app_instance._startup()
        
        # Start NSE pipeline
        base_app_instance.logger.info("Starting NSE pipeline...")
        pipeline_thread = pipeline_service_instance.start_nse_pipeline()
        app.state.pipeline_thread = pipeline_thread
        base_app_instance.logger.info("✓ NSE pipeline started in background thread")
        
        yield
        
        # Shutdown
        await base_app_instance._shutdown()
    
    return lifespan_with_pipeline

# Initialize BaseApp
base_app = BaseApp(
    name=SERVICE_NAME,
    version="1.0.0",
    custom_lifespan=None,  # Will be set after creation
    custom_cors={
        "allow_origins": ALLOWED_ORIGINS,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "x-api-key"],
    },
)

# Create and set custom lifespan
lifespan_func = create_lifespan(base_app, pipeline_service)
base_app.app.router.lifespan_context = lifespan_func

# Update pipeline service logger
pipeline_service.logger = base_app.logger

# Initialize error handling
base_app.initialize_error_handling()

# Setup routes
base_app.add_routes("/api/pipeline", create_pipeline_routes(pipeline_service, server_dir))
base_app.add_routes("", create_health_routes(pipeline_service, server_dir))

# Override root endpoint
@base_app.app.get("/")
async def root():
    """Root endpoint"""
    pipeline_running = (
        hasattr(base_app.app.state, "pipeline_thread")
        and base_app.app.state.pipeline_thread.is_alive()
    )
    return {
        "message": f"Welcome to {SERVICE_NAME}",
        "version": "1.0.0",
        "docs": "/docs",
        "pipeline": {
            "running": pipeline_running,
            "status": "active" if pipeline_running else "stopped",
        },
    }

# Export app for uvicorn
app = base_app.app

# Start server
async def start_server():
    """Start the server"""
    await base_app.start(port=PORT)


if __name__ == "__main__":
    import asyncio
    import signal
    
    async def shutdown_handler():
        """Handle shutdown signals"""
        await base_app.shutdown()
    
    def signal_handler(sig, frame):
        """Signal handler for graceful shutdown"""
        asyncio.create_task(shutdown_handler())
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        asyncio.run(base_app.shutdown())

