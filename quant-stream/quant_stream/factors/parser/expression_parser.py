"""Expression parser for quant-stream formula language.

This module provides parsing functionality for mathematical and logical expressions
used in quantitative finance. It converts string expressions into executable code
that uses quant-stream functions.

Example:
    >>> parser = ExpressionParser()
    >>> result = parser.parse("RANK(DELTA($open, 1) - DELTA($close, 1)) / (1e-8 + 1)")
    >>> # Returns: "DIVIDE(RANK(SUBTRACT(DELTA($open, 1), DELTA($close, 1))), (1e-8+1))"
"""

from pyparsing import (
    Word,
    alphas,
    alphanums,
    infixNotation,
    opAssoc,
    oneOf,
    Optional,
    delimitedList,
    Forward,
    Group,
    ParseException,
    Regex,
    Combine,
    Literal,
    ParserElement,
)
import re
import sys

# Enable packrat parsing for better performance with nested expressions
ParserElement.enablePackrat()

# Set higher recursion limit for deeply nested expressions
sys.setrecursionlimit(5000)


class ExpressionParser:
    """Parser for quant-stream expression language.

    Supports:
        - Variables with optional $ prefix (e.g., $open, $close)
        - Numbers (integers, floats, scientific notation)
        - Arithmetic operators (+, -, *, /)
        - Comparison operators (>, <, >=, <=, ==, !=)
        - Logical operators (&&, ||, &, |)
        - Conditional expressions (? :)
        - Function calls with nested arguments
        - Unary operators (+, -)
    """

    def __init__(self):
        """Initialize the expression parser."""
        self._build_grammar()

    def _build_grammar(self):
        """Build the parsing grammar."""
        # Define variable (with optional $ prefix)
        var = Combine(Optional(Literal("$")) + Word(alphas, alphanums + "_")).setName(
            "variable"
        )

        # Define number (integer, float, scientific notation)
        number_pattern = r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?"
        number = Regex(number_pattern)

        # Define operators
        mul_div = oneOf("* /", useRegex=True)
        add_minus = oneOf("+ -")
        comparison_op = oneOf("> < >= <= == !=")
        logical_and = oneOf("&& &")
        logical_or = oneOf("|| |")
        conditional_op = ("?", ":")

        # Forward declaration for recursive grammar
        expr = Forward()

        # Define function calls
        unary_op = Optional(oneOf("+ -")).setParseAction(lambda t: t[0] if t else "")
        function_call = var + "(" + Optional(delimitedList(expr)) + ")"
        function_call.setParseAction(self._parse_function_call)

        # Define nested expressions
        nested_expr = Group("(" + expr + ")")

        # Define operand
        operand = Group(unary_op + (function_call | var | number | nested_expr | expr))

        # Build expression with operator precedence
        expr <<= infixNotation(
            operand,
            [
                (mul_div, 2, opAssoc.LEFT, self._parse_arith_op),
                (add_minus, 2, opAssoc.LEFT, self._parse_arith_op),
                (comparison_op, 2, opAssoc.LEFT, self._parse_comparison_op),
                (logical_and, 2, opAssoc.LEFT, self._parse_logical_expression),
                (logical_or, 2, opAssoc.LEFT, self._parse_logical_expression),
                (conditional_op, 3, opAssoc.RIGHT, self._parse_conditional_expression),
            ],
        )

        expr.setParseAction(self._parse_entire_expression)
        self.expr = expr

    @staticmethod
    def _flatten_nested_tokens(tokens):
        """Flatten nested ParseResults into a list of strings.

        Args:
            tokens: Nested list/ParseResults structure

        Returns:
            Flattened list of string tokens
        """
        flattened = []
        for token in tokens:
            if isinstance(token, str):
                flattened.append(token)
            elif isinstance(token, list):
                flattened.extend(ExpressionParser._flatten_nested_tokens(token))
            else:  # ParseResults
                flattened.extend(
                    ExpressionParser._flatten_nested_tokens(token.asList())
                )
        return flattened

    @staticmethod
    def _is_number(s):
        """Check if a string represents a number.

        Args:
            s: String to check

        Returns:
            True if s is a valid number, False otherwise
        """
        try:
            float(s)
            return True
        except ValueError:
            return False

    @staticmethod
    def _strip_outer_parens(s):
        """Strip outer parentheses from an expression if they wrap the entire expression.

        Args:
            s: String expression

        Returns:
            Expression with outer parentheses removed if appropriate
        """
        s = s.strip()
        if not s.startswith("(") or not s.endswith(")"):
            return s

        # Check if the parentheses actually wrap the entire expression
        depth = 0
        for i, char in enumerate(s):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1

            # If depth reaches 0 before the end, outer parens don't wrap everything
            if depth == 0 and i < len(s) - 1:
                return s

        # Outer parens wrap the entire expression, strip them
        return s[1:-1]

    def _parse_arith_op(self, s, loc, tokens):
        """Parse arithmetic operations.

        Converts operations between variables into function calls (ADD, SUBTRACT, etc.)
        while keeping operations with at least one numeric literal as inline operations.

        Args:
            s: Original string being parsed
            loc: Location in string
            tokens: Parsed tokens

        Returns:
            Transformed expression string
        """

        def recursive_build_expression(tokens):
            if len(tokens) == 3:
                A, op, B = tokens
                return self._build_arith_expression(A, op, B)
            else:
                left = tokens[:-2]
                op = tokens[-2]
                right = tokens[-1]
                left_expr = recursive_build_expression(left)
                return self._build_arith_expression(left_expr, op, right)

        return recursive_build_expression(tokens[0])

    def _build_arith_expression(self, A, op, B):
        """Build an arithmetic expression.

        Args:
            A: Left operand
            op: Operator (+, -, *, /)
            B: Right operand

        Returns:
            Transformed expression string
        """
        A = "".join(self._flatten_nested_tokens([A]))
        B = "".join(self._flatten_nested_tokens([B]))

        # Strip outer parentheses for function call arguments
        A_stripped = self._strip_outer_parens(A)
        B_stripped = self._strip_outer_parens(B)

        A_is_number = self._is_number(A)
        B_is_number = self._is_number(B)

        # Check if either operand contains function calls
        # Function names are uppercase, followed by (
        import re
        func_pattern = r'[A-Z_][A-Z0-9_]*\s*\('
        A_has_funcs = bool(re.search(func_pattern, A))
        B_has_funcs = bool(re.search(func_pattern, B))

        # If one operand has functions, ALWAYS use function call format
        # to ensure proper evaluation (e.g., TS_ZSCORE(...) + 1e-8 → ADD(TS_ZSCORE(...), 1e-8))
        if A_has_funcs or B_has_funcs:
            # Convert to function call
            if op == "+":
                return f"ADD({A_stripped}, {B_stripped})"
            elif op == "-":
                return f"SUBTRACT({A_stripped}, {B_stripped})"
            elif op == "*":
                return f"MULTIPLY({A_stripped}, {B_stripped})"
            elif op == "/":
                return f"DIVIDE({A_stripped}, {B_stripped})"
            else:
                raise NotImplementedError(f"Arithmetic operator '{op}' is not implemented")
        
        # If both are simple (no functions), keep inline if at least one is a number
        if A_is_number or B_is_number:
            return f"{A}{op}{B}"

        # Both operands are variables/expressions - convert to function call
        if op == "+":
            return f"ADD({A_stripped}, {B_stripped})"
        elif op == "-":
            return f"SUBTRACT({A_stripped}, {B_stripped})"
        elif op == "*":
            return f"MULTIPLY({A_stripped}, {B_stripped})"
        elif op == "/":
            return f"DIVIDE({A_stripped}, {B_stripped})"
        else:
            raise NotImplementedError(f"Arithmetic operator '{op}' is not implemented")

    def _parse_comparison_op(self, s, loc, tokens):
        """Parse comparison operations.

        Args:
            s: Original string being parsed
            loc: Location in string
            tokens: Parsed tokens

        Returns:
            Comparison expression string
        """
        A = "".join(self._flatten_nested_tokens(tokens[0][0]))
        op = "".join(self._flatten_nested_tokens(tokens[0][1]))
        B = "".join(self._flatten_nested_tokens(tokens[0][2]))

        return f"({A}{op}{B})"

    def _parse_logical_expression(self, s, loc, tokens):
        """Parse logical operations (AND, OR).

        Args:
            s: Original string being parsed
            loc: Location in string
            tokens: Parsed tokens

        Returns:
            Transformed logical expression
        """

        def recursive_flatten(tokens):
            if len(tokens) == 1:
                return "".join(self._flatten_nested_tokens([tokens[0]]))
            else:
                left = tokens[0]
                operator = tokens[1]
                left_str = "".join(self._flatten_nested_tokens([left]))
                right_str = recursive_flatten(tokens[2:])

                # Strip outer parentheses for function call arguments
                left_str = self._strip_outer_parens(left_str)
                right_str = self._strip_outer_parens(right_str)

                if operator in ["||", "|"]:
                    return f"OR({left_str}, {right_str})"
                elif operator in ["&&", "&"]:
                    return f"AND({left_str}, {right_str})"

        return recursive_flatten(tokens[0])

    def _parse_conditional_expression(self, s, loc, tokens):
        """Parse ternary conditional expressions (condition ? true_val : false_val).

        Args:
            s: Original string being parsed
            loc: Location in string
            tokens: Parsed tokens

        Returns:
            Conditional expression using TERNARY function
        """
        A = "".join(self._flatten_nested_tokens(tokens[0][0]))
        B = "".join(self._flatten_nested_tokens(tokens[0][2]))
        C = "".join(self._flatten_nested_tokens(tokens[0][4]))

        # Strip outer parentheses for function call arguments
        A = self._strip_outer_parens(A)
        B = self._strip_outer_parens(B)
        C = self._strip_outer_parens(C)

        return f"TERNARY({A}, {B}, {C})"

    def _parse_function_call(self, s, loc, tokens):
        """Parse function calls with arguments.

        Args:
            s: Original string being parsed
            loc: Location in string
            tokens: Parsed tokens

        Returns:
            Function call string
        """
        function_name = tokens[0]
        arguments = tokens[2:-1]

        # Process arguments
        arguments_flat = []
        for arg in arguments:
            if isinstance(arg, str):
                arguments_flat.append(arg)
            else:
                flattened_arg = "".join(self._flatten_nested_tokens(arg))
                arguments_flat.append(flattened_arg)

        arguments_str = ", ".join(arguments_flat)
        return f"{function_name}({arguments_str})"

    def _parse_entire_expression(self, s, loc, tokens):
        """Final parse action to flatten entire expression.

        Args:
            s: Original string being parsed
            loc: Location in string
            tokens: Parsed tokens

        Returns:
            Complete flattened expression string
        """
        return "".join(self._flatten_nested_tokens(tokens))

    @staticmethod
    def _check_parentheses_balance(expression):
        """Check if parentheses are balanced in expression.

        Args:
            expression: Expression string to check

        Raises:
            ParseException: If parentheses are not balanced
        """
        if expression.count("(") != expression.count(")"):
            raise ParseException("Unbalanced parentheses in expression")

    @staticmethod
    def _check_for_invalid_operators(expression):
        """Check for invalid operators in expression.

        Args:
            expression: Expression string to check

        Raises:
            Exception: If invalid operators are found
        """
        valid_operators = {
            "(",
            ")",
            ",",
            "+",
            "-",
            "*",
            "/",
            "&&",
            "||",
            "&",
            "|",
            ">",
            "<",
            ">=",
            "<=",
            "==",
            "!=",
            "?",
            ":",
            ".",
        }

        # Find potential invalid operators
        pattern = r'([+\-*/,><?:.]{2,})|([><=!&|^`~@#%\\;{}[\]"\'\\]+)'
        found_operators_tuples = re.findall(pattern, expression)
        found_operators = [op for tup in found_operators_tuples for op in tup if op]
        invalid_operators = set(found_operators) - valid_operators

        if invalid_operators:
            raise Exception(f'Invalid operators: "{"".join(invalid_operators)}"')

    def parse(self, expression):
        """Parse a quant-stream expression.

        Args:
            expression: String expression to parse

        Returns:
            Parsed expression with operations converted to function calls

        Raises:
            ParseException: If expression has syntax errors
            Exception: If expression contains invalid operators

        Example:
            >>> parser = ExpressionParser()
            >>> parser.parse("$open + $close")
            'ADD($open, $close)'
            >>> parser.parse("RANK(DELTA($open, 1))")
            'RANK(DELTA($open, 1))'
        """
        self._check_parentheses_balance(expression)
        self._check_for_invalid_operators(expression)

        parsed_result = self.expr.parseString(expression, parseAll=True)[0]
        return parsed_result

    def replace_column_symbols(self, expression, columns):
        """Replace column symbols with their actual names.

        This handles special values like TRUE, FALSE, NAN, NULL and maps
        column names (with or without $ prefix) to their actual variable names.

        Args:
            expression: Parsed expression string
            columns: List of column names to recognize

        Returns:
            Expression with symbols replaced

        Example:
            >>> parser = ExpressionParser()
            >>> parser.replace_column_symbols("$open + NAN", ["$open", "$close"])
            'open + None'
        """
        replace_map = {
            "TRUE": "True",
            "true": "True",
            "FALSE": "False",
            "false": "False",
            "NAN": "None",
            "NaN": "None",
            "nan": "None",
            "NULL": "None",
            "null": "None",
        }

        # Add column mappings (remove $ prefix)
        for col in columns:
            replace_map[col] = col.replace("$", "")

        # Apply replacements
        result = expression
        for var, var_replacement in replace_map.items():
            result = result.replace(var, var_replacement)

        return result


# Module-level convenience function
_default_parser = None


def parse_expression(expression):
    """Parse a quant-stream expression using default parser.

    This is a convenience function that uses a singleton parser instance.

    Args:
        expression: String expression to parse

    Returns:
        Parsed expression with operations converted to function calls

    Example:
        >>> parse_expression("$open + $close * 2")
        'ADD($open, $close*2)'
        >>> parse_expression("RANK(DELTA($open, 1) - DELTA($close, 1))")
        'RANK(SUBTRACT(DELTA($open, 1), DELTA($close, 1)))'
    """
    global _default_parser
    if _default_parser is None:
        _default_parser = ExpressionParser()
    return _default_parser.parse(expression)


if __name__ == "__main__":
    # Test the parser
    test_expressions = [
        "RANK(DELTA($open, 1) - DELTA($open, 1)) / (1e-8 + 1)",
        "$open + $close",
        "$high * $low",
        "SMA($close, 10) > SMA($close, 20)",
        "RANK($volume) & ($close > $open)",
        "TS_MAX($high, 20) - TS_MIN($low, 20)",
    ]

    parser = ExpressionParser()
    for expr in test_expressions:
        try:
            result = parser.parse(expr)
            print(f"Input:  {expr}")
            print(f"Output: {result}")
            print()
        except Exception as e:
            print(f"Error parsing '{expr}': {e}")
            print()
