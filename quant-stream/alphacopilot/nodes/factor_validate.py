"""
Factor Validate Node - Validate factor expressions using MCP server validation tool.

This module contains the factor_validate node function.
Uses the expression parser to validate syntax and structure before backtesting.
Factor calculation is done automatically by the backtest tool.
"""

from typing import Any
from datetime import datetime

from ..types import WorkflowState
from ..mcp_client import call_mcp_tool
from ..recorder_utils import create_recorder_logger
from ..async_utils import run_async

# ============================================================================
# NODE FUNCTION
# ============================================================================

def factor_validate(state: WorkflowState, node_number: str = "03") -> dict[str, Any]:
    """
    Validate factor expressions using MCP server validation tool.

    Uses the expression parser to validate syntax and structure before backtesting.
    Factor calculation is done automatically by the backtest tool.

    Inputs:
        - state['experiment']: Experiment object with sub_tasks (containing factor expressions)
        - state['mcp_tools']: List of MCP tools loaded via langchain-mcp-adapters

    Outputs:
        - Returns dict with 'experiment': Same experiment object (validation only)

    Note: In the original alphacopilot, this step used CoSTEER for iterative code generation.
    In this simplified version, we use the MCP validation tool for syntax checking.
    """
    recorder = state.get("recorder")
    logger = create_recorder_logger(recorder)
    iteration = state.get("_mlflow_iteration", 0)

    node_tag = f"{node_number}_factor_validate"
    with logger.tag(f"iter_{iteration}.{node_tag}"):
        logger.info("Validating factor expressions via MCP server")

        experiment = state.get("experiment")
        mcp_tools = state.get("mcp_tools", [])
        mcp_server = state.get("mcp_server")

        # Track validation error state (default: False)
        validation_error = False
        log_msg = f"{node_tag}: validation not run"

        validation_payload = None

        def _basic_validation():
            nonlocal validation_error, log_msg
            factor_error_log = []
            for idx, factor_task in enumerate(experiment.sub_tasks):
                if not factor_task.expression or not factor_task.name:
                    factor_error = f"✗ Factor {idx+1} has invalid expression or name"
                    logger.error(factor_error)
                    factor_error_log.append(factor_error)
                    validation_error = True
                else:
                    logger.info(f"✓ Factor '{factor_task.name}': {factor_task.expression}")
            if validation_error:
                log_msg = "basic validation failed for some factors\n" + "\n".join(factor_error_log)
            else:
                log_msg = f"{node_tag}: basic validation executed"

        if mcp_server:
            factor_expressions = [
                {"name": task.name, "expression": task.expression}
                for task in experiment.sub_tasks
            ]
            try:
                raw_response = run_async(
                    call_mcp_tool(
                        mcp_server,
                        "validate_factors",
                        {"factor_expressions": factor_expressions},
                    )
                )
                if isinstance(raw_response, str):
                    import json

                    try:
                        response = json.loads(raw_response)
                    except json.JSONDecodeError:
                        logger.warning(f"Unexpected validation result: {raw_response}")
                        response = None
                else:
                    response = raw_response

                if isinstance(response, dict):
                    wrapped = response.get("result") if "result" in response else response
                    if isinstance(wrapped, dict):
                        validation_payload = wrapped
                        valid_flag = wrapped.get("valid")
                        errors = wrapped.get("errors", [])
                        results = wrapped.get("results")

                        if valid_flag is True or (valid_flag is None and not errors):
                            logger.info(f"✓ All {len(factor_expressions)} factor expressions are valid (MCP)")
                            if results:
                                for result in results:
                                    name = result.get("name", "unknown")
                                    variables = result.get("variables", [])
                                    functions = result.get("functions", [])
                                    logger.info(f"  - {name}: variables={variables}, functions={functions}")
                            else:
                                logger.warning("Validation response contained no per-factor results; treating as success.")
                            log_msg = (
                                f"{node_tag}: validated {len(factor_expressions)} factors at "
                                f"{datetime.now().isoformat()}"
                            )
                        else:
                            logger.error("✗ Some factor expressions are invalid:")
                            if errors:
                                for error in errors:
                                    logger.error(f"  - {error}")
                            else:
                                logger.error("  - MCP server marked response invalid but returned no error details.")
                            validation_error = True
                            error_msg = "\n".join(errors) if errors else "Unknown validation error from MCP"
                            log_msg = f"Encountered error in validating factor expressions: {error_msg}"
                    else:
                        logger.warning(f"Unexpected validation result shape: {response!r}")
                else:
                    logger.warning(f"Unexpected validation result type: {type(response)}")
            except Exception as e:
                logger.warning("MCP validation tool raised exception; falling back to basic validation.")
                logger.warning(f"Validation exception detail: {e}")
                _basic_validation()
        else:
            # No MCP server (binary/library backend) - rely on existing tools list
            validate_tool = next(
                (t for t in mcp_tools if hasattr(t, "name") and "validate" in t.name.lower()),
                None,
            )
            if validate_tool is None:
                logger.warning("Validation tool not available, using basic validation")
                available = [getattr(t, "name", str(t)) for t in mcp_tools]
                if available:
                    logger.info("Available tools: " + ", ".join(available))
                _basic_validation()
            else:
                factor_expressions = [
                    {"name": task.name, "expression": task.expression}
                    for task in experiment.sub_tasks
                ]

                try:
                    validation_result = run_async(
                        validate_tool.ainvoke({"factor_expressions": factor_expressions})
                    )
                    validation_payload = validation_result if isinstance(validation_result, dict) else None
                    if isinstance(validation_result, dict):
                        if validation_result.get("valid"):
                            logger.info(f"✓ All {len(factor_expressions)} factor expressions are valid")
                            for result in validation_result.get("results", []):
                                name = result.get("name", "unknown")
                                variables = result.get("variables", [])
                                functions = result.get("functions", [])
                                logger.info(f"  - {name}: variables={variables}, functions={functions}")
                            log_msg = f"{node_tag}: validated {len(factor_expressions)} factors at {datetime.now().isoformat()}"
                        else:
                            logger.error("✗ Some factor expressions are invalid:")
                            errors = validation_result.get("errors", [])
                            for error in errors:
                                logger.error(f"  - {error}")
                            validation_error = True
                            error_msg = "\n".join(errors)
                            log_msg = f"Encountered error in validating factor expressions: {error_msg}"
                    else:
                        logger.warning(f"Unexpected validation result: {validation_result}")
                except Exception as e:
                    logger.warning("Validation tool raised exception; falling back to basic validation.")
                    logger.warning(f"Validation exception detail: {e}")
                    _basic_validation()

        if validation_error:
            experiment = None

        logger.info("Note: Factors will be calculated automatically during backtesting")

        if validation_payload:
            logger.log_json(
                "factor_validation",
                validation_payload,
                artifact_path=f"alphacopilot/iter_{iteration}/state/{node_tag}",
            )
            if recorder and recorder.active_run:
                try:
                    recorder.log_metrics(
                        step=iteration,
                        factor_validate_checked=float(len(validation_payload.get("results", factor_expressions))),
                        factor_validate_valid=float(len(experiment.sub_tasks)),
                    )
                    recorder.log_metrics(
                        factor_validate_checked=float(len(validation_payload.get("results", factor_expressions))),
                        factor_validate_valid=float(len(experiment.sub_tasks)),
                    )
                except Exception:
                    pass
        elif recorder and recorder.active_run:
            try:
                recorder.log_metrics(
                    step=iteration,
                    factor_validate_checked=float(len(experiment.sub_tasks)),
                )
                recorder.log_metrics(
                    factor_validate_checked=float(len(experiment.sub_tasks)),
                )
            except Exception:
                pass

        logger.flush()

        return {
            "validation_error": validation_error,
            "experiment": experiment,
            "agent_logs": [log_msg]
        }

