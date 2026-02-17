"""Factor calculation tools for MCP server.

This module provides thin wrappers for factor calculation for use with the MCP server.
"""

from typing import Dict, Any, Optional

from quant_stream.backtest.runner import load_market_data, calculate_factors


def calculate_factor(
    expression: str,
    factor_name: str = "alpha",
    data_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calculate alpha factor from expression.
    
    Args:
        expression: Factor expression (e.g., 'DELTA($close, 1)')
        factor_name: Name for the output factor
        data_config: Data configuration (path, start_date, end_date, etc.)
        
    Returns:
        Dict with success, factor_name, num_samples, and error fields
    """
    try:
        # Extract data config
        data_config = data_config or {}
        data_path = data_config.get("path")
        symbols = data_config.get("symbols")
        date_ranges = []
        start_date = data_config.get("start_date")
        end_date = data_config.get("end_date")
        if start_date or end_date:
            date_ranges.append((start_date, end_date))

        for segment in ("train", "validation", "test"):
            segment_start = data_config.get(f"{segment}_start_date")
            segment_end = data_config.get(f"{segment}_end_date")
            if segment_start or segment_end:
                date_ranges.append((segment_start, segment_end))
        
        # Load data using general runner
        table = load_market_data(
            data_path=data_path,
            date_ranges=date_ranges,
            symbols=symbols,
            mode="full",
        )
        
        # Calculate factor using general runner
        factor_expressions = [{"name": factor_name, "expression": expression}]
        result_table, result_df = calculate_factors(table, factor_expressions)
        
        # Return response
        return {
            "success": True,
            "factor_name": factor_name,
            "num_samples": len(result_df),
            "data": None,
            "error": None,
        }
        
    except Exception as e:
        return {
            "success": False,
            "factor_name": factor_name,
            "num_samples": 0,
            "data": None,
            "error": str(e),
        }


def calculate_factor_sync(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous version for Celery tasks."""
    return calculate_factor(
        expression=request_data["expression"],
        factor_name=request_data.get("factor_name", "alpha"),
        data_config=request_data.get("data_config"),
    )
