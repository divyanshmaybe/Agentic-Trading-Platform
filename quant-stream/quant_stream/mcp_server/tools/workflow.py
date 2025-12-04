"""Workflow execution tools for MCP server.

This module provides thin wrappers for both:
1. YAML-based workflows (via WorkflowRunner)
2. ML workflows (via run_ml_workflow from runner)
"""

from typing import Dict, Any, Optional, List

from quant_stream.workflows import run_from_yaml, WorkflowRunner
from quant_stream.backtest.runner import run_ml_workflow
from quant_stream.utils.symbol_filter import load_symbols_from_file
from quant_stream.config import WorkflowConfig


def run_ml_workflow_mcp(
    config_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """Run ML workflow via MCP server (thin wrapper around run_ml_workflow)."""

    workflow_config = WorkflowConfig(**config_dict)

    # Data configuration
    data_cfg = workflow_config.data
    data_path = data_cfg.path
    symbol_col = data_cfg.symbol_col
    timestamp_col = data_cfg.timestamp_col

    symbols: Optional[List[str]] = None
    if data_cfg.symbols_file:
        symbols = load_symbols_from_file(data_cfg.symbols_file, max_symbols=data_cfg.max_symbols)
        print(f"[MCP] Loaded {len(symbols)} symbols from {data_cfg.symbols_file}")
    elif data_cfg.symbols:
        symbols = data_cfg.symbols
        if data_cfg.max_symbols and len(symbols) > data_cfg.max_symbols:
            symbols = symbols[: data_cfg.max_symbols]
        print(f"[MCP] Using {len(symbols)} symbols from config")
    else:
        # Default to .data/nifty500.txt if no symbols configured
        default_symbols_file = ".data/nifty500.txt"
        symbols = load_symbols_from_file(default_symbols_file, max_symbols=data_cfg.max_symbols)
        print(f"[MCP] Loaded {len(symbols)} symbols from default file: {default_symbols_file}")

    # Features
    factor_expressions = workflow_config.get_all_factor_expressions()

    # Strategy
    strategy_type = workflow_config.strategy.type
    strategy_params = workflow_config.strategy.params

    # Backtest
    backtest_cfg = workflow_config.backtest
    backtest_segments = None
    if backtest_cfg.segments is not None:
        backtest_segments = {
            "train": backtest_cfg.segments.train,
            "test": backtest_cfg.segments.test,
        }
        if backtest_cfg.segments.validation is not None:
            backtest_segments["validation"] = backtest_cfg.segments.validation

    # Model
    model_cfg: Optional[Dict[str, Any]] = None
    if workflow_config.model is not None:
        if workflow_config.model.train_test_split is not None:
            raise ValueError(
                "WorkflowConfig.model.train_test_split is no longer supported. "
                "Specify train/validation/test windows under backtest.segments."
            )
        model_cfg = {
            "type": workflow_config.model.type,
            "features": workflow_config.model.features,
            "include_ohlcv": workflow_config.model.include_ohlcv,
            "params": workflow_config.model.params,
            "target": workflow_config.model.target,
        }
        if backtest_segments is None or not backtest_segments.get("train") or not backtest_segments.get("test"):
            raise ValueError(
                "backtest.segments must define train and test ranges when using a model."
            )

    # Experiment
    experiment_cfg = workflow_config.experiment

    result = run_ml_workflow(
        data_path=data_path,
        symbols=symbols,
        factor_expressions=factor_expressions,
        model_config=model_cfg,
        strategy_type=strategy_type,
        strategy_params=strategy_params,
        initial_capital=backtest_cfg.initial_capital,
        commission=backtest_cfg.commission,
        slippage=backtest_cfg.slippage,
        min_commission=backtest_cfg.min_commission,
        rebalance_frequency=backtest_cfg.rebalance_frequency,
        backtest_segments=backtest_segments,
        symbol_col=symbol_col,
        timestamp_col=timestamp_col,
        recorder=None,
        experiment_name=experiment_cfg.name,
        run_name=experiment_cfg.run_name,
        log_to_mlflow=False,
    )
    
    # Remove non-serializable objects for JSON
    result.pop("model", None)  # sklearn/lightgbm models can't be serialized
    result.pop("results_df", None)  # DataFrames can't be serialized
    result.pop("train_results_df", None)
    result.pop("test_results_df", None)
    result.pop("validation_results_df", None)
    result.pop("holdings_df", None)
    result.pop("train_holdings_df", None)
    result.pop("test_holdings_df", None)
    result.pop("validation_holdings_df", None)
    
    return result


def run_ml_workflow_sync(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous version for Celery tasks that requires a unified config dict."""
    if "config_dict" not in request_data:
        raise ValueError("request_data must include a 'config_dict' payload for workflow execution.")

    config_dict = request_data["config_dict"]
    output_path = request_data.get("output_path")
    result = run_workflow(config_dict=config_dict, output_path=output_path)
    return result


def run_workflow(
    config_path: Optional[str] = None,
    config_dict: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute complete end-to-end workflow from YAML config.
    
    Args:
        config_path: Path to YAML config file
        config_dict: Configuration dictionary
        output_path: Path to save results CSV
        
    Returns:
        Dict with success, metrics, run_info, and error fields
        
    Example:
        >>> result = run_workflow(config_path="workflow.yaml")
        >>> result = run_workflow(config_dict={"data": {...}, "model": {...}})
    """
    try:
        if config_path:
            # Run from YAML file
            results = run_from_yaml(config_path, output_path=output_path, verbose=False)
        elif config_dict:
            # Run from dict - enable verbose so we can see progress
            runner = WorkflowRunner(config_dict, verbose=True)
            results = runner.run(output_path=output_path)
        else:
            return {
                "success": False,
                "error": "Must provide either config_path or config_dict",
                "metrics": {},
                "run_info": {}
            }
        
        # Extract results for MCP
        metrics = results.get("metrics", {})
        train_metrics = results.get("train_metrics")
        test_metrics = results.get("test_metrics")
        holdings_history = results.get("holdings_history")
        train_holdings_history = results.get("train_holdings_history")
        test_holdings_history = results.get("test_holdings_history")
        config = results.get("config")
        
        run_info = results.get("run_info") or {}
        if not run_info and config:
            run_info["experiment_name"] = getattr(config.experiment, "name", None)
            run_info["run_name"] = getattr(config.experiment, "run_name", None)
            run_info["model_type"] = getattr(config.model, "type", None) if config.model else None
            run_info["strategy_type"] = getattr(config.strategy, "type", None)
        
        return {
            "success": True,
            "metrics": metrics,
            "train_metrics": train_metrics,
            "test_metrics": test_metrics,
            "holdings_history": holdings_history,
            "train_holdings_history": train_holdings_history,
            "test_holdings_history": test_holdings_history,
            "run_info": run_info,
            "error": None
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "metrics": {},
            "run_info": {}
        }


def get_job_status(job_id: str) -> Dict[str, Any]:
    """Get status of a background job.
    
    Args:
        job_id: The job identifier
        
    Returns:
        Dict with job_id, status, progress, result, and error fields
    """
    # Handle special cases for synchronous execution
    if job_id in ["sync_execution", "mcp_sync_fallback", "library_sync_execution", "binary_sync_execution"]:
        return {
            "job_id": job_id,
            "status": "SUCCESS",
            "progress": {"status": "Complete", "progress": 100},
            "result": None,  # Result was already returned in the initial call
            "error": None,
        }
    
    try:
        from celery.result import AsyncResult
        from quant_stream.mcp_server.core import get_celery_app
        celery_app = get_celery_app()
        
        # Get task result
        result = AsyncResult(job_id, app=celery_app)
    except ImportError:
        return {
            "job_id": job_id,
            "status": "ERROR",
            "error": "Celery not available - cannot check job status",
            "progress": None,
            "result": None,
        }
    
    # Build response based on state
    response = {
        "job_id": job_id,
        "status": result.state,
        "progress": None,
        "result": None,
        "error": None,
    }
    
    if result.state == "PENDING":
        response["progress"] = {"status": "Waiting in queue", "progress": 0}
    elif result.state == "STARTED":
        response["progress"] = {"status": "Job started", "progress": 5}
    elif result.state == "PROCESSING":
        # Get custom progress info
        info = result.info or {}
        if isinstance(info, dict):
            response["progress"] = {
                "status": info.get("status", "Processing"),
                "progress": info.get("progress", 0)
            }
    elif result.state == "SUCCESS":
        # Job completed - return result
        response["progress"] = {"status": "Complete", "progress": 100}
        response["result"] = result.result
    elif result.state == "FAILURE":
        # Job failed
        response["error"] = str(result.info) if result.info else "Unknown error"
        response["progress"] = {"status": "Failed", "progress": 0}
    elif result.state == "REVOKED":
        response["progress"] = {"status": "Cancelled", "progress": 0}
    
    return response


def cancel_job(job_id: str, terminate: bool = False) -> Dict[str, Any]:
    """Cancel a background job.
    
    Args:
        job_id: The job identifier
        terminate: If True, forcefully terminate running job
        
    Returns:
        Dict with job_id, status, and message fields
    """
    try:
        from quant_stream.mcp_server.core import get_celery_app
        celery_app = get_celery_app()
        
        # Revoke the task
        celery_app.control.revoke(job_id, terminate=terminate, signal="SIGTERM")
        
        return {
            "job_id": job_id,
            "status": "REVOKED",
            "message": f"Job cancelled {'and terminated' if terminate else 'successfully'}"
        }
    except ImportError:
        return {
            "job_id": job_id,
            "status": "ERROR",
            "message": "Celery not available - cannot cancel jobs"
        }
