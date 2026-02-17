"""Workflow runner for executing end-to-end quantitative research from configuration.

This module orchestrates complete ML-based quant research workflows:
- Load data
- Create alpha factors
- Train ML models
- Run backtests
- Track experiments

Uses general-purpose functions from backtest.runner for data loading and backtesting.
"""

from pathlib import Path
from typing import Optional, Union, Dict, Any, List
import json
import tempfile

import mlflow
import pandas as pd

from quant_stream.config import WorkflowConfig, load_config, load_config_from_dict
from quant_stream.backtest.runner import run_ml_workflow
from quant_stream.recorder import Recorder
from quant_stream.utils.symbol_filter import load_symbols_from_file


def _serialize_dataframe(df: Any) -> Optional[List[Dict[str, Any]]]:
    """Convert a pandas DataFrame into a JSON-serialisable structure."""
    if df is None:
        return None
    if isinstance(df, pd.DataFrame):
        if df.empty:
            return []
        return json.loads(df.to_json(orient="records", date_format="iso"))
    return df


class WorkflowRunner:
    """Execute end-to-end quantitative research workflows from configuration.
    
    Example:
        >>> runner = WorkflowRunner("workflow.yaml")
        >>> results = runner.run()
        >>> print(results["metrics"])
    """
    
    def __init__(
        self,
        config: Union[str, Path, Dict[str, Any], WorkflowConfig],
        verbose: bool = True,
    ):
        """Initialize workflow runner.
        
        Args:
            config: Configuration (file path, dict, or WorkflowConfig object)
            verbose: Whether to print progress messages
        """
        self.verbose = verbose
        
        # Load configuration
        if isinstance(config, (str, Path)):
            self.config = load_config(config)
        elif isinstance(config, dict):
            self.config = load_config_from_dict(config)
        elif isinstance(config, WorkflowConfig):
            self.config = config
        else:
            raise TypeError(f"Invalid config type: {type(config)}")
        
        # Initialize recorder
        self.recorder = Recorder(
            experiment_name=self.config.experiment.name,
            tracking_uri=self.config.experiment.tracking_uri,
        )
        
        self.results = {}
    
    def _print(self, message: str) -> None:
        """Print message if verbose."""
        if self.verbose:
            print(message)
    
    def run(self, output_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """Run complete workflow by delegating to runner.
        
        Args:
            output_path: Optional path to save results CSV
            
        Returns:
            Dictionary with results:
                - config: Configuration used
                - metrics: Performance metrics
                - results_df: Backtest results DataFrame
        """
        run_name = self.config.experiment.run_name or "workflow_run"

        mlflow_current = mlflow.active_run()
        nested_run = mlflow_current is not None

        with self.recorder.start_run(run_name, nested=nested_run):
            # Set tags
            if self.config.experiment.tags is not None:
                self.recorder.set_tags(**self.config.experiment.tags)
            
            self._print("=" * 80)
            self._print("Running ML Workflow")
            self._print("=" * 80)
            
            factor_expressions = self.config.get_all_factor_expressions()
            
            if factor_expressions:
                self._print(f"\nFactors: {len(factor_expressions)}")
                for f in factor_expressions:
                    self._print(f"  - {f['name']}: {f['expression']}")
            
            # Build backtest segments first (can be used for model training too)
            backtest_segments = None
            if self.config.backtest.segments is not None:
                backtest_segments = {
                    "train": self.config.backtest.segments.train,
                    "test": self.config.backtest.segments.test,
                }
                if self.config.backtest.segments.validation is not None:
                    backtest_segments["validation"] = self.config.backtest.segments.validation
            
            model_config = None
            if self.config.model is not None:
                if self.config.model.train_test_split is not None:
                    raise ValueError(
                        "WorkflowConfig.model.train_test_split is no longer supported. "
                        "Define train/validation/test windows under backtest.segments instead."
                    )
                model_config = {
                    "type": self.config.model.type,
                    "features": self.config.model.features,
                    "include_ohlcv": self.config.model.include_ohlcv,
                    "params": self.config.model.params,
                    "target": self.config.model.target,
                }
                self._print(f"\nModel: {self.config.model.type}")
                self._print(f"Parameters: {self.config.model.params}")
            
            self._print(f"\nData: {self.config.data.path}")
            self._print(f"Strategy: {self.config.strategy.type}")
            self._print(f"Initial Capital: ${self.config.backtest.initial_capital:,.0f}")
            self._print("")
            
            # Load symbols if configured
            symbols: Optional[List[str]] = None
            if self.config.data.symbols_file:
                # Load from file
                symbols = load_symbols_from_file(
                    self.config.data.symbols_file,
                    max_symbols=self.config.data.max_symbols
                )
                self._print(f"[INFO] Loaded {len(symbols)} symbols from {self.config.data.symbols_file}")
            elif self.config.data.symbols:
                # Use explicit list
                symbols = self.config.data.symbols
                if self.config.data.max_symbols and len(symbols) > self.config.data.max_symbols:
                    symbols = symbols[:self.config.data.max_symbols]
                self._print(f"[INFO] Using {len(symbols)} symbols from config")
            else:
                # Default to .data/nifty500.txt if no symbols configured
                default_symbols_file = ".data/nifty500.txt"
                symbols = load_symbols_from_file(
                    default_symbols_file,
                    max_symbols=self.config.data.max_symbols
                )
                self._print(f"[INFO] Loaded {len(symbols)} symbols from default file: {default_symbols_file}")
            
            # Call runner's ML workflow function (we handle MLflow ourselves)
            result = run_ml_workflow(
                data_path=str(self.config.data.path),
                symbols=symbols,
                factor_expressions=factor_expressions,
                model_config=model_config,
                strategy_type=self.config.strategy.type,
                strategy_params=self.config.strategy.params,
                initial_capital=self.config.backtest.initial_capital,
                commission=self.config.backtest.commission,
                slippage=self.config.backtest.slippage,
                min_commission=self.config.backtest.min_commission,
                rebalance_frequency=self.config.backtest.rebalance_frequency,
                backtest_segments=backtest_segments,
                symbol_col=self.config.data.symbol_col,
                timestamp_col=self.config.data.timestamp_col,
                log_to_mlflow=False,  # We handle MLflow logging in yaml_runner
                allow_short=getattr(self.config.backtest, 'allow_short', False),
                intraday_short_only=getattr(self.config.backtest, 'intraday_short_only', True),
                short_funding_rate=getattr(self.config.backtest, 'short_funding_rate', 0.0002),
            )
            
            
            if not result["success"]:
                raise RuntimeError(f"Workflow failed: {result['error']}")
            
            # Log to MLflow
            self._log_to_mlflow(result, model_config)
            
            # Print results
            self._print_results(result)
            
            # Save results if requested
            results_df = result["results_df"]
            if output_path:
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                results_df.to_csv(output_path, index=False)
                self._print(f"\nResults saved to: {output_path}")
                self.recorder.log_artifact(str(output_path), artifact_path="backtest")
            
            self._print("\nWorkflow complete!")
            self._print(f"View results: mlflow ui --backend-store-uri {self.config.experiment.tracking_uri}")
            
            holdings_history = _serialize_dataframe(result.get("holdings_df"))
            train_holdings_history = _serialize_dataframe(result.get("train_holdings_df"))
            validation_holdings_history = _serialize_dataframe(result.get("validation_holdings_df"))
            test_holdings_history = _serialize_dataframe(result.get("test_holdings_df"))
            
            return {
                "config": self.config,
                "metrics": result["metrics"],
                "train_metrics": result.get("train_metrics"),
                "validation_metrics": result.get("validation_metrics"),
                "test_metrics": result.get("test_metrics"),
                "results_df": results_df,
                "holdings_df": result.get("holdings_df"),
                "train_holdings_df": result.get("train_holdings_df"),
                "validation_holdings_df": result.get("validation_holdings_df"),
                "test_holdings_df": result.get("test_holdings_df"),
                "holdings_history": holdings_history,
                "train_holdings_history": train_holdings_history,
                "validation_holdings_history": validation_holdings_history,
                "test_holdings_history": test_holdings_history,
                "run_info": result.get("run_info"),
            }
    
    def _log_to_mlflow(self, result: Dict[str, Any], model_config: Optional[Dict[str, Any]]) -> None:
        """Log results to MLflow.
        
        Args:
            result: Result dictionary from run_ml_workflow
            model_config: Model configuration dict
        """
        # Log model training metrics if available
        if "train_ic" in result and result["train_ic"] is not None:
            self.recorder.log_metrics(
                train_ic=result["train_ic"]["IC"],
                train_rank_ic=result["train_ic"]["Rank_IC"],
            )
        if "test_ic" in result and result["test_ic"] is not None:
            self.recorder.log_metrics(
                test_ic=result["test_ic"]["IC"],
                test_rank_ic=result["test_ic"]["Rank_IC"],
            )
        
        # Log model params if model was trained
        if model_config:
            self.recorder.log_params(
                model_type=model_config["type"],
                **model_config["params"]
            )
        
        # Log backtest metrics (with train/test prefixes if available)
        if result.get("train_metrics") is not None and result.get("test_metrics") is not None:
            train_metrics_prefixed = {f"train_{k}": v for k, v in result["train_metrics"].items()}
            test_metrics_prefixed = {f"test_{k}": v for k, v in result["test_metrics"].items()}
            self.recorder.log_metrics(**train_metrics_prefixed)
            self.recorder.log_metrics(**test_metrics_prefixed)
        else:
            self.recorder.log_metrics(**result["metrics"])
        
        # Log strategy and backtest params
        self.recorder.log_params(**self.config.strategy.params)
        self.recorder.log_params(**{f"backtest_{k}": v for k, v in self.config.backtest.model_dump().items()})
        
        # Helper function to log DataFrame as JSON artifact
        def _log_dataframe_as_json(df: pd.DataFrame, name: str, artifact_path: str = "backtest") -> None:
            """Log a DataFrame as a JSON artifact."""
            if df is None or df.empty:
                return
            with tempfile.TemporaryDirectory() as tmpdir:
                file_path = Path(tmpdir) / f"{name}.json"
                df.to_json(file_path, orient="records", date_format="iso", indent=2)
                self.recorder.log_artifact(str(file_path), artifact_path=artifact_path)
        
        # Log daily portfolio values as artifacts
        results_df = result.get("results_df")
        if results_df is not None and not results_df.empty:
            _log_dataframe_as_json(results_df, "daily_portfolio_values", "backtest")
        
        # Log segment-specific portfolio values if available
        train_results_df = result.get("train_results_df")
        if train_results_df is not None and not train_results_df.empty:
            _log_dataframe_as_json(train_results_df, "daily_portfolio_values_train", "backtest")
        
        validation_results_df = result.get("validation_results_df")
        if validation_results_df is not None and not validation_results_df.empty:
            _log_dataframe_as_json(validation_results_df, "daily_portfolio_values_validation", "backtest")
        
        test_results_df = result.get("test_results_df")
        if test_results_df is not None and not test_results_df.empty:
            _log_dataframe_as_json(test_results_df, "daily_portfolio_values_test", "backtest")
        
        # Log holdings as artifacts
        holdings_df = result.get("holdings_df")
        if holdings_df is not None and not holdings_df.empty:
            _log_dataframe_as_json(holdings_df, "daily_holdings", "backtest")
        
        train_holdings_df = result.get("train_holdings_df")
        if train_holdings_df is not None and not train_holdings_df.empty:
            _log_dataframe_as_json(train_holdings_df, "daily_holdings_train", "backtest")
        
        validation_holdings_df = result.get("validation_holdings_df")
        if validation_holdings_df is not None and not validation_holdings_df.empty:
            _log_dataframe_as_json(validation_holdings_df, "daily_holdings_validation", "backtest")
        
        test_holdings_df = result.get("test_holdings_df")
        if test_holdings_df is not None and not test_holdings_df.empty:
            _log_dataframe_as_json(test_holdings_df, "daily_holdings_test", "backtest")
    
    def _print_results(self, result: Dict[str, Any]) -> None:
        """Print workflow results.
        
        Args:
            result: Result dictionary from run_ml_workflow
        """
        self._print("\n" + "=" * 80)
        self._print("Results")
        self._print("=" * 80)
        
        # Print model training results if available
        if "train_ic" in result and result["train_ic"] is not None:
            self._print("\nModel Training:")
            self._print(f"  Train IC: {result['train_ic']['IC']:.4f}, Rank IC: {result['train_ic']['Rank_IC']:.4f}")
            self._print(f"  Test IC:  {result['test_ic']['IC']:.4f}, Rank IC: {result['test_ic']['Rank_IC']:.4f}")
        
        # Print backtest results
        self._print("\nBacktest Performance:")
        if result.get("train_metrics") is not None and result.get("test_metrics") is not None:
            self._print("\n  TRAIN SEGMENT:")
            self._print_metrics_simple(result["train_metrics"])
            self._print("\n  TEST SEGMENT:")
            self._print_metrics_simple(result["test_metrics"])
        else:
            self._print_metrics_simple(result["metrics"])
        
        self._print("=" * 80)
    
    def _print_metrics_simple(self, metrics: Dict[str, float]) -> None:
        """Print metrics in a simple format.
        
        Args:
            metrics: Metrics dictionary
        """
        self._print(f"    Total Return:     {metrics.get('total_return', 0):>10.2%}")
        self._print(f"    Sharpe Ratio:     {metrics.get('sharpe_ratio', 0):>10.2f}")
        self._print(f"    Max Drawdown:     {metrics.get('max_drawdown', 0):>10.2%}")
        if "IC" in metrics:
            self._print(f"    IC:               {metrics.get('IC', 0):>10.4f}")


def run_from_yaml(
    config_path: Union[str, Path],
    output_path: Optional[Union[str, Path]] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Run workflow from YAML configuration file.
    
    Args:
        config_path: Path to YAML configuration file
        output_path: Optional path to save results CSV
        verbose: Whether to print progress messages
        
    Returns:
        Dictionary with results
        
    Example:
        >>> results = run_from_yaml("workflow.yaml", output_path="results.csv")
        >>> print(results["metrics"])
    """
    runner = WorkflowRunner(config_path, verbose=verbose)
    return runner.run(output_path=output_path)
