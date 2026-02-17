# Quant-Stream Quick Start

Get started with quant-stream in 5 minutes.

## Installation

```bash
# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

## Choose Your Workflow

### Option 1: YAML Configuration (Easiest - No Code!)

**1. Create a configuration file:**
```bash
quant-stream init --output my_strategy.yaml
```

**2. Edit the config** (`my_strategy.yaml`):
```yaml
data:
  path: ".data/indian_stock_market_nifty500.csv"

features:
  - name: "momentum"
    expression: "DELTA($close, 1)"

strategy:
  type: "TopkDropout"
  params:
    topk: 30

backtest:
  segments:
    train: ["2021-01-01", "2021-12-31"]
    test: ["2022-01-01", "2022-12-31"]
  initial_capital: 1000000
```

**3. Run it:**
```bash
quant-stream run --config my_strategy.yaml
```

**Output:**
```
Performance Metrics
===================
TRAIN SEGMENT:
  Sharpe Ratio:         1.65
  IC:                   0.0543

TEST SEGMENT:
  Sharpe Ratio:         1.82
  IC:                   0.0489
```

---

### Option 2: Python Library (Full Control)

**Create a simple momentum strategy:**

```python
import pathway as pw
from quant_stream import DELTA, RANK, Backtester, TopkDropoutStrategy

# Load data
table = pw.debug.table_from_pandas(df)

# Create factor
table = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
table = RANK(table, pw.this.delta)

# Convert to signals
signals_df = pw.debug.table_to_pandas(table)[["symbol", "timestamp", "delta"]]
signals_df.columns = ["symbol", "timestamp", "signal"]

# Backtest
strategy = TopkDropoutStrategy(topk=30)
backtester = Backtester(initial_capital=1_000_000)
results = backtester.run(signals_df, prices_df, strategy)

print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
```

---

### Option 3: Expression-Based (Rapid Prototyping)

**Test alpha ideas quickly:**

```python
from quant_stream import AlphaEvaluator, parse_expression
from quant_stream.data import replay_market_data

# Load data
table = replay_market_data()

# Create evaluator
evaluator = AlphaEvaluator(table)

# Test different alpha expressions
expressions = [
    "RANK(DELTA($close, 1))",                    # Momentum rank
    "($close - SMA($close, 20)) / TS_STD($close, 20)",  # Bollinger position
    "TS_CORR($close, $volume, 10)",              # Price-volume correlation
]

for expr in expressions:
    parsed = parse_expression(expr)
    result = evaluator.evaluate(parsed, factor_name="alpha")
    # result is a Pathway table with the factor
```

---

### Option 4: ML-Based Workflow (YAML)

**Use machine learning for predictions:**

```yaml
# ml_strategy.yaml
features:
  - name: "momentum_1d"
    expression: "DELTA($close, 1)"
  - name: "momentum_5d"
    expression: "DELTA($close, 5)"
  - name: "volatility"
    expression: "TS_STD($close, 20)"

model:
  type: "LightGBM"
  params:
    learning_rate: 0.05
    max_depth: 5
    num_boost_round: 100

strategy:
  type: "TopkDropout"
  params:
    topk: 50
    method: "signal"  # Weight by model predictions

backtest:
  segments:
    train: ["2020-01-01", "2021-12-31"]
    test: ["2022-01-01", "2022-12-31"]
```

```bash
quant-stream run --config ml_strategy.yaml
```

---

### Option 5: MCP Server (AI Agents)

**For AlphaCopilot integration with full configuration:**

```bash
# Start server (requires Redis + Celery)
python -m quant_stream.mcp_server
```

**From your AI agent - now supports all YAML config options:**
```python
# Simple backtest
backtest(factor_expression="DELTA($close, 1)", train_dates=["2021-01-01", "2021-12-31"])

# Or with full configuration
backtest(
    factor_expression="...",
    strategy_method="signal",
    commission=0.0015,
    experiment_name="my_research"
    # + 20+ more config options
)

# Or complete ML workflow
run_ml_workflow(
    factor_expressions=[...],
    model_type="LightGBM",
    model_params={...}
)
```

**📖 See [README.md](README.md#mcp-server-for-ai-agents) for complete MCP configuration options**

---

## Common Workflows

### Workflow 1: Factor-Only Strategy
Create factors → Use as signals → Backtest

```yaml
features:
  - name: "signal"
    expression: "RANK(DELTA($close, 1))"
# NO model section

strategy:
  type: "TopkDropout"
  params: {topk: 30}

backtest:
  segments:
    train: ["2022-01-01", "2022-12-31"]
```

### Workflow 2: ML-Based Strategy
Create features → Train model → Predictions as signals → Backtest

```yaml
features:
  - name: "momentum"
    expression: "DELTA($close, 1)"
  - name: "volume_rank"
    expression: "RANK($volume)"

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

### Workflow 3: Multiple Strategies Comparison
```python
from quant_stream.backtest import run_ml_workflow

strategies = [
    ("TopkDropout", {"topk": 30}),
    ("TopkDropout", {"topk": 50}),
    ("Weight", {"method": "proportional"}),
]

for strategy_type, params in strategies:
    result = run_ml_workflow(
        data_path=".data/indian_stock_market_nifty500.csv",
        factor_expressions=[{"name": "signal", "expression": "DELTA($close, 1)"}],
        strategy_type=strategy_type,
        strategy_params=params,
        backtest_segments={"train": ["2021-01-01", "2021-12-31"], "test": ["2022-01-01", "2022-12-31"]},
        log_to_mlflow=False,
    )
    print(f"{strategy_type}: Sharpe={result['metrics']['sharpe_ratio']:.2f}")
```

## Metrics You Get

Every backtest automatically provides:

**Portfolio Performance:**
- Total/Annual Return, Volatility
- Sharpe, Sortino, Calmar Ratios
- Max Drawdown, Win Rate, Profit Factor

**Signal Quality (IC):**
- IC, Rank IC - Signal predictive power
- ICIR, Rank ICIR - Information ratios

**Model Performance (if ML used):**
- train_ic, test_ic - Model accuracy
- train_rank_ic, test_rank_ic

**All logged to MLflow for tracking and comparison.**

## Next Steps

1. **See full examples:** [examples/](examples/)
2. **Read documentation:** [README.md](README.md)
3. **Understand architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)
4. **Try the demos:**
   - `python examples/alpha_demo.py` - Manual factor construction
   - `python examples/alpha_runner.py` - Expression evaluation
   - `quant-stream run --config examples/configs/basic_momentum.yaml` - YAML workflow

## Need Help?

- **Examples:** See [examples/](examples/) directory
- **API Reference:** Check [README.md](README.md)
- **Issues:** See function implementations in `quant_stream/`
- **Testing:** Run `pytest tests/` to see how everything works
