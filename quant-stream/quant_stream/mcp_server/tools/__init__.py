"""Tools for MCP server.

UNIFIED WORKFLOW APPROACH:
- run_ml_workflow: Single tool for all factor-based trading (with/without ML model)
- validate_factors: Validate expression syntax before execution
- Job management: get_job_status, cancel_job for async operations
"""

from quant_stream.mcp_server.tools.workflow import run_workflow, run_ml_workflow_mcp as run_ml_workflow, get_job_status, cancel_job
from quant_stream.mcp_server.tools.validator import validate_factor_expression, validate_factor_expressions

__all__ = [
    "run_workflow",      # Run from YAML config
    "run_ml_workflow",   # UNIFIED TOOL - with/without model
    "get_job_status",    # Poll async jobs
    "cancel_job",        # Cancel async jobs
    "validate_factor_expression",   # Validate single expression
    "validate_factor_expressions",  # Validate multiple expressions
]
