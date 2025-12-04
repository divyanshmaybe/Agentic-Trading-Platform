"""Expression-based alpha evaluation demonstration.

This example shows how to use the expression evaluator for rapid alpha prototyping.
Test multiple alpha ideas quickly using string expressions.

This example demonstrates:
1. Expression parsing
2. Automatic evaluation on data
3. Testing multiple alphas
4. Quick backtesting with auto MLflow logging

Usage:
    python examples/alpha_runner.py
    
    # View results
    mlflow ui --backend-store-uri sqlite:///mlruns.db
"""

import pathway as pw
from pathlib import Path

from quant_stream import AlphaEvaluator, parse_expression
from quant_stream.backtest import run_ml_workflow
from quant_stream.data.replayer import replay_market_data


def main():
    """Run expression-based alpha evaluation."""
    print("=" * 80)
    print("Alpha Runner - Expression-Based Evaluation")
    print("=" * 80)
    print()
    
    # Create outputs directory
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    
    # Load market data
    print("Loading market data...")
    table = replay_market_data()
    
    # Create evaluator (auto-detects symbol column)
    evaluator = AlphaEvaluator(table)
    print("  ✓ Evaluator initialized")
    
    # Define alpha expressions to test
    alphas = {
        "momentum_1d": "DELTA($close, 1)",
        "momentum_5d": "DELTA($close, 5)",
        "momentum_rank": "RANK(DELTA($close, 1))",
        "mean_reversion": "($close - SMA($close, 20)) / TS_STD($close, 20)",
        "rsi_centered": "RSI($close, 14) - 50",
        "volume_surge": "DIVIDE($volume, SMA($volume, 20))",
        "vol_adj_momentum": "DIVIDE(DELTA($close, 1), TS_STD($close, 20))",
        "price_vs_sma": "DIVIDE(SUBTRACT($close, SMA($close, 50)), SMA($close, 50))",
    }
    
    print(f"\nTesting {len(alphas)} alpha expressions...")
    print("=" * 80)
    
    backtest_results = {}
    
    for name, expression in alphas.items():
        print(f"\nAlpha: {name}")
        print(f"  Expression: {expression}")
        
        # Parse expression
        parsed = parse_expression(expression)
        print(f"  Parsed: {parsed}")
        
        # Evaluate on data
        result_table = evaluator.evaluate(parsed, factor_name="signal")
        
        # Convert to pandas
        result_df = pw.debug.table_to_pandas(result_table, include_id=False)
        
        # Save to CSV
        output_file = output_dir / f"alpha_{name}.csv"
        result_df.to_csv(output_file, index=False)
        print(f"  ✓ Saved: {output_file}")
        
        # Quick workflow with automatic MLflow logging
        print(f"  Running workflow...")
        
        workflow_result = run_ml_workflow(
            data_path=".data/indian_stock_market_nifty500.csv",
            factor_expressions=[{"name": "signal", "expression": expression}],
            model_config=None,  # No ML model - use factor values directly
            backtest_segments={"train": ["2021-06-01", "2021-12-31"], "test": ["2022-01-01", "2022-06-30"]},
            strategy_type="TopkDropout",
            strategy_params={"topk": 30, "n_drop": 5},
            initial_capital=1_000_000,
            experiment_name="alpha_expression_comparison",
            run_name=f"alpha_{name}",
        )
        
        if workflow_result["success"]:
            test_metrics = workflow_result.get("test_metrics") or workflow_result.get("metrics", {})
            backtest_results[name] = test_metrics
            print(f"  ✓ Test IC: {test_metrics.get('IC', 0):>7.4f}, Sharpe: {test_metrics.get('sharpe_ratio', 0):>6.2f}")
        else:
            print(f"  ✗ Workflow failed: {workflow_result.get('error', 'Unknown error')}")
    
    # Print comparison
    print("\n" + "=" * 80)
    print("Alpha Comparison (Test Set Performance)")
    print("=" * 80)
    print(f"{'Alpha':<25} {'IC':>10} {'Rank IC':>10} {'Sharpe':>10} {'Return':>10}")
    print("-" * 80)
    
    # Sort by IC
    sorted_alphas = sorted(backtest_results.items(), key=lambda x: x[1]["IC"], reverse=True)
    
    for name, metrics in sorted_alphas:
        print(f"{name:<25} {metrics['IC']:>10.4f} {metrics['Rank_IC']:>10.4f} "
              f"{metrics['sharpe_ratio']:>10.2f} {metrics['total_return']:>10.2%}")
    
    # Highlight best alpha
    best_alpha = sorted_alphas[0][0]
    best_ic = sorted_alphas[0][1]["IC"]
    
    print("=" * 80)
    print(f"\n🏆 Best Alpha: {best_alpha}")
    print(f"   Test IC: {best_ic:.4f}")
    print(f"   Sharpe Ratio: {sorted_alphas[0][1]['sharpe_ratio']:.2f}")
    
    print("\n" + "=" * 80)
    print("✓ All results logged to MLflow")
    print("  View experiments: mlflow ui --backend-store-uri sqlite:///mlruns.db")
    print("  Navigate to: http://localhost:5000")
    print("  Experiment: 'alpha_expression_comparison'")
    print("=" * 80)
    
    print("\nNext steps:")
    print("  1. Check CSV files in outputs/ directory")
    print("  2. View MLflow UI to compare all alphas")
    print("  3. Use best alpha in production config")
    print("  4. Try modifying expressions and re-running")


if __name__ == "__main__":
    main()
