"""Service layer for run management and workflow execution."""

from typing import Dict, Any, Optional, List
import logging

from sqlalchemy.orm import Session

from ..graph import create_workflow_graph
from ..types import WorkflowState, Trace
from quant_stream.recorder import Recorder

from .models import Run, Iteration, Result, RunStatus
from .schemas import RunCreateRequest

logger = logging.getLogger(__name__)


class RunService:
    """Service for managing runs and executing workflows."""

    def __init__(self, db: Session):
        self.db = db

    def create_run(self, request: RunCreateRequest) -> Run:
        """Create a new run record in the database."""
        # Build config dict from request
        config = request.model_dump()
        
        run = Run(
            hypothesis=request.hypothesis,
            status=RunStatus.PENDING,
            config=config,
            num_iterations=request.max_iterations,
            current_iteration=0,
        )
        
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        
        logger.info(f"Created run {run.id} with hypothesis: {request.hypothesis[:50]}...")
        return run

    def get_run(self, run_id: str) -> Optional[Run]:
        """Get a run by ID."""
        return self.db.query(Run).filter(Run.id == run_id).first()

    def list_runs(
        self,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[Run], int]:
        """List runs with optional filtering."""
        query = self.db.query(Run)
        
        if status:
            try:
                status_enum = RunStatus(status.upper())
                query = query.filter(Run.status == status_enum)
            except ValueError:
                pass  # Invalid status, ignore filter
        
        total = query.count()
        runs = query.order_by(Run.created_at.desc()).offset(offset).limit(limit).all()
        
        return runs, total

    def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        error_message: Optional[str] = None,
    ) -> Run:
        """Update run status."""
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        
        run.status = status
        if error_message:
            run.error_message = error_message
        
        self.db.commit()
        self.db.refresh(run)
        return run

    def update_run_iteration(self, run_id: str, iteration_num: int) -> Run:
        """Update current iteration number."""
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        
        run.current_iteration = iteration_num
        self.db.commit()
        self.db.refresh(run)
        return run

    def save_iteration_result(
        self,
        run_id: str,
        iteration_num: int,
        factors: Optional[List[Dict[str, Any]]],
        metrics: Optional[Dict[str, Any]],
    ) -> Iteration:
        """Save iteration results."""
        iteration = Iteration(
            run_id=run_id,
            iteration_num=iteration_num,
            factors=factors,
            metrics=metrics,
        )
        
        self.db.add(iteration)
        self.db.commit()
        self.db.refresh(iteration)
        
        logger.info(f"Saved iteration {iteration_num} for run {run_id}")
        return iteration

    def save_final_result(
        self,
        run_id: str,
        final_metrics: Optional[Dict[str, Any]],
        all_factors: Optional[List[Dict[str, Any]]],
        best_factors: Optional[List[Dict[str, Any]]],
    ) -> Result:
        """Save final results for a run."""
        # Delete existing result if any
        self.db.query(Result).filter(Result.run_id == run_id).delete()
        
        result = Result(
            run_id=run_id,
            final_metrics=final_metrics,
            all_factors=all_factors,
            best_factors=best_factors,
        )
        
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        
        logger.info(f"Saved final results for run {run_id}")
        return result

    def cancel_run(self, run_id: str) -> Run:
        """Cancel a run."""
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
            raise ValueError(f"Cannot cancel run in status {run.status}")
        
        run.status = RunStatus.CANCELLED
        self.db.commit()
        self.db.refresh(run)
        
        logger.info(f"Cancelled run {run_id}")
        return run

    def execute_workflow(self, run_id: str) -> None:
        """Execute the alphacopilot workflow for a run.
        
        This method is designed to be called in a background task.
        It updates the run status and stores results as the workflow progresses.
        """
        run = self.get_run(run_id)
        if not run:
            logger.error(f"Run {run_id} not found")
            return
        
        try:
            # Update status to RUNNING
            self.update_run_status(run_id, RunStatus.RUNNING)
            
            # Build workflow config from run config
            config = run.config
            
            # Calculate data loading range
            data_start_date = None
            data_end_date = None
            start_candidates = [
                date
                for date in (
                    config.get("train_start_date"),
                    config.get("validation_start_date"),
                    config.get("test_start_date"),
                )
                if date
            ]
            end_candidates = [
                date
                for date in (
                    config.get("train_end_date"),
                    config.get("validation_end_date"),
                    config.get("test_end_date"),
                )
                if date
            ]
            if start_candidates:
                data_start_date = min(start_candidates)
            if end_candidates:
                data_end_date = max(end_candidates)
            
            # Build workflow configuration
            workflow_config = {
                "data_path": config.get("data_path") or ".data/indian_stock_market_nifty500.csv",
                "data_start_date": data_start_date,
                "data_end_date": data_end_date,
                "symbols_file": config.get("symbols_file") or ".data/nifty500.txt",
                "max_symbols": config.get("max_symbols"),
                "symbol_col": config.get("symbol_col", "symbol"),
                "timestamp_col": config.get("timestamp_col", "timestamp"),
                "model_type": config.get("model_type"),
                "model_params": {},
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
                "tracking_uri": "sqlite:///mlruns.db",
            }
            
            # Setup MLflow recorder (best effort)
            recorder: Optional[Recorder] = None
            mlflow_context = None
            try:
                recorder = Recorder(
                    experiment_name=workflow_config.get("experiment_name", "alphacopilot_server"),
                    tracking_uri=workflow_config.get("tracking_uri", "sqlite:///mlruns.db"),
                )
                mlflow_context = recorder.start_run(workflow_config.get("run_name", f"run_{run_id[:8]}"))
                mlflow_context.__enter__()
                recorder.set_tags(workflow="alphacopilot_server", run_id=run_id)
                recorder.log_params(hypothesis=run.hypothesis, run_id=run_id)
            except Exception as mlflow_exc:
                logger.warning(f"MLflow recorder setup failed: {mlflow_exc}")
                recorder = None
                mlflow_context = None
            
            # Use MCP server backend (default: http://127.0.0.1:6969/mcp)
            mcp_server_url = "http://127.0.0.1:6969/mcp"
            mcp_tool_names = ["validate_factors", "run_ml_workflow"]
            
            # Create initial state
            initial_state = WorkflowState(
                trace=Trace(),
                hypothesis=None,
                experiment=None,
                feedback=None,
                potential_direction=run.hypothesis,
                mcp_tools=mcp_tool_names,  # Tool names for MCP backend
                mcp_server=mcp_server_url,  # MCP server URL
                workflow_config=workflow_config,
                custom_factors=config.get("custom_factors") or [],
                max_iterations=run.num_iterations,
                stop_on_sota=False,
                _mlflow_iteration=0,
                agent_logs=[],
                validation_error=False,
            )
            
            if recorder is not None:
                initial_state["recorder"] = recorder
                initial_state["mlflow_context"] = mlflow_context
                initial_state["_mlflow_llm_step"] = 0
                recorder.log_params(max_iterations=run.num_iterations)
            
            # Create custom logger that writes to database in real-time
            import sys
            import builtins
            from .models import Log
            
            class DatabaseLogger:
                """Logger that writes to database in real-time."""
                def __init__(self, run_id: str, db_session):
                    self.run_id = run_id
                    self.db = db_session
                    self.original_stdout = sys.stdout
                    self.original_stderr = sys.stderr
                    self.original_print = builtins.print
                    self.line_buffer = ""
                
                def write(self, text: str):
                    """Write to both original stdout and database."""
                    # Write to original stdout first
                    self.original_stdout.write(text)
                    self.original_stdout.flush()
                    
                    # Buffer text until we have complete lines
                    self.line_buffer += text
                    if '\n' in self.line_buffer:
                        lines = self.line_buffer.split('\n')
                        self.line_buffer = lines[-1]  # Keep incomplete line in buffer
                        
                        # Save complete lines to database
                        for line in lines[:-1]:
                            if line.strip():
                                self._save_log_line(line.strip())
                
                def _save_log_line(self, line: str):
                    """Save a single log line to database."""
                    try:
                        # Determine log level from content
                        level = "INFO"
                        line_lower = line.lower()
                        if "error" in line_lower or "✗" in line or "failed" in line_lower:
                            level = "ERROR"
                        elif "warn" in line_lower or "⚠" in line:
                            level = "WARNING"
                        elif "debug" in line_lower or "[debug]" in line_lower:
                            level = "DEBUG"
                        
                        log_entry = Log(
                            run_id=self.run_id,
                            level=level,
                            message=line,
                        )
                        self.db.add(log_entry)
                        self.db.commit()
                    except Exception as e:
                        logger.error(f"Failed to save log: {e}")
                        try:
                            self.db.rollback()
                        except Exception:
                            pass
                
                def flush(self):
                    self.original_stdout.flush()
                    # Flush any remaining buffer
                    if self.line_buffer.strip():
                        self._save_log_line(self.line_buffer.strip())
                        self.line_buffer = ""
                
                def print_wrapper(self, *args, **kwargs):
                    """Wrapper for print() that also logs to database."""
                    # Capture the output first
                    import io
                    output = io.StringIO()
                    # Use original print to capture
                    self.original_print(*args, file=output, **kwargs)
                    output_str = output.getvalue()
                    
                    # Write to original stdout
                    self.original_stdout.write(output_str)
                    if kwargs.get('end', '\n') == '\n':
                        self.original_stdout.flush()
                    
                    # Save to database
                    if output_str.strip():
                        for line in output_str.rstrip().split('\n'):
                            if line.strip():
                                self._save_log_line(line.strip())
            
            # Helper to save iteration
            def save_iteration_from_trace(trace: Trace, iteration_num: int):
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
                
                self.save_iteration_result(run_id, iteration_num, factors, metrics)
                self.update_run_iteration(run_id, iteration_num)
                return factors, metrics
            
            # Create and execute workflow graph with streaming
            graph = create_workflow_graph()
            
            # Set up stdout/stderr capture BEFORE any workflow code runs
            db_logger = DatabaseLogger(run_id, self.db)
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            original_print = builtins.print
            
            # Redirect stdout/stderr and monkey-patch print()
            sys.stdout = db_logger
            sys.stderr = db_logger
            builtins.print = db_logger.print_wrapper
            
            all_factors = []
            best_factors = []
            final_metrics = None
            
            try:
                # Use stream() to get real-time updates
                last_iteration_saved = 0
                final_state = None
                
                # Stream workflow execution - this yields chunks as nodes complete
                for chunk in graph.stream(initial_state):
                    # Process each chunk as it arrives
                    for node_name, node_output in chunk.items():
                        if node_output:
                            # Track final state (accumulate state)
                            if final_state is None:
                                final_state = node_output.copy()
                            else:
                                # Merge state updates
                                final_state.update(node_output)
                            
                            # Check if this is a feedback node completion (end of iteration)
                            if node_name == "feedback":
                                trace: Trace = node_output.get("trace")
                                if trace and trace.hist:
                                    iteration_num = len(trace.hist)
                                    if iteration_num > last_iteration_saved:
                                        factors, metrics = save_iteration_from_trace(trace, iteration_num)
                                        if factors:
                                            all_factors.extend(factors)
                                        
                                        # Check if SOTA
                                        if trace.hist[iteration_num - 1][2].decision:  # feedback.decision
                                            best_factors = factors.copy() if factors else []
                                            if metrics:
                                                final_metrics = metrics
                                        
                                        last_iteration_saved = iteration_num
                
                # Use final state from stream
                trace: Trace = final_state.get("trace") if final_state else None
                
                # Ensure all iterations are saved (in case stream missed any)
                if trace and trace.hist:
                    for iteration_num in range(last_iteration_saved + 1, len(trace.hist) + 1):
                        factors, metrics = save_iteration_from_trace(trace, iteration_num)
                        if factors:
                            all_factors.extend(factors)
                        
                        # Check if SOTA
                        if trace.hist[iteration_num - 1][2].decision:
                            best_factors = factors.copy() if factors else []
                            if metrics:
                                final_metrics = metrics
                    
                    # If no SOTA found, use last iteration's metrics
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
            finally:
                # Restore original stdout/stderr and print()
                sys.stdout = original_stdout
                sys.stderr = original_stderr
                builtins.print = original_print
                db_logger.flush()  # Flush any remaining logs
            
            # Save final results
            self.save_final_result(run_id, final_metrics, all_factors, best_factors)
            
            # Update status to COMPLETED
            self.update_run_status(run_id, RunStatus.COMPLETED)
            
            logger.info(f"Workflow completed successfully for run {run_id}")
            
        except Exception as e:
            logger.exception(f"Workflow execution failed for run {run_id}: {e}")
            self.update_run_status(run_id, RunStatus.FAILED, error_message=str(e))
        finally:
            # Cleanup MLflow context
            if mlflow_context is not None:
                try:
                    mlflow_context.__exit__(None, None, None)
                except Exception:
                    pass

