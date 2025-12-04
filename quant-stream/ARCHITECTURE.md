# Quant-Stream Architecture

## Overview

Quant-Stream is a flexible quantitative research framework that supports multiple usage patterns, from low-level Pathway operations to high-level YAML workflows.

## Usage Patterns

### 1. Direct Library Usage (Pythonic)
For researchers who want full control over the workflow.

**Components:**
- 50+ technical indicators and operations
- Manual table joining and transformations
- Direct Pathway API access

**Example:**
```python
import pathway as pw
from quant_stream import DELTA, SMA, RANK

table = pw.debug.table_from_pandas(df)
table = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
table = SMA(table, pw.this.close, m=20, by_instrument=pw.this.symbol)
result = pw.debug.table_to_pandas(table)
```

### 2. Expression-Based (Semi-Automatic)
For rapid prototyping with string-based alpha expressions.

**Components:**
- Expression parser (converts strings to function calls)
- Alpha evaluator (executes on Pathway tables)

**Example:**
```python
from quant_stream import AlphaEvaluator, parse_expression

evaluator = AlphaEvaluator(table)
expr = parse_expression("RANK(DELTA($close, 1))")
result = evaluator.evaluate(expr, factor_name="momentum")
```

### 3. YAML Configuration (Declarative)
For complete workflows without writing Python code.

**Components:**
- YAML schema validation
- Workflow runner
- CLI interface

**Example:**
```yaml
# workflow.yaml
features:
  - name: "momentum"
    expression: "DELTA($close, 1)"

model:
  type: "LightGBM"
  params: {learning_rate: 0.05}

strategy:
  type: "TopkDropout"
  params: {topk: 30}

backtest:
  segments:
    train: ["2021-01-01", "2021-12-31"]
    test: ["2022-01-01", "2022-12-31"]
```

```bash
quant-stream run --config workflow.yaml
```

### 4. MCP Server (AI Agent Integration)
For integration with AI agents like AlphaCopilot using langchain-mcp-adapters.

**Components:**
- FastMCP server with comprehensive tools
- Celery workers for async execution  
- Job management (status, cancellation)
- Full YAML-equivalent configuration via tool parameters
- ML workflow support (features → model → backtest)

**MCP Tools:**
- **validate_factors**: Validate expression syntax using parser
- **run_ml_workflow**: Unified workflow tool (with/without ML model)
  - `model_type=None`: Use factor values directly as signals
  - `model_type="LightGBM"`: Train ML model, use predictions as signals
- **check_job_status**: Poll async job completion
- **cancel_background_job**: Cancel running jobs

**Unified Workflow:**
The MCP server uses a single `run_ml_workflow` tool for all scenarios:
- Direct factor trading: Set `model_type=None`
- ML model trading: Set `model_type` to "LightGBM", "XGBoost", etc.

**Configuration Parity:**
Full YAML-equivalent configuration via tool parameters:
- Data: path, date filters, column mapping
- Strategy: type, method, topk, n_drop, hold_periods
- Backtest: capital, commission, slippage, rebalance frequency
- Model: type (optional), hyperparameters, train/test splits
- Experiment: name, run_name, tags, tracking URI

**Async Job Pattern:**
1. Submit job → get `job_id`
2. Poll `check_job_status` until `status="SUCCESS"`
3. Extract results

See [alphacopilot/ARCHITECTURE.md](alphacopilot/ARCHITECTURE.md) for AlphaCopilot integration details.

## Module Organization

```
quant_stream/
├── functions/          # 50+ technical indicators (core operations)
├── factors/            # Expression parser & evaluator
├── models/             # ML models (LightGBM, XGBoost, RandomForest, Linear)
├── strategy/           # Portfolio strategies (TopkDropout, Weight)
├── backtest/           # Backtesting engine, metrics, reporting
├── config/             # YAML configuration system
├── workflows/          # YAML workflow runner
├── mcp_server/         # MCP server for AI agents
├── recorder/           # MLflow experiment tracking
├── data/               # Data schema & replay
└── utils/              # Utilities (data splitting, etc.)
```

## Signal Generation Flow

### Path 1: Factor-Only (No ML)
```
Data → Factor Expressions → Signals → Strategy → Backtest
```

Example: Momentum rank directly as signal
```yaml
features:
  - name: "momentum_rank"
    expression: "RANK(DELTA($close, 1))"
# No model section - uses factor directly
```

### Path 2: ML-Based
```
Data → Factor Engineering → ML Model Training → Predictions → Strategy → Backtest
```

Example: Multiple factors → LightGBM → predictions as signals
```yaml
features:
  - name: "momentum"
    expression: "DELTA($close, 1)"
  - name: "volume_ratio"
    expression: "DIVIDE($volume, SMA($volume, 20))"

model:
  type: "LightGBM"
  params: {learning_rate: 0.05}
```

## Backtesting Segmentation

### Simple (Train Only)
```yaml
backtest:
  segments:
    train: ["2022-01-01", "2022-12-31"]
```

Runs backtest on train segment, reports single set of metrics.

### Train/Test Split
```yaml
backtest:
  segments:
    train: ["2021-01-01", "2021-12-31"]
    test: ["2022-01-01", "2022-12-31"]
```

Runs backtest on both segments, reports separate train_metrics and test_metrics.

## Metrics Hierarchy

### Portfolio Performance Metrics
Calculated from portfolio returns:
- Total Return, Annual Return, Volatility
- Sharpe Ratio, Sortino Ratio, Calmar Ratio
- Max Drawdown, Win Rate, Profit Factor

### Signal Quality Metrics (IC)
Calculated from signal vs forward returns:
- **IC**: Pearson correlation (signal predictive power)
- **Rank IC**: Spearman rank correlation
- **ICIR**: IC Information Ratio
- **Rank ICIR**: Rank IC Information Ratio

### Model Performance Metrics
Calculated during training (if model used):
- train_ic, train_rank_ic (in-sample)
- test_ic, test_rank_ic (out-of-sample)

## Experiment Tracking

All workflows integrate with MLflow:
- Parameters logged automatically
- Metrics tracked for train/test
- Artifacts saved (results CSV, models)
- Run comparison in MLflow UI

## Design Principles

1. **Composability**: Functions can be chained and nested
2. **Flexibility**: Multiple entry points for different use cases
3. **Streaming-First**: Built on Pathway's incremental computation
4. **Production-Ready**: Transaction costs, realistic simulation
5. **Experiment Tracking**: MLflow integration throughout
6. **Clean APIs**: Minimal, focused interfaces

## When to Use Each Pattern

| Use Case | Pattern | Why |
|----------|---------|-----|
| Research & exploration | YAML + CLI | Fast iteration, no coding |
| Production alpha deployment | Direct Library | Full control, optimization |
| Rapid prototyping | Expression-based | Quick testing of ideas |
| AI agent factor mining | MCP Server | Async, agent-driven |
| Team collaboration | YAML + Git | Version controlled configs |
| Custom workflows | Direct Library | Maximum flexibility |

## Integration Points

### With AlphaCopilot
```python
# AlphaCopilot workflow nodes call MCP tools
def factor_backtest(state):
    result = mcp_client.backtest(
        factor_expression=state.factor.expression,
        train_dates=state.config.train_dates,
        test_dates=state.config.test_dates
    )
    return {"job_id": result["job_id"]}
```

### With Jupyter Notebooks
```python
from quant_stream import WorkflowRunner

runner = WorkflowRunner("config.yaml", verbose=True)
results = runner.run()
results["results_df"].plot(x="timestamp", y="portfolio_value")
```

### With Data Pipelines
```python
from quant_stream.backtest import run_ml_workflow

# Can be called from Airflow, Prefect, etc.
results = run_ml_workflow(
    data_path=".data/indian_stock_market_nifty500.csv",
    factor_expressions=[...],
    strategy_type="TopkDropout",
    strategy_params={"topk": 30},
    backtest_segments={"train": [...], "test": [...]},
    log_to_mlflow=False,
)
```

## Key Abstractions

### Factor Expression
A string describing an alpha factor:
```
"RANK(DELTA($close, 1))"
```

### Workflow Config
A declarative specification of the complete research pipeline (YAML or dict).

### Segments
Time period specification for backtesting:
```python
{
    "train": ["2021-01-01", "2021-12-31"],
    "test": ["2022-01-01", "2022-12-31"]
}
```

### Strategy
A rule for converting signals into portfolio positions.

### Backtest Result
A dictionary containing:
- metrics (or train_metrics + test_metrics)
- results_df (portfolio values over time)
- success/error status

## Extension Points

### Custom Functions
Add new technical indicators to `quant_stream/functions/` and register in `__init__.py`.

### Custom Models
Extend `ForecastModel` base class for new ML algorithms.

### Custom Strategies
Extend `Strategy` base class for custom portfolio construction logic.

### Custom MCP Tools
Add tools to `mcp_server/tools/` and register with `@mcp.tool()` decorator. Full configuration schemas available in `mcp_server/schemas/requests.py`.
