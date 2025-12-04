"""FastAPI server for AlphaCopilot workflow execution."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
import time

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .database import init_db, get_db_session
from .models import RunStatus
from .schemas import (
    RunCreateRequest,
    RunResponse,
    RunListResponse,
    ResultsResponse,
    StatusResponse,
    IterationResponse,
)
from .services import RunService
from .config import DEFAULT_POLL_TIMEOUT, MAX_POLL_TIMEOUT

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
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized")
    yield
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="AlphaCopilot Server",
    description="REST API for executing AlphaCopilot workflows",
    version="0.1.0",
    lifespan=lifespan,
)


def get_service(db: Session = Depends(get_db_session)) -> RunService:
    """Dependency to get RunService."""
    return RunService(db)


@app.post("/runs", response_model=RunListResponse, status_code=201)
async def create_runs(
    request: RunCreateRequest,
    background_tasks: BackgroundTasks,
    service: RunService = Depends(get_service),
):
    """Create one or more runs from a hypothesis.
    
    If num_runs > 1, creates multiple independent runs that execute in parallel.
    Each run starts from scratch with the same hypothesis and parameters.
    """
    runs = []
    
    # Create num_runs independent runs
    for i in range(request.num_runs):
        run = service.create_run(request)
        runs.append(run)
        
        # Queue background task for execution
        background_tasks.add_task(service.execute_workflow, run.id)
        logger.info(f"Queued background task for run {run.id}")
    
    return RunListResponse(
        runs=[RunResponse(**run.to_dict()) for run in runs],
        total=len(runs),
    )


@app.get("/runs", response_model=RunListResponse)
async def list_runs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of runs to return"),
    offset: int = Query(0, ge=0, description="Number of runs to skip"),
    service: RunService = Depends(get_service),
):
    """List all runs with optional filtering."""
    runs, total = service.list_runs(status=status, limit=limit, offset=offset)
    
    return RunListResponse(
        runs=[RunResponse(**run.to_dict()) for run in runs],
        total=total,
    )


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    service: RunService = Depends(get_service),
):
    """Get details of a specific run."""
    run = service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    return RunResponse(**run.to_dict())


@app.get("/runs/{run_id}/status", response_model=StatusResponse)
async def get_run_status(
    run_id: str,
    timeout: int = Query(DEFAULT_POLL_TIMEOUT, ge=0, le=MAX_POLL_TIMEOUT, description="Long polling timeout in seconds"),
    service: RunService = Depends(get_service),
):
    """Get run status with optional long polling.
    
    If timeout > 0, the server will wait up to timeout seconds for the status to change.
    Returns immediately if status changes or timeout is reached.
    Includes all iterations for this run.
    """
    run = service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    initial_status = run.status
    initial_iteration = run.current_iteration
    
    # Long polling: wait for status change
    if timeout > 0:
        start_time = time.time()
        check_interval = min(1.0, timeout / 10)  # Check every second or 10% of timeout
        
        while time.time() - start_time < timeout:
            await asyncio.sleep(check_interval)
            
            # Refresh run from database
            service.db.refresh(run)
            
            # Check if status or iteration changed
            if run.status != initial_status or run.current_iteration != initial_iteration:
                break
        
        # Final refresh
        service.db.refresh(run)
    
    # Calculate progress
    if run.num_iterations > 0:
        progress_percent = (run.current_iteration / run.num_iterations) * 100
    else:
        progress_percent = 0.0
    
    if run.status == RunStatus.COMPLETED:
        progress_percent = 100.0
    elif run.status == RunStatus.FAILED:
        progress_percent = 0.0
    
    # Get all iterations
    from .models import Iteration
    from .schemas import IterationResponse
    iterations = service.db.query(Iteration).filter(Iteration.run_id == run_id).order_by(Iteration.iteration_num).all()
    iterations_data = [IterationResponse(**it.to_dict()) for it in iterations]
    
    return StatusResponse(
        run_id=run.id,
        status=run.status.value,
        current_iteration=run.current_iteration,
        num_iterations=run.num_iterations,
        progress_percent=progress_percent,
        error_message=run.error_message,
        iterations=iterations_data,
    )


@app.get("/runs/{run_id}/results", response_model=ResultsResponse)
async def get_run_results(
    run_id: str,
    service: RunService = Depends(get_service),
):
    """Get results for a completed run."""
    run = service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    if run.status != RunStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} is not completed (status: {run.status.value})"
        )
    
    # Get result
    from .models import Result, Iteration
    result_obj = service.db.query(Result).filter(Result.run_id == run_id).first()
    
    # Get all iterations
    iterations = service.db.query(Iteration).filter(Iteration.run_id == run_id).order_by(Iteration.iteration_num).all()
    
    return ResultsResponse(
        run_id=run.id,
        status=run.status.value,
        final_metrics=result_obj.final_metrics if result_obj else None,
        all_factors=result_obj.all_factors if result_obj else None,
        best_factors=result_obj.best_factors if result_obj else None,
        iterations=[IterationResponse(**it.to_dict()) for it in iterations] if iterations else None,
    )


@app.delete("/runs/{run_id}", status_code=204)
async def cancel_run(
    run_id: str,
    service: RunService = Depends(get_service),
):
    """Cancel a running or pending run."""
    try:
        service.cancel_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return None


@app.get("/runs/{run_id}/logs/stream")
async def stream_run_logs(
    run_id: str,
    db: Session = Depends(get_db_session),
):
    """Stream logs for a run via Server-Sent Events (SSE).
    
    This endpoint streams logs in real-time as they are generated.
    The client should use EventSource to consume this stream.
    """
    # Verify run exists (close this session immediately)
    from .models import Run
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    from .models import Log
    from .database import SessionLocal
    import asyncio
    import json
    
    async def log_generator():
        """Generate SSE events for logs."""
        last_timestamp = None
        seen_ids = set()
        
        # First, send any existing logs (with a fresh session)
        session = SessionLocal()
        try:
            existing_logs = session.query(Log).filter(
                Log.run_id == run_id
            ).order_by(Log.timestamp).all()
            
            for log in existing_logs:
                seen_ids.add(log.id)
                yield f"data: {json.dumps(log.to_dict())}\n\n"
                if last_timestamp is None or log.timestamp > last_timestamp:
                    last_timestamp = log.timestamp
        finally:
            session.close()
        
        # Then poll for new logs (create new session for each poll)
        while True:
            session = None
            try:
                # Wait before next poll (no connection held during sleep)
                await asyncio.sleep(1)
                
                # Create fresh session for this poll
                session = SessionLocal()
                
                # Query for new logs
                query = session.query(Log).filter(Log.run_id == run_id)
                if last_timestamp:
                    # Get logs after the last timestamp we sent
                    query = query.filter(Log.timestamp > last_timestamp)
                
                new_logs = query.order_by(Log.timestamp).all()
                
                for log in new_logs:
                    if log.id not in seen_ids:
                        seen_ids.add(log.id)
                        if last_timestamp is None or log.timestamp > last_timestamp:
                            last_timestamp = log.timestamp
                        yield f"data: {json.dumps(log.to_dict())}\n\n"
                
                # Check if run is completed (fresh query)
                current_run = session.query(Run).filter(Run.id == run_id).first()
                if current_run and current_run.status.value in ("COMPLETED", "FAILED", "CANCELLED"):
                    # Send a final event and close
                    yield f"event: close\ndata: {json.dumps({'status': current_run.status.value})}\n\n"
                    break
                    
            except Exception as e:
                logger.error(f"Error in log stream: {e}")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                break
            finally:
                # Always close the session after each poll
                if session:
                    session.close()
    
    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

