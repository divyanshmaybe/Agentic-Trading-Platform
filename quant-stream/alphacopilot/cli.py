"""Command-line interface for alphacopilot."""

import sys
from typing import Optional, List
import fire
import asyncio

from alphacopilot.graph import create_workflow_graph, is_langsmith_enabled, get_langsmith_project
from alphacopilot.types import WorkflowState, Trace
from alphacopilot.mcp_client import create_mcp_tools
from quant_stream.recorder import Recorder


class AlphaCopilotCLI:
    """Command-line interface for AlphaCopilot factor generation."""

    def _create_library_tools(self):
        """Create mock MCP tools that use library functions directly.

        This uses low-level library functions for fastest execution.
        Good for debugging and when you don't need async/distributed features.

        Returns synchronous execution results DIRECTLY (no job_id).
        """
        from quant_stream.mcp_server.tools.validator import validate_factor_expressions
        from quant_stream.mcp_server.tools.workflow import run_ml_workflow_sync

        class LibraryTool:
            """Mock tool that wraps library functions directly."""
            def __init__(self, name, func):
                self.name = name
                self.func = func
                self.description = func.__doc__ or ""
                self.execution_mode = "sync"  # Mark as synchronous

            async def ainvoke(self, args):
                """Async invoke that calls sync function and returns result directly."""
                # Handle different function signatures
                if self.name == "validate_factors":
                    # validate_factor_expressions expects factor_expressions list
                    if isinstance(args, dict) and "factor_expressions" in args:
                        result = self.func(args["factor_expressions"])
                    else:
                        result = self.func(args)
                else:
                    # run_ml_workflow_sync expects request_data dict
                    result = self.func(args)

                # Return result directly for synchronous execution
                # No job_id wrapping - the caller should detect sync mode
                return result

        # Create tools list
        tools = [
            LibraryTool("validate_factors", validate_factor_expressions),
            LibraryTool("run_ml_workflow", run_ml_workflow_sync),
        ]

        return tools

    def _create_binary_tools(self):
        """Create mock MCP tools that use quant-stream workflow runner.

        This uses the same workflow runner as library backend, but wrapped
        to provide a "binary-like" interface (high-level, stable API).
        Has full feature parity with MCP and library backends.

        Returns synchronous execution results DIRECTLY (no job_id).
        """
        from quant_stream.mcp_server.tools.validator import validate_factor_expressions
        from quant_stream.mcp_server.tools.workflow import run_ml_workflow_sync

        class BinaryTool:
            """Mock tool that wraps workflow runner with stable API."""
            def __init__(self, name, func):
                self.name = name
                self.func = func
                self.description = func.__doc__ or ""
                self.execution_mode = "sync"  # Mark as synchronous

            async def ainvoke(self, args):
                """Async invoke that calls sync function and returns result directly."""
                # Handle different function signatures
                if self.name == "validate_factors":
                    # validate_factor_expressions expects factor_expressions list
                    if isinstance(args, dict) and "factor_expressions" in args:
                        result = self.func(args["factor_expressions"])
                    else:
                        result = self.func(args)
                else:
                    # run_ml_workflow_sync expects request_data dict
                    result = self.func(args)

                # Return result directly for synchronous execution
                # No job_id wrapping - the caller should detect sync mode
                return result

        # Create tools list - same functions as library, just different label
        tools = [
            BinaryTool("validate_factors", validate_factor_expressions),
            BinaryTool("run_ml_workflow", run_ml_workflow_sync),
        ]

        return tools

    def run(
        self,
        hypothesis: str,
        custom_factors: Optional[List[str]] = None,
        model_type: str = "LightGBM",
        data_path: Optional[str] = None,
        symbol_col: str = "symbol",
        timestamp_col: str = "timestamp",
        symbols_file: Optional[str] = ".data/nifty500.txt",
        max_symbols: Optional[int] = None,
        train_start_date: Optional[str] = None,
        train_end_date: Optional[str] = None,
        test_start_date: Optional[str] = None,
        test_end_date: Optional[str] = None,
        validation_start_date: Optional[str] = None,
        validation_end_date: Optional[str] = None,
        max_iterations: int = 3,
        backend: str = "library",
        mcp_server: Optional[str] = None,  # Default: http://127.0.0.1:6969/mcp
        strategy: str = "TopkDropout",
        topk: int = 30,
        n_drop: int = 5,
        n_long: int = 20,
        n_short: int = 20,
        allow_short: bool = False,
        verbose: bool = True,
    ) -> None:
        """Run AlphaCopilot workflow with a mandatory hypothesis.

        This command generates alpha factors based on a hypothesis, validates them,
        and runs backtests to evaluate performance.

        Args:
            hypothesis: REQUIRED. The hypothesis to test (e.g., "momentum predicts returns")
            custom_factors: Optional list of custom factor expressions to include
            model_type: ML model type - "LightGBM", "XGBoost", "RandomForest", or None
            data_path: Path to market data CSV (default: .data/indian_stock_market_nifty500.csv)
            symbol_col: Column name containing instrument symbols (default: 'symbol')
            timestamp_col: Column name containing timestamps (default: 'timestamp')
            symbols_file: Path to file with symbols to filter (default: .data/nifty500.txt)
            max_symbols: Optional maximum number of symbols to use
            train_start_date: Training period start date (YYYY-MM-DD)
            train_end_date: Training period end date (YYYY-MM-DD)
            test_start_date: Testing period start date (YYYY-MM-DD)
            test_end_date: Testing period end date (YYYY-MM-DD)
            validation_start_date: Validation period start date (YYYY-MM-DD, optional)
            validation_end_date: Validation period end date (YYYY-MM-DD, optional)
            max_iterations: Maximum feedback iterations (default: 3)
            backend: Execution backend - "library" (direct functions, default), "binary" (workflow API), or "mcp" (MCP server)
            mcp_server: MCP server for 'mcp' backend - URL (http://...) or script path (./server.py), default: http://127.0.0.1:6969/mcp
            strategy: Strategy type - "TopkDropout", "Weight", "BetaNeutral", "DollarNeutral", "IntradayMomentum" (default: TopkDropout)
            topk: Number of top stocks to hold for TopkDropout strategy (default: 30)
            n_drop: Number of stocks to drop each rebalance for TopkDropout (default: 5)
            n_long: Number of stocks to go long for BetaNeutral strategies (default: 20)
            n_short: Number of stocks to go short for BetaNeutral strategies (default: 20)
            allow_short: Enable short selling (required for BetaNeutral strategies, default: False)
            verbose: Whether to print progress messages (default: True)

        Example:
            # Using direct library backend (default) with TopkDropout
            alphacopilot run "Short-term momentum predicts returns" \\
                           --model_type LightGBM
            
            # Using BetaNeutral strategy (long-short, dollar neutral)
            alphacopilot run "Mean reversion in volatile stocks" \\
                           --strategy BetaNeutral \\
                           --n_long 20 --n_short 20 \\
                           --allow_short

            # Using MCP server (async, distributed)
            alphacopilot run "Short-term momentum predicts returns" \\
                           --backend mcp \\
                           --mcp_server "http://custom-host:8000/mcp" \\
                           --model_type LightGBM
        """
        if not hypothesis:
            print("✗ Error: --hypothesis is required", file=sys.stderr)
            print("\nUsage: alphacopilot run --hypothesis 'Your hypothesis here'", file=sys.stderr)
            sys.exit(1)

        try:
            # Validate backend choice
            valid_backends = ["library", "binary", "mcp"]
            if backend not in valid_backends:
                print(f"✗ Error: Invalid backend '{backend}'. Choose from: {', '.join(valid_backends)}", file=sys.stderr)
                sys.exit(1)

            if (validation_start_date and not validation_end_date) or (
                validation_end_date and not validation_start_date
            ):
                print("✗ Error: validation_start_date and validation_end_date must both be provided.", file=sys.stderr)
                sys.exit(1)

            # Set default data path if not provided
            if data_path is None:
                data_path = ".data/indian_stock_market_nifty500.csv"

            # Print header
            if verbose:
                print("\n" + "=" * 80)
                print("AlphaCopilot - Automated Alpha Factor Generation")
                print("=" * 80)
                print(f"\nHypothesis: {hypothesis}")
                print(f"Model: {model_type}")
                print(f"Strategy: {strategy}")
                if strategy in ("BetaNeutral", "DollarNeutral", "IntradayMomentum"):
                    print(f"  Long positions: {n_long}, Short positions: {n_short}")
                else:
                    print(f"  Top-k: {topk}, Drop: {n_drop}")
                print(f"Backend: {backend.upper()}")
                print(f"Data: {data_path}")
                if train_start_date and train_end_date:
                    print(f"Train Period: {train_start_date} to {train_end_date}")
                if validation_start_date and validation_end_date:
                    print(f"Validation Period: {validation_start_date} to {validation_end_date}")
                if test_start_date and test_end_date:
                    print(f"Test Period: {test_start_date} to {test_end_date}")
                print(f"Max Iterations: {max_iterations}")
                if is_langsmith_enabled():
                    print(f"LangSmith: Enabled (project: {get_langsmith_project()})")
                else:
                    print("LangSmith: Disabled")
                print("\n" + "=" * 80 + "\n")

            # Initialize tools based on backend
            mcp_server_url = None
            mcp_tool_names = []

            if backend == "mcp":
                if verbose:
                    server_desc = mcp_server or "http://127.0.0.1:6969/mcp (default)"
                    print(f"🔌 Connecting to MCP server: {server_desc}")
                    print("   (async, distributed execution with Celery)")
                mcp_info = asyncio.run(create_mcp_tools(server=mcp_server))
                mcp_server_url = mcp_info["server"]
                mcp_tool_names = mcp_info.get("tools", [])
                if verbose and mcp_tool_names:
                    print(f"   Tools: {', '.join(mcp_tool_names)}")
            elif backend == "binary":
                if verbose:
                    print("🔧 Using workflow runner (stable API, full features)...")
                # Same underlying functions as library, but labeled as "binary"
                # This represents the stable, high-level API surface
                mcp_tools = self._create_binary_tools()
            elif backend == "library":
                if verbose:
                    print("⚡ Using library functions directly (low-level access)...")
                # Direct library function calls - useful for debugging
                mcp_tools = self._create_library_tools()

            # Calculate data loading range from train/test dates (for efficient filtering)
            # Load only the data we need for backtesting
            data_start_date = None
            data_end_date = None
            start_candidates = [
                date
                for date in (train_start_date, validation_start_date, test_start_date)
                if date
            ]
            end_candidates = [
                date
                for date in (train_end_date, validation_end_date, test_end_date)
                if date
            ]
            if start_candidates:
                data_start_date = min(start_candidates)
            if end_candidates:
                data_end_date = max(end_candidates)
            
            # Build strategy params based on strategy type
            if strategy in ("BetaNeutral", "DollarNeutral", "IntradayMomentum"):
                strategy_params = {
                    "n_long": n_long,
                    "n_short": n_short,
                    "method": "equal",
                }
                # Auto-enable shorts for neutral strategies
                effective_allow_short = True
            else:
                strategy_params = {
                    "topk": topk,
                    "n_drop": n_drop,
                    "method": "equal",
                }
                effective_allow_short = allow_short

            # Build workflow configuration
            workflow_config = {
                # Data configuration (with filtering for performance)
                "data_path": data_path,
                "data_start_date": data_start_date,  # Filter data during loading
                "data_end_date": data_end_date,  # Filter data during loading
                "symbols_file": symbols_file,  # Filter to specific symbols from file
                "max_symbols": max_symbols,  # Limit number of symbols
                "symbol_col": symbol_col,
                "timestamp_col": timestamp_col,
                
                # Model configuration
                "model_type": model_type,
                "model_params": {},
                
                # Strategy configuration
                "strategy_type": strategy,
                "strategy_params": strategy_params,
                "topk": topk,
                "n_drop": n_drop,
                
                # Backtest configuration (train/test split)
                "backtest_train_dates": [train_start_date, train_end_date] if train_start_date and train_end_date else None,
                "backtest_validation_dates": [validation_start_date, validation_end_date] if validation_start_date and validation_end_date else None,
                "backtest_test_dates": [test_start_date, test_end_date] if test_start_date and test_end_date else None,
                "initial_capital": 1_000_000,
                "commission": 0.001,
                "slippage": 0.001,
                "rebalance_frequency": 1,
                "allow_short": effective_allow_short,
                "intraday_short_only": True,  # Indian market default
                "short_funding_rate": 0.0002,
                
                # Experiment configuration
                "experiment_name": "alphacopilot_workflow",
                "run_name": hypothesis[:50],  # Use first 50 chars of hypothesis
            }
            
            recorder: Optional[Recorder] = None
            mlflow_context = None
            try:
                recorder = Recorder(
                    experiment_name=workflow_config.get("experiment_name", "alphacopilot_workflow"),
                    tracking_uri="sqlite:///mlruns.db",
                )
                mlflow_context = recorder.start_run(workflow_config.get("run_name", hypothesis[:50]))
                mlflow_context.__enter__()
                recorder.set_tags(workflow="alphacopilot", backend=backend)
                recorder.log_params(hypothesis=hypothesis, model_type=model_type, backend=backend)
            except Exception as mlflow_exc:  # pragma: no cover - best effort setup
                print(f"[WARN] MLflow recorder setup failed: {mlflow_exc}")
                recorder = None
                mlflow_context = None

            try:
                # Create initial state
                initial_state = WorkflowState(
                    trace=Trace(),
                    hypothesis=None,
                    experiment=None,
                    feedback=None,
                    potential_direction=hypothesis,  # Use hypothesis as initial direction
                    mcp_tools=mcp_tool_names if backend == "mcp" else mcp_tools,
                    mcp_server=mcp_server_url,
                    workflow_config=workflow_config,
                    custom_factors=[expr for expr in (custom_factors or [])],  # Just the expressions
                    max_iterations=max_iterations,
                    stop_on_sota=False,
                    _mlflow_iteration=0,
                )

                if recorder is not None:
                    initial_state["recorder"] = recorder
                    initial_state["mlflow_context"] = mlflow_context
                    initial_state["_mlflow_llm_step"] = 0
                    recorder.log_params(max_iterations=max_iterations)

                # Create and run workflow
                # Set recursion_limit based on max_iterations
                # Each iteration uses ~6 node traversals (propose, construct, validate, workflow, feedback, conditional)
                # Add buffer for validation retries and safety margin
                recursion_limit = max(50, max_iterations * 10 + 20)
                graph = create_workflow_graph()
                result = graph.invoke(initial_state, {"recursion_limit": recursion_limit})
            finally:
                if mlflow_context is not None:
                    mlflow_context.__exit__(None, None, None)

            if verbose:
                print("\n" + "=" * 80)
                print("Workflow Completed Successfully")
                print("=" * 80)

                if result.get("results"):
                    results = result["results"]
                    metrics = results.get("metrics", {})

                    print("\n📊 Backtest Results:")
                    print(f"  Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.2f}")
                    print(f"  Total Return: {metrics.get('total_return', 0):.2%}")
                    print(f"  Annualized Return: {metrics.get('annualized_return', 0):.2%}")
                    print(f"  Max Drawdown: {metrics.get('max_drawdown', 0):.2%}")
                    print(f"  Win Rate: {metrics.get('win_rate', 0):.2%}")

                if result.get("experiment"):
                    experiment = result["experiment"]
                    print(f"\n🔬 Generated {len(experiment.sub_tasks)} factors")
                    for i, task in enumerate(experiment.sub_tasks, 1):
                        print(f"  {i}. {task.name}")
                        print(f"     {task.expression}")

                print(f"\n✓ Workflow completed in {result.get('iteration', 0)} iterations")
                print("=" * 80 + "\n")

        except KeyboardInterrupt:
            print("\n\n✗ Workflow interrupted by user", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            print(f"\n✗ Error: {e}", file=sys.stderr)
            if verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

    def validate(
        self,
        factor_expression: str,
    ) -> None:
        """Validate a factor expression.

        Args:
            factor_expression: Factor expression to validate (e.g., "DELTA($close, 1)")

        Example:
            alphacopilot validate --factor_expression "RANK(DELTA($close, 5))"
        """
        try:
            from quant_stream.factors.parser.validator import validate_expression

            result = validate_expression(factor_expression)

            if result["valid"]:
                print(f"✓ Expression is valid: {factor_expression}")
                if result["variables"]:
                    print(f"  Variables: {', '.join(result['variables'])}")
                if result["functions"]:
                    print(f"  Functions: {', '.join(result['functions'])}")
            else:
                print(f"✗ Expression is invalid: {result['error']}", file=sys.stderr)
                sys.exit(1)

        except Exception as e:
            print(f"✗ Validation error: {e}", file=sys.stderr)
            sys.exit(1)

    def list_functions(self) -> None:
        """List all available functions for factor expressions.

        Example:
            alphacopilot list-functions
        """
        from quant_stream.factors.parser.validator import AVAILABLE_FUNCTIONS

        print("\n📋 Available Functions for Factor Expressions:")
        print("=" * 80 + "\n")

        categories = {
            "Element-wise": ["MAX_ELEMENTWISE", "MIN_ELEMENTWISE", "ABS", "SIGN"],
            "Time-series": ["DELTA", "DELAY"],
            "Cross-sectional": ["RANK", "MEAN", "STD", "SKEW", "MAX", "MIN", "MEDIAN", "ZSCORE", "SCALE"],
            "Rolling": ["TS_MAX", "TS_MIN", "TS_MEAN", "TS_MEDIAN", "TS_SUM", "TS_STD", "TS_VAR",
                       "TS_ARGMAX", "TS_ARGMIN", "TS_RANK", "PERCENTILE", "TS_ZSCORE", "TS_MAD",
                       "TS_QUANTILE", "TS_PCTCHANGE"],
            "Indicators": ["SMA", "EMA", "EWM", "WMA", "COUNT", "SUMIF", "FILTER", "PROD",
                          "DECAYLINEAR", "MACD", "RSI", "BB_MIDDLE", "BB_UPPER", "BB_LOWER"],
            "Two-column": ["TS_CORR", "TS_COVARIANCE", "HIGHDAY", "LOWDAY", "SUMAC", "REGBETA",
                          "REGRESI", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "AND", "OR"],
            "Math": ["EXP", "SQRT", "LOG", "INV", "POW", "FLOOR"],
            "Conditional": ["IF", "TERNARY"],
        }

        for category, funcs in categories.items():
            print(f"{category}:")
            for func in funcs:
                if func in AVAILABLE_FUNCTIONS:
                    print(f"  • {func}")
            print()

        print("Available Variables: $open, $high, $low, $close, $volume")
        print("\n" + "=" * 80 + "\n")

    def version(self) -> None:
        """Show alphacopilot version.

        Example:
            alphacopilot version
        """
        try:
            import importlib.metadata
            version = importlib.metadata.version("alphacopilot")
            print(f"alphacopilot version {version}")
        except Exception:
            print("alphacopilot version 0.1.0")

    def server(
        self,
        host: str = "0.0.0.0",
        port: int = 8069,
        reload: bool = False,
    ) -> None:
        """Start the AlphaCopilot REST API server.

        Args:
            host: Host to bind to (default: 0.0.0.0)
            port: Port to bind to (default: 8069)
            reload: Enable auto-reload for development (default: False)

        Example:
            # Start server on default port
            alphacopilot server

            # Start on custom port
            alphacopilot server --port 9000

            # Start with auto-reload (development)
            alphacopilot server --reload
        """
        import uvicorn
        from alphacopilot.server.main import app

        print(f"\n🚀 Starting AlphaCopilot server on http://{host}:{port}")
        print(f"📚 API docs available at http://{host}:{port}/docs\n")

        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=reload,
        )


def main():
    """Main entry point for CLI."""
    fire.Fire(AlphaCopilotCLI)


if __name__ == "__main__":
    main()

