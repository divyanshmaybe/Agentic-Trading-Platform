"""Service layer for run management and workflow execution."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from schemas import RunCreateRequest, RunStatus
from database import get_prisma_client
from metrics import (
    record_run_created,
    record_run_completed,
    record_iteration_start,
    record_iteration_complete,
    record_factor_validation,
    record_factor_generated,
)

# Add quant-stream to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"
if str(QUANT_STREAM_PATH) not in sys.path:
    sys.path.insert(0, str(QUANT_STREAM_PATH))

logger = logging.getLogger(__name__)


def _safe_json_serialize(obj: Any) -> Optional[str]:
    """Safely serialize an object to JSON, handling circular references and non-serializable types."""
    if obj is None:
        return None
    
    def _clean_for_json(o, seen=None):
        """Recursively clean an object for JSON serialization."""
        if seen is None:
            seen = set()
        
        # Handle None
        if o is None:
            return None
        
        # Handle primitives
        if isinstance(o, (str, int, float, bool)):
            return o
        
        # Check for circular reference
        obj_id = id(o)
        if obj_id in seen:
            return "<circular reference>"
        
        # Handle dict
        if isinstance(o, dict):
            seen.add(obj_id)
            result = {}
            for k, v in o.items():
                try:
                    result[str(k)] = _clean_for_json(v, seen.copy())
                except Exception:
                    result[str(k)] = str(v)
            return result
        
        # Handle list/tuple
        if isinstance(o, (list, tuple)):
            seen.add(obj_id)
            return [_clean_for_json(item, seen.copy()) for item in o]
        
        # Handle numpy types
        if hasattr(o, 'item'):
            try:
                return o.item()
            except Exception:
                pass
        
        # Handle pandas Series/DataFrame
        if hasattr(o, 'to_dict'):
            try:
                return _clean_for_json(o.to_dict(), seen)
            except Exception:
                pass
        
        # Fallback to string representation
        try:
            return str(o)
        except Exception:
            return "<non-serializable>"
    
    try:
        cleaned = _clean_for_json(obj)
        return json.dumps(cleaned)
    except Exception as e:
        logger.warning(f"Failed to serialize object: {e}")
        return json.dumps({"error": "serialization_failed", "message": str(e)})


class RunService:
    """Service for managing runs and executing workflows."""

    def __init__(self):
        self._client = None

    def _create_library_tools(self):
        """Create library tools that use quant-stream functions directly.
        
        This is the same approach as alphacopilot CLI with backend="library".
        Returns synchronous execution results DIRECTLY (no job_id).
        """
        from quant_stream.mcp_server.tools.validator import validate_factor_expressions
        from quant_stream.mcp_server.tools.workflow import run_ml_workflow_sync

        class LibraryTool:
            """Tool that wraps library functions directly."""
            def __init__(self, name, func):
                self.name = name
                self.func = func
                self.description = func.__doc__ or ""
                self.execution_mode = "sync"

            async def ainvoke(self, args):
                """Async invoke that calls sync function and returns result directly."""
                logger.info(f"[LIBRARY] Executing tool '{self.name}'")
                if self.name == "validate_factors":
                    if isinstance(args, dict) and "factor_expressions" in args:
                        result = self.func(args["factor_expressions"])
                    else:
                        result = self.func(args)
                else:
                    result = self.func(args)
                logger.info(f"[LIBRARY] Tool '{self.name}' completed")
                return result

        tools = [
            LibraryTool("validate_factors", validate_factor_expressions),
            LibraryTool("run_ml_workflow", run_ml_workflow_sync),
        ]
        return tools

    async def _get_client(self):
        """Get Prisma client."""
        if self._client is None:
            self._client = await get_prisma_client()
        return self._client

    async def create_run(self, request: RunCreateRequest, customer_id: str) -> Dict[str, Any]:
        """Create a new run record in the database."""
        client = await self._get_client()
        
        # Build config dict from request
        config = request.model_dump()
        run_id = str(uuid.uuid4())
        
        run = await client.alphacopilotrun.create(
            data={
                "id": run_id,
                "customer_id": customer_id,
                "hypothesis": request.hypothesis,
                "status": RunStatus.PENDING.value,
                "metadata": json.dumps(config),
                "max_iterations": request.max_iterations,
                "current_iteration": 0,
                "symbols_file": request.symbols_file,
                "data_path": request.data_path,
            }
        )
        
        # Record metrics
        record_run_created(run_id)
        
        logger.info(f"Created run {run_id} with hypothesis: {request.hypothesis[:50]}...")
        return self._run_to_dict(run)

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a run by ID."""
        client = await self._get_client()
        run = await client.alphacopilotrun.find_unique(where={"id": run_id})
        if run:
            run_dict = self._run_to_dict(run)
            # Fetch results separately to get generated factors
            result = await client.alphacopilotresult.find_first(where={"run_id": run_id})
            if result:
                result_dict = self._result_to_dict(result)
                run_dict["generated_factors"] = result_dict.get("all_factors")
                run_dict["workflow_config"] = result_dict.get("workflow_config")
                run_dict["best_factors"] = result_dict.get("best_factors")
            return run_dict
        return None

    async def list_runs(
        self,
        customer_id: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """List runs for a specific user with optional filtering."""
        client = await self._get_client()
        
        where_clause = {"customer_id": customer_id}
        if status:
            where_clause["status"] = status.upper()
        
        total = await client.alphacopilotrun.count(where=where_clause)
        runs = await client.alphacopilotrun.find_many(
            where=where_clause,
            order={"created_at": "desc"},
            skip=offset,
            take=limit,
        )
        
        # Convert runs to dict and add results data
        run_dicts = []
        for run in runs:
            run_dict = self._run_to_dict(run)
            # Fetch results separately for each run
            logger.info(f"Fetching result for run_id: {run.id}")
            result = await client.alphacopilotresult.find_first(where={"run_id": run.id})
            logger.info(f"Result found: {result is not None}")
            if result:
                result_dict = self._result_to_dict(result)
                run_dict["generated_factors"] = result_dict.get("all_factors")
                run_dict["workflow_config"] = result_dict.get("workflow_config")
                run_dict["best_factors"] = result_dict.get("best_factors")
                logger.info(f"Run {run.id}: added {len(result_dict.get('all_factors') or [])} factors, {len(result_dict.get('best_factors') or [])} best_factors, and workflow_config={result_dict.get('workflow_config') is not None}")
            else:
                logger.warning(f"No result found for run {run.id}")
            run_dicts.append(run_dict)
        
        return run_dicts, total

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update run status."""
        client = await self._get_client()
        
        update_data: Dict[str, Any] = {
            "status": status.value,
        }
        
        # Store error message in metadata if provided
        if error_message:
            # Get current run to preserve existing metadata
            current_run = await client.alphacopilotrun.find_unique(where={"id": run_id})
            if current_run:
                existing_metadata = current_run.metadata or {}
                if isinstance(existing_metadata, str):
                    existing_metadata = json.loads(existing_metadata)
                existing_metadata["error_message"] = error_message
                update_data["metadata"] = json.dumps(existing_metadata)
        
        if status == RunStatus.COMPLETED or status == RunStatus.FAILED:
            update_data["completed_at"] = datetime.utcnow()
            # Record completion metrics
            record_run_completed(run_id, status.value.lower(), "full")
        
        run = await client.alphacopilotrun.update(
            where={"id": run_id},
            data=update_data,
        )
        return self._run_to_dict(run)

    async def update_run_iteration(self, run_id: str, iteration_num: int) -> Dict[str, Any]:
        """Update current iteration number."""
        client = await self._get_client()
        
        run = await client.alphacopilotrun.update(
            where={"id": run_id},
            data={
                "current_iteration": iteration_num,
            },
        )
        return self._run_to_dict(run)

    async def save_iteration_result(
        self,
        run_id: str,
        iteration_num: int,
        factors: Optional[List[Dict[str, Any]]],
        metrics: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Save iteration results."""
        client = await self._get_client()
        
        iteration = await client.alphacopilotiteration.create(
            data={
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "iteration_number": iteration_num,
                "factors": _safe_json_serialize(factors),
                "metrics": _safe_json_serialize(metrics),
                "status": "completed",
            }
        )
        
        logger.info(f"Saved iteration {iteration_num} for run {run_id}")
        return self._iteration_to_dict(iteration)

    async def save_final_result(
        self,
        run_id: str,
        final_metrics: Optional[Dict[str, Any]],
        all_factors: Optional[List[Dict[str, Any]]],
        best_factors: Optional[List[Dict[str, Any]]],
        workflow_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Save final results for a run."""
        client = await self._get_client()
        
        # Delete existing result if any
        await client.alphacopilotresult.delete_many(where={"run_id": run_id})
        
        # Combine metrics and factors info into schema-compatible format
        combined_metrics = {
            "final": final_metrics,
            "best_factors": best_factors,
        }
        
        result = await client.alphacopilotresult.create(
            data={
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "metrics": _safe_json_serialize(combined_metrics),
                "factors": _safe_json_serialize(all_factors),
                "workflow_config": _safe_json_serialize(workflow_config),
            }
        )
        
        logger.info(f"Saved final results for run {run_id}")
        return self._result_to_dict(result)

    async def get_run_results(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get results for a run."""
        client = await self._get_client()
        
        result = await client.alphacopilotresult.find_first(where={"run_id": run_id})
        if result:
            return self._result_to_dict(result)
        return None

    async def get_run_iterations(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all iterations for a run."""
        client = await self._get_client()
        
        iterations = await client.alphacopilotiteration.find_many(
            where={"run_id": run_id},
            order={"iteration_number": "asc"},
        )
        return [self._iteration_to_dict(it) for it in iterations]

    async def add_log(self, run_id: str, level: str, message: str, node_name: Optional[str] = None, iteration_number: Optional[int] = None) -> None:
        """Add a log entry for a run."""
        client = await self._get_client()
        
        data: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "level": level,
            "message": message,
        }
        if node_name:
            data["node_name"] = node_name
        if iteration_number is not None:
            data["iteration_number"] = iteration_number
        
        await client.alphacopilotlog.create(data=data)

    async def get_logs(self, run_id: str, after_timestamp: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Get logs for a run."""
        client = await self._get_client()
        
        where_clause: Dict[str, Any] = {"run_id": run_id}
        if after_timestamp:
            where_clause["created_at"] = {"gt": after_timestamp}
        
        logs = await client.alphacopilotlog.find_many(
            where=where_clause,
            order={"created_at": "asc"},
        )
        return [self._log_to_dict(log) for log in logs]

    async def cancel_run(self, run_id: str) -> Dict[str, Any]:
        """Cancel a run."""
        run = await self.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        
        if run["status"] in (RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value):
            raise ValueError(f"Cannot cancel run in status {run['status']}")
        
        return await self.update_run_status(run_id, RunStatus.CANCELLED)

    async def execute_workflow(self, run_id: str) -> None:
        """Execute the alphacopilot workflow for a run.
        
        This method is designed to be called in a background task.
        """
        run = await self.get_run(run_id)
        if not run:
            logger.error(f"Run {run_id} not found")
            return
        
        try:
            # Update status to RUNNING
            await self.update_run_status(run_id, RunStatus.RUNNING)
            
            # Import quant-stream components
            try:
                from alphacopilot.graph import create_workflow_graph
                from alphacopilot.types import WorkflowState, Trace
            except ImportError as e:
                logger.error(f"Failed to import quant-stream: {e}")
                await self.update_run_status(run_id, RunStatus.FAILED, error_message=f"Import error: {e}")
                return
            
            # Build workflow config from run config
            config = run["config"]
            if isinstance(config, str):
                config = json.loads(config)
            
            # Calculate data loading range
            data_start_date = None
            data_end_date = None
            start_candidates = [d for d in [
                config.get("train_start_date"),
                config.get("validation_start_date"),
                config.get("test_start_date"),
            ] if d]
            end_candidates = [d for d in [
                config.get("train_end_date"),
                config.get("validation_end_date"),
                config.get("test_end_date"),
            ] if d]
            if start_candidates:
                data_start_date = min(start_candidates)
            if end_candidates:
                data_end_date = max(end_candidates)
            
            # Build workflow configuration
            # Use absolute paths relative to quant-stream directory
            quant_stream_data_dir = QUANT_STREAM_PATH / ".data"
            default_data_path = str(quant_stream_data_dir / "indian_stock_market_nifty500.csv")
            default_symbols_file = str(quant_stream_data_dir / "nifty500.txt")
            
            # Resolve data_path - convert relative paths to absolute under quant-stream
            data_path = config.get("data_path")
            if not data_path:
                data_path = default_data_path
            elif not Path(data_path).is_absolute() and data_path.startswith(".data"):
                data_path = str(QUANT_STREAM_PATH / data_path)
            
            # Resolve symbols_file - convert relative paths to absolute under quant-stream
            symbols_file = config.get("symbols_file")
            if not symbols_file:
                symbols_file = default_symbols_file
            elif not Path(symbols_file).is_absolute() and symbols_file.startswith(".data"):
                symbols_file = str(QUANT_STREAM_PATH / symbols_file)
            
            workflow_config = {
                "data_path": data_path,
                "data_start_date": data_start_date,
                "data_end_date": data_end_date,
                "symbols_file": symbols_file,
                "max_symbols": config.get("max_symbols"),
                "symbol_col": config.get("symbol_col", "symbol"),
                "timestamp_col": config.get("timestamp_col", "timestamp"),
                "model_type": config.get("model_type"),
                "model_params": config.get("model_params") or {},
                "strategy_type": config.get("strategy_type", "TopkDropout"),
                "strategy_method": config.get("strategy_method", "equal"),
                "topk": config.get("topk", 30),
                "n_drop": config.get("n_drop", 5),
                "backtest_train_dates": (
                    [config.get("train_start_date"), config.get("train_end_date")]
                    if config.get("train_start_date") and config.get("train_end_date")
                    else None
                ),
                "backtest_validation_dates": (
                    [config.get("validation_start_date"), config.get("validation_end_date")]
                    if config.get("validation_start_date") and config.get("validation_end_date")
                    else None
                ),
                "backtest_test_dates": (
                    [config.get("test_start_date"), config.get("test_end_date")]
                    if config.get("test_start_date") and config.get("test_end_date")
                    else None
                ),
                "initial_capital": config.get("initial_capital", 1_000_000),
                "commission": config.get("commission", 0.001),
                "slippage": config.get("slippage", 0.001),
                "rebalance_frequency": config.get("rebalance_frequency", 1),
                "experiment_name": "alphacopilot_server",
                "run_name": f"run_{run_id[:8]}",
            }
            
            # Create library tools (direct function calls, no MCP server needed)
            # This is the same approach as alphacopilot CLI with backend="library"
            library_tools = self._create_library_tools()
            logger.info(f"Using library backend with {len(library_tools)} tools")
            
            # Create initial state
            # When using library backend: mcp_tools=tool_objects, mcp_server=None
            initial_state = WorkflowState(
                trace=Trace(),
                hypothesis=None,
                experiment=None,
                feedback=None,
                potential_direction=run["hypothesis"],
                mcp_tools=library_tools,  # Pass tool objects, not names
                mcp_server=None,  # No MCP server for library backend
                workflow_config=workflow_config,
                custom_factors=config.get("custom_factors") or [],
                max_iterations=run["num_iterations"],
                stop_on_sota=False,
                _mlflow_iteration=0,
                agent_logs=[],
                validation_error=False,
            )
            
            # Execute workflow
            graph = create_workflow_graph()
            
            all_factors = []
            best_factors = []
            final_metrics = None
            last_iteration_saved = 0
            final_state = None
            
            # Stream workflow execution
            for chunk in graph.stream(initial_state):
                for node_name, node_output in chunk.items():
                    if node_output:
                        if final_state is None:
                            final_state = node_output.copy()
                        else:
                            final_state.update(node_output)
                        
                        # Log progress
                        await self.add_log(run_id, "INFO", f"Completed node: {node_name}")
                        
                        # Save iteration on feedback node
                        if node_name == "feedback":
                            trace = node_output.get("trace")
                            if trace and trace.hist:
                                iteration_num = len(trace.hist)
                                if iteration_num > last_iteration_saved:
                                    factors, metrics = await self._save_iteration_from_trace(
                                        run_id, trace, iteration_num
                                    )
                                    if factors:
                                        all_factors.extend(factors)
                                    
                                    # Check if SOTA
                                    if trace.hist[iteration_num - 1][2].decision:
                                        best_factors = factors.copy() if factors else []
                                        if metrics:
                                            final_metrics = metrics
                                    
                                    await self.update_run_iteration(run_id, iteration_num)
                                    last_iteration_saved = iteration_num
            
            # Process final state
            if final_state:
                trace = final_state.get("trace")
                if trace and trace.hist:
                    # Ensure all iterations saved
                    for iteration_num in range(last_iteration_saved + 1, len(trace.hist) + 1):
                        factors, metrics = await self._save_iteration_from_trace(
                            run_id, trace, iteration_num
                        )
                        if factors:
                            all_factors.extend(factors)
                        if trace.hist[iteration_num - 1][2].decision:
                            best_factors = factors.copy() if factors else []
                            if metrics:
                                final_metrics = metrics
                    
                    # If no SOTA, use last iteration metrics
                    if not final_metrics and trace.hist:
                        last_experiment = trace.hist[-1][1]
                        if last_experiment and last_experiment.result:
                            result_data = last_experiment.result
                            if isinstance(result_data, dict):
                                final_metrics = result_data.get("metrics") or {}
                                if result_data.get("train_metrics"):
                                    final_metrics["train"] = result_data["train_metrics"]
                                if result_data.get("test_metrics"):
                                    final_metrics["test"] = result_data["test_metrics"]
            
            # Fallback: If no SOTA iteration found (no decision=True), select best iteration by metrics
            if not best_factors and all_factors:
                logger.info("No SOTA iteration marked, selecting best iteration by metrics...")
                await self._select_best_iteration_as_sota(run_id)
                # Re-fetch iterations to find the best one
                client = await self._get_client()
                iterations = await client.alphacopilotiteration.find_many(
                    where={"run_id": run_id},
                    order={"iteration_number": "asc"}
                )
                if iterations:
                    best_iter = self._find_best_iteration(iterations)
                    if best_iter:
                        best_factors = json.loads(best_iter.factors) if isinstance(best_iter.factors, str) else best_iter.factors
                        best_metrics = json.loads(best_iter.metrics) if isinstance(best_iter.metrics, str) else best_iter.metrics
                        if best_metrics:
                            final_metrics = best_metrics
                        logger.info(f"Selected iteration {best_iter.iteration_number} as SOTA with {len(best_factors or [])} factors")
            
            # Build final workflow config for deployment
            final_workflow_config = self._build_workflow_config(config, best_factors or all_factors)
            
            # Save final results
            await self.save_final_result(
                run_id, final_metrics, all_factors, best_factors, final_workflow_config
            )
            
            # Update status to COMPLETED
            await self.update_run_status(run_id, RunStatus.COMPLETED)
            await self.add_log(run_id, "INFO", "Workflow completed successfully")
            
            logger.info(f"Workflow completed successfully for run {run_id}")
            
        except Exception as e:
            logger.exception(f"Workflow execution failed for run {run_id}: {e}")
            await self.update_run_status(run_id, RunStatus.FAILED, error_message=str(e))
            await self.add_log(run_id, "ERROR", f"Workflow failed: {e}")

    async def _save_iteration_from_trace(
        self, run_id: str, trace, iteration_num: int
    ) -> tuple[Optional[List[Dict]], Optional[Dict]]:
        """Save a single iteration from trace."""
        if not trace or not trace.hist or iteration_num > len(trace.hist):
            return None, None
        
        hypothesis, experiment, feedback = trace.hist[iteration_num - 1]
        
        factors = []
        if experiment and experiment.sub_tasks:
            for task in experiment.sub_tasks:
                factors.append({
                    "name": task.name,
                    "expression": task.expression,
                    "description": task.description,
                    "formulation": task.formulation,
                    "variables": task.variables,
                })
        
        metrics = None
        if experiment and experiment.result:
            result_data = experiment.result
            if isinstance(result_data, dict):
                metrics = result_data.get("metrics") or {}
                if result_data.get("train_metrics"):
                    metrics["train"] = result_data["train_metrics"]
                if result_data.get("test_metrics"):
                    metrics["test"] = result_data["test_metrics"]
        
        await self.save_iteration_result(run_id, iteration_num, factors, metrics)
        return factors, metrics

    def _build_workflow_config(
        self, config: Dict[str, Any], factors: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build a complete workflow config for deployment."""
        # Convert factors to features format
        features = []
        for factor in factors:
            features.append({
                "name": factor.get("name", ""),
                "expression": factor.get("expression", ""),
            })
        
        return {
            "data": {
                "path": config.get("data_path") or ".data/indian_stock_market_nifty500.csv",
                "symbols_file": config.get("symbols_file"),
                "symbol_col": config.get("symbol_col", "symbol"),
                "timestamp_col": config.get("timestamp_col", "timestamp"),
            },
            "features": features,
            "model": {
                "type": config.get("model_type", "LightGBM"),
                "params": config.get("model_params") or {
                    "objective": "regression",
                    "learning_rate": 0.05,
                    "num_leaves": 127,
                    "max_depth": 5,
                    "num_boost_round": 300,
                    "early_stopping_rounds": 30,
                },
                "target": "forward_return_1d",
            },
            "strategy": {
                "type": config.get("strategy_type", "TopkDropout"),
                "params": {
                    "topk": config.get("topk", 30),
                    "n_drop": config.get("n_drop", 5),
                    "method": config.get("strategy_method", "equal"),
                },
            },
            "backtest": {
                "segments": {
                    "train": [config.get("train_start_date"), config.get("train_end_date")],
                    "validation": [config.get("validation_start_date"), config.get("validation_end_date")] 
                        if config.get("validation_start_date") else None,
                    "test": [config.get("test_start_date"), config.get("test_end_date")],
                },
                "initial_capital": config.get("initial_capital", 1_000_000),
                "commission": config.get("commission", 0.001),
                "slippage": config.get("slippage", 0.001),
                "rebalance_frequency": config.get("rebalance_frequency", 1),
            },
        }

    def _run_to_dict(self, run) -> Dict[str, Any]:
        """Convert run record to dictionary."""
        metadata = run.metadata
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        elif metadata is None:
            metadata = {}
        
        # Extract error_message from metadata if present
        error_message = metadata.get("error_message") if isinstance(metadata, dict) else None
        
        return {
            "id": run.id,
            "customer_id": run.customer_id,
            "hypothesis": run.hypothesis,
            "status": run.status,
            "config": metadata,  # Keep as 'config' for API compatibility
            "num_iterations": run.max_iterations,  # Keep as 'num_iterations' for API compatibility
            "current_iteration": run.current_iteration,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "completed_at": run.completed_at,
            "error_message": error_message,
        }

    def _iteration_to_dict(self, iteration) -> Dict[str, Any]:
        """Convert iteration record to dictionary."""
        factors = iteration.factors
        if isinstance(factors, str):
            factors = json.loads(factors)
        
        metrics = iteration.metrics
        if isinstance(metrics, str):
            metrics = json.loads(metrics)
        
        return {
            "id": iteration.id,
            "run_id": iteration.run_id,
            "iteration_num": iteration.iteration_number,  # Map to API-compatible name
            "factors": factors,
            "metrics": metrics,
            "status": iteration.status,
            "created_at": iteration.created_at,
            "updated_at": iteration.updated_at,
        }

    def _result_to_dict(self, result) -> Dict[str, Any]:
        """Convert result record to dictionary."""
        def parse_json(val):
            if isinstance(val, str):
                return json.loads(val)
            return val
        
        factors = parse_json(result.factors)
        metrics = parse_json(result.metrics)
        
        # Extract structured metrics if stored in combined format
        final_metrics = None
        best_factors = None
        if isinstance(metrics, dict):
            final_metrics = metrics.get("final")
            best_factors = metrics.get("best_factors")
        else:
            final_metrics = metrics
        
        return {
            "id": result.id,
            "run_id": result.run_id,
            "final_metrics": final_metrics,
            "all_factors": factors,
            "best_factors": best_factors,
            "workflow_config": parse_json(result.workflow_config) if result.workflow_config else None,
            "created_at": result.created_at,
            "updated_at": result.updated_at,
        }

    def _log_to_dict(self, log) -> Dict[str, Any]:
        """Convert log record to dictionary."""
        return {
            "id": log.id,
            "run_id": log.run_id,
            "level": log.level,
            "message": log.message,
            "node_name": log.node_name,
            "iteration_number": log.iteration_number,
            "timestamp": log.created_at,  # Map to API-compatible name
        }

    def _find_best_iteration(self, iterations):
        """Find the best iteration based on test metrics (Sharpe, IC, Return)."""
        if not iterations:
            return None
        
        best_iter = None
        best_score = -float('inf')
        
        for iteration in iterations:
            try:
                metrics = json.loads(iteration.metrics) if isinstance(iteration.metrics, str) else iteration.metrics
                if not metrics:
                    continue
                
                # Extract test metrics (if available) or use train metrics
                test_metrics = metrics
                if isinstance(metrics, dict) and 'test' in metrics:
                    # Handle circular reference case
                    if metrics['test'] == "<circular reference>":
                        test_metrics = metrics  # Use top-level metrics which are test metrics
                    else:
                        test_metrics = metrics['test']
                
                # Calculate composite score: prioritize Sharpe, IC, and Return
                sharpe = float(test_metrics.get('sharpe_ratio', 0))
                ic = float(test_metrics.get('IC', 0))
                annual_return = float(test_metrics.get('annual_return', 0))
                
                # Weighted score: Sharpe (50%), IC (30%), Return (20%)
                score = (sharpe * 0.5) + (ic * 0.3) + (annual_return * 0.2)
                
                logger.info(f"Iteration {iteration.iteration_number}: Sharpe={sharpe:.3f}, IC={ic:.4f}, Return={annual_return:.2%}, Score={score:.4f}")
                
                if score > best_score:
                    best_score = score
                    best_iter = iteration
            except Exception as e:
                logger.warning(f"Error evaluating iteration {iteration.iteration_number}: {e}")
                continue
        
        return best_iter

    async def _select_best_iteration_as_sota(self, run_id: str):
        """Log selection of best iteration when no SOTA was marked."""
        await self.add_log(
            run_id,
            "INFO",
            "No SOTA iteration marked by workflow. Automatically selecting best iteration based on test metrics (Sharpe, IC, Return)."
        )



