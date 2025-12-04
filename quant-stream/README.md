# Quant Stream

![Coverage](./assets/coverage-badge.svg)
![Tests](./assets/tests-badge.svg)

A **flexible quantitative research framework** for alpha factor development and backtesting, powered by [Pathway](https://pathway.com/framework).

## What is Quant-Stream?

Quant-Stream provides everything you need for quantitative alpha research:
- **50+ Technical Indicators** - Complete factor library (momentum, mean-reversion, volume, volatility, etc.)
- **Expression Language** - Write alphas as strings: `"RANK(DELTA($close, 1))"`
- **ML Integration** - LightGBM, XGBoost, RandomForest, Linear regression
- **Realistic Backtesting** - Transaction costs, IC metrics, comprehensive performance analysis
- **Multiple Interfaces** - Python library, YAML configs, CLI commands, or MCP server
- **Experiment Tracking** - Built-in MLflow integration

## Five Ways to Use Quant-Stream

Choose the approach that fits your workflow:

### 1️⃣ YAML Configuration (No Code Required)

Perfect for: Rapid iteration, team collaboration, version control

```bash
# Create config
quant-stream init --output strategy.yaml

# Edit strategy.yaml, then run
quant-stream run --config strategy.yaml
```

**Features:** Declarative configs, CLI commands, automatic experiment tracking

### 2️⃣ Python Library (Full Control)

Perfect for: Production deployment, custom workflows, maximum flexibility

```python
from quant_stream import DELTA, RANK, Backtester, TopkDropoutStrategy

# Build factor manually
table = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
table = RANK(table, pw.this.delta)

# Backtest
strategy = TopkDropoutStrategy(topk=30)
backtester = Backtester(initial_capital=1_000_000)
results = backtester.run(signals_df, prices_df, strategy)
```

**Features:** Direct Pathway API, composable functions, low-level control

### 3️⃣ Expression-Based (Rapid Prototyping)

Perfect for: Testing ideas quickly, research exploration

```python
from quant_stream import AlphaEvaluator, parse_expression

evaluator = AlphaEvaluator(table)
result = evaluator.evaluate("RANK(DELTA($close, 1))", factor_name="momentum")
```

**Features:** String-based expressions, automatic evaluation, fast prototyping

### 4️⃣ MCP Server (AI Agent Integration)

Perfect for: AlphaCopilot integration, distributed execution, async workflows

```bash
# Start both MCP server and Celery worker together (recommended)
quant-stream serve

# Or start separately:
# Start MCP server
python -m quant_stream.mcp_server

# Start Celery worker for async jobs
celery -A quant_stream.mcp_server.core.celery_config worker -Q workflow -l info

# Custom configuration
quant-stream serve --celery_queue backtest --celery_workers 4
```

```python
# Unified workflow tool - use for all scenarios
run_ml_workflow(
    factor_expressions=[
        {"name": "momentum", "expression": "DELTA($close, 20)"}
    ],
    model_type=None,  # Direct factors, or "LightGBM", "XGBoost", etc.
    train_start="2021-01-01",
    train_end="2021-12-31",
    strategy_type="TopkDropout",
    topk=30,
    commission=0.001,
)
# Returns: {"job_id": "abc123", "status": "PENDING"}

# Poll for completion
check_job_status(job_id="abc123")
# Returns: {"status": "SUCCESS", "result": {"metrics": {...}}}

# Also available:
validate_factors(factor_expressions=[...])  # Validate syntax
cancel_background_job(job_id="abc123")  # Cancel job
```

**Features:** Unified workflow tool, async job pattern, expression validation, langchain-mcp-adapters compatible

**Quick Start:**
```bash
# Start services (MCP + Celery)
quant-stream serve

# Then use with alphacopilot or other MCP clients
alphacopilot run "hypothesis" --backend mcp
```

### 5️⃣ AlphaCopilot CLI (Automated Factor Generation)

Perfect for: LLM-powered factor mining, hypothesis-driven research, automated workflows

```bash
# Generate factors from a hypothesis (LLM-powered) using default library backend
alphacopilot run "Short-term momentum predicts returns" \
  --model_type LightGBM \
  --data_start_date 2021-06-01 \
  --data_end_date 2021-12-31 \
  --max_iterations 3

# Or use workflow API (high-level, YAML-based)
alphacopilot run "Volume predicts returns" \
  --backend binary \
  --model_type LightGBM

# Or use direct library explicitly (low-level, fastest)
alphacopilot run "Volume predicts returns" \
  --backend library \
  --model_type LightGBM

# Need distributed async execution? Use MCP server
alphacopilot run "Volume predicts returns" \
  --backend mcp \
  --model_type LightGBM

# Validate expressions
alphacopilot validate --factor_expression "RANK(DELTA(\$close, 5))"

# List available functions
alphacopilot list-functions
```

**Features:** Mandatory hypothesis, LLM-based factor generation, iterative refinement, LangGraph workflow  
**Backends:** All have full parity - MCP (async), binary (stable API), or library (direct)

📖 See [`alphacopilot/README.md`](alphacopilot/README.md) for complete AlphaCopilot documentation

---

📖 **New to quant-stream?** Start with [examples/01_quickstart_backtest.py](examples/01_quickstart_backtest.py)  
🏗️ **Want to understand the architecture?** See [ARCHITECTURE.md](ARCHITECTURE.md)  
💡 **Looking for all examples?** Check the [examples/](examples/) directory  
📚 **Quick reference?** See [QUICKSTART.md](QUICKSTART.md)

## Table of Contents

- [Quant Stream](#quant-stream)
  - [What is Quant-Stream?](#what-is-quant-stream)
  - [Five Ways to Use Quant-Stream](#five-ways-to-use-quant-stream)
    - [1️⃣ YAML Configuration (No Code Required)](#1️⃣-yaml-configuration-no-code-required)
    - [2️⃣ Python Library (Full Control)](#2️⃣-python-library-full-control)
    - [3️⃣ Expression-Based (Rapid Prototyping)](#3️⃣-expression-based-rapid-prototyping)
    - [4️⃣ MCP Server (AI Agent Integration)](#4️⃣-mcp-server-ai-agent-integration)
    - [5️⃣ AlphaCopilot CLI (Automated Factor Generation)](#5️⃣-alphacopilot-cli-automated-factor-generation)
  - [Table of Contents](#table-of-contents)
  - [Project Structure](#project-structure)
  - [Installation](#installation)
    - [Requirements](#requirements)
    - [Using uv (Recommended)](#using-uv-recommended)
    - [Using pip](#using-pip)
    - [Data Setup](#data-setup)
  - [Usage Patterns](#usage-patterns)
    - [Pattern 1: YAML Workflow (Recommended for Most Users)](#pattern-1-yaml-workflow-recommended-for-most-users)
    - [Pattern 2: Python Library (Direct API)](#pattern-2-python-library-direct-api)
    - [Pattern 3: Expression-Based Evaluation](#pattern-3-expression-based-evaluation)
    - [Pattern 4: MCP Server for AI Agents](#pattern-4-mcp-server-for-ai-agents)
  - [Available Operations](#available-operations)
    - [Element-wise Operations](#element-wise-operations)
    - [Time-series Operations](#time-series-operations)
    - [Cross-sectional Operations (Group by Time)](#cross-sectional-operations-group-by-time)
    - [Rolling Window Operations](#rolling-window-operations)
    - [Technical Indicators](#technical-indicators)
    - [Two-column Operations](#two-column-operations)
    - [Mathematical Operations](#mathematical-operations)
  - [Expression Parser \& Evaluator](#expression-parser--evaluator)
    - [Parser](#parser)
    - [Parser Features](#parser-features)
    - [Parser Usage](#parser-usage)
    - [Evaluator](#evaluator)
    - [Parsing Rules](#parsing-rules)
    - [Examples](#examples)
    - [Known Limitations](#known-limitations)
  - [Experiment Tracking with Recorder](#experiment-tracking-with-recorder)
    - [Features](#features)
    - [Usage](#usage)
  - [Machine Learning Models](#machine-learning-models)
    - [Built-in Models](#built-in-models)
    - [Usage](#usage-1)
    - [Custom Models](#custom-models)
  - [Portfolio Strategies](#portfolio-strategies)
    - [Built-in Strategies](#built-in-strategies)
      - [TopkDropoutStrategy](#topkdropoutstrategy)
      - [WeightStrategy](#weightstrategy)
    - [Custom Strategies](#custom-strategies)
  - [Backtesting Engine](#backtesting-engine)
    - [Features](#features-1)
    - [Usage](#usage-2)
    - [Performance Metrics](#performance-metrics)
  - [Complete Workflow Example](#complete-workflow-example)
  - [YAML Configuration](#yaml-configuration)
    - [Quick Start](#quick-start)
    - [Example Configuration](#example-configuration)
    - [Available Examples](#available-examples)
    - [Python API](#python-api)
  - [MCP Server for AI Agents](#mcp-server-for-ai-agents)
    - [Quick Start](#quick-start-1)
    - [Available Tools](#available-tools)
    - [Available Resources](#available-resources)
    - [Workflow: Submit Job → Poll Status → Get Results](#workflow-submit-job--poll-status--get-results)
    - [Accessing Documentation Resources](#accessing-documentation-resources)
    - [Example: AI Agent Workflow](#example-ai-agent-workflow)
    - [Key Benefits for AI Agents](#key-benefits-for-ai-agents)
    - [AlphaCopilot Integration](#alphacopilot-integration)
    - [Running Without Docker](#running-without-docker)
      - [Quick Start (Recommended)](#quick-start-recommended)
      - [Manual Setup (Alternative)](#manual-setup-alternative)
      - [1. Install Dependencies](#1-install-dependencies)
      - [2. Start Redis](#2-start-redis)
      - [3. Start Services](#3-start-services)
      - [5. Configure Data Path (Optional)](#5-configure-data-path-optional)
      - [6. Test the Server](#6-test-the-server)
      - [Troubleshooting](#troubleshooting)
    - [Docker Deployment](#docker-deployment)
    - [Configuration](#configuration)
    - [Documentation](#documentation)
  - [Testing](#testing)
  - [Development](#development)
    - [Project Structure](#project-structure-1)
    - [Setting Up Development Environment](#setting-up-development-environment)
    - [Code Style](#code-style)
    - [Adding New Functions](#adding-new-functions)
    - [Running Tests](#running-tests)
  - [Contributing](#contributing)
  - [Architecture](#architecture)
  - [Performance Considerations](#performance-considerations)
  - [License](#license)
    - [Quant-Stream License](#quant-stream-license)
    - [Important: Pathway Dependency License](#important-pathway-dependency-license)
      - [Key Points About Pathway's License](#key-points-about-pathways-license)
      - [License Compatibility](#license-compatibility)
      - [What This Means For Common Use Cases](#what-this-means-for-common-use-cases)

## Project Structure

```text
quant_stream/
├── functions/          # 50+ technical indicators and operations
├── factors/            # Alpha factor parser and evaluator
├── models/             # ML models (LightGBM, XGBoost, RandomForest, Linear)
├── strategy/           # Portfolio strategies (TopkDropout, Weight)
├── backtest/           # Backtesting engine with IC metrics
├── config/             # YAML configuration system
├── workflows/          # YAML workflow runner
├── mcp_server/         # MCP server for AI agents (FastMCP + Celery)
├── recorder/           # MLflow experiment tracking
├── data/               # Data schema and replay
├── utils/              # Utilities (data splitting, etc.)
└── cli.py              # Command-line interface

examples/
├── configs/                             # YAML configuration examples
├── mcp_integration/                     # MCP server usage examples
├── 01_quickstart_backtest.py            # Quick start - one function call
├── 02_manual_factor_construction.py     # Manual factors (RECOMMENDED for production)
├── 03_expression_based_alphas.py        # Expression-based alpha comparison
├── 04_ml_model_comparison.py            # ML model training & selection
└── 05_expression_parser_demo.py         # Expression parser demonstration
```

**Core Modules:**
- **functions/** - All technical indicators (DELTA, SMA, RSI, RANK, etc.)
- **factors/** - Expression parser + evaluator for string-based alphas
- **models/** - ML forecasting with `create_model()` and `train_and_evaluate()`
- **backtest/** - Realistic simulation with `run_ml_workflow(...)` or `Backtester().run(...)`
- **workflows/** - YAML runner with `run_from_yaml()`
- **mcp_server/** - AI agent integration with async job execution

## Installation

This project uses [uv](https://github.com/astral-sh/uv) for dependency management.

### Requirements

- Python 3.11 or 3.12 (required by Pathway)
- Core Dependencies:
  - `pathway>=0.26.4` - Stream processing framework
  - `pandas>=2.3.3` - Data manipulation
  - `pyparsing>=3.0.0` - Expression parsing
- ML & Experiment Tracking:
  - `mlflow>=2.10.0` - Experiment tracking
  - `lightgbm>=4.1.0` - Gradient boosting
  - `xgboost>=2.0.0` - Gradient boosting
  - `scikit-learn>=1.3.0` - ML models
  - `scipy>=1.11.0` - Scientific computing
- Optional:
  - `yahooquery>=2.4.1` - Market data fetching

### Using uv (Recommended)

```bash
# Install dependencies
uv sync --all-groups --all-packages
```

### Using pip

```bash
pip install -e .
```

### Data Setup

For examples to work, you need market data. The examples expect data at `.data/indian_stock_market_nifty500.csv` with the following schema:

- `symbol`: Stock ticker
- `date`: Trading date (YYYY-MM-DD)
- `timestamp`: Unix timestamp
- `open`, `high`, `low`, `close`: OHLC prices
- `volume`: Trading volume

You can provide your own CSV data with this schema or use the data replayer with a custom path.

## Usage Patterns

### Pattern 1: YAML Workflow (Recommended for Most Users)

**Create a declarative configuration and run with CLI:**

```yaml
# momentum_strategy.yaml
data:
  path: ".data/indian_stock_market_nifty500.csv"

features:
  - name: "momentum"
    expression: "DELTA($close, 1)"
  - name: "volatility"
    expression: "TS_STD($close, 20)"

model:
  type: "LightGBM"
  params:
    learning_rate: 0.05
    num_boost_round: 100

strategy:
  type: "TopkDropout"
  params:
    topk: 30
    n_drop: 5
    method: "signal"

backtest:
  segments:
    train: ["2021-01-01", "2021-12-31"]
    test: ["2022-01-01", "2022-12-31"]
  initial_capital: 1000000
  commission: 0.001
  slippage: 0.001

experiment:
  name: "momentum_strategy"
  tracking_uri: "sqlite:///mlruns.db"
```

```bash
# Run the complete workflow
quant-stream run --config momentum_strategy.yaml --output results.csv

# View results in MLflow
mlflow ui --backend-store-uri sqlite:///mlruns.db
```

**What happens:**
1. ✅ Loads data with date filtering
2. ✅ Creates features from expressions
3. ✅ Trains ML model (if configured)
4. ✅ Generates signals/predictions
5. ✅ Applies portfolio strategy
6. ✅ Runs backtest with transaction costs
7. ✅ Calculates all metrics (returns + IC)
8. ✅ Logs everything to MLflow
9. ✅ Saves results to CSV

**Output:**
```
Performance Metrics
===================
TRAIN SEGMENT:
  Total Return:            12.34%
  Sharpe Ratio:              1.65
  IC:                        0.0543  ← Signal quality

TEST SEGMENT:
  Total Return:            15.67%
  Sharpe Ratio:              1.82
  IC:                        0.0489  ← Out-of-sample signal quality
```

---

### Pattern 2: Python Library (Direct API)

**Full control over every step:**

```python
from quant_stream.backtest import run_ml_workflow

result = run_ml_workflow(
    data_path=".data/indian_stock_market_nifty500.csv",
    factor_expressions=[
        {"name": "momentum", "expression": "DELTA($close, 1)"},
        {"name": "vol_rank", "expression": "RANK($volume)"},
    ],
    model_config={
        "type": "LightGBM",
        "params": {"learning_rate": 0.05, "max_depth": 5},
        "target": "forward_return_1d",
    },
    strategy_type="TopkDropout",
    strategy_params={"topk": 30, "n_drop": 5},
    backtest_segments={
        "train": ["2021-01-01", "2021-12-31"],
        "validation": ["2022-01-01", "2022-03-31"],
        "test": ["2022-04-01", "2022-12-31"],
    },
    log_to_mlflow=False,
)

print(f"Sharpe: {result['metrics']['sharpe_ratio']:.2f}")

# run_ml_workflow automatically derives the model's train/test/validation windows
# from backtest_segments, so backtesting and ML evaluation always share the same dates.
```

---

### Pattern 3: Expression-Based Evaluation

**Rapid alpha prototyping with string expressions:**

```python
from quant_stream import AlphaEvaluator, parse_expression
from quant_stream.data import replay_market_data
from quant_stream.backtest.engine import Backtester
from quant_stream.strategy import TopkDropoutStrategy
from quant_stream.backtest.metrics import calculate_sharpe_ratio
import pathway as pw

# Load data
table = replay_market_data()

# Create evaluator
evaluator = AlphaEvaluator(table)

# Test multiple alpha expressions
alphas = {
    "momentum_rank": "RANK(DELTA($close, 1))",
    "mean_reversion": "($close - SMA($close, 20)) / TS_STD($close, 20)",
    "volume_surge": "DIVIDE($volume, SMA($volume, 20))",
}

for name, expression in alphas.items():
    # Evaluate expression
    parsed = parse_expression(expression)
    result_table = evaluator.evaluate(parsed, factor_name="signal")
    
    # Convert to signals and backtest
    result_df = pw.debug.table_to_pandas(result_table)
    signals_df = result_df[["symbol", "timestamp", "signal"]].copy()
    prices_df = result_df[["symbol", "timestamp", "close"]].copy()
    
    # Quick backtest
    backtester = Backtester(initial_capital=1_000_000)
    backtest_result_df = backtester.run(
        signals_df=signals_df,
        prices_df=prices_df,
        strategy=TopkDropoutStrategy(topk=30),
    )
    
    sharpe = calculate_sharpe_ratio(backtest_result_df["returns"].dropna())
    print(f"{name}: periods={len(backtest_result_df)} Sharpe={sharpe:.2f}")
```

---

### Pattern 4: MCP Server for AI Agents

**Start the server and integrate with agents:**

**Server setup:**
```bash
# Install Redis (required for Celery)
brew install redis  # macOS
# or: sudo apt-get install redis-server  # Linux

# Start Redis
redis-server

# Start Celery worker
celery -A quant_stream.mcp_server.worker worker --loglevel=info

# Start MCP server
python -m quant_stream.mcp_server
```

**From AlphaCopilot or other AI agents:**
```python
# Tool call from agent
result = run_ml_workflow(
    config_dict={
        "data": {"path": ".data/indian_stock_market_nifty500.csv"},
        "features": [
            {"name": "momentum_rank", "expression": "RANK(DELTA($close, 1))"}
        ],
        "model": None,
        "strategy": {"type": "TopkDropout", "params": {"topk": 30, "n_drop": 5}},
        "backtest": {
            "segments": {
                "train": ["2021-01-01", "2021-12-31"],
                "test": ["2022-01-01", "2022-12-31"],
            }
        },
        "experiment": {"name": "agent_backtest"},
    }
)
# Returns immediately: {"job_id": "abc-123", "status": "PENDING"}

# Poll for completion
status = get_job_status(job_id="abc-123")
# Returns: {
#   "status": "SUCCESS",
#   "result": {
#     "success": True,
#     "train_metrics": {...},
#     "test_metrics": {...}
#   }
# }
```

**Python client for testing:**
```python
from examples.mcp_integration.agent_integration import MCPClient

with MCPClient() as client:
    # Simple backtest
    result = client.run_workflow(
        config_dict={
            "data": {"path": ".data/indian_stock_market_nifty500.csv"},
            "features": [{"name": "mom", "expression": "DELTA($close, 1)"}],
            "model": None,
            "strategy": {"type": "TopkDropout", "params": {"topk": 30}},
            "backtest": {"initial_capital": 1_000_000},
            "experiment": {"name": "demo_backtest"},
        }
    )
    print(f"Sharpe: {result['metrics']['sharpe_ratio']:.2f}")
```

## Available Operations

### Element-wise Operations
*[Implementation](quant_stream/functions/elementwise.py) | [Tests](tests/functions/test_elementwise.py)*

- `ABS`, `SIGN`, `MAX_ELEMENTWISE`, `MIN_ELEMENTWISE`, `IF`, `TERNARY`

### Time-series Operations
*[Implementation](quant_stream/functions/timeseries.py) | [Tests](tests/functions/test_timeseries.py)*

- `DELTA` - Calculate differences
- `DELAY` - Lag/shift data

### Cross-sectional Operations (Group by Time)
*[Implementation](quant_stream/functions/crosssectional.py) | [Tests](tests/functions/test_crosssectional.py)*

- `RANK`, `MEAN`, `STD`, `SKEW`, `MAX`, `MIN`, `MEDIAN`, `ZSCORE`, `SCALE`

### Rolling Window Operations
*[Implementation](quant_stream/functions/rolling.py) | [Tests](tests/functions/test_rolling.py)*

- `TS_MAX`, `TS_MIN`, `TS_MEAN`, `TS_MEDIAN`, `TS_SUM`
- `TS_STD`, `TS_VAR`, `TS_ARGMAX`, `TS_ARGMIN`, `TS_RANK`
- `PERCENTILE`, `TS_ZSCORE`, `TS_MAD`, `TS_QUANTILE`, `TS_PCTCHANGE`

### Technical Indicators
*[Implementation](quant_stream/functions/indicators.py) | [Tests](tests/functions/test_indicators.py)*

- `SMA`, `EMA`, `EWM`, `WMA` - Moving averages
- `COUNT`, `SUMIF`, `FILTER`, `PROD`, `DECAYLINEAR`
- `MACD`, `RSI` - Technical indicators
- `BB_MIDDLE`, `BB_UPPER`, `BB_LOWER` - Bollinger Bands

### Two-column Operations
*[Implementation](quant_stream/functions/twocolumn.py) | [Tests](tests/functions/test_twocolumn.py)*

- `TS_CORR`, `TS_COVARIANCE` - Correlation and covariance
- `HIGHDAY`, `LOWDAY`, `SUMAC`
- `REGBETA`, `REGRESI` - Regression analysis
- `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE` - Binary operations
- `AND`, `OR` - Logical operations

### Mathematical Operations
*[Implementation](quant_stream/functions/math_ops.py) | [Tests](tests/functions/test_math_ops.py)*

- `EXP`, `SQRT`, `LOG`, `INV`, `POW`, `FLOOR`

## Expression Parser & Evaluator

Quant-Stream includes a powerful expression parser and evaluator that converts mathematical formulas into executable Pathway operations. This enables you to write alpha factors using familiar mathematical notation and automatically execute them.

### Parser
*[Implementation](quant_stream/parser/expression_parser.py) | [Tests](tests/parser/test_expression_parser.py)*

The parser converts string expressions into function call syntax.

### Parser Features

- **Arithmetic Operations**: `+`, `-`, `*`, `/`
- **Comparison Operations**: `>`, `<`, `>=`, `<=`, `==`, `!=`
- **Logical Operations**: `&&`, `||`, `&`, `|`
- **Function Calls**: Support for all quant-stream functions
- **Nested Expressions**: Full support for complex nested formulas
- **Variable References**: Use `$column` syntax for column references

### Parser Usage
*See [`examples/parser_demo.py`](examples/parser_demo.py) for a complete example*

```python
from quant_stream.factors.parser.expression_parser import parse_expression

# Simple arithmetic
result = parse_expression("$open + $close")
# Output: "ADD($open, $close)"

# Complex alpha factor
result = parse_expression("RANK(DELTA($open, 1) - DELTA($close, 1)) / (1e-8 + 1)")
# Output: "DIVIDE(RANK(SUBTRACT(DELTA($open, 1), DELTA($close, 1))), 1e-8+1)"

# Technical indicator
result = parse_expression("($close - SMA($close, 20)) / TS_STD($close, 20)")
# Output: "DIVIDE(SUBTRACT($close, SMA($close, 20)), TS_STD($close, 20))"

# Logical operations
result = parse_expression("($close > $open) && ($volume > 1000)")
# Output: "AND(($close>$open), ($volume>1000))"
```

### Evaluator
*[Implementation](quant_stream/evaluator.py) | [Tests](tests/engine/test_evaluator.py)*

The evaluator executes parsed expressions on Pathway tables:

```python
from quant_stream import AlphaEvaluator
from quant_stream.factors.parser.expression_parser import parse_expression
from quant_stream.data.replayer import replay_market_data

# Load data
table = replay_market_data()

# Create evaluator (auto-detects 'symbol' or 'instrument' column)
evaluator = AlphaEvaluator(table)

# Parse and evaluate
expr = parse_expression("DELTA($close, 1)")
result = evaluator.evaluate(expr, factor_name="momentum")
```

### Parsing Rules

1. **Arithmetic with variables**: Converted to function calls
   - `$a + $b` → `ADD($a, $b)`
   - `$a - $b` → `SUBTRACT($a, $b)`
   - `$a * $b` → `MULTIPLY($a, $b)`
   - `$a / $b` → `DIVIDE($a, $b)`

2. **Arithmetic with constants**: Kept as inline operations
   - `$close + 1` → `$close+1`
   - `$close * 2` → `$close*2`

3. **Logical operations**: Converted to function calls
   - `$a && $b` → `AND($a, $b)`
   - `$a || $b` → `OR($a, $b)`

4. **Operator precedence**: Standard mathematical precedence
   - Multiplication and division before addition and subtraction
   - Parentheses override precedence

### Examples

See the [`examples/`](examples/) directory for complete demonstrations:

**Expression Parser:** [`examples/parser_demo.py`](examples/parser_demo.py)

```bash
uv run python examples/parser_demo.py
```

**Manual Alpha Factor Construction (Recommended):** [`examples/alpha_demo.py`](examples/alpha_demo.py)

```bash
uv run python examples/alpha_demo.py
```

**Automatic Expression Evaluation:** [`examples/alpha_runner.py`](examples/alpha_runner.py)

```bash
uv run python examples/alpha_runner.py
```

For detailed documentation and more examples, see [`examples/README.md`](examples/README.md).

### Known Limitations

- **Column Detection**: The evaluator auto-detects `symbol` or `instrument` columns for grouping operations.
- **Computation Graph**: The expression evaluator builds computation graphs dynamically. For complex multi-stage alphas, the manual approach ([`examples/alpha_demo.py`](examples/alpha_demo.py)) provides more explicit control over intermediate steps.

## Experiment Tracking with Recorder

*[Implementation](quant_stream/recorder/) | [Tests](tests/recorder/)*

Quant-Stream includes an MLflow-based experiment tracking system for logging parameters, metrics, and artifacts.

### Features

- **MLflow Backend**: Full MLflow compatibility with UI support
- **Run Management**: Organize experiments into runs with metadata
- **Artifact Storage**: Save models, predictions, and results
- **Search & Compare**: Filter and compare runs by metrics

### Usage

```python
from quant_stream import Recorder

# Create recorder
recorder = Recorder("my_experiment", tracking_uri="sqlite:///mlruns.db")

# Start a run
with recorder.start_run("test_run"):
    # Log parameters
    recorder.log_params(model="LightGBM", learning_rate=0.05)
    
    # Log metrics
    recorder.log_metrics(IC=0.05, sharpe_ratio=1.8)
    
    # Save artifacts
    recorder.save_objects(predictions=pred_df)
    recorder.log_artifact_dataframe(results_df, "backtest_results")
    
    # Set tags
    recorder.set_tags(strategy="momentum", dataset="US_stocks")

# View in MLflow UI
# mlflow ui --backend-store-uri sqlite:///mlruns.db
```

## Machine Learning Models

*[Implementation](quant_stream/models/) | [Tests](tests/models/)*

Framework-agnostic ML forecasting with built-in implementations for financial time-series.

### Built-in Models

- **LightGBM**: Gradient boosting optimized for finance
- **XGBoost**: High-performance gradient boosting
- **RandomForest**: Ensemble of decision trees
- **Linear**: Ridge/Lasso/ElasticNet regression

### Usage

```python
from quant_stream import LightGBMModel, LinearModel
from quant_stream.models.utils import calculate_ic

# Train LightGBM model
model = LightGBMModel(
    params={"learning_rate": 0.05, "max_depth": 5},
    num_boost_round=100
)
model.fit(X_train, y_train, eval_set=(X_val, y_val))

# Generate predictions
predictions = model.predict(X_test)

# Get feature importance
importance = model.get_feature_importance()

# Calculate IC metrics
ic_metrics = calculate_ic(predictions, y_test)
print(f"IC: {ic_metrics['IC']:.4f}, Rank IC: {ic_metrics['Rank_IC']:.4f}")

# Save model
model.save("model.txt")

# Load model
loaded_model = LightGBMModel.load("model.txt")
```

### Custom Models

Extend the `ForecastModel` base class:

```python
from quant_stream.models import ForecastModel

class MyCustomModel(ForecastModel):
    def fit(self, X, y, **kwargs):
        # Your training logic
        self.is_fitted = True
        return self
    
    def predict(self, X):
        # Your prediction logic
        return predictions
```

## Portfolio Strategies

*[Implementation](quant_stream/strategy/) | [Tests](tests/strategy/)*

Convert signals into portfolio positions with built-in and custom strategies.

### Built-in Strategies

#### TopkDropoutStrategy

Select top-k instruments by signal strength with periodic rebalancing:

```python
from quant_stream import TopkDropoutStrategy

strategy = TopkDropoutStrategy(
    topk=50,          # Hold top 50 instruments
    n_drop=5,         # Drop bottom 5 each period
    method="equal"    # Equal weight or "signal" for proportional
)
```

#### WeightStrategy

Allocate capital based on signal weights:

```python
from quant_stream import WeightStrategy

strategy = WeightStrategy(
    method="proportional",  # Weight by signal strength
    long_only=True,        # Only long positions
    normalize=True         # Normalize weights to sum to 1
)
```

### Custom Strategies

Extend the `Strategy` base class:

```python
from quant_stream import Strategy
import pathway as pw

class MyCustomStrategy(Strategy):
    def generate_positions(self, signals, current_positions=None):
        # Your portfolio construction logic
        return target_positions_table
```

## Backtesting Engine

*[Implementation](quant_stream/backtest/) | [Tests](tests/backtest/)*

Realistic portfolio simulation with transaction costs and performance metrics.

### Features

- **Transaction Costs**: Commission and slippage modeling
- **Position Tracking**: Track cash and holdings over time
- **Performance Metrics**: Sharpe, Sortino, drawdown, IC, etc.
- **MLflow Integration**: Log backtest results automatically

### Usage

```python
from quant_stream import Backtester, TopkDropoutStrategy, calculate_returns_metrics

# Create backtester
backtester = Backtester(
    initial_capital=1_000_000,
    commission=0.001,      # 0.1% commission
    slippage=0.001,        # 0.1% slippage
    min_commission=5.0     # $5 minimum per trade
)

# Create strategy
strategy = TopkDropoutStrategy(topk=30, n_drop=5)

# Run backtest (pandas mode for easier implementation)
results_df = backtester.run(
    signals_df,  # DataFrame with [symbol, timestamp, signal]
    prices_df,   # DataFrame with [symbol, timestamp, close]
    strategy,
    recorder=recorder  # Optional: log to MLflow
)

# Calculate performance metrics
returns = results_df["returns"].dropna()
metrics = calculate_returns_metrics(returns)

print(f"Total Return:  {metrics['total_return']:>7.2%}")
print(f"Sharpe Ratio:  {metrics['sharpe_ratio']:>7.2f}")
print(f"Max Drawdown:  {metrics['max_drawdown']:>7.2%}")
print(f"Calmar Ratio:  {metrics['calmar_ratio']:>7.2f}")
```

### Performance Metrics

```python
from quant_stream import (
    calculate_returns_metrics,
    calculate_ic_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
)

# Comprehensive metrics
metrics = calculate_returns_metrics(returns)
# Returns: total_return, annual_return, sharpe_ratio, sortino_ratio,
#          max_drawdown, calmar_ratio, win_rate, avg_win, avg_loss

# IC metrics
ic_metrics = calculate_ic_metrics(predictions, actual_returns)
# Returns: IC, Rank_IC, ICIR, Rank_ICIR

# Individual metrics
sharpe = calculate_sharpe_ratio(returns)
sortino = calculate_sortino_ratio(returns)
```

## Complete Workflow Example

See [`examples/end_to_end_workflow.py`](examples/end_to_end_workflow.py) for a complete quantitative research workflow:

```python
from quant_stream import (
    replay_market_data, DELTA, SMA, RANK,
    LightGBMModel, TopkDropoutStrategy,
    Backtester, Recorder
)

# 1. Load data and create features
table = replay_market_data()
table = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
table = SMA(table, pw.this.close, m=20, by_instrument=pw.this.symbol)

# 2. Train model with experiment tracking
recorder = Recorder("quant_research")
with recorder.start_run("lightgbm_momentum"):
    model = LightGBMModel()
    model.fit(X_train, y_train)
    predictions = model.predict(X_test)
    recorder.log_metrics(IC=ic_metrics["IC"])

# 3. Apply strategy and backtest
strategy = TopkDropoutStrategy(topk=30)
backtester = Backtester(initial_capital=1_000_000)
results = backtester.run(signals_df, prices_df, strategy, recorder)

# 4. Analyze performance
metrics = calculate_returns_metrics(results["returns"])
print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
```

See more examples:
- [`examples/model_training_demo.py`](examples/model_training_demo.py) - ML model training
- [`examples/backtest_demo.py`](examples/backtest_demo.py) - Strategy backtesting
- [`examples/end_to_end_workflow.py`](examples/end_to_end_workflow.py) - Complete workflow

## YAML Configuration

**NEW**: Run complete workflows from declarative YAML configuration files - no Python code required!

### Quick Start

```bash
# Initialize a configuration file
quant-stream init --output my_workflow.yaml

# Validate the configuration
quant-stream validate --config my_workflow.yaml

# Run the workflow
quant-stream run --config my_workflow.yaml --output results.csv
```

### Example Configuration

```yaml
data:
  path: ".data/indian_stock_market_nifty500.csv"
  start_date: "2021-06-01"
  end_date: "2022-06-30"

features:
  - name: "momentum_1d"
    expression: "DELTA($close, 1)"
  - name: "volatility_20d"
    expression: "TS_STD($close, 20)"

model:
  type: "LightGBM"
  params:
    learning_rate: 0.05
    max_depth: 5
    num_boost_round: 100
  target: "forward_return_1d"

strategy:
  type: "TopkDropout"
  params:
    topk: 30
    n_drop: 5
    method: "equal"

backtest:
  segments:
    train: ["2021-06-01", "2021-12-31"]
    test: ["2022-01-01", "2022-06-30"]
  initial_capital: 1000000
  commission: 0.001
  slippage: 0.001

experiment:
  name: "my_strategy"
  tracking_uri: "sqlite:///mlruns.db"
  tags:
    strategy: "momentum"
```

### Available Examples

See [`examples/configs/`](examples/configs/):
- [`basic_momentum.yaml`](examples/configs/basic_momentum.yaml) - Simple momentum strategy
- [`multi_factor.yaml`](examples/configs/multi_factor.yaml) - Multiple alpha factors
- [`lightgbm_strategy.yaml`](examples/configs/lightgbm_strategy.yaml) - Advanced LightGBM with 13 factors

### Python API

```python
from quant_stream.runner import run_from_yaml

# Run workflow from YAML
results = run_from_yaml("workflow.yaml", output_path="results.csv")

# Access metrics
print(f"Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
print(f"Total Return: {results['metrics']['total_return']:.2%}")
```

See [`examples/configs/README.md`](examples/configs/README.md) for complete documentation.

## MCP Server for AI Agents

**NEW**: Expose quant-stream as a Model Context Protocol (MCP) server for AI agent integration with comprehensive alpha construction documentation!

### Quick Start

```bash
# Start the MCP server with Redis and Celery
cd quant_stream/mcp
docker-compose up

# Or run locally (requires Redis running)
celery -A quant_stream.mcp_server.core.celery_app worker --loglevel=info -Q backtest &
mcp dev quant_stream/mcp_server/app.py
```

The FastMCP server provides tools and resources for autonomous alpha factor generation and backtesting.

### Available Tools

1. **backtest**: Run single-factor backtests with full configuration (async)
   - Data config: path, date filters, column names
   - Strategy config: type, method, topk, n_drop, hold_periods
   - Backtest config: capital, commission, slippage, rebalance frequency
   - Experiment config: name, run_name, tags, tracking URI
   
2. **run_ml_workflow**: Complete ML pipeline (features → model → backtest)
   - Multiple features with expressions
   - Model training: LightGBM, XGBoost, RandomForest, Linear
   - Train/test splits for model and backtest
   - All configuration options from YAML workflows
   
3. **check_job_status**: Poll job status and retrieve results
4. **cancel_background_job**: Cancel running or pending jobs

### Available Resources

The server provides comprehensive documentation for AI agents:

1. **`docs://functions/available`** - Complete library of 70+ functions organized by category
2. **`docs://alpha/construction`** - Factor construction guide with syntax rules and best practices
3. **`docs://alpha/patterns`** - 40+ proven factor patterns (momentum, mean reversion, volatility, etc.)
4. **`config://strategy/topk_dropout`** - TopkDropout strategy configuration
5. **`config://strategy/weight`** - Weight strategy configuration
6. **`config://backtest/default`** - Backtest parameters with segments
7. **`config://data/default`** - Data loading configuration
8. **`config://model/lightgbm`** - LightGBM model configuration
9. **`config://experiment/default`** - MLflow experiment tracking config

### Workflow: Submit Job → Poll Status → Get Results

The MCP server uses asynchronous background jobs with full configuration support:

```python
# 1. Submit backtest job with full configuration (returns immediately)
result = backtest(
    factor_expression="RANK(DELTA($close, 5))",
    factor_name="momentum_5d",
    train_dates=["2021-01-01", "2021-12-31"],
    test_dates=["2022-01-01", "2022-12-31"],
    # Data configuration
    data_path=".data/market_data.csv",
    data_start_date="2021-01-01",
    data_end_date="2022-12-31",
    # Strategy configuration
    strategy_type="TopkDropout",
    strategy_method="signal",
    topk=40,
    n_drop=8,
    hold_periods=5,
    # Backtest configuration
    initial_capital=5_000_000,
    commission=0.0015,
    slippage=0.001,
    min_commission=5.0,
    rebalance_frequency=5,
    # Experiment tracking
    experiment_name="momentum_research",
    run_name="momentum_5d_weekly",
    experiment_tags={"strategy": "momentum", "rebalance": "weekly"}
)
job_id = result["job_id"]

# 2. Poll for status
status = check_job_status(job_id)
# Returns: {"status": "PROCESSING", "progress": {"status": "Running", "progress": 50}}

# 3. Get results when complete
final_result = check_job_status(job_id)
if final_result["status"] == "SUCCESS":
    train_metrics = final_result["result"]["train_metrics"]
    test_metrics = final_result["result"]["test_metrics"]
    print(f"Train Sharpe: {train_metrics['sharpe_ratio']:.2f}")
    print(f"Test Sharpe: {test_metrics['sharpe_ratio']:.2f}")
```

### Accessing Documentation Resources

AI agents can query the documentation resources to understand available functions and construction patterns:

```python
# Get complete function library
functions_doc = get_resource("docs://functions/available")
# Returns markdown with all 70+ functions organized by category

# Get alpha construction guide
construction_guide = get_resource("docs://alpha/construction")
# Returns comprehensive guide with syntax rules and best practices

# Get pattern library
patterns = get_resource("docs://alpha/patterns")
# Returns 40+ ready-to-use factor patterns

# Get example configs
strategy_config = get_resource("config://strategy/topk_dropout")
backtest_config = get_resource("config://backtest/default")
```

### Example: AI Agent Workflow

```python
# 1. AI agent queries available functions
functions = get_resource("docs://functions/available")
# Learns about RANK, DELTA, TS_STD, etc.

# 2. AI agent reads construction guide
guide = get_resource("docs://alpha/construction")
# Learns: "Always use relative changes, not raw prices"
# Learns: "Apply RANK() for cross-sectional comparability"

# 3. AI agent constructs factor following best practices
factor_expr = "RANK(DELTA($close, 5) / ($close + 1e-8))"

# 4. AI agent submits backtest
result = backtest(
    factor_expression=factor_expr,
    factor_name="ai_momentum",
    topk=30,
    n_drop=5
)

# 5. AI agent polls and evaluates results
job_id = result["job_id"]
while True:
    status = check_job_status(job_id)
    if status["status"] == "SUCCESS":
        metrics = status["result"]["metrics"]
        break
    time.sleep(2)  # Poll every 2 seconds
```

### Key Benefits for AI Agents

The MCP server is specifically designed for autonomous alpha factor generation:

1. **Self-Documenting**: AI agents can query the function library and construction guide to learn syntax and best practices
2. **Proven Patterns**: 40+ validated factor patterns serve as templates for new ideas
3. **Asynchronous**: Background job processing allows agents to work on multiple factors concurrently
4. **Best Practices Embedded**: Construction guide includes AlphaCopilot research insights on robust factor design
5. **Complete Workflow**: From factor expression to backtest results in one integrated system

### AlphaCopilot Integration

**🚀 Quick Start:** AlphaCopilot now has a dedicated CLI for automated factor generation!

```bash
# Run with hypothesis (required) - all backends have full feature parity
alphacopilot run "Short-term momentum predicts returns" \
  --backend library \        # or: binary, mcp
  --model_type LightGBM \
  --data_start_date 2021-06-01 \
  --data_end_date 2021-12-31

# Use custom MCP server (SSE or stdio)
alphacopilot run "Short-term momentum predicts returns" \
  --backend mcp \
  --mcp_server "http://localhost:8000/mcp" \
  --model_type LightGBM

# Validate factor expressions
alphacopilot validate --factor_expression "RANK(DELTA(\$close, 5))"

# List available functions
alphacopilot list-functions
```

**Backend Comparison:** All have identical features, choose by deployment needs:
- `mcp`: Async, distributed (MCP server via SSE/stdio + Redis)
- `binary`: Sync, stable API (no setup required)
- `library`: Sync, direct calls (for debugging)

**MCP Connection:** Supports SSE (`http://...`), stdio (`./script.py`), or default built-in server

See [`alphacopilot/README.md`](alphacopilot/README.md) for complete documentation.

The MCP server serves as the execution backend for AlphaCopilot's factor mining workflow:

- **Factor Calculate Node**: Use the `run_ml_workflow` tool to evaluate factor expressions
- **Factor Validation Node**: Use the `validate_factors` tool to check syntax
- **Factor Backtest Node**: Poll `check_job_status` to retrieve backtest metrics
- **Feedback Loop**: Use construction guide to improve factor quality iteratively
- **Documentation Resources**: Provide context for hypothesis-to-factor translation

### Running Without Docker

For local development or testing, you can run the components manually:

#### Quick Start (Recommended)

```bash
# 1. Install dependencies
uv sync --group mcp

# 2. Start Redis (if not already running)
brew services start redis  # macOS
# or
redis-server               # Linux

# 3. Start both MCP server and Celery worker together
quant-stream serve
```

#### Manual Setup (Alternative)

#### 1. Install Dependencies

```bash
# Install quant-stream with MCP dependencies using uv
uv sync --group mcp

# Or with pip (from project root)
pip install -e "."
pip install "mcp[cli]>=1.0.0" "celery[redis]>=5.3.0" "redis>=5.0.0"

# Verify installation
python -c "import mcp; import celery; import redis; print('Dependencies installed successfully')"
```

#### 2. Start Redis

```bash
# Install Redis (macOS)
brew install redis
brew services start redis

# Or run Redis directly
redis-server

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# Verify Redis is running
redis-cli ping  # Should return "PONG"
```

#### 3. Start Services

**Option A: Combined (Recommended)**
```bash
# Start both MCP server and Celery worker together
quant-stream serve

# With custom options
quant-stream serve --celery_queue backtest --celery_workers 4
```

**Option B: Separate Processes**
```bash
# Terminal 1: Start Celery Worker
celery -A quant_stream.mcp_server.core.celery_config:celery_app worker \
  --loglevel=info \
  -Q workflow \
  --pool=solo  # Use solo pool on macOS/Windows

# Terminal 2: Start MCP Server
python -m quant_stream.mcp_server

# Or using mcp CLI
mcp dev quant_stream/mcp_server/app.py
```

#### 5. Configure Data Path (Optional)

Set environment variables for custom configuration:

```bash
export DATA_PATH=".data/your_data.csv"
export REDIS_URL="redis://localhost:6379/0"
export LOG_LEVEL="INFO"

# Then start services
celery -A quant_stream.mcp_server.core.celery_app worker --loglevel=info -Q backtest --pool=solo
mcp dev quant_stream/mcp_server/app.py
```

#### 6. Test the Server

```bash
# Check if server is running (if using Inspector)
mcp list-tools

# Or test with Python
python -c "
from quant_stream.mcp_server.app import mcp
print('MCP Server loaded successfully')
"
```

#### Troubleshooting

**Redis Connection Issues:**

```bash
# Check if Redis is running
redis-cli ping

# Check Redis connection
redis-cli -h localhost -p 6379 ping
```

**Celery Worker Issues:**

```bash
# Check Celery configuration
celery -A quant_stream.mcp_server.core.celery_app inspect active

# View worker status
celery -A quant_stream.mcp_server.core.celery_app status
```

**Port Conflicts:**

- Redis default port: 6379
- Change in config if needed: `REDIS_URL=redis://localhost:6380/0`

### Docker Deployment

For production or easier setup, use Docker Compose:

```bash
# Start all services (Redis + Celery + FastMCP)
cd quant_stream/mcp_server
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

The docker-compose setup includes:
- **Redis**: Message broker for Celery
- **Celery Worker**: Background job processor
- **FastMCP Server**: MCP protocol server with tools and resources

### Configuration

Customize via environment variables in `docker-compose.yml`:

```yaml
environment:
  - DATA_PATH=/app/.data/indian_stock_market_nifty500.csv
  - REDIS_URL=redis://redis:6379/0
  - LOG_LEVEL=INFO
```

### Documentation

- MCP Server: [`quant_stream/mcp_server/README.md`](quant_stream/mcp_server/README.md)
- Integration examples: [`examples/mcp_integration/README.md`](examples/mcp_integration/README.md)
- AlphaCopilot documentation: [`alphacopilot/README.md`](alphacopilot/README.md)
- AlphaCopilot CLI: Run `alphacopilot --help` for usage

## Testing
*See [`tests/`](tests/) directory for all tests*

Run the test suite:

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/functions/test_elementwise.py -v

# Run with coverage and generate test report
pytest tests/ --cov=quant_stream --cov-report=xml --cov-report=term-missing --junitxml=junit.xml

# Generate coverage and test badges
mkdir -p assets
genbadge coverage -i coverage.xml -o assets/coverage-badge.svg
genbadge tests -i junit.xml -o assets/tests-badge.svg
```

All tests use ID columns for verification and compare Pathway results against Pandas implementations. For testing utilities and helpers, see [`tests/functions/test_utils.py`](tests/functions/test_utils.py).

## Development

### Project Structure

The codebase is organized into logical modules under [`quant_stream/functions/`](quant_stream/functions/):

- **[helpers.py](quant_stream/functions/helpers.py)** - Core utilities and helper functions used across modules
- **[elementwise.py](quant_stream/functions/elementwise.py)** - Simple element-wise transformations
- **[timeseries.py](quant_stream/functions/timeseries.py)** - Operations that work on time-ordered data per instrument
- **[crosssectional.py](quant_stream/functions/crosssectional.py)** - Operations that aggregate across instruments at each timestamp
- **[rolling.py](quant_stream/functions/rolling.py)** - Time-series rolling window aggregations per instrument
- **[indicators.py](quant_stream/functions/indicators.py)** - Technical analysis indicators and moving averages
- **[twocolumn.py](quant_stream/functions/twocolumn.py)** - Operations involving two columns (correlation, regression, etc.)
- **[math_ops.py](quant_stream/functions/math_ops.py)** - Mathematical transformations

Each module is self-contained and can be imported independently.

### Setting Up Development Environment

1. **Install with dev dependencies**:

   ```bash
   uv sync --group test
   ```

2. **Verify installation**:

   ```bash
   pytest tests/ -v
   ```

3. **Generate badges** (optional, for README display):

   ```bash
   pytest tests/ --cov=quant_stream --cov-report=xml --junitxml=junit.xml
   mkdir -p assets
   genbadge coverage -i coverage.xml -o assets/coverage-badge.svg
   genbadge tests -i junit.xml -o assets/tests-badge.svg
   ```

### Code Style

This project uses:

- **Ruff** for linting and formatting
- **pytest** for testing with coverage

Run formatting and linting:

```bash
# Format code
ruff format quant_stream/ tests/

# Lint code
ruff check quant_stream/ tests/

# Auto-fix linting issues
ruff check --fix quant_stream/ tests/
```

### Adding New Functions

When adding a new function:

1. **Choose the appropriate module** based on the operation type (see [Project Structure](#project-structure))
2. **Implement the function** following the existing patterns:
   - Accept `table` as first parameter
   - Use Pathway operations (`pw.this`, `select`, `groupby`, etc.)
   - Include docstring with parameters and return type
3. **Export in [`quant_stream/__init__.py`](quant_stream/__init__.py)** to make it available at package level
4. **Write tests** in [`tests/functions/test_<module>.py`](tests/functions/):
   - Use test utilities from [`test_utils.py`](tests/functions/test_utils.py)
   - Compare against pandas implementation
   - Test with multiple instruments and edge cases
5. **Update documentation** in this README

Example workflow:

```python
# 1. Add function to quant_stream/functions/indicators.py
def MY_INDICATOR(table, col, param):
    """Your indicator implementation"""
    return table.select(...)

# 2. Export in quant_stream/__init__.py
from quant_stream.functions.indicators import MY_INDICATOR

# 3. Add test in tests/functions/test_indicators.py
def test_my_indicator():
    # Test implementation
    pass
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/functions/test_indicators.py -v

# Run with coverage report
pytest tests/ --cov=quant_stream --cov-report=xml --cov-report=term-missing --junitxml=junit.xml

# Generate badges (after running tests with coverage)
mkdir -p assets
genbadge coverage -i coverage.xml -o assets/coverage-badge.svg
genbadge tests -i junit.xml -o assets/tests-badge.svg

# Run specific test
pytest tests/functions/test_indicators.py::test_sma -v
```

## Contributing

Contributions are welcome! Please ensure:

1. All tests pass: `pytest tests/`
2. New functions include tests in [`tests/functions/`](tests/functions/)
3. Code follows the existing module structure (see [Project Structure](#project-structure))
4. Functions are exported in [`quant_stream/__init__.py`](quant_stream/__init__.py)

## Architecture

Quant-Stream is built on [Pathway](https://pathway.com), a high-performance stream processing framework. Key design principles:

- **Incremental Computation**: Changes propagate efficiently through the computation graph
- **Event-driven**: Data is processed as it arrives (or replays)
- **Composable**: Functions can be chained and nested
- **Type-safe**: Pathway's type system ensures correctness

## Performance Considerations

- **Memory**: Rolling window operations maintain state per instrument
- **Computation**: Cross-sectional operations process all instruments at each timestamp
- **Replay Speed**: Control data replay rate with the `speedup` parameter
- **Parallelism**: Pathway automatically parallelizes computations

## License

### Quant-Stream License

This project (Quant-Stream) is licensed under the MIT License:

```text
MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Important: Pathway Dependency License

**⚠️ This project depends on [Pathway](https://pathway.com), which is licensed under the Business Source License 1.1 (BSL 1.1).**

#### Key Points About Pathway's License

1. **Free for Development & Single-Machine Production**: You can use Pathway for free in development and for single-machine production deployments
2. **Production Restrictions**:
   - Limited to single-machine deployments (one physical or virtual machine)
   - Cannot be used for "Stream Data Processing Service" offerings
   - Cannot circumvent resource limits or license keys
3. **Converts to Apache 2.0**: After 4 years from release date (no earlier than July 20, 2027), Pathway converts to Apache 2.0 license
4. **Commercial License Available**: For use cases beyond the Additional Use Grant, contact Pathway for commercial licensing

#### License Compatibility

While Quant-Stream itself is MIT licensed (permissive), using it requires Pathway (BSL 1.1, which has restrictions). This means:

- ✅ You can freely use, modify, and distribute Quant-Stream code (MIT)
- ⚠️ But if you run it with Pathway, you must comply with Pathway's BSL 1.1 restrictions
- ✅ For typical quantitative research and single-machine backtesting, this is generally fine
- ❌ For offering this as a multi-tenant service or cloud offering, you'll need a Pathway commercial license

**Recommendation**: Review the full [Pathway BSL 1.1 license](https://github.com/pathwaycom/pathway/blob/main/LICENSE.txt) to ensure your use case complies with the Additional Use Grant.

#### What This Means For Common Use Cases

| Use Case | Permitted Under Pathway BSL 1.1? |
|----------|----------------------------------|
| Personal quantitative research | ✅ Yes |
| Single-machine backtesting | ✅ Yes |
| Academic research | ✅ Yes |
| Internal company tools (single machine) | ✅ Yes |
| Hedge fund alpha research | ✅ Yes (single machine) |
| Cloud/SaaS offering to customers | ❌ No - needs commercial license |
| Multi-tenant data processing service | ❌ No - needs commercial license |

For questions about licensing, contact Pathway at [pathway.com](https://pathway.com) or consult with your legal team.
