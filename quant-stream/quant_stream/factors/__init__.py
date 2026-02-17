"""Alpha factor expression evaluation and parsing.

This module provides tools for:
- Parsing alpha factor expressions (e.g., 'RANK(DELTA($close, 5))')
- Evaluating expressions on market data using Pathway
- Converting parsed AST to executable operations
"""

from quant_stream.factors.evaluator import AlphaEvaluator
from quant_stream.factors.parser import parse_expression, ExpressionParser

__all__ = [
    "AlphaEvaluator",
    "parse_expression",
    "ExpressionParser",
]

