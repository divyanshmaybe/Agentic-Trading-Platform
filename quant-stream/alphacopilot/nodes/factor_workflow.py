"""
Factor Workflow Node - Run ML workflow using MCP server tool.

This module contains the factor_workflow node function.
The agent generates factor expressions, and this step runs a configurable workflow
that can either use factors directly as signals (model_type=None) or train an ML model.
"""

from typing import Any, Dict
from datetime import datetime
import time
import numbers
import pandas as pd

from ..types import WorkflowState
from ..recorder_utils import create_recorder_logger
from ..mlflow_utils import log_workflow_config_to_mlflow
from ..mcp_client import call_mcp_tool
from ..async_utils import run_async


def factor_workflow(state: WorkflowState, node_number: str = "04") -> dict[str, Any]:
    """
    Run the ML workflow using either the MCP server or locally available tools.
    """

    recorder = state.get("recorder")
    logger = create_recorder_logger(recorder)
    iteration = state.get("_mlflow_iteration", 0)

    node_tag = f"{node_number}_factor_workflow"
    with logger.tag(f"iter_{iteration}.{node_tag}"):
        logger.info("Starting factor workflow via MCP server")

        experiment = state.get("experiment")
        workflow_config = state.get("workflow_config", {})
        mcp_tools = state.get("mcp_tools", [])
        mcp_server = state.get("mcp_server")

        # ------------------------------------------------------------------
        # Factor preparation
        # ------------------------------------------------------------------
        factor_expressions = [
            {"name": task.name, "expression": task.expression}
            for task in experiment.sub_tasks
        ]

        custom_factors = state.get("custom_factors", [])
        if custom_factors:
            logger.info(
                "Merging %d user-provided custom factors with %d agent-generated factors",
                len(custom_factors),
                len(factor_expressions),
            )
            for i, expr in enumerate(custom_factors, start=1):
                factor_expressions.append(
                    {"name": f"custom_factor_{i}", "expression": expr}
                )
            logger.info("Total factors: %d", len(factor_expressions))

        train_dates = workflow_config.get("backtest_train_dates")
        validation_dates = workflow_config.get("backtest_validation_dates")
        test_dates = workflow_config.get("backtest_test_dates")

        backtest_segments = None
        if train_dates or validation_dates or test_dates:
            backtest_segments = {}
            if train_dates:
                backtest_segments["train"] = train_dates
            if validation_dates:
                backtest_segments["validation"] = validation_dates
            if test_dates:
                backtest_segments["test"] = test_dates

        base_run_name = workflow_config.get("run_name", f"factors_{len(factor_expressions)}")
        iter_run_name = f"{base_run_name}_iter_{iteration:02d}"

        config_dict: Dict[str, Any] = {
            "data": {
                "path": workflow_config.get("data_path"),
                "start_date": workflow_config.get("data_start_date"),
                "end_date": workflow_config.get("data_end_date"),
                "symbols_file": workflow_config.get("symbols_file"),
                "max_symbols": workflow_config.get("max_symbols"),
                "symbol_col": workflow_config.get("symbol_col"),
                "timestamp_col": workflow_config.get("timestamp_col"),
            },
            "features": factor_expressions,
            "strategy": {
                "type": workflow_config.get("strategy_type", "TopkDropout"),
                "params": {
                    "method": workflow_config.get("strategy_method", "equal"),
                    "topk": workflow_config.get("topk", 30),
                    "n_drop": workflow_config.get("n_drop", 5),
                    "hold_periods": workflow_config.get("hold_periods"),
                },
            },
            "backtest": {
                "segments": backtest_segments,
                "initial_capital": workflow_config.get("initial_capital", 1_000_000),
                "commission": workflow_config.get("commission", 0.001),
                "slippage": workflow_config.get("slippage", 0.001),
                "min_commission": workflow_config.get("min_commission", 0.0),
                "rebalance_frequency": workflow_config.get("rebalance_frequency", 1),
            },
            "experiment": {
                "name": workflow_config.get("experiment_name", "alphacopilot_workflow"),
                "run_name": iter_run_name,
                "tracking_uri": workflow_config.get("tracking_uri", "sqlite:///mlruns.db"),
                "tags": workflow_config.get("experiment_tags", {}),
            },
        }

        if workflow_config.get("model_type"):
            if not (train_dates and test_dates):
                raise ValueError(
                    "When specifying model_type, train and test date ranges must be provided."
                )
            validation_start = None
            validation_end = None
            if validation_dates:
                if len(validation_dates) != 2:
                    raise ValueError(
                        "backtest_validation_dates must be [start, end] when provided."
                    )
                validation_start, validation_end = validation_dates
                if not (validation_start and validation_end):
                    raise ValueError(
                        "Both validation start and end dates must be provided when specifying validation range."
                    )
            config_dict["model"] = {
                "type": workflow_config.get("model_type"),
                "params": workflow_config.get("model_params", {}),
                "target": workflow_config.get("model_target", "forward_return"),
            }
        else:
            config_dict["model"] = None

        workflow_params = {"config_dict": config_dict}

        def _log_metric_block(label: str, metric_dict: Dict[str, Any]) -> None:
            if not metric_dict:
                return
            logger.info("  [%s] Annualized Return: %.2f%%", label, metric_dict.get("annual_return", 0.0) * 100)
            logger.info("  [%s] Sharpe Ratio: %.2f", label, metric_dict.get("sharpe_ratio", 0.0))
            logger.info("  [%s] Max Drawdown: %.2f%%", label, metric_dict.get("max_drawdown", 0.0) * 100)
            if "IC" in metric_dict:
                logger.info("  [%s] IC: %.4f", label, metric_dict.get("IC", 0.0))
            if "Rank_IC" in metric_dict:
                logger.info("  [%s] Rank IC: %.4f", label, metric_dict.get("Rank_IC", 0.0))

        def _apply_result(result: Dict[str, Any]) -> None:
            experiment.result = result
            metrics = result.get("metrics", {})
            for task in experiment.sub_tasks:
                experiment.sub_results[task.name] = metrics.get("annual_return", 0.0)
            if metrics:
                logger.info("  Annualized Return: %.2f%%", metrics.get("annual_return", 0.0) * 100)
                logger.info("  Sharpe Ratio: %.2f", metrics.get("sharpe_ratio", 0.0))
                logger.info("  Max Drawdown: %.2f%%", metrics.get("max_drawdown", 0.0) * 100)
            train_metrics = result.get("train_metrics")
            test_metrics = result.get("test_metrics")
            if train_metrics:
                _log_metric_block("TRAIN", train_metrics)
            if test_metrics:
                _log_metric_block("TEST", test_metrics)
            if not train_metrics and not test_metrics:
                _log_metric_block("RESULT", metrics)

        config_snapshot = {
            "factor_count": len(factor_expressions),
            "custom_factor_count": len(custom_factors),
            "workflow_config": workflow_config,
            "sync_mode": False,
        }
        log_workflow_config_to_mlflow(recorder, config_snapshot, step=iteration)

        try:
            model_info = workflow_config.get("model_type", "None (direct factors)")

            if mcp_server:
                logger.info(
                    "Submitting workflow job for %d factors (model: %s)...",
                    len(factor_expressions),
                    model_info,
                )
                submit_result = run_async(
                    call_mcp_tool(
                        mcp_server,
                        "run_ml_workflow",
                        {
                            "factor_expressions": factor_expressions,
                            "model_type": workflow_config.get("model_type"),
                            "model_params": workflow_config.get("model_params", {}),
                            "data_path": workflow_config.get("data_path"),
                            "symbol_col": workflow_config.get("symbol_col", "symbol"),
                            "timestamp_col": workflow_config.get("timestamp_col", "timestamp"),
                            "target": workflow_config.get("model_target", "forward_return_1d"),
                            "train_start": train_dates[0] if train_dates else None,
                            "train_end": train_dates[1] if train_dates else None,
                            "test_start": test_dates[0] if test_dates else None,
                            "test_end": test_dates[1] if test_dates else None,
                            "backtest_train_dates": train_dates,
                            "backtest_validation_dates": validation_dates,
                            "backtest_test_dates": test_dates,
                            "strategy_type": workflow_config.get("strategy_type", "TopkDropout"),
                            "strategy_method": workflow_config.get("strategy_method", "equal"),
                            "topk": workflow_config.get("topk", 30),
                            "n_drop": workflow_config.get("n_drop", 5),
                            "hold_periods": workflow_config.get("hold_periods"),
                            "initial_capital": workflow_config.get("initial_capital", 1_000_000),
                            "commission": workflow_config.get("commission", 0.001),
                            "slippage": workflow_config.get("slippage", 0.001),
                            "min_commission": workflow_config.get("min_commission", 0.0),
                            "rebalance_frequency": workflow_config.get("rebalance_frequency", 1),
                            "experiment_name": workflow_config.get("experiment_name", "alphacopilot_workflow"),
                            "run_name": iter_run_name,
                            "tracking_uri": workflow_config.get("tracking_uri", "sqlite:///mlruns.db"),
                            "experiment_tags": workflow_config.get("experiment_tags"),
                        },
                    )
                )

                if not isinstance(submit_result, dict) or "job_id" not in submit_result:
                    logger.error("Unexpected submission result: %s", submit_result)
                    experiment.result = {
                        "success": False,
                        "error": "Unexpected submission response",
                        "metrics": {},
                    }
                    raise RuntimeError("Unexpected submission response from MCP workflow tool")

                job_id = submit_result["job_id"]
                status = submit_result.get("status", "UNKNOWN")
                logger.info("✓ Workflow job submitted: %s", job_id)
                logger.info("  Status: %s", status)

                if status == "SUCCESS" and "result" in submit_result:
                    result = submit_result["result"]
                    if not result.get("success", False):
                        error_msg = result.get("error", "Unknown workflow error")
                        logger.error("✗ Workflow failed: %s", error_msg)
                        experiment.result = result
                        raise RuntimeError(f"Workflow execution failed: {error_msg}")
                    logger.info("✓ Workflow completed immediately")
                    _apply_result(result)
                else:
                    poll_interval = 5
                    poll_count = 0
                    logger.info("Polling for job completion (waiting indefinitely)...")
                    while True:
                        poll_count += 1
                        status_result = run_async(
                            call_mcp_tool(
                                mcp_server,
                                "check_job_status",
                                {"job_id": job_id},
                            )
                        )
                        if isinstance(status_result, dict):
                            status = status_result.get("status", "UNKNOWN")
                            progress = status_result.get("progress", {})
                            if status == "SUCCESS":
                                result = status_result.get("result", {})
                                if not result.get("success", False):
                                    error_msg = result.get("error", "Unknown workflow error")
                                    logger.error("✗ Workflow failed: %s", error_msg)
                                    experiment.result = result
                                    raise RuntimeError(f"Workflow execution failed: {error_msg}")
                                logger.info("✓ Workflow completed successfully")
                                _apply_result(result)
                                break
                            if status == "FAILURE":
                                error_msg = status_result.get("error", "Unknown workflow error")
                                logger.error("✗ Workflow job failed: %s", error_msg)
                                experiment.result = {
                                    "success": False,
                                    "error": error_msg,
                                    "metrics": {},
                                }
                                raise RuntimeError(f"Workflow execution failed: {error_msg}")
                            if status in {"REVOKED", "CANCELLED"}:
                                logger.error("✗ Workflow job was cancelled")
                                experiment.result = {
                                    "success": False,
                                    "error": "Job cancelled",
                                    "metrics": {},
                                }
                                raise RuntimeError("Workflow job cancelled")

                            progress_msg = progress.get("status", status) if progress else status
                            progress_pct = progress.get("progress", 0) if progress else 0
                            logger.info("  [poll %d] %s (%s%%)", poll_count, progress_msg, progress_pct)
                        else:
                            logger.warning("Unexpected status result: %s", status_result)
                        time.sleep(poll_interval)

            else:
                workflow_tool = next(
                    (
                        t
                        for t in mcp_tools
                        if hasattr(t, "name")
                        and "workflow" in t.name.lower()
                        and "cancel" not in t.name.lower()
                    ),
                    None,
                )
                status_tool = next(
                    (
                        t
                        for t in mcp_tools
                        if hasattr(t, "name") and "check_job_status" in t.name.lower()
                    ),
                    None,
                )

                if workflow_tool is None:
                    logger.warning("Workflow tool not available, creating mock result")
                    available = [getattr(t, "name", str(t)) for t in mcp_tools]
                    if available:
                        logger.info("Available tools: %s", ", ".join(available))
                    experiment.result = {
                        "success": False,
                        "error": "Workflow tool not found",
                        "metrics": {},
                    }
                else:
                    is_sync_mode = getattr(workflow_tool, "execution_mode", None) == "sync"
                    config_snapshot["sync_mode"] = is_sync_mode

                    if is_sync_mode:
                        logger.info(
                            "Running workflow synchronously for %d factors (model: %s)...",
                            len(factor_expressions),
                            model_info,
                        )
                        result = run_async(workflow_tool.ainvoke(workflow_params))
                        if not result.get("success", False):
                            error_msg = result.get("error", "Unknown workflow error")
                            logger.error("✗ Workflow failed: %s", error_msg)
                            experiment.result = result
                            raise RuntimeError(f"Workflow execution failed: {error_msg}")
                        logger.info("✓ Workflow completed successfully")
                        _apply_result(result)
                    else:
                        logger.info(
                            "Submitting workflow job for %d factors (model: %s)...",
                            len(factor_expressions),
                            model_info,
                        )
                        submit_result = run_async(workflow_tool.ainvoke(workflow_params))
                        if isinstance(submit_result, dict) and "job_id" in submit_result:
                            job_id = submit_result["job_id"]
                            status = submit_result.get("status", "UNKNOWN")
                            logger.info("✓ Workflow job submitted: %s", job_id)
                            logger.info("  Status: %s", status)
                            if status == "SUCCESS" and "result" in submit_result:
                                result = submit_result["result"]
                                if not result.get("success", False):
                                    error_msg = result.get("error", "Unknown workflow error")
                                    logger.error("✗ Workflow failed: %s", error_msg)
                                    experiment.result = result
                                    raise RuntimeError(f"Workflow execution failed: {error_msg}")
                                logger.info("✓ Workflow completed immediately")
                                _apply_result(result)
                            elif status_tool is None:
                                logger.warning("Job status tool not available, cannot poll for results")
                                experiment.result = {
                                    "success": False,
                                    "error": "Job status tool not found",
                                    "metrics": {},
                                }
                            else:
                                poll_interval = 5
                                poll_count = 0
                                logger.info("Polling for job completion (waiting indefinitely)...")
                                while True:
                                    poll_count += 1
                                    status_result = run_async(status_tool.ainvoke({"job_id": job_id}))
                                    if isinstance(status_result, dict):
                                        status = status_result.get("status", "UNKNOWN")
                                        progress = status_result.get("progress", {})
                                        if status == "SUCCESS":
                                            result = status_result.get("result", {})
                                            if not result.get("success", False):
                                                error_msg = result.get("error", "Unknown workflow error")
                                                logger.error("✗ Workflow failed: %s", error_msg)
                                                experiment.result = result
                                                raise RuntimeError(f"Workflow execution failed: {error_msg}")
                                            logger.info("✓ Workflow completed successfully")
                                            _apply_result(result)
                                            break
                                        if status == "FAILURE":
                                            error_msg = status_result.get("error", "Unknown workflow error")
                                            logger.error("✗ Workflow job failed: %s", error_msg)
                                            experiment.result = {
                                                "success": False,
                                                "error": error_msg,
                                                "metrics": {},
                                            }
                                            raise RuntimeError(f"Workflow execution failed: {error_msg}")
                                        if status in ["REVOKED", "CANCELLED"]:
                                            logger.error("✗ Workflow job was cancelled")
                                            experiment.result = {
                                                "success": False,
                                                "error": "Job cancelled",
                                                "metrics": {},
                                            }
                                            raise RuntimeError("Workflow job cancelled")
                                        progress_msg = progress.get("status", status) if progress else status
                                        progress_pct = progress.get("progress", 0) if progress else 0
                                        logger.info(
                                            "  [poll %d] %s (%s%%)", poll_count, progress_msg, progress_pct
                                        )
                                    else:
                                        logger.warning("Unexpected status result: %s", status_result)
                                    time.sleep(poll_interval)
                        else:
                            logger.error("✗ Unexpected workflow submission result: %s", submit_result)
                            experiment.result = {
                                "success": False,
                                "error": "Invalid job submission",
                                "metrics": {},
                            }

        except Exception as e:
            logger.error("✗ Workflow exception: %s", e)
            import traceback

            logger.error(traceback.format_exc())
            experiment.result = {"success": False, "error": str(e), "metrics": {}}
            raise

        log_msg = f"{node_tag}: completed run at {datetime.now().isoformat()}"

        if experiment.result is not None:
            logger.log_json(
                "workflow_result",
                experiment.result,
                artifact_path=f"alphacopilot/iter_{iteration}/state/{node_tag}",
            )
            if recorder and recorder.active_run and isinstance(experiment.result, dict):
                base_metrics = experiment.result.get("metrics") or {}
                numeric_metrics: dict[str, float] = {}
                if not experiment.result.get("train_metrics") and not experiment.result.get("test_metrics"):
                    numeric_metrics.update(
                        {
                            f"backtest_{key}": float(value)
                            for key, value in base_metrics.items()
                            if isinstance(value, numbers.Number) and not isinstance(value, bool)
                        }
                    )

                train_metrics = experiment.result.get("train_metrics") or {}
                numeric_metrics.update(
                    {
                        f"train_{key}": float(value)
                        for key, value in train_metrics.items()
                        if isinstance(value, numbers.Number) and not isinstance(value, bool)
                    }
                )

                test_metrics = experiment.result.get("test_metrics") or {}
                numeric_metrics.update(
                    {
                        f"test_{key}": float(value)
                        for key, value in test_metrics.items()
                        if isinstance(value, numbers.Number) and not isinstance(value, bool)
                    }
                )

                if numeric_metrics:
                    try:
                        recorder.log_metrics(step=iteration, **numeric_metrics)
                        recorder.log_metrics(**numeric_metrics)
                    except Exception:
                        pass

            def _log_holdings(df: Any, label: str) -> None:
                if df is None:
                    return
                if isinstance(df, pd.DataFrame) and df.empty:
                    return
                if hasattr(df, "empty") and getattr(df, "empty"):
                    return
                logger.log_dataframe_csv(
                    f"holdings_{label}",
                    df,
                    artifact_path=f"alphacopilot/iter_{iteration}/state/{node_tag}",
                )

            _log_holdings(experiment.result.get("holdings_df"), "full")
            _log_holdings(experiment.result.get("train_holdings_df"), "train")
            _log_holdings(experiment.result.get("test_holdings_df"), "test")

        logger.flush()

        return {
            "experiment": experiment,
            "agent_logs": [log_msg],
        }

