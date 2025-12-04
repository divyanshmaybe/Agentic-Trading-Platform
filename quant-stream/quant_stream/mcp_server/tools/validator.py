"""
Validation tools for MCP server.

Provides expression validation for factor expressions.
"""

from typing import Dict, Any, List

from quant_stream.factors.parser.validator import validate_expression, validate_expressions


def validate_factor_expression(
    expression: str,
    factor_name: str = "alpha",
) -> Dict[str, Any]:
    """
    Validate a single factor expression.
    
    Args:
        expression: Factor expression (e.g., 'DELTA($close, 1)')
        factor_name: Name for the factor
        
    Returns:
        Dict with validation results including valid, error, variables, functions
    """
    result = validate_expression(expression)
    result["factor_name"] = factor_name
    return result


def validate_factor_expressions(
    factor_expressions: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Validate multiple factor expressions.
    
    Args:
        factor_expressions: List of {"name": "...", "expression": "..."} dicts
        
    Returns:
        Dict with overall validation including valid, results per factor, errors
    """
    return validate_expressions(factor_expressions)

