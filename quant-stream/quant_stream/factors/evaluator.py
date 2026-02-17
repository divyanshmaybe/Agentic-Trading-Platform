"""Expression evaluator for alpha factors.

This module provides functionality to evaluate parsed alpha expressions on Pathway tables.
It bridges the gap between the parsed expression strings and actual function execution.
"""

import re
import pathway as pw
from quant_stream.functions import (
    # Element-wise operations
    ABS,
    SIGN,
    MAX_ELEMENTWISE,
    MIN_ELEMENTWISE,
    IF,
    TERNARY,
    # Time-series operations
    DELTA,
    DELAY,
    # Cross-sectional operations
    RANK,
    MEAN,
    STD,
    SKEW,
    MAX,
    MIN,
    MEDIAN,
    ZSCORE,
    SCALE,
    # Rolling operations
    TS_MAX,
    TS_MIN,
    TS_MEAN,
    TS_MEDIAN,
    TS_SUM,
    TS_STD,
    TS_VAR,
    TS_ARGMAX,
    TS_ARGMIN,
    TS_RANK,
    PERCENTILE,
    TS_ZSCORE,
    TS_MAD,
    TS_QUANTILE,
    TS_PCTCHANGE,
    # Technical indicators
    SMA,
    EMA,
    EWM,
    WMA,
    COUNT,
    SUMIF,
    FILTER,
    PROD,
    DECAYLINEAR,
    MACD,
    RSI,
    BB_MIDDLE,
    BB_UPPER,
    BB_LOWER,
    # Two-column operations
    TS_CORR,
    TS_COVARIANCE,
    HIGHDAY,
    LOWDAY,
    SUMAC,
    REGBETA,
    REGRESI,
    ADD,
    SUBTRACT,
    MULTIPLY,
    DIVIDE,
    AND,
    OR,
    # Mathematical operations
    EXP,
    SQRT,
    LOG,
    INV,
    POW,
    FLOOR,
)


class AlphaEvaluator:
    """Evaluates parsed alpha expressions on Pathway tables.

    This class takes a Pathway table and evaluates alpha factor expressions,
    automatically handling function calls, column references, and nested expressions.

    Example:
        >>> from quant_stream.factors.evaluator import AlphaEvaluator
        >>> from quant_stream.factors.parser.expression_parser import parse_expression
        >>>
        >>> table = replay_market_data()
        >>> evaluator = AlphaEvaluator(table)
        >>>
        >>> expr = parse_expression("DELTA($close, 1)")
        >>> result = evaluator.evaluate(expr, factor_name="momentum")
    """

    # Functions that require by_instrument parameter (time-series and indicators)
    TIMESERIES_FUNCS = {
        "DELTA",
        "DELAY",
        "TS_MAX",
        "TS_MIN",
        "TS_MEAN",
        "TS_MEDIAN",
        "TS_SUM",
        "TS_STD",
        "TS_VAR",
        "TS_ARGMAX",
        "TS_ARGMIN",
        "TS_RANK",
        "PERCENTILE",
        "TS_ZSCORE",
        "TS_MAD",
        "TS_QUANTILE",
        "TS_PCTCHANGE",
        "SMA",
        "EMA",
        "EWM",
        "WMA",
        "COUNT",
        "SUMIF",
        "FILTER",
        "PROD",
        "DECAYLINEAR",
        "MACD",
        "RSI",
        "BB_MIDDLE",
        "BB_UPPER",
        "BB_LOWER",
        "TS_CORR",
        "TS_COVARIANCE",
        "HIGHDAY",
        "LOWDAY",
        "SUMAC",
        "REGBETA",
        "REGRESI",
    }

    # Map of function names to their result column names
    RESULT_COLUMNS = {
        "DELTA": "delta",
        "DELAY": "delayed",
        "SMA": "sma",
        "EMA": "ema",
        "EWM": "ewm",
        "WMA": "wma",
        "RANK": "rank",
        "MEAN": "mean",
        "STD": "std",
        "SKEW": "skew",
        "MAX": "max",
        "MIN": "min",
        "MEDIAN": "median",
        "ZSCORE": "zscore",
        "SCALE": "scaled",
        "TS_MAX": "ts_max",
        "TS_MIN": "ts_min",
        "TS_MEAN": "ts_mean",
        "TS_MEDIAN": "ts_median",
        "TS_SUM": "ts_sum",
        "TS_STD": "ts_std",
        "TS_VAR": "ts_var",
        "TS_ARGMAX": "ts_argmax",
        "TS_ARGMIN": "ts_argmin",
        "TS_RANK": "ts_rank",
        "PERCENTILE": "percentile",
        "TS_ZSCORE": "ts_zscore",
        "TS_MAD": "ts_mad",
        "TS_QUANTILE": "ts_quantile",
        "TS_PCTCHANGE": "ts_pctchange",
        "RSI": "rsi",
        "MACD": "macd",
        "BB_MIDDLE": "bb_middle",
        "BB_UPPER": "bb_upper",
        "BB_LOWER": "bb_lower",
        "TS_CORR": "ts_corr",
        "TS_COVARIANCE": "ts_cov",
        "HIGHDAY": "highday",
        "LOWDAY": "lowday",
        "SUMAC": "sumac",
        "REGBETA": "regbeta",
        "REGRESI": "regresi",
        "COUNT": "count",
        "SUMIF": "sumif",
        "FILTER": "filtered",
        "PROD": "prod",
        "DECAYLINEAR": "decaylinear",
        "ADD": "add",
        "SUBTRACT": "subtract",
        "MULTIPLY": "multiply",
        "DIVIDE": "divide",
        "AND": "and_result",
        "OR": "or_result",
        "ABS": "abs_value",
        "SIGN": "sign_value",
        "EXP": "exp",
        "SQRT": "sqrt",
        "LOG": "log",
        "INV": "inv",
        "POW": "pow",
        "FLOOR": "floor",
        "MAX_ELEMENTWISE": "max_value",
        "MIN_ELEMENTWISE": "min_value",
        "IF": "if_result",
        "TERNARY": "ternary",
    }

    def __init__(self, table: pw.Table, instrument_col: str = None):
        """Initialize evaluator with a data table.

        Args:
            table: Pathway table with market data
            instrument_col: Name of the instrument/symbol column. If None, auto-detects from 'symbol' or 'instrument'
        """
        self.table = table

        # Auto-detect instrument column if not provided
        if instrument_col is None:
            cols = table.column_names()
            if "symbol" in cols:
                self.instrument_col = "symbol"
            elif "instrument" in cols:
                self.instrument_col = "instrument"
            else:
                # Default to None - functions will use their defaults
                self.instrument_col = None
        else:
            self.instrument_col = instrument_col

        # Counter for unique temporary column names (to avoid conflicts with nested functions)
        self._temp_col_counter = 0
        
        # Cache for expression results: maps normalized expression string -> column name
        # This allows reusing computations for identical subexpressions
        self._expression_cache = {}
        
        # PERFORMANCE OPTIMIZATION: Track which columns are actually needed
        # This helps avoid creating unnecessary intermediate columns
        # Set of column names that are needed (final outputs or used by needed columns)
        self._needed_columns = set()
        
        # Core columns that are always needed (metadata + OHLCV)
        self._core_columns = {"symbol", "date", "timestamp", "open", "high", "low", "close", "volume", "instrument"}
        self._needed_columns.update(self._core_columns)
        
        # PERFORMANCE NOTE: Pathway limitation - universe mismatch prevents sorted table reuse
        # When table state changes (columns added/removed), the universe changes
        # sorted_table.prev from one table state cannot be used with another table state
        # Therefore, each rolling operation must sort its own current table
        # The sorted_table parameter in rolling functions is reserved for future intra-operation optimization
        
        # PERFORMANCE OPTIMIZATION: Track intermediate columns created during evaluation
        # These can be pruned after each factor to reduce memory and computation overhead
        self._intermediate_columns: set[str] = set()

        # Map of function names to actual functions
        self.functions = {
            # Element-wise operations
            "ABS": ABS,
            "SIGN": SIGN,
            "MAX_ELEMENTWISE": MAX_ELEMENTWISE,
            "MIN_ELEMENTWISE": MIN_ELEMENTWISE,
            "IF": IF,
            "TERNARY": TERNARY,
            # Time-series operations
            "DELTA": DELTA,
            "DELAY": DELAY,
            # Cross-sectional operations
            "RANK": RANK,
            "MEAN": MEAN,
            "STD": STD,
            "SKEW": SKEW,
            "MAX": MAX,
            "MIN": MIN,
            "MEDIAN": MEDIAN,
            "ZSCORE": ZSCORE,
            "SCALE": SCALE,
            # Rolling operations
            "TS_MAX": TS_MAX,
            "TS_MIN": TS_MIN,
            "TS_MEAN": TS_MEAN,
            "TS_MEDIAN": TS_MEDIAN,
            "TS_SUM": TS_SUM,
            "TS_STD": TS_STD,
            "TS_VAR": TS_VAR,
            "TS_ARGMAX": TS_ARGMAX,
            "TS_ARGMIN": TS_ARGMIN,
            "TS_RANK": TS_RANK,
            "PERCENTILE": PERCENTILE,
            "TS_ZSCORE": TS_ZSCORE,
            "TS_MAD": TS_MAD,
            "TS_QUANTILE": TS_QUANTILE,
            "TS_PCTCHANGE": TS_PCTCHANGE,
            # Technical indicators
            "SMA": SMA,
            "EMA": EMA,
            "EWM": EWM,
            "WMA": WMA,
            "COUNT": COUNT,
            "SUMIF": SUMIF,
            "FILTER": FILTER,
            "PROD": PROD,
            "DECAYLINEAR": DECAYLINEAR,
            "MACD": MACD,
            "RSI": RSI,
            "BB_MIDDLE": BB_MIDDLE,
            "BB_UPPER": BB_UPPER,
            "BB_LOWER": BB_LOWER,
            # Two-column operations
            "TS_CORR": TS_CORR,
            "TS_COVARIANCE": TS_COVARIANCE,
            "HIGHDAY": HIGHDAY,
            "LOWDAY": LOWDAY,
            "SUMAC": SUMAC,
            "REGBETA": REGBETA,
            "REGRESI": REGRESI,
            "ADD": ADD,
            "SUBTRACT": SUBTRACT,
            "MULTIPLY": MULTIPLY,
            "DIVIDE": DIVIDE,
            "AND": AND,
            "OR": OR,
            # Mathematical operations
            "EXP": EXP,
            "SQRT": SQRT,
            "LOG": LOG,
            "INV": INV,
            "POW": POW,
            "FLOOR": FLOOR,
        }

    def _parse_function_call(self, expr: str) -> tuple:
        """Parse a function call expression.

        Args:
            expr: Function call string like "DELTA($close, 1)"

        Returns:
            Tuple of (function_name, args_list)
        """
        expr = expr.strip()
        if not expr or "(" not in expr or not expr[0].isalpha():
            return None, None

        # Find the first opening parenthesis that starts the call
        first_paren = expr.find("(")
        func_name = expr[:first_paren].strip()

        if not func_name.isidentifier():
            return None, None

        args_str = expr[first_paren + 1 :]
        depth = 1
        closing_index = None

        for idx, ch in enumerate(args_str):
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    closing_index = idx
                    break

        if closing_index is None:
            return None, None

        # Ensure there are no trailing characters after the closing parenthesis
        trailing = args_str[closing_index + 1 :].strip()
        if trailing:
            return None, None

        args_section = args_str[:closing_index]

        # Parse arguments (simple split by comma, accounting for nested parens)
        args = []
        depth = 0
        current_arg = ""

        for char in args_section:
            if char in "([{":
                depth += 1
                current_arg += char
            elif char in ")]}":
                depth -= 1
                current_arg += char
            elif char == "," and depth == 0:
                args.append(current_arg.strip())
                current_arg = ""
            else:
                current_arg += char

        if current_arg.strip():
            args.append(current_arg.strip())

        return func_name, args

    def _is_column_ref(self, expr: str) -> bool:
        """Check if expression is a pure column reference (no operators or expressions)."""
        if not expr.startswith("$"):
            return False
        # Check if it's ONLY a column reference (no operators, spaces after the $)
        col_name = expr[1:]  # Remove the $
        # A valid column reference should be alphanumeric + underscores only
        return col_name.replace("_", "").isalnum() and col_name in self.table.column_names()

    def _get_column_ref(self, col_name: str):
        """Convert column name to Pathway column reference."""
        col_name = col_name.strip("$")
        return pw.this[col_name]

    def _is_number(self, s: str) -> bool:
        """Check if string is a number."""
        try:
            float(s)
            return True
        except (ValueError, AttributeError):
            return False

    def _apply_unary_minus(
        self, table: pw.Table, column_name: str | float | int
    ) -> tuple[pw.Table, str | float | int]:
        """Apply unary minus to either a column or literal value."""
        if isinstance(column_name, (int, float, str)) and self._is_number(
            str(column_name)
        ):
            # Literal number - simply return as string with minus applied
            value = float(column_name)
            # Preserve int formatting when possible
            if float(value).is_integer():
                return table, str(int(-value))
            return table, str(-value)

        if not isinstance(column_name, str):
            raise ValueError("Unary minus requires a column name or numeric literal.")

        self._temp_col_counter += 1
        result_col = f"_negate_{self._temp_col_counter}"

        result_table = table.select(
            *pw.this,
            **{
                result_col: pw.apply_with_type(
                    lambda x: -x if x is not None else None,
                    float | None,
                    pw.this[column_name],
                )
            },
        )

        self.table = result_table
        return result_table, result_col

    def evaluate(self, expr: str, factor_name: str = "alpha") -> pw.Table:
        """Evaluate a parsed alpha expression.

        Args:
            expr: Parsed expression string
            factor_name: Name for the output factor column

        Returns:
            Table with the computed factor
        """
        # Mark this factor name as needed (it's a final output)
        self._needed_columns.add(factor_name)
        # First, check if it's a simple arithmetic expression with columns
        if not any(func in expr for func in self.functions.keys()):
            # Simple expression - use table.select
            # Replace $column with pw.this.column
            eval_expr = expr
            for col in [
                "symbol",
                "date",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "instrument",
            ]:
                eval_expr = eval_expr.replace(f"${col}", f"pw.this.{col}")

            result = self.table.select(*pw.this, **{factor_name: eval(eval_expr)})
            return result

        # Complex expression with functions
        result_table, result_col = self._evaluate_expr(expr)

        # Rename result column to factor_name
        # Note: We keep temporary/cached columns in the table for reuse in future factors
        # They will be filtered out later when selecting feature columns
        if result_col != factor_name:
            existing_columns = set(result_table.column_names())
            if factor_name in existing_columns:
                result_table = result_table.select(
                    *pw.this.without(pw.this[factor_name]),
                    **{factor_name: pw.this[result_col]},
                )
            else:
                result_table = result_table.select(
                    *pw.this,
                    **{factor_name: pw.this[result_col]},
                )

        return result_table

    def _evaluate_expr(self, expr: str) -> tuple:
        """Recursively evaluate an expression.

        Returns:
            Tuple of (result_table, result_column_name)
        """
        # Normalize expression (strip whitespace and outer parentheses)
        expr = expr.strip()
        
        # Strip outer parentheses if present (before caching and parsing)
        while expr.startswith("(") and expr.endswith(")"):
            # Check if these are matching outer parens
            depth = 0
            is_outer = True
            for i, char in enumerate(expr):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                # If depth reaches 0 before the end, these aren't outer parens
                if depth == 0 and i < len(expr) - 1:
                    is_outer = False
                    break
            if is_outer:
                expr = expr[1:-1].strip()
            else:
                break
        
        normalized_expr = expr
        
        # Check cache first - if we've already computed this exact expression, reuse it
        if normalized_expr in self._expression_cache:
            cached_col = self._expression_cache[normalized_expr]
            # Verify the cached column actually exists in the current table
            if cached_col in self.table.column_names():
                # Mark cached column as needed since we're reusing it
                self._needed_columns.add(cached_col)
                print(f"[CACHE HIT] Reusing column '{cached_col}' for expression: {normalized_expr[:50]}...", flush=True)
                return self.table, cached_col
            else:
                # Column was cached but doesn't exist in current table - remove from cache
                print(f"[CACHE INVALIDATED] Column '{cached_col}' not in table, recomputing: {normalized_expr[:50]}...", flush=True)
                del self._expression_cache[normalized_expr]
        
        # Handle unary minus explicitly (e.g., "-RANK(...)", "-$close")
        if normalized_expr.startswith("-") and not self._is_number(normalized_expr):
            sub_expr = normalized_expr[1:].lstrip()
            if not sub_expr:
                raise ValueError("Unary minus must be followed by an expression.")
            sub_table, sub_col = self._evaluate_expr(sub_expr)
            result_table, result_col = self._apply_unary_minus(sub_table, sub_col)
            # Mark sub_col as needed since we used it
            self._needed_columns.add(sub_col)
            self._needed_columns.add(result_col)
            self._expression_cache[normalized_expr] = result_col
            return result_table, result_col

        # Check if it's a function call
        func_name, args = self._parse_function_call(expr)

        if func_name is None:
            # Not a function call - could be a column reference, constant, or inline expression
            if self._is_column_ref(expr):
                col_name = expr.strip("$")
                # Mark referenced column as needed
                self._needed_columns.add(col_name)
                return self.table, col_name
            
            # Check if it's a pure number
            if self._is_number(expr):
                # Return as-is (will be handled by the calling function)
                return self.table, expr
            
            # It's an inline arithmetic expression (should only contain $columns, numbers, and operators)
            # PERFORMANCE OPTIMIZATION: Only create intermediate column if it's actually needed
            # Check if this expression is used by a needed column (will be determined by caller)
            import hashlib
            expr_hash = hashlib.md5(expr.encode()).hexdigest()[:8]
            col_name = f"_inline_{expr_hash}"
            
            # Check if we already created this column
            if col_name in self.table.column_names():
                # Mark as needed since we're using it
                self._needed_columns.add(col_name)
                return self.table, col_name
            
            # Check if this intermediate is actually needed
            # For now, we'll create it but could optimize further by tracking dependencies
            # TODO: Implement dependency tracking to skip truly unused intermediates
            
            # Replace $column with pw.this.column and evaluate
            eval_expr = expr

            # Identify top-level function calls so we evaluate them separately and
            # replace them with their resulting column references before inline eval.
            def _find_top_level_function_calls(expression: str) -> list[tuple[int, int, str]]:
                results: list[tuple[int, int, str]] = []
                length = len(expression)
                idx = 0
                while idx < length:
                    ch = expression[idx]
                    if ch.isalpha() or ch == "_":
                        j = idx
                        while j < length and (expression[j].isalnum() or expression[j] == "_"):
                            j += 1
                        func_name = expression[idx:j]
                        if func_name in self.functions:
                            k = j
                            while k < length and expression[k].isspace():
                                k += 1
                            if k < length and expression[k] == "(":
                                depth = 1
                                m = k + 1
                                while m < length and depth > 0:
                                    if expression[m] == "(":
                                        depth += 1
                                    elif expression[m] == ")":
                                        depth -= 1
                                    m += 1
                                if depth == 0:
                                    results.append((idx, m, expression[idx:m]))
                                    idx = m
                                    continue
                    idx += 1
                return results

            func_calls = _find_top_level_function_calls(eval_expr)
            for start, end, call_expr in reversed(func_calls):
                # Avoid infinite recursion if the entire expression is just the call
                if call_expr.strip() == expr.strip():
                    continue
                _, call_col = self._evaluate_expr(call_expr)
                eval_expr = (
                    eval_expr[:start]
                    + f"pw.this.{call_col}"
                    + eval_expr[end:]
                )

            for col in self.table.column_names():
                eval_expr = eval_expr.replace(f"${col}", f"pw.this.{col}")

            has_comparison = any(op in eval_expr for op in ["<=", ">=", "<", ">"])
            if has_comparison:
                def _wrap_match(match: re.Match) -> str:
                    column_name = match.group(1)
                    return f"pw.coalesce(pw.this.{column_name}, 0.0)"

                eval_expr = re.sub(
                    r"pw\.this\.(\w+)",
                    _wrap_match,
                    eval_expr,
                )
            
            # Create the column
            try:
                new_table = self.table.select(
                    *pw.this,
                    **{col_name: eval(eval_expr)}
                )
                self.table = new_table
                
                # Mark as needed since we created it
                self._needed_columns.add(col_name)
                
                # Cache this inline expression
                self._expression_cache[normalized_expr] = col_name
                print(f"[CACHE STORE] Cached inline column '{col_name}' for expression: {normalized_expr[:50]}...", flush=True)
                
                return new_table, col_name
            except Exception as e:
                error_msg = str(e)
                unary_expr = normalized_expr.lstrip()
                if unary_expr.startswith("-") and not self._is_number(unary_expr) and "unary operator neg" in error_msg.lower():
                    sub_expr = unary_expr[1:].lstrip()
                    if not sub_expr:
                        raise ValueError("Unary minus must be followed by an expression.") from e
                    sub_table, sub_col = self._evaluate_expr(sub_expr)
                    result_table, result_col = self._apply_unary_minus(sub_table, sub_col)
                    # Mark sub_col and result_col as needed
                    self._needed_columns.add(sub_col)
                    self._needed_columns.add(result_col)
                    self._expression_cache[normalized_expr] = result_col
                    print(f"[CACHE STORE] Cached inline column '{result_col}' for expression: {normalized_expr[:50]}...", flush=True)
                    return result_table, result_col
                raise ValueError(f"Failed to evaluate inline expression '{expr}': {e}") from e

        # It's a function call - evaluate arguments first
        if func_name not in self.functions:
            raise ValueError(f"Unknown function: {func_name}")

        # PERFORMANCE NOTE: Expression-level optimizations removed
        # They were adding overhead without significant benefit since Pathway
        # still computes all intermediate columns in the dependency chain.
        # The real optimization needs to happen at Pathway's execution level.
        
        # Special case: MAX/MIN with multiple arguments should use element-wise versions
        # MAX(a, b) or MAX(a, b, c) -> MAX_ELEMENTWISE
        # MIN(a, b) or MIN(a, b, c) -> MIN_ELEMENTWISE
        if func_name in ["MAX", "MIN"] and len(args) >= 2:
            func_name = f"{func_name}_ELEMENTWISE"
            if func_name not in self.functions:
                raise ValueError(f"Unknown function: {func_name}")

        func = self.functions[func_name]

        # Process arguments
        processed_args = []
        current_table = self.table

        for arg in args:
            arg = arg.strip()
            # Note: outer parentheses are now stripped in _evaluate_expr, not here

            if self._is_number(arg):
                # Numeric argument
                # Try to parse as int first, then float
                try:
                    processed_args.append(int(arg))
                except ValueError:
                    processed_args.append(float(arg))
            elif self._is_column_ref(arg):
                # Column reference
                col_name = arg.strip("$")
                # Mark referenced column as needed
                self._needed_columns.add(col_name)
                processed_args.append(self._get_column_ref(arg))
            elif self._parse_function_call(arg)[0] is not None:
                # Nested function call - evaluate it first
                arg_table, arg_col = self._evaluate_expr(arg)
                
                # Mark nested result as needed since we're using it
                self._needed_columns.add(arg_col)
                
                # The function already returns a unique column name (from ALWAYS rename logic)
                # So we just use it directly - no additional renaming needed
                current_table = arg_table
                processed_args.append(pw.this[arg_col])
            else:
                # Try to parse as a literal or expression
                if (
                    arg.replace(".", "")
                    .replace("-", "")
                    .replace("+", "")
                    .replace("e", "")
                    .replace("E", "")
                    .isdigit()
                ):
                    processed_args.append(float(arg))
                else:
                    # It's a complex expression (e.g., "$volume * DELTA($close, 5)")
                    # Recursively evaluate it using _evaluate_expr
                    try:
                        arg_table, arg_col = self._evaluate_expr(arg)
                        # Mark complex expression result as needed since we're using it
                        self._needed_columns.add(arg_col)
                        current_table = arg_table
                        processed_args.append(pw.this[arg_col])
                    except Exception as e:
                        raise ValueError(f"Failed to evaluate argument '{arg}': {e}")

        # Call the function
        # Add by_instrument parameter for functions that group by instrument
        if func_name in self.TIMESERIES_FUNCS and self.instrument_col:
            # Pass the instrument column dynamically
            # Rolling functions handle their own sorting internally to ensure universe alignment
            result_table = func(
                current_table,
                *processed_args,
                by_instrument=pw.this[self.instrument_col],
            )
        else:
            result_table = func(current_table, *processed_args)

        result_col = self.RESULT_COLUMNS.get(func_name, "result")
        
        # ALWAYS rename function result columns to unique names
        # This prevents Pathway "duplicate column" errors when:
        # 1. The same function is called multiple times (e.g., TS_PCTCHANGE twice)
        # 2. Nested expressions build up intermediate columns
        # We use a unique counter-based name for each function call result
        self._temp_col_counter += 1
        unique_col = f"_{result_col}_{self._temp_col_counter}"
        
        # Rename the result column
        result_table = result_table.select(
            *pw.this.without(pw.this[result_col]),
            **{unique_col: pw.this[result_col]}
        )
        result_col = unique_col
        
        # Update global table state with new column
        self.table = result_table
        
        # Mark as needed since we created it
        self._needed_columns.add(result_col)
        
        # PERFORMANCE: Track intermediate columns (those starting with _)
        if result_col.startswith("_") and result_col not in self._core_columns:
            self._intermediate_columns.add(result_col)
        
        # Cache this expression result for future reuse
        self._expression_cache[normalized_expr] = result_col
        print(f"[CACHE STORE] Cached column '{result_col}' for expression: {normalized_expr[:50]}...", flush=True)

        return result_table, result_col
    
    def get_needed_columns(self) -> set[str]:
        """Get the set of columns that are actually needed.
        
        This includes:
        - Final factor output columns
        - Columns used in the dependency chain
        - Core data columns (symbol, timestamp, OHLCV)
        
        Returns:
            Set of column names that are needed
        """
        return self._needed_columns.copy()
    
    def reset_needed_columns(self):
        """Reset the needed columns tracking (useful when starting new factor evaluation)."""
        self._needed_columns = set(self._core_columns)
    
    def prune_intermediate_columns(self, keep_factor_columns: set[str] | None = None) -> pw.Table:
        """
        Remove intermediate columns that are no longer needed.
        
        PERFORMANCE OPTIMIZATION: After each factor is computed, we can remove
        intermediate columns (those starting with _) that aren't needed for future factors.
        This reduces memory and computation overhead.
        
        IMPORTANT: This function ONLY removes intermediate columns (those starting with _).
        It NEVER removes factor columns or core columns, even if they're not explicitly
        in keep_factor_columns.
        
        Args:
            keep_factor_columns: Set of factor column names to keep (final outputs)
            
        Returns:
            Table with intermediate columns removed (factor and core columns always kept)
        """
        if keep_factor_columns is None:
            keep_factor_columns = set()
        
        # Columns to keep: core columns + factor outputs + any cached expressions still in use
        columns_to_keep = set(self._core_columns)
        columns_to_keep.update(keep_factor_columns)
        
        # Also keep columns that are marked as needed (used by future factors)
        columns_to_keep.update(self._needed_columns)
        
        # Get all current columns
        all_columns = set(self.table.column_names())
        
        # DEBUG: Log what columns we have before pruning
        factor_cols_before = [col for col in all_columns if col not in self._core_columns and not col.startswith("_")]
        if factor_cols_before:
            print(f"[DEBUG] Factor columns in table before pruning: {sorted(factor_cols_before)}", flush=True)
        
        # CRITICAL: Also keep any columns that don't start with _ (these are factor outputs or core columns)
        # We never remove non-intermediate columns, even if not explicitly listed
        for col in all_columns:
            if not col.startswith("_"):
                columns_to_keep.add(col)
        
        # Identify intermediate columns to remove (start with _ but not in keep set)
        intermediate_to_remove = [
            col for col in all_columns
            if col.startswith("_") and col not in columns_to_keep
        ]
        
        if not intermediate_to_remove:
            # No intermediate columns to remove
            return self.table
        
        # Build select dict with only columns to keep
        select_dict = {col: pw.this[col] for col in columns_to_keep if col in all_columns}
        
        # DEBUG: Verify factor columns are in select_dict
        factor_cols_after = [col for col in select_dict.keys() if col not in self._core_columns and not col.startswith("_")]
        if factor_cols_after:
            print(f"[DEBUG] Factor columns kept after pruning: {sorted(factor_cols_after)}", flush=True)
        
        # Remove intermediate columns only
        pruned_table = self.table.select(**select_dict)
        
        # Update tracked intermediate columns
        self._intermediate_columns -= set(intermediate_to_remove)
        
        print(f"[PERF] Pruned {len(intermediate_to_remove)} intermediate columns, kept {len(select_dict)} columns", flush=True)
        
        return pruned_table
    