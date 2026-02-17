"""Demo script showing expression parser usage."""

from quant_stream.factors.parser.expression_parser import ExpressionParser, parse_expression


def main():
    """Demonstrate the expression parser with various examples."""

    print("=" * 80)
    print("Quant-Stream Expression Parser Demo")
    print("=" * 80)
    print()

    # Create a parser instance
    parser = ExpressionParser()

    # Example expressions
    examples = [
        # Basic arithmetic
        ("Basic Addition", "$open + $close"),
        ("Basic Subtraction", "$high - $low"),
        ("Basic Multiplication", "$close * $volume"),
        ("Basic Division", "$close / $open"),
        # Arithmetic with numbers
        ("Constant Addition", "$close + 1"),
        ("Scaling", "$close * 100"),
        # Nested operations
        ("Mid Price", "($high + $low) / 2"),
        ("Price Range Ratio", "($high - $low) / ($high + $low)"),
        # Function calls
        ("Simple Function", "ABS($close)"),
        ("Delta", "DELTA($close, 1)"),
        ("Nested Functions", "RANK(DELTA($close, 1))"),
        # Complex expressions
        ("Alpha Factor", "RANK(DELTA($open, 1) - DELTA($close, 1)) / (1e-8 + 1)"),
        ("Moving Average Cross", "SMA($close, 10) > SMA($close, 20)"),
        # Logical operations
        ("Logical AND", "($close > $open) && ($volume > 1000)"),
        ("Logical OR", "($close > $high) || ($close < $low)"),
        # Technical indicators
        ("Bollinger Band", "($close - SMA($close, 20)) / TS_STD($close, 20)"),
        ("Momentum", "($close - DELAY($close, 10)) / DELAY($close, 10)"),
        ("Volatility", "TS_STD($close, 20) / TS_MEAN($close, 20)"),
        ("Price Range", "TS_MAX($high, 20) - TS_MIN($low, 20)"),
    ]

    # Parse and display each example
    for name, expr in examples:
        print(f"{name}:")
        print(f"  Input:  {expr}")
        try:
            result = parser.parse(expr)
            print(f"  Output: {result}")
        except Exception as e:
            print(f"  Error:  {e}")
        print()

    print("=" * 80)
    print("Column Symbol Replacement Demo")
    print("=" * 80)
    print()

    # Demonstrate column symbol replacement
    columns = ["$open", "$high", "$low", "$close", "$volume"]

    expr = "$close > $open && $volume > NAN"
    print(f"Original Expression: {expr}")
    print(f"Available Columns:   {columns}")
    print()

    parsed = parser.parse(expr)
    print(f"After Parsing:       {parsed}")

    replaced = parser.replace_column_symbols(parsed, columns)
    print(f"After Replacement:   {replaced}")
    print()

    print("=" * 80)
    print("Module-Level Function Demo")
    print("=" * 80)
    print()

    # Demonstrate module-level parse_expression function
    expr = "RANK($volume) & ($close > $open)"
    print("Using parse_expression():")
    print(f"  Input:  {expr}")
    result = parse_expression(expr)
    print(f"  Output: {result}")
    print()

    print("=" * 80)
    print("Real-World Alpha Factor Examples")
    print("=" * 80)
    print()

    alpha_factors = [
        ("Alpha#1", "RANK(TS_ARGMAX($close, 10)) - RANK(TS_ARGMIN($close, 10))"),
        ("Alpha#2", "SIGN(DELTA($close, 1))"),
        ("Alpha#3", "RANK(TS_CORR($close, $volume, 10))"),
        ("Alpha#4", "(-1 * TS_RANK(RANK($close), 10))"),
        ("Mean Reversion", "(SMA($close, 5) - SMA($close, 20)) / TS_STD($close, 20)"),
    ]

    for name, expr in alpha_factors:
        print(f"{name}:")
        print(f"  {expr}")
        result = parse_expression(expr)
        print(f"  → {result}")
        print()


if __name__ == "__main__":
    main()
