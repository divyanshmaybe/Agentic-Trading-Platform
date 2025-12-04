"""
Expression validation for quant-stream factor expressions.

Validates factor expressions before execution to catch errors early.
"""

from typing import Dict, Any, List
from quant_stream.factors.parser.expression_parser import parse_expression

# Available functions - imported from quant_stream.functions
AVAILABLE_FUNCTIONS = {
    # Element-wise
    "MAX_ELEMENTWISE", "MIN_ELEMENTWISE", "ABS", "SIGN",
    # Time-series
    "DELTA", "DELAY",
    # Cross-sectional
    "RANK", "MEAN", "STD", "SKEW", "MAX", "MIN", "MEDIAN", "ZSCORE", "SCALE",
    # Rolling
    "TS_MAX", "TS_MIN", "TS_MEAN", "TS_MEDIAN", "TS_SUM", "TS_STD", "TS_VAR",
    "TS_ARGMAX", "TS_ARGMIN", "TS_RANK", "PERCENTILE", "TS_ZSCORE", "TS_MAD",
    "TS_QUANTILE", "TS_PCTCHANGE",
    # Indicators
    "SMA", "EMA", "EWM", "WMA", "COUNT", "SUMIF", "FILTER", "PROD",
    "DECAYLINEAR", "MACD", "RSI", "BB_MIDDLE", "BB_UPPER", "BB_LOWER",
    # Two-column
    "TS_CORR", "TS_COVARIANCE", "HIGHDAY", "LOWDAY", "SUMAC", "REGBETA", "REGRESI",
    "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "AND", "OR",
    # Math
    "EXP", "SQRT", "LOG", "INV", "POW", "FLOOR",
    # Conditional
    "IF",
    "TERNARY",
}

# Available variables
AVAILABLE_VARIABLES = {"open", "high", "low", "close", "volume"}


def validate_expression(expression: str) -> Dict[str, Any]:
    """
    Validate a factor expression.
    
    Args:
        expression: Factor expression to validate (e.g., "DELTA($close, 1)")
        
    Returns:
        Dict with validation results:
        {
            "valid": bool,
            "expression": str,
            "error": str or None,
            "parsed": dict or None (parsed AST if valid),
            "variables": list (variables used in expression),
            "functions": list (functions used in expression),
        }
    """
    result = {
        "valid": False,
        "expression": expression,
        "error": None,
        "parsed": None,
        "variables": [],
        "functions": [],
    }
    
    try:
        # Extract variables and functions from ORIGINAL expression first
        # (before parsing transforms it)
        result["variables"] = _extract_variables(expression)
        result["functions"] = _extract_functions(expression)
        
        # Check for unknown functions
        unknown_functions = set(result["functions"]) - AVAILABLE_FUNCTIONS
        if unknown_functions:
            result["error"] = f"Unknown function(s): {', '.join(sorted(unknown_functions))}"
            return result
        
        # Check for unknown variables
        unknown_variables = set(result["variables"]) - AVAILABLE_VARIABLES
        if unknown_variables:
            result["error"] = f"Unknown variable(s): {', '.join(sorted(unknown_variables))}"
            return result
        
        # Check for negative periods in time-series functions
        negative_period_error = _check_negative_periods(expression)
        if negative_period_error:
            result["error"] = negative_period_error
            return result
        
        # Parse the expression to validate syntax
        parsed = parse_expression(expression)
        
        # If parsing succeeded, it's valid
        result["valid"] = True
        result["parsed"] = parsed
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def validate_expressions(expressions: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Validate multiple factor expressions.
    
    Args:
        expressions: List of {"name": "...", "expression": "..."} dicts
        
    Returns:
        Dict with overall validation results:
        {
            "valid": bool (all expressions valid),
            "results": list of validation results per expression,
            "errors": list of error messages,
        }
    """
    results = []
    errors = []
    
    for expr_dict in expressions:
        name = expr_dict.get("name", "unknown")
        expression = expr_dict.get("expression", "")
        
        validation = validate_expression(expression)
        validation["name"] = name
        
        results.append(validation)
        
        if not validation["valid"]:
            errors.append(f"{name}: {validation['error']}")
    
    return {
        "valid": len(errors) == 0,
        "results": results,
        "errors": errors,
    }


def _extract_variables(parsed: Any) -> List[str]:
    """Extract variable names from parsed expression string.
    
    Args:
        parsed: Parsed expression string (e.g., "ZSCORE(TS_PCTCHANGE($close,5))")
        
    Returns:
        List of unique variable names found in the expression
    """
    import re
    
    # If parsed is a dict (AST), traverse it
    if isinstance(parsed, dict):
        variables = set()
        
        def traverse(node):
            if isinstance(node, dict):
                if node.get("type") == "variable":
                    variables.add(node.get("name", ""))
                for value in node.values():
                    traverse(value)
            elif isinstance(node, list):
                for item in node:
                    traverse(item)
        
        traverse(parsed)
        return sorted(list(variables))
    
    # Otherwise, parse the string to extract variables
    # Variables are column references starting with $ (e.g., $close, $open, $volume)
    if isinstance(parsed, str):
        # Match $variable_name patterns
        variable_pattern = r'\$([a-zA-Z_][a-zA-Z0-9_]*)'
        matches = re.findall(variable_pattern, parsed)
        return sorted(list(set(matches)))
    
    return []


def _extract_functions(parsed: Any) -> List[str]:
    """Extract function names from parsed expression string.
    
    Args:
        parsed: Parsed expression string (e.g., "ZSCORE(TS_PCTCHANGE($close,5))")
        
    Returns:
        List of unique function names found in the expression
    """
    import re
    
    # If parsed is a dict (AST), traverse it
    if isinstance(parsed, dict):
        functions = set()
        
        def traverse(node):
            if isinstance(node, dict):
                if node.get("type") == "function":
                    functions.add(node.get("name", ""))
                for value in node.values():
                    traverse(value)
            elif isinstance(node, list):
                for item in node:
                    traverse(item)
        
        traverse(parsed)
        return sorted(list(functions))
    
    # Otherwise, parse the string to extract functions
    # Functions are UPPERCASE identifiers followed by opening parenthesis
    if isinstance(parsed, str):
        # Match FUNCTION_NAME( patterns
        function_pattern = r'([A-Z_][A-Z0-9_]*)\s*\('
        matches = re.findall(function_pattern, parsed)
        return sorted(list(set(matches)))
    
    return []


def _check_negative_periods(expression: str) -> str | None:
    """Check for negative or zero period parameters in time-series functions.
    
    Args:
        expression: Factor expression string
        
    Returns:
        Error message if negative periods found, None otherwise
    """
    import re
    
    # Time-series functions that require positive period parameters
    TS_FUNCTIONS = [
        "DELTA", "DELAY", "TS_MEAN", "TS_SUM", "TS_RANK", "TS_ZSCORE", "TS_MEDIAN",
        "TS_PCTCHANGE", "TS_MIN", "TS_MAX", "TS_ARGMAX", "TS_ARGMIN", "TS_QUANTILE",
        "TS_STD", "TS_VAR", "TS_CORR", "TS_COVARIANCE", "TS_MAD", "PERCENTILE",
        "HIGHDAY", "LOWDAY", "SUMAC", "SMA", "WMA", "EMA", "DECAYLINEAR",
        "PROD", "COUNT", "SUMIF", "REGBETA", "REGRESI", "RSI", "MACD",
        "BB_MIDDLE", "BB_UPPER", "BB_LOWER"
    ]
    
    # Pattern to match function calls with arguments
    # e.g., DELTA($close, -1) or TS_PCTCHANGE($volume, -1)
    for func in TS_FUNCTIONS:
        # Match function with comma-separated arguments
        pattern = rf'{func}\s*\(([^)]+)\)'
        matches = re.finditer(pattern, expression)
        
        for match in matches:
            args_str = match.group(1)
            # Split by comma and extract numeric arguments
            args = [arg.strip() for arg in args_str.split(',')]
            
            # Check each argument that looks like a number
            for i, arg in enumerate(args):
                # Skip variable references and nested function calls
                if '$' in arg or '(' in arg:
                    continue
                
                # Check if it's a negative number
                try:
                    value = float(arg)
                    if value < 0:
                        return (f"Function {func} has negative period parameter ({arg}). "
                               f"All period/window parameters must be positive integers (> 0). "
                               f"Negative periods cause data leakage by looking forward in time.")
                    if value == 0 and i > 0:  # First arg might be the data column, check others
                        return (f"Function {func} has zero period parameter ({arg}). "
                               f"All period/window parameters must be positive integers (> 0).")
                except ValueError:
                    # Not a number, skip
                    continue
    
    return None

