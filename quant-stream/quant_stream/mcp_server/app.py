"""FastMCP server for quant-stream backtesting."""

import logging
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP

from quant_stream.mcp_server.core import app_lifespan
from quant_stream.mcp_server.tools import get_job_status, cancel_job, validate_factor_expressions

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create FastMCP server with lifespan
mcp = FastMCP(
    name="Quant-Stream Backtesting Server",
    lifespan=app_lifespan,
    port=6969
)


# ============================================================================
# Tools - Unified Workflow
# ============================================================================

@mcp.tool()
def run_ml_workflow(
    factor_expressions: list[Dict[str, str]],
    model_type: Optional[str] = None,
    model_params: Optional[Dict[str, Any]] = None,
    # Data configuration
    data_path: Optional[str] = None,
    symbol_col: str = "symbol",
    timestamp_col: str = "timestamp",
    # Model configuration
    target: str = "forward_return_1d",
    train_start: Optional[str] = None,
    train_end: Optional[str] = None,
    test_start: Optional[str] = None,
    test_end: Optional[str] = None,
    # Strategy configuration
    strategy_type: str = "TopkDropout",
    strategy_method: str = "equal",
    topk: int = 30,
    n_drop: int = 5,
    hold_periods: Optional[int] = None,
    # Backtest configuration
    backtest_train_dates: Optional[list] = None,
    backtest_test_dates: Optional[list] = None,
    initial_capital: float = 1_000_000,
    commission: float = 0.001,
    slippage: float = 0.001,
    min_commission: float = 0.0,
    rebalance_frequency: int = 1,
    # Experiment configuration
    experiment_name: str = "mcp_ml_workflow",
    run_name: Optional[str] = None,
    experiment_tags: Optional[Dict[str, str]] = None,
    tracking_uri: str = "sqlite:///mlruns.db",
) -> Dict[str, Any]:
    """Run complete ML workflow: feature engineering -> [optional model training] -> backtesting.
    
    This is the UNIFIED tool for all factor-based trading workflows:
    - model_type=None: Use factor values directly as signals (simple factor backtest)
    - model_type="LightGBM"|"XGBoost"|etc.: Train model on factors, use predictions as signals
    
    Workflow steps:
    1. Load data and calculate features from factor expressions
    2. [If model_type specified] Train ML model on features
    3. Generate signals (factor values OR model predictions)
    4. Run backtest with strategy
    5. Return comprehensive results
    
    Args:
        factor_expressions: List of {"name": "...", "expression": "..."} dicts
        model_type: Model type - None (direct factors), "LightGBM", "XGBoost", "RandomForest", "Linear"
        model_params: Model hyperparameters dict (only used if model_type is not None)
        
        # Data configuration
        data_path: Path to market data CSV
        data_start_date: Filter data from this date (YYYY-MM-DD)
        data_end_date: Filter data until this date (YYYY-MM-DD)
        symbol_col: Symbol column name (default: "symbol")
        timestamp_col: Timestamp column name (default: "timestamp")
        
        # Model training configuration
        target: Target variable (default: "forward_return_1d")
        
        # Strategy configuration
        strategy_type: "TopkDropout" or "Weight"
        strategy_method: "equal", "signal", or "inv_vol"
        topk: Number of top stocks (TopkDropout)
        n_drop: Stocks to drop per rebalance (TopkDropout)
        hold_periods: Holding periods (TopkDropout)
        
        # Backtest configuration
        backtest_train_dates: [start, end] for backtest train period
        backtest_test_dates: [start, end] for backtest test period
        initial_capital: Starting capital
        commission: Commission rate
        slippage: Slippage rate
        min_commission: Minimum commission per trade
        rebalance_frequency: Rebalance every N periods
        
        # Experiment tracking
        experiment_name: MLflow experiment name
        run_name: MLflow run name
        experiment_tags: Experiment tags dict
        tracking_uri: MLflow tracking URI
        
    Returns:
        Dict with job_id and status
        
    Examples:
        # Direct factor trading (no model)
        run_ml_workflow(
            factor_expressions=[
                {"name": "momentum", "expression": "DELTA($close, 20)"}
            ],
            model_type=None,  # Use factor values directly as signals
            backtest_train_dates=["2022-01-01", "2022-12-31"],
            strategy_type="TopkDropout",
            topk=30
        )
        
        # ML model-based trading
        run_ml_workflow(
            factor_expressions=[
                {"name": "momentum_5d", "expression": "DELTA($close, 5)"},
                {"name": "volume_ratio", "expression": "DIVIDE($volume, SMA($volume, 20))"}
            ],
            model_type="LightGBM",  # Train model on factors
            model_params={
                "objective": "regression",
                "metric": "l2",
                "learning_rate": 0.05,
                "num_leaves": 31,
                "max_depth": 5,
                "num_boost_round": 100,
            },
            data_path=".data/market_data.csv",
            train_start="2021-01-01",
            train_end="2021-12-31",
            test_start="2022-01-01",
            test_end="2022-12-31",
            strategy_type="TopkDropout",
            topk=40
        )
    """
    # Check if async execution is available (requires celery)
    # MCP mode should ALWAYS use async execution with job_id when Celery is available
    try:
        from quant_stream.mcp_server.core.tasks import run_workflow_task
        use_async = True
        logger.info("MCP mode: Using async execution with Celery")
    except ImportError:
        use_async = False
        logger.warning("Celery not available - falling back to synchronous execution")
        logger.warning("For production MCP usage, install Celery: pip install celery redis")
    
    # Build configuration dict matching WorkflowConfig schema
    backtest_segments_payload = None
    if backtest_train_dates or backtest_test_dates:
        backtest_segments_payload = {
            "train": backtest_train_dates,
            "test": backtest_test_dates,
        }
    else:
        inferred_segments = {}
        if train_start and train_end:
            inferred_segments["train"] = [train_start, train_end]
        if test_start and test_end:
            inferred_segments["test"] = [test_start, test_end]
        if inferred_segments:
            backtest_segments_payload = inferred_segments

    if model_type:
        if not backtest_segments_payload or not backtest_segments_payload.get("train") or not backtest_segments_payload.get("test"):
            raise ValueError(
                "When specifying model_type, you must provide backtest train and test date ranges."
            )

    config_dict = {
        "data": {
            "path": data_path or ".data/indian_stock_market_nifty500.csv",
            "symbol_col": symbol_col,
            "timestamp_col": timestamp_col,
        },
        "features": factor_expressions,
        "model": {
            "type": model_type,
            "params": model_params or {},
            "target": target,
        } if model_type else None,  # No model config if model_type is None
        "strategy": {
            "type": strategy_type,
            "params": {
                "method": strategy_method,
                **({"topk": topk, "n_drop": n_drop} if strategy_type == "TopkDropout" else {}),
                **({"hold_periods": hold_periods} if hold_periods else {}),
            }
        },
        "backtest": {
            "segments": backtest_segments_payload,
            "initial_capital": initial_capital,
            "commission": commission,
            "slippage": slippage,
            "min_commission": min_commission,
            "rebalance_frequency": rebalance_frequency,
        },
        "experiment": {
            "name": experiment_name,
            "tracking_uri": tracking_uri,
            "run_name": run_name,
            "tags": experiment_tags or {},
        }
    }
    
    if use_async:
        # Asynchronous execution via Celery (MCP mode with job_id)
        # This is the STANDARD MCP behavior - returns immediately with job_id
        request_data = {
            "config_dict": config_dict,
            "output_path": None,
        }
        
        # Submit workflow task to Celery
        task = run_workflow_task.apply_async(
            args=[request_data],
            queue="workflow"
        )
        
        logger.info(f"Submitted async workflow job: {task.id}")
        
        return {
            "job_id": task.id,
            "status": "PENDING",
            "message": f"Workflow job submitted ({'with ' + model_type if model_type else 'direct factors'} -> backtesting). Use check_job_status to poll for results."
        }
    else:
        # Fallback: Synchronous execution (no celery available)
        # This happens when Celery is not installed or not configured
        # Returns immediately with completed result
        from quant_stream.mcp_server.tools.workflow import run_ml_workflow_sync
        
        logger.warning("Running workflow synchronously - Celery not available")
        logger.warning("For async execution, install: pip install celery redis")
        
        # Wrap config_dict in request_data format expected by run_ml_workflow_sync
        request_data = {"config_dict": config_dict}
        result = run_ml_workflow_sync(request_data)
        
        # Return with a special job_id indicating synchronous execution
        # and include result immediately
        return {
            "job_id": "mcp_sync_fallback",
            "status": "SUCCESS",
            "result": result,
            "message": "Workflow completed synchronously (Celery not available). For async execution, install Celery."
        }


# ============================================================================
# Tools - Job Management
# ============================================================================

@mcp.tool()
def check_job_status(job_id: str) -> Dict[str, Any]:
    """Check the status of a background job.
    
    Poll this tool to monitor the progress of async operations.
    
    Args:
        job_id: The job identifier returned from async tools
        
    Returns:
        Dict with job_id, status, progress, result, and error fields
        
    Status values:
        - PENDING: Job is queued but not started
        - STARTED: Job has been picked up by a worker
        - PROCESSING: Job is actively running (with progress updates)
        - SUCCESS: Job completed successfully
        - FAILURE: Job failed with an error
        - REVOKED: Job was cancelled
    """
    return get_job_status(job_id)


@mcp.tool()
def cancel_background_job(job_id: str, force_terminate: bool = False) -> Dict[str, Any]:
    """Cancel a running or pending background job.
    
    Args:
        job_id: The job identifier
        force_terminate: If True, forcefully terminate running job (use with caution)
        
    Returns:
        Dict with job_id, status, and message
    """
    return cancel_job(job_id, terminate=force_terminate)


@mcp.tool()
def validate_factors(factor_expressions: list[Dict[str, str]]) -> Dict[str, Any]:
    """Validate factor expressions before backtesting.
    
    Validates syntax and structure of factor expressions to catch errors early.
    
    Args:
        factor_expressions: List of factor expressions with names
            [{"name": "momentum", "expression": "DELTA($close, 20)"}, ...]
            
    Returns:
        Dict with validation results:
        {
            "valid": bool (all expressions valid),
            "results": list of validation results per factor,
            "errors": list of error messages
        }
        
    Examples:
        # Valid expression
        validate_factors([
            {"name": "momentum", "expression": "DELTA($close, 1)"}
        ])
        # Returns: {"valid": True, "results": [...], "errors": []}
        
        # Invalid expression
        validate_factors([
            {"name": "bad", "expression": "INVALID("}
        ])
        # Returns: {"valid": False, "results": [...], "errors": ["bad: ..."]}
    """
    result = validate_factor_expressions(factor_expressions)
    logger.info(
        "validate_factors -> valid=%s errors=%s",
        result.get("valid"),
        result.get("errors"),
    )
    return result


# ============================================================================
# Resources (optional - for providing config templates)
# ============================================================================

@mcp.resource("config://strategy/topk_dropout")
def get_topk_dropout_config() -> str:
    """Get example TopkDropout strategy configuration."""
    return """{
  "type": "TopkDropout",
  "params": {
    "topk": 30,
    "n_drop": 5,
    "method": "equal",
    "hold_periods": 1
  }
}

# Available weighting methods:
# - "equal": Equal weight across all positions
# - "signal": Weight by signal strength (factor values)
# - "inv_vol": Inverse volatility weighting
"""


@mcp.resource("config://strategy/weight")
def get_weight_strategy_config() -> str:
    """Get example Weight strategy configuration."""
    return """{
  "type": "Weight",
  "params": {
    "method": "signal",
    "long_only": true
  }
}

# Weight strategy allocates capital based on signal strength
# - method: "equal", "signal", or "inv_vol"
# - long_only: If true, only take long positions
"""


@mcp.resource("config://backtest/default")
def get_default_backtest_config() -> str:
    """Get default backtest configuration."""
    return """{
  "segments": {
    "train": ["2021-01-01", "2021-12-31"],
    "test": ["2022-01-01", "2022-12-31"]
  },
  "initial_capital": 1000000,
  "commission": 0.001,
  "slippage": 0.001,
  "min_commission": 0.0,
  "rebalance_frequency": 1
}"""


@mcp.resource("config://data/default")
def get_default_data_config() -> str:
    """Get default data configuration."""
    return """{
  "path": ".data/indian_stock_market_nifty500.csv",
  "start_date": null,
  "end_date": null,
  "symbol_col": "symbol",
  "timestamp_col": "timestamp"
}

# Data configuration options:
# - path: Path to CSV file with market data
# - start_date: Filter data from this date (YYYY-MM-DD)
# - end_date: Filter data until this date (YYYY-MM-DD)
# - symbol_col: Column name for stock symbol/ticker
# - timestamp_col: Column name for timestamp
"""


@mcp.resource("config://model/lightgbm")
def get_lightgbm_config() -> str:
    """Get example LightGBM model configuration."""
    return """{
  "type": "LightGBM",
  "features": [
    "momentum_5d",
    "volume_ratio",
    "($close - $open) / $open",
    "TS_PCTCHANGE($close, 10)"
  ],
  "include_ohlcv": false,
  "params": {
    "objective": "regression",
    "metric": "l2",
    "boosting_type": "gbdt",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": 5,
    "min_child_samples": 50,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
    "random_state": 42,
    "verbose": -1,
    "num_boost_round": 100,
    "early_stopping_rounds": 10
  },
  "target": "forward_return_1d"
}

# Feature Selection:
# - features: List of feature names or inline expressions (e.g., "($close - $open) / $open")
#   Can mix computed factor names and expressions. If null, uses all computed factors.
# - include_ohlcv: Whether to include OHLCV columns when features=null (default: true)

# Common hyperparameters for LightGBM:
# - objective: "regression" (for regression tasks)
# - metric: "l2" (mean squared error)
# - learning_rate: Step size (0.01-0.1)
# - num_leaves: Number of leaves (2^max_depth to 2^max_depth * 2)
# - max_depth: Maximum tree depth (3-10)
# - min_child_samples: Minimum samples per leaf (10-100)
# - subsample: Fraction of data for bagging (0.5-1.0)
# - colsample_bytree: Fraction of features to use (0.5-1.0)
# - reg_alpha: L1 regularization (0.0-1.0)
# - reg_lambda: L2 regularization (0.0-1.0)
# - num_boost_round: Number of boosting iterations (50-500)
# - early_stopping_rounds: Early stopping patience (5-20)
"""


@mcp.resource("config://experiment/default")
def get_experiment_config() -> str:
    """Get default experiment tracking configuration."""
    return """{
  "name": "mcp_backtest",
  "tracking_uri": "sqlite:///mlruns.db",
  "run_name": null,
  "tags": {
    "environment": "mcp",
    "version": "1.0"
  }
}

# Experiment tracking with MLflow:
# - name: Experiment name (groups related runs)
# - tracking_uri: MLflow tracking server URI or local path
# - run_name: Specific run name (auto-generated if null)
# - tags: Key-value pairs for organizing experiments
"""


@mcp.resource("docs://functions/available")
def get_available_functions() -> str:
    """Get comprehensive documentation of all available factor functions."""
    return """# Available Factor Functions

All functions operate on market data columns (accessed with $ prefix, e.g., $close, $open, $volume).

## Element-wise Operations
- **ABS($column)**: Absolute value
- **SIGN($column)**: Sign of value (-1, 0, or 1)
- **MAX_ELEMENTWISE($col1, $col2)**: Element-wise maximum
- **MIN_ELEMENTWISE($col1, $col2)**: Element-wise minimum
- **IF(condition, true_value, false_value)**: Conditional expression returning `if_result`
- **TERNARY(condition, true_value, false_value)**: Conditional expression returning `ternary`; produced by `condition ? true_value : false_value`

## Mathematical Operations
- **EXP($column)**: Exponential (e^x)
- **SQRT($column)**: Square root
- **LOG($column)**: Natural logarithm
- **INV($column)**: Inverse (1/x)
- **POW($column, n)**: Power (x^n)
- **FLOOR($column)**: Floor function

## Time-Series Operations (per instrument)
- **DELTA($column, periods=1)**: Difference over time (current - previous)
- **DELAY($column, p=1)**: Lag/shift values by p periods

## Cross-Sectional Operations (across instruments at each timestamp)
- **RANK($column)**: Percentile rank (0.0 to 1.0)
- **MEAN($column)**: Mean across instruments
- **STD($column)**: Standard deviation across instruments
- **SKEW($column)**: Skewness across instruments
- **MAX($column)**: Maximum across instruments
- **MIN($column)**: Minimum across instruments
- **MEDIAN($column)**: Median across instruments
- **ZSCORE($column)**: Z-score normalization (mean=0, std=1)
- **SCALE($column, target_sum=1.0)**: Scale so sum of absolute values equals target

## Rolling Window Operations (per instrument over time)
- **TS_MAX($column, p=5)**: Rolling maximum
- **TS_MIN($column, p=5)**: Rolling minimum
- **TS_MEAN($column, p=5)**: Rolling mean
- **TS_MEDIAN($column, p=5)**: Rolling median
- **TS_SUM($column, p=5)**: Rolling sum
- **TS_STD($column, p=20)**: Rolling standard deviation
- **TS_VAR($column, p=5, ddof=1)**: Rolling variance
- **TS_ARGMAX($column, p=5)**: Periods since maximum occurred
- **TS_ARGMIN($column, p=5)**: Periods since minimum occurred
- **TS_RANK($column, p=5)**: Percentile rank within window
- **TS_ZSCORE($column, p=5)**: Rolling z-score
- **TS_MAD($column, p=5)**: Median absolute deviation
- **TS_QUANTILE($column, p=5, q=0.5)**: Rolling quantile
- **TS_PCTCHANGE($column, p=1)**: Percentage change
- **PERCENTILE($column, q, p=None)**: Quantile (rolling if p given, cross-sectional if not)

## Technical Indicators
- **SMA($column, m)**: Simple moving average (or EWM if n is also provided)
- **EMA($column, p)**: Exponential moving average
- **EWM($column, alpha)**: Exponential weighted moving average
- **WMA($column, p=20)**: Weighted moving average with decay
- **COUNT($condition, p=20)**: Count True values in window
- **SUMIF($column, p, $condition)**: Conditional rolling sum
- **FILTER($column, $condition)**: Filter values (multiply by condition)
- **PROD($column, p=5)**: Rolling product
- **DECAYLINEAR($column, p=5)**: Linear decay weighted average
- **MACD($column, short=12, long=26)**: Moving average convergence divergence
- **RSI($column, window=14)**: Relative strength index
- **BB_MIDDLE($column, window=20)**: Bollinger Bands middle line
- **BB_UPPER($column, window=20, num_std=2.0)**: Bollinger Bands upper line
- **BB_LOWER($column, window=20, num_std=2.0)**: Bollinger Bands lower line

## Two-Column Operations
- **ADD($col1, $col2)**: Addition
- **SUBTRACT($col1, $col2)**: Subtraction
- **MULTIPLY($col1, $col2)**: Multiplication
- **DIVIDE($col1, $col2)**: Division
- **AND($col1, $col2)**: Logical AND
- **OR($col1, $col2)**: Logical OR
- **TS_CORR($col1, $col2, p)**: Rolling correlation
- **TS_COVARIANCE($col1, $col2, p)**: Rolling covariance
- **HIGHDAY($high, $close, p)**: Days since highest high
- **LOWDAY($low, $close, p)**: Days since lowest low
- **SUMAC($close, $volume)**: Sum of (close * volume)
- **REGBETA($col1, $col2, p)**: Rolling regression beta
- **REGRESI($col1, $col2, p)**: Rolling regression residuals

## Example Factor Expressions
1. Simple momentum: `DELTA($close, 1)`
2. Mean reversion: `ZSCORE($close)`
3. Volume-adjusted momentum: `MULTIPLY(DELTA($close, 5), $volume)`
4. RSI-based signal: `SUBTRACT(RSI($close, 14), 50)`
5. Cross-sectional rank of returns: `RANK(DELTA($close, 1))`
6. Volatility-adjusted returns: `DIVIDE(DELTA($close, 1), TS_STD($close, 20))`
7. Trend strength: `MACD($close, 12, 26)`
8. Price vs moving average: `SUBTRACT($close, SMA($close, 20))`

## Notes
- Most functions default to grouping by instrument and ordering by timestamp
- Column references use $ prefix: $close, $open, $high, $low, $volume
- Rolling windows include the current period
- Cross-sectional operations compute values across all instruments at each time point
- Time-series operations compute values for each instrument across time
"""


@mcp.resource("docs://alpha/construction")
def get_alpha_construction_guide() -> str:
    """Get comprehensive guide on how to construct alpha factor expressions."""
    return """# Alpha Factor Construction Guide

## Expression Syntax Rules

### 1. Variables and Columns
- **Column References**: Use `$` prefix to reference data columns
  - `$close`, `$open`, `$high`, `$low`, `$volume`
  - Example: `$close + $open`

### 2. Operators
- **Arithmetic**: `+`, `-`, `*`, `/`
  - With numbers: `$close * 2` (inline operation)
  - Between columns: `$close + $open` → converts to `ADD($close, $open)`
- **Comparison**: `>`, `<`, `>=`, `<=`, `==`, `!=`
  - Example: `$close > $open` (creates boolean condition)
- **Logical**: `&&` (AND), `||` (OR), `&`, `|`
  - Example: `($close > $open) && ($volume > 1000)`
- **Conditional**: `condition ? true_value : false_value`
  - Example: `$close > $open ? 1 : -1`

### 3. Function Calls
- Functions use parentheses with comma-separated arguments
- Can be nested: `RANK(DELTA($close, 5))`
- Column references and other functions as arguments: `TS_CORR($high - $low, $volume, 20)`

## Best Practices for Factor Construction

### 1. Data Preprocessing and Standardization
**IMPORTANT**: Avoid using raw prices and volumes directly due to scale differences

✅ **DO THIS:**
- Use relative changes: `DELTA($close, 1) / $close` (returns)
- Transform volume: `DELTA($volume, 1) / $volume` (volume change rate)
- Apply standardization: `RANK($close)`, `ZSCORE($close)`

❌ **DON'T DO THIS:**
- `$close` (raw price levels - not comparable across stocks)
- `$volume` (raw volume - scale varies by stock)
- `$close - $open` (absolute differences - biased by price level)

### 2. Normalization and Stability
- **Add small constants** to denominators to prevent division by zero
  - Example: `$close / (TS_STD($close, 20) + 1e-8)`
- **Use SIGN()** to reduce impact of extreme values
  - Example: `SIGN($close - $open) * LOG(ABS($close - $open) + 1)`
- **Apply value truncation** using MAX/MIN for bounds
  - Example: `MAX(MIN($close/$open - 1, 0.1), -0.1)`

### 3. Cross-sectional Treatment
- **Apply RANK()** for cross-sectional comparability at each timestamp
  - Example: `RANK(DELTA($close, 1))`
- **Apply ZSCORE()** for standardization (mean=0, std=1)
  - Example: `ZSCORE($volume)`
- **Use FILTER()** for outlier handling
  - Example: `FILTER($close, $volume > MEAN($volume))`

### 4. Time Series Processing
- **Choose appropriate window sizes**
  - Short-term: 5-10 days for momentum
  - Medium-term: 20-60 days for trends
  - Long-term: 120-250 days for macro patterns
- **Use suitable moving averages**
  - SMA: Simple average, equal weights
  - EMA: Exponential, more weight on recent data
  - WMA: Weighted with decay

### 5. Robustness Considerations
- **Prefer TS_MEDIAN()** over TS_MEAN() to reduce outlier impact
- **Apply smoothing** to reduce noise
  - Example: `SMA(DELTA($close, 1), 5)` instead of `DELTA($close, 1)`
- **Validate stability** across different time windows

### 6. Flexibility Over Strict Equality
❌ **Avoid strict equality** (too restrictive):
```
TS_MIN($low, 10) == DELAY(TS_MIN($low, 10), 1)
```

✅ **Use range-based conditions**:
```
(TS_MIN($low, 10) < DELAY(TS_MIN($low, 10), 1) + 0.1 * TS_STD($low, 20)) && 
(TS_MIN($low, 10) > DELAY(TS_MIN($low, 10), 1) - 0.1 * TS_STD($low, 20))
```

## Factor Construction Examples

### Example 1: Normalized Intraday Range (10-day volatility adjusted)
```
ABS($close - $open) / (TS_STD($close, 10) + 1e-8)
```
**Explanation**: Candlestick body size normalized by recent volatility

### Example 2: Volume-Range Correlation (20-day)
```
TS_CORR($high - $low, $volume, 20)
```
**Explanation**: Correlation between price range and trading activity

### Example 3: Momentum with Cross-sectional Rank
```
RANK(DELTA($close, 5) / $close)
```
**Explanation**: 5-day return ranked across all stocks

### Example 4: Volatility-Adjusted Returns
```
DIVIDE(DELTA($close, 10), TS_STD($close, 20) + 1e-8)
```
**Explanation**: 10-day return normalized by 20-day volatility (Sharpe-like ratio)

### Example 5: Mean Reversion Signal
```
MULTIPLY(ZSCORE($close), -1)
```
**Explanation**: Inverted z-score to buy oversold, sell overbought

### Example 6: Volume Surge Detection
```
($volume > TS_MEAN($volume, 20) * 1.5) ? DELTA($close, 1) / $close : 0
```
**Explanation**: Only consider returns when volume exceeds 1.5x average

### Example 7: Trend Strength with Dual Moving Average
```
DIVIDE(SMA($close, 5) - SMA($close, 20), SMA($close, 20) + 1e-8)
```
**Explanation**: Percentage difference between fast and slow moving averages

### Example 8: Price-Volume Divergence
```
MULTIPLY(
    RANK(DELTA($close, 5)),
    MULTIPLY(RANK(DELTA($volume, 5)), -1)
)
```
**Explanation**: Detects when price and volume move in opposite directions

## Common Pitfalls to Avoid

1. **No undeclared variables**: Don't use `n`, `w_1`, or other undefined symbols
2. **Pay attention to TS_ prefix**: `TS_STD()` vs `STD()` are different
3. **Each factor is independent**: Don't reference other factor names in expressions
4. **Avoid operations with constants only**: `1 + 2` has no predictive value
5. **Must include at least one data column**: Every expression needs `$open`, `$close`, etc.

## Syntax Transformation Rules

The parser automatically converts operations:
- `$close + $open` → `ADD($close, $open)` (when both are columns)
- `$close * 2` → `$close*2` (when one is numeric, keeps inline)
- `$close > $open` → `($close>$open)` (comparison preserved)
- `A && B` → `AND(A, B)` (logical operations)
- `A ? B : C` → `TERNARY(A, B, C)` (conditional expression)

## Output Format
When constructing factors, provide:
1. **Factor Name**: Descriptive name (e.g., "Volatility_Adjusted_Momentum_10D")
2. **Description**: What the factor captures and why it's predictive
3. **Variables**: Dictionary of all functions/columns used with descriptions
4. **Formulation**: LaTeX mathematical representation
5. **Expression**: Executable factor expression following syntax rules
"""


@mcp.resource("docs://alpha/patterns")
def get_alpha_patterns() -> str:
    """Get quick reference of common alpha factor patterns."""
    return """# Common Alpha Factor Patterns - Quick Reference

## Momentum Factors
1. **Simple Returns**: `DELTA($close, 1) / $close`
2. **Ranked Momentum**: `RANK(DELTA($close, 5) / $close)`
3. **Multi-period Momentum**: `RANK(DELTA($close, 20) / $close - DELTA($close, 5) / $close)`
4. **Accelerating Momentum**: `DELTA(DELTA($close, 5), 5)`

## Mean Reversion Factors
1. **Price Z-Score**: `MULTIPLY(ZSCORE($close), -1)`
2. **Distance from MA**: `($close - SMA($close, 20)) / SMA($close, 20)`
3. **Bollinger Band Position**: `($close - BB_LOWER($close, 20)) / (BB_UPPER($close, 20) - BB_LOWER($close, 20) + 1e-8)`
4. **RSI Reversion**: `(50 - RSI($close, 14)) / 50`

## Volatility Factors
1. **Historical Volatility**: `TS_STD($close / DELAY($close, 1) - 1, 20)`
2. **Volatility Rank**: `RANK(TS_STD($close, 20))`
3. **ATR Normalized**: `($high - $low) / (TS_MEAN($high - $low, 14) + 1e-8)`
4. **Volatility Change**: `TS_STD($close, 10) / (TS_STD($close, 50) + 1e-8)`

## Volume Factors
1. **Volume Momentum**: `RANK(DELTA($volume, 5) / ($volume + 1e-8))`
2. **Volume-Price Correlation**: `TS_CORR($close, $volume, 20)`
3. **Relative Volume**: `$volume / (TS_MEAN($volume, 20) + 1e-8)`
4. **Volume Trend**: `($volume > TS_MEAN($volume, 20)) ? 1 : -1`

## Trend Factors
1. **MACD**: `MACD($close, 12, 26)`
2. **Moving Average Crossover**: `SMA($close, 5) / (SMA($close, 20) + 1e-8) - 1`
3. **ADX-like (Trend Strength)**: `TS_MEAN(ABS(DELTA($close, 1)), 14) / (TS_STD($close, 14) + 1e-8)`
4. **Price vs Volume Regression**: `REGBETA($close, $volume, 20)`

## Volatility-Adjusted Returns
1. **Sharpe-like Ratio**: `(DELTA($close, 10) / $close) / (TS_STD(DELTA($close, 1) / $close, 20) + 1e-8)`
2. **Normalized Returns**: `ZSCORE(DELTA($close, 5) / $close)`
3. **Risk-Adjusted Momentum**: `RANK(DELTA($close, 20)) / (RANK(TS_STD($close, 20)) + 0.1)`

## Cross-Sectional Factors
1. **Relative Strength**: `RANK($close / DELAY($close, 20) - 1)`
2. **Relative Volume**: `RANK($volume / TS_MEAN($volume, 20))`
3. **Price vs Universe**: `($close - MEAN($close)) / (STD($close) + 1e-8)`
4. **Sector Residual**: `$close - MEAN($close)`

## Intraday Factors
1. **Open-Close Gap**: `($open - DELAY($close, 1)) / (DELAY($close, 1) + 1e-8)`
2. **Intraday Range**: `($high - $low) / ($open + 1e-8)`
3. **Body to Range Ratio**: `ABS($close - $open) / ($high - $low + 1e-8)`
4. **Close Position**: `($close - $low) / ($high - $low + 1e-8)`

## Combined Factors (Multi-Signal)
1. **Momentum + Volume**: `MULTIPLY(RANK(DELTA($close, 5)), RANK($volume))`
2. **Mean Reversion + Volatility**: `MULTIPLY(ZSCORE($close), INV(TS_STD($close, 20)))`
3. **Trend + Volume Confirmation**: `MACD($close, 12, 26) * SIGN($volume - TS_MEAN($volume, 20))`
4. **Multi-Factor Score**: `ADD(MULTIPLY(RANK(DELTA($close, 5)), 0.4), ADD(MULTIPLY(RANK($volume), 0.3), MULTIPLY(RANK(TS_STD($close, 20)), 0.3)))`

## Technical Pattern Recognition
1. **New High/Low**: `(TS_ARGMAX($high, 20) == 0) ? 1 : ((TS_ARGMIN($low, 20) == 0) ? -1 : 0)`
2. **Breakout**: `($close > TS_MAX($high, 20)) ? 1 : (($close < TS_MIN($low, 20)) ? -1 : 0)`
3. **Support/Resistance Test**: `ABS($close - TS_MIN($low, 20)) / (TS_STD($close, 20) + 1e-8)`

## Key Transformation Templates

### Convert Raw to Returns
- Raw: `$close`
- Returns: `DELTA($close, 1) / $close`
- Log Returns: `LOG($close / DELAY($close, 1))`

### Add Cross-Sectional Normalization
- Before: `DELTA($close, 5)`
- After: `RANK(DELTA($close, 5))`
- Alternative: `ZSCORE(DELTA($close, 5))`

### Add Stability (Prevent Division by Zero)
- Before: `$close / $volume`
- After: `$close / ($volume + 1e-8)`

### Add Smoothing (Reduce Noise)
- Before: `DELTA($close, 1)`
- After: `SMA(DELTA($close, 1), 5)`
- Alternative: `EMA(DELTA($close, 1), 5)`

## Tips for Combining Factors
1. **Use RANK() before combining**: Ensures equal weighting
   - `ADD(RANK(factor1), RANK(factor2))`
2. **Weight factors explicitly**:
   - `ADD(MULTIPLY(RANK(momentum), 0.6), MULTIPLY(RANK(volume), 0.4))`
3. **Conditional combinations**:
   - `(condition) ? factor1 : factor2`
4. **Interaction terms**:
   - `MULTIPLY(factor1, factor2)` captures non-linear relationships
"""