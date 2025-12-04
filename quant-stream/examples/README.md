# Quant-Stream Examples

This directory contains comprehensive examples demonstrating all ways to use quant-stream.

## Quick Navigation

| What You Want | Example | Description |
|---------------|---------|-------------|
| **Get started fast** | `configs/basic_momentum.yaml` | YAML config - no code needed |
| **Quick backtest** | `01_quickstart_backtest.py` | One function call with auto MLflow logging |
| **Full Python control** | `02_manual_factor_construction.py` | Manual factor construction (RECOMMENDED) |
| **Test many alphas** | `03_expression_based_alphas.py` | String-based expression evaluation & comparison |
| **Parse expressions** | `05_expression_parser_demo.py` | Expression parser demonstration |
| **Train ML models** | `04_ml_model_comparison.py` | ML model comparison with IC metrics |
| **MCP integration** | `mcp_integration/` | AI agent integration examples |

## Usage Patterns

### 1. YAML Configuration (Recommended)

**Zero code required - just edit YAML and run:**

```bash
# Start with a template
quant-stream init --output my_strategy.yaml

# Validate your config
quant-stream validate --config my_strategy.yaml

# Run the strategy
quant-stream run --config my_strategy.yaml --output results.csv

# View results
mlflow ui --backend-store-uri sqlite:///mlruns.db
```

**Examples:**
- `configs/basic_momentum.yaml` - Single momentum factor
- `configs/multi_factor.yaml` - 5 alpha factors
- `configs/lightgbm_strategy.yaml` - Advanced ML with 13 factors

**Features:**
- ✅ Declarative configuration
- ✅ Automatic MLflow logging
- ✅ Train/test segmentation
- ✅ IC metrics calculated automatically
- ✅ No Python code needed

---

### 2. Simple Backtest (Quick Start)

**One function call with automatic everything:**

```bash
python examples/01_quickstart_backtest.py
```

**What it shows:**
- Single `run_ml_workflow()` call
- Automatic MLflow logging
- Train/test segmentation
- IC metrics calculated automatically

**When to use:**
- Quick factor testing
- Prototyping strategies
- Learning the API

---

### 3. Python Library - Manual Construction

**Full control over every step (RECOMMENDED for production):**

```bash
python examples/02_manual_factor_construction.py
```

**What it shows:**
- Loading data with Pathway
- Applying functions manually (`DELTA`, `SMA`, `RANK`)
- Building 6 different factor types
- Complete control over computation graph

**When to use:**
- Production deployments
- Custom factor logic
- Performance optimization
- Complex multi-stage factors

---

### 4. Python Library - Expression-Based

**Test 8 different alphas and compare automatically:**

```bash
python examples/03_expression_based_alphas.py
```

**What it shows:**
- Parsing alpha expressions from strings
- Automatic evaluation on data
- Backtesting all alphas
- Automatic comparison with MLflow
- Ranks alphas by IC

**When to use:**
- Quick alpha testing
- Research exploration
- Alpha factor mining
- Comparing multiple ideas

---

### 5. Model Training & Comparison

**Train 4 ML models and select the best:**

```bash
python examples/04_ml_model_comparison.py
```

**What it shows:**
- Feature engineering with Pathway
- Training LightGBM, XGBoost, RandomForest, Linear
- IC metrics calculation
- Automatic model comparison
- MLflow experiment tracking

**When to use:**
- ML-based strategies
- Model selection
- Feature importance analysis

---

### 6. MCP Server Integration

**AI agent integration:**

```bash
# 1. Start Redis
redis-server

# 2. Start Celery worker
celery -A quant_stream.mcp_server.worker worker --loglevel=info

# 3. Start MCP server
python -m quant_stream.mcp_server

# 4. Test the integration
python examples/mcp_integration/test_mcp_client.py
```

**What it shows:**
- MCP tool calls
- Async job execution
- Status polling
- AlphaCopilot integration

**When to use:**
- AlphaCopilot factor mining
- Distributed backtesting
- API-driven workflows

---

## Signal Generation Approaches

### Approach A: Factor-Only (No ML)

Use alpha factors directly as signals:

**YAML:**
```yaml
features:
  - name: "momentum_signal"
    expression: "RANK(DELTA($close, 1))"
# NO model section - factor used directly as signal

strategy:
  type: "TopkDropout"
  params: {topk: 30}
```

**Python:**
```python
# Create factor
table = DELTA(table, pw.this.close, periods=1)
table = RANK(table, pw.this.delta)

# Use directly as signals
signals_df = pw.debug.table_to_pandas(table)
```

---

### Approach B: ML-Based

Use ML model predictions as signals:

**YAML:**
```yaml
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
  params: {topk: 30}
```

**Python:**
```python
# Create features
table = DELTA(table, pw.this.close, periods=1)
features_df = pw.debug.table_to_pandas(table)

# Train model
model = LightGBMModel(params={"learning_rate": 0.05}, num_boost_round=100)
model.fit(X_train, y_train)

# Predictions as signals
signals = model.predict(X_test)
```

---

## Backtesting Modes

### Mode 1: Train-Only (Simple Backtest)

```yaml
backtest:
  segments:
    train: ["2022-01-01", "2022-12-31"]
  # No test segment
```

**Output:** Single set of metrics (returns + IC)

---

### Mode 2: Train/Test Split

```yaml
backtest:
  segments:
    train: ["2021-01-01", "2021-12-31"]
    test: ["2022-01-01", "2022-12-31"]
```

**Output:**
```
TRAIN SEGMENT:
  Sharpe Ratio: 1.65
  IC: 0.0543

TEST SEGMENT:
  Sharpe Ratio: 1.82
  IC: 0.0489
```

**MLflow Logs:**
- `train_sharpe_ratio`, `train_IC`, ...
- `test_sharpe_ratio`, `test_IC`, ...

---

## Metrics Explained

### Portfolio Performance
Calculated from backtest returns:
- **Total/Annual Return**: Cumulative and annualized gains
- **Sharpe Ratio**: Risk-adjusted return
- **Max Drawdown**: Largest peak-to-trough decline
- **Win Rate**: Percentage of profitable periods

### Signal Quality (IC Metrics)
Calculated from signal vs forward returns:
- **IC**: Information Coefficient (Pearson correlation)
- **Rank IC**: Spearman rank correlation
- Higher IC = better signal predictive power

### Model Performance
Calculated during training (if ML model used):
- **train_ic / test_ic**: Model prediction accuracy
- Separate from backtest IC (which measures final signals)

---

## File Structure

```
examples/
├── configs/                              # YAML configuration examples
│   ├── basic_momentum.yaml               # Simple 1-factor strategy
│   ├── multi_factor.yaml                 # 5-factor strategy
│   ├── lightgbm_strategy.yaml            # Advanced 13-factor ML strategy
│   └── README.md                         # Config documentation
│
├── mcp_integration/                      # MCP server examples
│   ├── test_mcp_client.py                # Test all MCP tools
│   ├── agent_integration.py              # AlphaCopilot integration
│   └── README.md                         # MCP documentation
│
├── 01_quickstart_backtest.py             # Quick backtest demo
├── 02_manual_factor_construction.py      # Manual factor construction ⭐ RECOMMENDED
├── 03_expression_based_alphas.py         # Expression evaluation & comparison
├── 04_ml_model_comparison.py             # ML model comparison
├── 05_expression_parser_demo.py          # Expression parser demo
└── README.md                             # This file
```

---

## Running Examples

### Prerequisites

1. **Install dependencies:**
```bash
uv sync --all-groups --all-packages
```

2. **Prepare data:**
Ensure you have market data at `.data/indian_stock_market_nifty500.csv` with schema:
- symbol, date, timestamp, open, high, low, close, volume

### Run Individual Examples

```bash
# YAML workflows (easiest - no code needed)
quant-stream run --config examples/configs/basic_momentum.yaml

# Python examples (in order of complexity)
python examples/01_quickstart_backtest.py        # Simplest - one function call
python examples/02_manual_factor_construction.py # Manual construction
python examples/03_expression_based_alphas.py    # Expression-based
python examples/04_ml_model_comparison.py        # ML model training
python examples/05_expression_parser_demo.py     # Parser demonstration

# MCP server (requires Redis + Celery)
python -m quant_stream.mcp_server  # Start server first
python examples/mcp_integration/test_mcp_client.py  # Then test
```

---

## Tips & Best Practices

### 1. Start Simple
Begin with `configs/basic_momentum.yaml` or `01_quickstart_backtest.py` before trying complex workflows.

### 2. Use Segments for Proper Validation
Always use train/test segments to avoid overfitting:
```yaml
backtest:
  segments:
    train: ["2021-01-01", "2021-12-31"]
    test: ["2022-01-01", "2022-12-31"]  # Out-of-sample validation
```

### 3. Monitor IC Metrics
- **IC > 0.03**: Good signal
- **IC > 0.05**: Strong signal
- **IC < 0**: Inverse signal (consider negating)

### 4. Compare Train vs Test
Watch for overfitting:
- `train_IC = 0.08, test_IC = 0.02` → Likely overfit
- `train_IC = 0.05, test_IC = 0.04` → Robust signal

### 5. Use MLflow for Tracking
Every run logs to MLflow:
```bash
mlflow ui --backend-store-uri sqlite:///mlruns.db
```
Compare runs, analyze trends, track experiments.

---

## Common Patterns

### Pattern: Multiple Factor Testing
See `03_expression_based_alphas.py` - tests 8 different alphas and compares them automatically.

```python
# This is demonstrated in 03_expression_based_alphas.py
# It tests multiple alpha expressions and ranks them by IC
```

### Pattern: Strategy Comparison
```yaml
# Create multiple YAML files with different strategies
# basic_topk30.yaml - topk: 30
# basic_topk50.yaml - topk: 50
# weight_proportional.yaml - type: Weight

# Run all and compare in MLflow UI
quant-stream run --config basic_topk30.yaml
quant-stream run --config basic_topk50.yaml
quant-stream run --config weight_proportional.yaml
```

### Pattern: ML Model Comparison
See `04_ml_model_comparison.py` - trains 4 models (LightGBM, XGBoost, RandomForest, Linear) and selects best by IC.

---

## Troubleshooting

### "Data file not found"
- Check path in config: `data.path: ".data/indian_stock_market_nifty500.csv"`
- Verify file exists: `ls -la .data/indian_stock_market_nifty500.csv`
- Use absolute path if needed

### "Column not found"
- Verify column names match data schema
- Available: symbol, date, timestamp, open, high, low, close, volume

### "MCP server won't start"
- Ensure Redis is running: `redis-cli ping` should return `PONG`
- Start Celery worker first
- Check logs for errors

### "Low IC values"
- IC < 0.02 may indicate weak signal
- Try different factors or parameters
- Check for look-ahead bias (data leakage)

---

## Next Steps

1. **Quick start:** `python examples/01_quickstart_backtest.py`
2. **Or with YAML:** `quant-stream run --config examples/configs/basic_momentum.yaml`
3. **Explore examples:** Work through 01 → 05 in order
4. **Read main docs:** [../README.md](../README.md) and [../ARCHITECTURE.md](../ARCHITECTURE.md)
5. **Build your own:** Create custom factors and strategies

## Need Help?

- **API Reference**: Main [README.md](../README.md)
- **Architecture**: [ARCHITECTURE.md](../ARCHITECTURE.md)
- **Tests**: See `tests/` for detailed usage examples
- **Issues**: Check function implementations in `quant_stream/`
