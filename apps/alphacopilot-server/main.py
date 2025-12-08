"""FastAPI server for AlphaCopilot workflow execution."""

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Initialize Phoenix tracing (must be done early, before loading .env)
try:
    from phoenix.otel import register
    
    # Configure Phoenix tracer with OTLP endpoint
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="alphacopilot-server",
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

# Add quant-stream to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"
if str(QUANT_STREAM_PATH) not in sys.path:
    sys.path.insert(0, str(QUANT_STREAM_PATH))

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import HOST, PORT, CORS_ORIGINS, DEFAULT_POLL_TIMEOUT, MAX_POLL_TIMEOUT
from database import init_db, close_db
from schemas import (
    RunCreateRequest,
    RunResponse,
    RunListResponse,
    ResultsResponse,
    StatusResponse,
    IterationResponse,
    RunStatus,
)
from services import RunService
from metrics import metrics_endpoint, set_service_info
from utils.auth import get_authenticated_user

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("Initializing database connection...")
    await init_db()
    logger.info("Database connected")
    logger.info("Using direct library calls (no MCP server required)")
    
    # Set service info for metrics
    set_service_info(
        version="0.1.0",
        environment=os.getenv("ENVIRONMENT", "development")
    )
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await close_db()


app = FastAPI(
    title="AlphaCopilot Server",
    description="REST API for executing AlphaCopilot workflows - hypothesis to alpha generation",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Prometheus metrics endpoint
app.add_api_route("/metrics", metrics_endpoint, methods=["GET"], include_in_schema=False)


def get_service() -> RunService:
    """Get RunService instance."""
    return RunService()


@app.post("/runs", response_model=RunListResponse, status_code=201)
async def create_runs(
    request: RunCreateRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_authenticated_user),
):
    """Create one or more runs from a hypothesis.
    
    If num_runs > 1, creates multiple independent runs that execute in parallel.
    Each run starts from scratch with the same hypothesis and parameters.
    """
    service = get_service()
    runs = []
    
    # Get customer_id from authenticated user
    customer_id = user.get("customer_id") or user.get("id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="User has no customer_id")
    
    # Create num_runs independent runs
    for i in range(request.num_runs):
        run = await service.create_run(request, customer_id=customer_id)
        runs.append(run)
        
        # Queue background task for execution
        background_tasks.add_task(service.execute_workflow, run["id"])
        logger.info(f"Queued background task for run {run['id']}")
    
    return RunListResponse(
        runs=[RunResponse(**run) for run in runs],
        total=len(runs),
    )


@app.get("/runs", response_model=RunListResponse)
async def list_runs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
    user: dict = Depends(get_authenticated_user),
):
    """List runs for the authenticated user with optional filtering."""
    service = get_service()
    
    # Get customer_id from authenticated user
    customer_id = user.get("customer_id") or user.get("id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="User has no customer_id")
    
    runs, total = await service.list_runs(
        customer_id=customer_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    
    return RunListResponse(
        runs=[RunResponse(**run) for run in runs],
        total=total,
    )


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    user: dict = Depends(get_authenticated_user),
):
    """Get details of a specific run."""
    service = get_service()
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    # Verify ownership
    customer_id = user.get("customer_id") or user.get("id")
    if run.get("customer_id") != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this run")
    
    return RunResponse(**run)


@app.get("/runs/{run_id}/status", response_model=StatusResponse)
async def get_run_status(
    run_id: str,
    timeout: int = Query(DEFAULT_POLL_TIMEOUT, ge=0, le=MAX_POLL_TIMEOUT, description="Long polling timeout in seconds"),
    user: dict = Depends(get_authenticated_user),
):
    """Get run status with optional long polling.
    
    If timeout > 0, the server will wait up to timeout seconds for the status to change.
    Returns immediately if status changes or timeout is reached.
    """
    service = get_service()
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    # Verify ownership
    customer_id = user.get("customer_id") or user.get("id")
    if run.get("customer_id") != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this run")
    
    initial_status = run["status"]
    initial_iteration = run["current_iteration"]
    
    # Long polling: wait for status change
    if timeout > 0:
        start_time = time.time()
        check_interval = min(1.0, timeout / 10)
        
        while time.time() - start_time < timeout:
            await asyncio.sleep(check_interval)
            
            # Refresh run from database
            run = await service.get_run(run_id)
            if run["status"] != initial_status or run["current_iteration"] != initial_iteration:
                break
    
    # Calculate progress
    num_iterations = run["num_iterations"]
    current_iteration = run["current_iteration"]
    
    if num_iterations > 0:
        progress_percent = (current_iteration / num_iterations) * 100
    else:
        progress_percent = 0.0
    
    if run["status"] == RunStatus.COMPLETED.value:
        progress_percent = 100.0
    elif run["status"] == RunStatus.FAILED.value:
        progress_percent = 0.0
    
    # Get all iterations
    iterations = await service.get_run_iterations(run_id)
    iterations_data = [IterationResponse(**it) for it in iterations]
    
    return StatusResponse(
        run_id=run["id"],
        status=run["status"],
        current_iteration=current_iteration,
        num_iterations=num_iterations,
        progress_percent=progress_percent,
        error_message=run.get("error_message"),
        iterations=iterations_data,
    )


@app.get("/runs/{run_id}/results", response_model=ResultsResponse)
async def get_run_results(
    run_id: str,
    user: dict = Depends(get_authenticated_user),
):
    """Get results for a completed or failed run."""
    service = get_service()
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    # Verify ownership
    customer_id = user.get("customer_id") or user.get("id")
    if run.get("customer_id") != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this run")
    
    # Allow viewing results for COMPLETED and FAILED runs
    allowed_statuses = [RunStatus.COMPLETED.value, RunStatus.FAILED.value]
    if run["status"] not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} is still in progress (status: {run['status']})"
        )
    
    # Get result and iterations
    result = await service.get_run_results(run_id)
    iterations = await service.get_run_iterations(run_id)
    
    return ResultsResponse(
        run_id=run["id"],
        status=run["status"],
        final_metrics=result.get("final_metrics") if result else None,
        all_factors=result.get("all_factors") if result else None,
        best_factors=result.get("best_factors") if result else None,
        workflow_config=result.get("workflow_config") if result else None,
        iterations=[IterationResponse(**it) for it in iterations] if iterations else None,
    )


@app.delete("/runs/{run_id}", status_code=204)
async def cancel_run(
    run_id: str,
    user: dict = Depends(get_authenticated_user),
):
    """Cancel a running or pending run."""
    service = get_service()
    
    # Verify ownership first
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    customer_id = user.get("customer_id") or user.get("id")
    if run.get("customer_id") != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this run")
    
    try:
        await service.cancel_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return None


@app.get("/runs/{run_id}/logs/stream")
async def stream_run_logs(
    run_id: str,
    user: dict = Depends(get_authenticated_user),
):
    """Stream logs for a run via Server-Sent Events (SSE).
    
    This endpoint streams logs in real-time as they are generated.
    The client should use EventSource to consume this stream.
    """
    service = get_service()
    run = await service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    # Verify ownership
    customer_id = user.get("customer_id") or user.get("id")
    if run.get("customer_id") != customer_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this run")
    
    async def log_generator():
        """Generate SSE events for logs."""
        last_timestamp = None
        seen_ids = set()
        
        # First, send any existing logs
        existing_logs = await service.get_logs(run_id)
        for log in existing_logs:
            seen_ids.add(log["id"])
            yield f"data: {json.dumps(log, default=str)}\n\n"
            if last_timestamp is None or log["timestamp"] > last_timestamp:
                last_timestamp = log["timestamp"]
        
        # Then poll for new logs
        while True:
            await asyncio.sleep(1)
            
            # Get new logs
            new_logs = await service.get_logs(run_id, after_timestamp=last_timestamp)
            
            for log in new_logs:
                if log["id"] not in seen_ids:
                    seen_ids.add(log["id"])
                    if last_timestamp is None or log["timestamp"] > last_timestamp:
                        last_timestamp = log["timestamp"]
                    yield f"data: {json.dumps(log, default=str)}\n\n"
            
            # Check if run is completed
            run = await service.get_run(run_id)
            if run["status"] in (RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value):
                yield f"event: close\ndata: {json.dumps({'status': run['status']})}\n\n"
                break
    
    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "alphacopilot-server"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)



