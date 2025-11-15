"""
Base FastAPI Application
Provides common setup and utilities for FastAPI services
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import logging
import os
import sys
import uvicorn
import time
import psutil
from typing import Optional, Dict, Any, Callable
from contextlib import asynccontextmanager

# Add shared/py to path for imports
_shared_py_path = os.path.dirname(os.path.abspath(__file__))
if _shared_py_path not in sys.path:
    sys.path.insert(0, _shared_py_path)

from redisManager import RedisManager
from dbManager import DBManager
from queueManager import QueueManager
from emailService import EmailService
from webSocketServer import WebSocketServer


class BaseApp:
    """Base FastAPI application with common utilities"""

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        custom_lifespan: Optional[Callable] = None,
        custom_cors: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.version = version
        self.custom_lifespan = custom_lifespan
        self.start_time = time.time()
        
        # Initialize managers
        self.redis_manager: Optional[RedisManager] = None
        self.db_manager: Optional[DBManager] = None
        self.queue_manager: Optional[QueueManager] = None
        self.email_service: Optional[EmailService] = None
        self.websocket_server: Optional[WebSocketServer] = None

        # Setup logging
        self._setup_logging()

        # Create FastAPI app
        lifespan_context = custom_lifespan if custom_lifespan else self._lifespan
        self.app = FastAPI(
            title=name,
            version=version,
            docs_url="/docs",
            redoc_url="/redoc",
            lifespan=lifespan_context,
        )

        # Setup middleware
        self._setup_middleware(custom_cors)

        # Setup routes
        self._setup_routes()

        # Error handling will be initialized separately via initialize_error_handling()

    def _setup_logging(self):
        """Setup application logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(self.name)

    def _setup_middleware(self, custom_cors: Optional[Dict[str, Any]] = None):
        """Setup FastAPI middleware"""
        # CORS middleware
        cors_config = custom_cors or {
            "allow_origins": ["*"],
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
        
        self.app.add_middleware(
            CORSMiddleware,
            **cors_config
        )

        # Trusted host middleware (for production)
        if os.getenv("ENV") == "production":
            self.app.add_middleware(
                TrustedHostMiddleware,
                allowed_hosts=["*"]
            )

    def _setup_routes(self):
        """Setup common routes"""
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint with Prometheus-style metrics"""
            # Get memory usage
            memory_info = psutil.virtual_memory()
            process = psutil.Process()
            process_memory = process.memory_info()
            
            return {
                "status": "OK",
                "service": self.name,
                "version": self.version,
                "timestamp": time.time(),
                "uptime": time.time() - self.start_time,
                "memory": {
                    "rss": process_memory.rss,
                    "vms": process_memory.vms,
                    "percent": process.memory_percent(),
                    "system_total": memory_info.total,
                    "system_available": memory_info.available,
                    "system_percent": memory_info.percent
                },
                "cpu": {
                    "percent": psutil.cpu_percent(interval=0.1)
                }
            }

        @self.app.get("/")
        async def root():
            """Root endpoint"""
            return {
                "message": f"Welcome to {self.name}",
                "version": self.version,
                "docs": "/docs"
            }

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        """Application lifespan context manager"""
        # Startup
        await self._startup()
        yield
        # Shutdown
        await self._shutdown()

    async def _startup(self):
        """Application startup logic"""
        self.logger.info(f"Starting {self.name} v{self.version}")

        # Initialize Redis if configured
        if os.getenv("REDIS_HOST"):
            self.redis_manager = RedisManager()
            await self.redis_manager.connect()

        # Initialize DB if configured
        db_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
        if db_url:
            self.db_manager = DBManager.get_instance(database_url=db_url)
            await self.db_manager.connect()

        # Initialize Queue Manager if Redis is available
        if self.redis_manager:
            self.queue_manager = QueueManager(self.redis_manager)

        # Initialize Email Service if configured
        if os.getenv("EMAIL_HOST"):
            self.email_service = EmailService()

        # Initialize WebSocket Server if needed
        if os.getenv("ENABLE_WEBSOCKETS", "false").lower() == "true":
            self.websocket_server = WebSocketServer(self.redis_manager)

    async def _shutdown(self):
        """Application shutdown logic"""
        self.logger.info(f"Shutting down {self.name}")

        # Close connections
        if self.redis_manager:
            await self.redis_manager.disconnect()

        if self.db_manager:
            await self.db_manager.disconnect()

        if self.websocket_server:
            await self.websocket_server.disconnect()

    def initialize_error_handling(self):
        """Initialize error handling middleware"""
        # Import error handler from middleware
        try:
            middleware_path = os.path.join(
                os.path.dirname(__file__), "../../middleware/py"
            )
            if middleware_path not in sys.path:
                sys.path.insert(0, middleware_path)
            
            from error_handler import error_handler
            
            async def exception_handler(request: Request, exc: Exception):
                return await error_handler(request, exc)
            
            self.app.add_exception_handler(Exception, exception_handler)
            self.logger.info("Error handling initialized")
        except ImportError as e:
            self.logger.warning(f"Error handler not found, using default: {e}")
            # Fallback to default error handler
            self.app.add_exception_handler(
                Exception,
                lambda request, exc: self.handle_error(request, exc)
            )

    def add_routes(self, path: str, router):
        """Add routes to the application"""
        self.app.include_router(router, prefix=path)

    async def start(self, db: Optional[DBManager] = None, port: int = 8000):
        """Start the server"""
        if db:
            await db.connect()
            self.db_manager = db
        elif not self.db_manager:
            db_url = os.getenv("DATABASE_URL") or os.getenv("DB_URL")
            if db_url:
                self.db_manager = DBManager.get_instance(database_url=db_url)
                await self.db_manager.connect()

        # Initialize Redis if configured
        if os.getenv("REDIS_HOST") and not self.redis_manager:
            self.redis_manager = RedisManager()
            await self.redis_manager.connect()

        # Initialize Queue Manager if Redis is available
        if self.redis_manager and not self.queue_manager:
            self.queue_manager = QueueManager(self.redis_manager)

        self.logger.info(f"🚀 {self.name} starting on port {port}")
        config = uvicorn.Config(
            app=self.app,
            host="0.0.0.0",
            port=port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()

    async def shutdown(self, db: Optional[DBManager] = None):
        """Graceful shutdown"""
        self.logger.info(f"🛑 Shutting down {self.name}")

        if self.queue_manager:
            await self.queue_manager.shutdown()

        if self.redis_manager:
            await self.redis_manager.disconnect()

        if self.db_manager:
            await self.db_manager.disconnect()
        elif db:
            await db.disconnect()

        if self.websocket_server:
            await self.websocket_server.disconnect()

        self.logger.info(f"✅ {self.name} shutdown complete")

    def get_app(self) -> FastAPI:
        """Get the FastAPI application instance"""
        return self.app

    async def handle_error(self, request: Request, exc: Exception) -> JSONResponse:
        """Default error handler fallback"""
        self.logger.error(f"Error processing request: {exc}")

        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail}
            )

        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )