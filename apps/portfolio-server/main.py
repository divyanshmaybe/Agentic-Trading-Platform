"""
Portfolio Server - FastAPI server with NSE pipeline integration
"""

import sys
import os
import asyncio
from dotenv import load_dotenv

# Load environment variables
if os.getenv("SKIP_DOTENV") != "true":
    load_dotenv()

# Initialize Phoenix tracing (must be done early)
try:
    from phoenix.otel import register
    
    # Configure Phoenix tracer with OTLP endpoint
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="portfolio-server",
            endpoint=collector_endpoint,
            auto_instrument=True
        )
        print(f"✅ Phoenix tracing initialized: {collector_endpoint}")
    else:
        print("⚠️ COLLECTOR_ENDPOINT not set, Phoenix tracing disabled")
except ImportError:
    print("⚠️ Phoenix not installed, tracing disabled")
except Exception as e:
    print(f"⚠️ Failed to initialize Phoenix tracing: {e}")

# Add project root and shared/middleware directories to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
shared_py_path = os.path.join(project_root, "shared/py")
middleware_py_path = os.path.join(project_root, "middleware/py")

# Add project root first so middleware and shared can be imported as top-level packages
sys.path.insert(0, project_root)
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
from routes.objective_routes import create_objective_routes
from routes.trade_routes import router as trade_router
from routes.regime_routes import router as regime_router
from routes.internal_routes import router as internal_router
from routes.alpha_routes import router as alpha_router
from routes.company_routes import router as company_router
from routes.low_risk_routes import router as low_risk_router
from routes.admin_routes import router as admin_router
from routes.observability_routes import router as observability_router
from utils.pipeline_utils import get_pipeline_status
from monitoring.http_metrics import PrometheusMiddleware, metrics_endpoint

# Get server directory for pipelines
server_dir = os.path.dirname(__file__)

# Initialize pipeline service
pipeline_service = PipelineService(server_dir, logger=None)

# Create custom lifespan to start NSE pipeline and Angel One token generation
def create_lifespan(base_app_instance, pipeline_service_instance):
    """Create lifespan context manager with pipeline startup"""
    @asynccontextmanager
    async def lifespan_with_pipeline(app: FastAPI):
        """Application lifespan with NSE pipeline and Angel One token generation"""
        # Run base startup
        await base_app_instance._startup()
        
        # Check if pipelines should run on startup
        news_on_startup = os.getenv("NEWS_PIPELINE_RUN_ON_STARTUP", "true").lower() in {"1", "true", "yes"}
        nse_on_startup = os.getenv("NSE_PIPELINE_RUN_ON_STARTUP", "true").lower() in {"1", "true", "yes"}
        
        # Initialize pipeline status tracking
        app.state.pipeline_status = "not_started"
        app.state.pipeline_job_id = None
        app.state.news_pipeline_job_id = None
        
        # Dispatch news pipeline on startup if configured
        if news_on_startup:
            try:
                from celery_app import celery_app
                base_app_instance.logger.info("🚀 Dispatching news sentiment pipeline at startup...")
                result = celery_app.send_task(
                    "pipeline.news_sentiment.run",
                    queue="news_pipeline",
                    routing_key="news_pipeline"
                )
                app.state.news_pipeline_job_id = result.id
                base_app_instance.logger.info(f"✅ News pipeline started: task_id={result.id}")
            except Exception as exc:
                base_app_instance.logger.error(f"❌ Failed to dispatch news pipeline: {exc}")
        
        # Dispatch NSE pipeline on startup if configured
        if nse_on_startup:
            try:
                from celery_app import celery_app
                base_app_instance.logger.info("🚀 Dispatching NSE pipeline at startup...")
                result = celery_app.send_task(
                    "pipeline.start",
                    queue="nse_pipeline",
                    routing_key="nse_pipeline"
                )
                app.state.pipeline_job_id = result.id
                app.state.pipeline_status = "running"
                base_app_instance.logger.info(f"✅ NSE pipeline started: task_id={result.id}")
            except Exception as exc:
                base_app_instance.logger.error(f"❌ Failed to dispatch NSE pipeline: {exc}")
        
        base_app_instance.logger.info(
            "📋 Pipelines configured. News: hourly via Beat + startup, NSE: continuous polling (60s interval)"
        )
        
        # Run allocation sweep on startup to handle pending portfolios
        allocation_on_startup = os.getenv("ALLOCATION_SWEEP_ON_STARTUP", "true").lower() in {"1", "true", "yes"}
        if allocation_on_startup:
            try:
                from celery_app import celery_app
                base_app_instance.logger.info("🔄 Running regime check and allocation sweep at startup...")
                result = celery_app.send_task(
                    "portfolio.check_regime_and_rebalance",
                    queue="regime",
                    routing_key="regime"
                )
                base_app_instance.logger.info(f"✅ Regime check and allocation sweep started: task_id={result.id}")
            except Exception as exc:
                base_app_instance.logger.error(f"❌ Failed to dispatch regime check and allocation sweep: {exc}")
        
        # Subscribe to Nifty 500 symbols on startup (if enabled)
        nifty500_subscribe = os.getenv("ENABLE_NIFTY500_SUBSCRIPTION", "false").lower() in {"1", "true", "yes"}
        if nifty500_subscribe:
            try:
                base_app_instance.logger.info("📊 Starting Nifty 500 subscription...")
                from market_data import subscribe_nifty500_on_startup  # type: ignore
                # Run in background task
                asyncio.create_task(subscribe_nifty500_on_startup())
                base_app_instance.logger.info("✅ Nifty 500 subscription task started")
            except Exception as exc:
                base_app_instance.logger.error(f"❌ Failed to start Nifty 500 subscription: {exc}")
        
        # Capture portfolio snapshots on startup - DISABLED FOR TESTING
        # These snapshot tasks were interfering with trade execution testing
        snapshot_on_startup = os.getenv("SNAPSHOT_CAPTURE_ON_STARTUP", "false").lower() in {"1", "true", "yes"}
        if snapshot_on_startup:
            try:
                from celery_app import celery_app
                base_app_instance.logger.info("📸 Capturing portfolio snapshots at startup...")
                
                # Dispatch both snapshot tasks
                portfolio_result = celery_app.send_task(
                    "snapshot.capture_portfolio_snapshots",
                    queue="general",
                    routing_key="general"
                )
                agent_result = celery_app.send_task(
                    "snapshot.capture_agent_snapshots",
                    queue="general",
                    routing_key="general"
                )
                
                base_app_instance.logger.info(
                    "✅ Snapshot tasks dispatched: portfolio=%s, agents=%s",
                    portfolio_result.id,
                    agent_result.id,
                )
            except Exception as exc:
                base_app_instance.logger.error("❌ Failed to dispatch snapshot tasks: %s", exc)
        
        # Initialize Regime Classification Service
        try:
            base_app_instance.logger.info("🚀 Initializing Regime Classification Service...")
            from services.regime_service import RegimeService
            regime_service = RegimeService.get_instance()
            app.state.regime_service = regime_service
            base_app_instance.logger.info("✅ Regime Classification Service initialized")
        except Exception as exc:  # pragma: no cover - defensive
            base_app_instance.logger.warning(
                "⚠️ Failed to initialize Regime Service: %s (service will not be available)", exc
            )
            app.state.regime_service = None
        
        # Start streaming risk monitor (real-time position monitoring)
        streaming_risk_enabled = os.getenv("STREAMING_RISK_MONITOR_ENABLED", "true").lower() in {"1", "true", "yes"}
        if streaming_risk_enabled:
            try:
                from celery_app import celery_app
                base_app_instance.logger.info("🚀 Starting streaming risk monitor for real-time alerts...")
                result = celery_app.send_task(
                    "risk.streaming_monitor.start",
                    queue="streaming",
                    routing_key="streaming"
                )
                app.state.streaming_risk_job_id = result.id
                base_app_instance.logger.info(
                    f"✅ Streaming risk monitor started: task_id={result.id} "
                    f"(sub-second alert latency via WebSocket feeds)"
                )
            except Exception as exc:
                base_app_instance.logger.error(f"❌ Failed to start streaming risk monitor: {exc}")
        else:
            base_app_instance.logger.info("⏭️  Streaming risk monitor disabled (using batch mode)")
        
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

# Add Prometheus HTTP metrics middleware
base_app.app.add_middleware(PrometheusMiddleware)

# Add Prometheus metrics endpoint
@base_app.app.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint"""
    return metrics_endpoint()

# Initialize error handling
base_app.initialize_error_handling()

# Setup routes
base_app.add_routes("/api/pipeline", create_pipeline_routes(pipeline_service, server_dir))
base_app.add_routes("/api", trade_router)
base_app.add_routes("/api", market_router)
base_app.add_routes("/api", portfolio_router)
base_app.add_routes("/api", create_objective_routes(pipeline_service))
base_app.add_routes("/api", internal_router)
base_app.add_routes("/api", regime_router)
base_app.add_routes("/api", alpha_router)
base_app.add_routes("/api", company_router)
base_app.add_routes("/api", low_risk_router)
base_app.add_routes("/api", admin_router)
base_app.add_routes("/api", observability_router)
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

