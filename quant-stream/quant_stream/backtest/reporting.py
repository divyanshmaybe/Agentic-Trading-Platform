"""Performance metrics reporting and formatting."""

from typing import Dict, Any, Optional, TextIO
import sys
import pandas as pd


def format_metric(value: float, format_type: str = "number") -> str:
    """Format a metric value for display.
    
    Args:
        value: Metric value
        format_type: Type of formatting ('number', 'percent', 'ratio')
        
    Returns:
        Formatted string
    """
    if format_type == "percent":
        return f"{value:>10.2%}"
    elif format_type == "ratio":
        return f"{value:>10.2f}"
    else:  # number
        return f"{value:>10.4f}"


def print_metrics_summary(
    metrics: Dict[str, float],
    title: str = "Performance Metrics",
    file: Optional[TextIO] = None,
) -> None:
    """Print a formatted summary of performance metrics.
    
    Args:
        metrics: Dictionary of metrics
        title: Title for the summary
        file: Output file (default: sys.stdout)
        
    Example:
        >>> metrics = calculate_returns_metrics(returns)
        >>> print_metrics_summary(metrics)
    """
    if file is None:
        file = sys.stdout
    
    # Print header
    print("=" * 80, file=file)
    print(title.center(80), file=file)
    print("=" * 80, file=file)
    
    # Define metric categories and their formatting
    metric_definitions = {
        # Returns
        "total_return": ("Total Return", "percent"),
        "annual_return": ("Annual Return", "percent"),
        "annual_volatility": ("Annual Volatility", "percent"),
        
        # Risk-adjusted returns
        "sharpe_ratio": ("Sharpe Ratio", "ratio"),
        "sortino_ratio": ("Sortino Ratio", "ratio"),
        "calmar_ratio": ("Calmar Ratio", "ratio"),
        
        # Risk metrics
        "max_drawdown": ("Max Drawdown", "percent"),
        
        # Win/loss statistics
        "win_rate": ("Win Rate", "percent"),
        "avg_win": ("Average Win", "percent"),
        "avg_loss": ("Average Loss", "percent"),
        "profit_factor": ("Profit Factor", "ratio"),
        
        # IC metrics (from backtest - signal vs forward return)
        "IC": ("IC (Signal Predictive Power)", "number"),
        "Rank_IC": ("Rank IC", "number"),
        "ICIR": ("IC Information Ratio", "ratio"),
        "Rank_ICIR": ("Rank ICIR", "ratio"),
        
        # Model IC metrics (from training - model predictions vs actual)
        "train_ic": ("Train IC (Model)", "number"),
        "train_rank_ic": ("Train Rank IC (Model)", "number"),
        "test_ic": ("Test IC (Model)", "number"),
        "test_rank_ic": ("Test Rank IC (Model)", "number"),
        
        # Benchmark metrics
        "alpha": ("Alpha (vs Benchmark)", "percent"),
        "beta": ("Beta (vs Benchmark)", "ratio"),
        "tracking_error": ("Tracking Error", "percent"),
        "information_ratio": ("Information Ratio", "ratio"),
    }
    
    # Print metrics by category
    categories = {
        "Returns": ["total_return", "annual_return", "annual_volatility"],
        "Risk-Adjusted Returns": ["sharpe_ratio", "sortino_ratio", "calmar_ratio"],
        "Risk Metrics": ["max_drawdown"],
        "Win/Loss Statistics": ["win_rate", "avg_win", "avg_loss", "profit_factor"],
        "Signal Predictive Power": ["IC", "Rank_IC", "ICIR", "Rank_ICIR"],
        "Model Performance": ["train_ic", "train_rank_ic", "test_ic", "test_rank_ic"],
        "Benchmark Comparison": ["alpha", "beta", "tracking_error", "information_ratio"],
    }
    
    for category, metric_keys in categories.items():
        # Check if any metrics in this category exist
        has_metrics = any(key in metrics for key in metric_keys)
        if not has_metrics:
            continue
        
        print(f"\n{category}:", file=file)
        print("-" * 80, file=file)
        
        for key in metric_keys:
            if key in metrics:
                label, fmt = metric_definitions.get(key, (key.replace("_", " ").title(), "number"))
                formatted_value = format_metric(metrics[key], fmt)
                print(f"  {label:<30} {formatted_value}", file=file)
    
    print("=" * 80, file=file)


def generate_metrics_report(
    metrics: Dict[str, float],
    results_df: Optional[pd.DataFrame] = None,
    output_path: Optional[str] = None,
) -> str:
    """Generate a comprehensive metrics report in markdown format.
    
    Args:
        metrics: Dictionary of metrics
        results_df: Optional backtest results DataFrame
        output_path: Optional path to save report
        
    Returns:
        Markdown-formatted report string
        
    Example:
        >>> report = generate_metrics_report(metrics, results_df)
        >>> with open("report.md", "w") as f:
        ...     f.write(report)
    """
    lines = []
    
    # Title
    lines.append("# Backtest Performance Report")
    lines.append("")
    
    # Summary statistics
    lines.append("## Summary Statistics")
    lines.append("")
    
    if results_df is not None and len(results_df) > 0:
        lines.append(f"- **Number of Periods**: {len(results_df)}")
        lines.append(f"- **Start Date**: {results_df['timestamp'].min()}")
        lines.append(f"- **End Date**: {results_df['timestamp'].max()}")
        
        if "portfolio_value" in results_df.columns:
            final_value = results_df["portfolio_value"].iloc[-1]
            initial_value = results_df["portfolio_value"].iloc[0]
            lines.append(f"- **Initial Value**: ${initial_value:,.2f}")
            lines.append(f"- **Final Value**: ${final_value:,.2f}")
        
        lines.append("")
    
    # Performance metrics
    lines.append("## Performance Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    
    key_metrics = [
        ("Total Return", "total_return", "percent"),
        ("Annual Return", "annual_return", "percent"),
        ("Annual Volatility", "annual_volatility", "percent"),
        ("Sharpe Ratio", "sharpe_ratio", "ratio"),
        ("Sortino Ratio", "sortino_ratio", "ratio"),
        ("Max Drawdown", "max_drawdown", "percent"),
        ("Calmar Ratio", "calmar_ratio", "ratio"),
        ("Win Rate", "win_rate", "percent"),
        ("Profit Factor", "profit_factor", "ratio"),
    ]
    
    for label, key, fmt in key_metrics:
        if key in metrics:
            if fmt == "percent":
                value_str = f"{metrics[key]:.2%}"
            else:
                value_str = f"{metrics[key]:.4f}"
            lines.append(f"| {label} | {value_str} |")
    
    lines.append("")
    
    # IC metrics (if available)
    ic_metrics = ["IC", "Rank_IC", "test_ic", "test_rank_ic"]
    if any(key in metrics for key in ic_metrics):
        lines.append("## Information Coefficient")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        
        for key in ic_metrics:
            if key in metrics:
                label = key.replace("_", " ").title()
                lines.append(f"| {label} | {metrics[key]:.4f} |")
        
        lines.append("")
    
    # Write to file if requested
    report = "\n".join(lines)
    
    if output_path:
        with open(output_path, "w") as f:
            f.write(report)
    
    return report


def print_backtest_summary(
    results_df: pd.DataFrame,
    metrics: Dict[str, float],
    config: Optional[Dict[str, Any]] = None,
    file: Optional[TextIO] = None,
) -> None:
    """Print a comprehensive backtest summary.
    
    Args:
        results_df: Backtest results DataFrame
        metrics: Performance metrics
        config: Optional configuration dictionary
        file: Output file (default: sys.stdout)
    """
    if file is None:
        file = sys.stdout
    
    print("\n" + "=" * 80, file=file)
    print("BACKTEST SUMMARY".center(80), file=file)
    print("=" * 80, file=file)
    
    # Configuration
    if config:
        print("\nConfiguration:", file=file)
        print("-" * 80, file=file)
        if "strategy" in config:
            print(f"  Strategy: {config['strategy']}", file=file)
        if "initial_capital" in config:
            print(f"  Initial Capital: ${config['initial_capital']:,.2f}", file=file)
        if "commission" in config:
            print(f"  Commission: {config['commission']:.3%}", file=file)
        if "slippage" in config:
            print(f"  Slippage: {config['slippage']:.3%}", file=file)
    
    # Period information
    if len(results_df) > 0:
        print("\nPeriod Information:", file=file)
        print("-" * 80, file=file)
        print(f"  Start Date: {results_df['timestamp'].min()}", file=file)
        print(f"  End Date: {results_df['timestamp'].max()}", file=file)
        print(f"  Number of Periods: {len(results_df)}", file=file)
        
        if "portfolio_value" in results_df.columns:
            print(f"  Initial Value: ${results_df['portfolio_value'].iloc[0]:,.2f}", file=file)
            print(f"  Final Value: ${results_df['portfolio_value'].iloc[-1]:,.2f}", file=file)
    
    # Print metrics
    print("", file=file)
    print_metrics_summary(metrics, title="Performance Metrics", file=file)
    
    print("", file=file)

