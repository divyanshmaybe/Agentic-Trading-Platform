"""Machine learning model training demonstration.

This example shows how to:
1. Create features using quant-stream functions
2. Train multiple ML models (LightGBM, XGBoost, Linear, RandomForest)
3. Compare models using IC metrics
4. Select the best model
5. All with automatic MLflow experiment tracking

Usage:
    python examples/model_training_demo.py
    
    # View results in MLflow
    mlflow ui --backend-store-uri sqlite:///mlruns.db
"""

import pandas as pd
import pathway as pw
from pathlib import Path

from quant_stream import (
    DELTA,
    create_model,
    train_and_evaluate,
    Recorder,
)
from quant_stream.data.replayer import DEFAULT_CSV_PATH
from quant_stream.data.schema import MarketData
from quant_stream.utils.data_split import train_test_split_by_date


def main():
    """Run ML model training comparison."""
    print("=" * 80)
    print("ML Model Training Demo - Automatic MLflow Tracking")
    print("=" * 80)
    print()
    
    # Initialize MLflow recorder
    recorder = Recorder("model_training_demo", tracking_uri="sqlite:///mlruns.db")
    
    with recorder.start_run("model_comparison"):
        recorder.set_tags(demo="model_training", asset_class="equities")
        
        # Load data
        print("Step 1: Loading market data...")
        df = pd.read_csv(DEFAULT_CSV_PATH)
        df['date'] = pd.to_datetime(df['date'])
        
        # Filter to relevant date range
        df = df[(df['date'] >= '2021-06-01') & (df['date'] <= '2022-06-30')]
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        print(f"  Loaded {len(df)} rows")
        
        # Convert to Pathway table
        table = pw.debug.table_from_pandas(df, schema=MarketData)
        
        # Create features
        print("\nStep 2: Creating features...")
        table = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
        features_df = pw.debug.table_to_pandas(table, include_id=False)
        
        # Prepare training data
        print("\nStep 3: Preparing training data...")
        features_df = features_df.sort_values(["symbol", "timestamp"])
        features_df["target"] = features_df.groupby("symbol")["close"].pct_change(1).shift(-1)
        features_df = features_df.dropna(subset=["delta", "target"])
        
        # Ensure timestamp is datetime
        features_df["timestamp"] = pd.to_datetime(features_df["timestamp"], unit="s")
        
        # Train/test split
        train_df, test_df = train_test_split_by_date(
            features_df,
            timestamp_col="timestamp",
            train_start_date="2021-06-01",
            train_end_date="2021-12-31",
            test_start_date="2022-01-01",
            test_end_date="2022-06-30",
        )
        
        feature_cols = ["delta"]
        X_train = train_df[feature_cols]
        y_train = train_df["target"]
        X_test = test_df[feature_cols]
        y_test = test_df["target"]
        
        print(f"  Train: {len(X_train)} samples")
        print(f"  Test:  {len(X_test)} samples")
        
        # Test different models
        print("\nStep 4: Training and comparing models...")
        print("-" * 80)
        
        model_configs = [
            ("LightGBM", {"learning_rate": 0.05, "max_depth": 5, "num_boost_round": 100}),
            ("XGBoost", {"learning_rate": 0.05, "max_depth": 5, "num_boost_round": 100}),
            ("RandomForest", {"n_estimators": 100, "max_depth": 5}),
            ("Linear", {"alpha": 1.0, "method": "ridge"}),
        ]
        
        results = {}
        
        for model_type, params in model_configs:
            print(f"\nTraining {model_type}...")
            
            with recorder.start_run(f"model_{model_type.lower()}", nested=True):
                # Log model config
                recorder.log_params(model_type=model_type, **params)
                
                # Create and train model
                model = create_model(model_type, params)
                model, train_ic, test_ic, validation_ic = train_and_evaluate(
                    model, X_train, y_train, X_test, y_test
                )
                
                # Log metrics
                recorder.log_metrics(
                    train_ic=train_ic["IC"],
                    train_rank_ic=train_ic["Rank_IC"],
                    **(
                        {
                            "validation_ic": validation_ic["IC"],
                            "validation_rank_ic": validation_ic["Rank_IC"],
                        }
                        if validation_ic is not None
                        else {}
                    ),
                    test_ic=test_ic["IC"],
                    test_rank_ic=test_ic["Rank_IC"],
                )
                
                # Print results
                print(f"  Train IC: {train_ic['IC']:>7.4f}, Rank IC: {train_ic['Rank_IC']:>7.4f}")
                if validation_ic is not None:
                    print(f"  Validation IC: {validation_ic['IC']:>7.4f}, Rank IC: {validation_ic['Rank_IC']:>7.4f}")
                print(f"  Test IC:  {test_ic['IC']:>7.4f}, Rank IC: {test_ic['Rank_IC']:>7.4f}")
                
                results[model_type] = {
                    "model": model,
                    "train_ic": train_ic,
                    "validation_ic": validation_ic,
                    "test_ic": test_ic,
                }
        
        # Select best model
        print("\n" + "=" * 80)
        print("Model Comparison")
        print("=" * 80)
        
        best_model_name = max(results, key=lambda k: results[k]["test_ic"]["IC"])
        best_ic = results[best_model_name]["test_ic"]["IC"]
        
        print(f"\nBest Model: {best_model_name}")
        print(f"Test IC: {best_ic:.4f}")
        print(f"Test Rank IC: {results[best_model_name]['test_ic']['Rank_IC']:.4f}")
        
        # Log best model
        recorder.log_params(best_model=best_model_name, best_test_ic=best_ic)
        
        print("\n" + "=" * 80)
        print("✓ All results logged to MLflow")
        print("  View experiments: mlflow ui --backend-store-uri sqlite:///mlruns.db")
        print("  Navigate to: http://localhost:5000")
        print("=" * 80)


if __name__ == "__main__":
    main()
