"""Simple workflow example using run_ml_workflow() with automatic MLflow logging.

This demonstrates the unified workflow approach with direct factor trading (no ML model).
All metrics are logged to MLflow without any manual setup.
"""

from quant_stream.backtest import run_ml_workflow

# Run a simple momentum workflow
# This will automatically:
# 1. Load data
# 2. Calculate the momentum factor
# 3. Use factor values directly as signals (model_config=None)
# 4. Apply TopkDropout strategy
# 5. Run backtest
# 6. Calculate all metrics (returns + IC)
# 7. Log everything to MLflow

result = run_ml_workflow(
    data_path=".data/indian_stock_market_nifty500.csv",  # Required
    factor_expressions=[
        {"name": "momentum", "expression": "DELTA($close, 1)"}
    ],
    model_config=None,  # No ML model - use factors directly
    backtest_segments={
        "train": ["2021-06-01", "2021-12-31"],
        "test": ["2022-01-01", "2022-06-30"],
    },
    strategy_type="TopkDropout",
    strategy_params={"topk": 30, "n_drop": 5, "method": "equal"},
    initial_capital=1_000_000,
    commission=0.001,
    slippage=0.001,
    experiment_name="simple_workflow_demo",
    run_name="momentum_topk30",
)

# Display results
if result["success"]:
    print("=" * 80)
    print("Backtest Results")
    print("=" * 80)
    
    print("\nTRAIN SEGMENT:")
    print("-" * 80)
    train = result["train_metrics"]
    print(f"  Total Return:  {train['total_return']:>7.2%}")
    print(f"  Sharpe Ratio:  {train['sharpe_ratio']:>7.2f}")
    print(f"  IC:            {train['IC']:>7.4f}")
    print(f"  Rank IC:       {train['Rank_IC']:>7.4f}")
    
    print("\nTEST SEGMENT:")
    print("-" * 80)
    test = result["test_metrics"]
    print(f"  Total Return:  {test['total_return']:>7.2%}")
    print(f"  Sharpe Ratio:  {test['sharpe_ratio']:>7.2f}")
    print(f"  IC:            {test['IC']:>7.4f}")
    print(f"  Rank IC:       {test['Rank_IC']:>7.4f}")
    
    print("\n" + "=" * 80)
    print("✓ Results logged to MLflow")
    print("  View: mlflow ui --backend-store-uri sqlite:///mlruns.db")
    print("  Navigate to: http://localhost:5000")
    print("=" * 80)
else:
    print(f"ERROR: {result['error']}")

