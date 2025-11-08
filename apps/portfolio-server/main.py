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
from routes.market_routes import router as market_router
from routes.portfolio_routes import router as portfolio_router
from routes.trade_routes import router as trade_router
from utils.pipeline_utils import get_pipeline_status
from workers.pipeline_tasks import start_nse_pipeline, run_news_sentiment_pipeline

# Get server directory for pipelines
server_dir = os.path.dirname(__file__)

# Initialize services
pipeline_service = PipelineService(server_dir, None)

# Create custom lifespan to start NSE pipeline and Angel One token generation
def create_lifespan(base_app_instance, pipeline_service_instance):
    """Create lifespan context manager with pipeline startup"""
    @asynccontextmanager
    async def lifespan_with_pipeline(app: FastAPI):
        """Application lifespan with NSE pipeline and Angel One token generation"""
        # Run base startup
        await base_app_instance._startup()
        
        # Start Angel One token map generation (async via Celery)
        if os.getenv("MARKET_DATA_PROVIDER", "").lower() in {"angelone", "angel", "smartapi"}:
            try:
                from workers.angelone_token_task import generate_angelone_tokens_task
                base_app_instance.logger.info("🚀 Dispatching Angel One token map generation to Celery...")
                token_task = generate_angelone_tokens_task.delay(force_refresh=False)
                base_app_instance.logger.info(
                    "✓ Angel One token task dispatched (task_id=%s)", token_task.id
                )
            except Exception as exc:
                base_app_instance.logger.warning(
                    "Failed to dispatch Angel One token task: %s (will use fallback)", exc
                )
        
        # Start NSE pipeline via Celery task
        app.state.pipeline_status = "initializing"
        app.state.pipeline_job_id = None
        app.state.news_pipeline_job_id = None

        try:
            base_app_instance.logger.info("Dispatching NSE pipeline task to Celery...")
            task_result = start_nse_pipeline.delay()
            app.state.pipeline_job_id = task_result.id
            app.state.pipeline_status = "queued"
            base_app_instance.logger.info(
                "✓ NSE pipeline task dispatched (task_id=%s)", task_result.id
            )
        except Exception as exc:  # pragma: no cover - defensive
            app.state.pipeline_job_id = None
            app.state.pipeline_status = "error"
            base_app_instance.logger.exception(
                "Failed to dispatch NSE pipeline task: %s", exc
            )

        # Dispatch news sentiment pipeline once at startup (Celery beat handles subsequent runs)
        try:
            base_app_instance.logger.info("Dispatching news sentiment pipeline task to Celery...")
            news_task = run_news_sentiment_pipeline.delay()
            app.state.news_pipeline_job_id = news_task.id
            base_app_instance.logger.info(
                "✓ News sentiment pipeline task dispatched (task_id=%s)", news_task.id
            )
        except Exception as exc:  # pragma: no cover - defensive
            app.state.news_pipeline_job_id = None
            base_app_instance.logger.exception(
                "Failed to dispatch news sentiment pipeline task: %s", exc
            )
        
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
base_app.add_routes("/api", trade_router)
base_app.add_routes("/api", market_router)
base_app.add_routes("/api", portfolio_router)
base_app.add_routes("", create_health_routes(pipeline_service, server_dir))

# Override root endpoint
@base_app.app.get("/")
async def root():
    """Root endpoint"""
    pipeline_status = getattr(base_app.app.state, "pipeline_status", "unknown")
    pipeline_job_id = getattr(base_app.app.state, "pipeline_job_id", None)
    status_payload = get_pipeline_status(
        server_dir,
        pipeline_status,
        pipeline_job_id,
    )
    return {
        "message": f"Welcome to {SERVICE_NAME}",
        "version": "1.0.0",
        "docs": "/docs",
        "pipeline": status_payload,
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

