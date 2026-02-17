# Configuration Examples

This directory contains example YAML configuration files for quant-stream workflows.

## Files

### `basic_momentum.yaml`
A simple momentum-based strategy using a single factor:
- **Features**: 1-day price momentum
- **Model**: LightGBM with basic parameters
- **Strategy**: Top-30 equal-weight portfolio
- **Period**: 2021-06-01 to 2022-06-30

**Usage:**
```bash
quant-stream run --config examples/configs/basic_momentum.yaml
```

### `multi_factor.yaml`
A multi-factor strategy combining momentum, mean reversion, volume, and volatility:
- **Features**: 5 alpha factors
- **Model**: LightGBM with extended training
- **Strategy**: Top-50 signal-weighted portfolio
- **Period**: 2021-01-01 to 2022-12-31

**Usage:**
```bash
quant-stream run --config examples/configs/multi_factor.yaml --output results/multi_factor.csv
```

### `lightgbm_strategy.yaml`
An advanced strategy with comprehensive feature engineering:
- **Features**: 13 factors (momentum, technical indicators, volatility, volume)
- **Model**: LightGBM with advanced hyperparameters
- **Strategy**: Top-40 signal-weighted with weekly rebalancing
- **Period**: 2020-01-01 to 2023-12-31

**Usage:**
```bash
quant-stream run --config examples/configs/lightgbm_strategy.yaml --output results/advanced.csv
```

## Configuration Structure

Each YAML file follows this structure:

```yaml
data:
  path: "path/to/data.csv"
  start_date: "YYYY-MM-DD"  # Optional
  end_date: "YYYY-MM-DD"    # Optional

features:
  - name: "feature_name"
    expression: "FEATURE_EXPRESSION"

model:  # OPTIONAL - omit this section to use raw factor values as signals
  type: "LightGBM"  # or "Linear", "XGBoost", "RandomForest"
  params:
    # Model-specific hyperparameters
  target: "forward_return_1d"

strategy:
  type: "TopkDropout"  # or "Weight"
  params:
    topk: 30
    n_drop: 5
    method: "equal"  # or "signal"

backtest:
  initial_capital: 1000000
  commission: 0.001
  slippage: 0.001
  min_commission: 0.0
  rebalance_frequency: 1

experiment:
  name: "experiment_name"
  tracking_uri: "sqlite:///mlruns.db"
  run_name: "run_name"
  tags:
    key: "value"
```

## Feature Expressions

Features use quant-stream's expression language. Available functions:

### Time-series Operations
- `DELTA($close, n)` - Price change over n periods
- `DELAY($close, n)` - Lagged values
- `TS_MAX($close, n)` - Rolling maximum
- `TS_MIN($close, n)` - Rolling minimum
- `TS_STD($close, n)` - Rolling standard deviation

### Technical Indicators
- `SMA($close, n)` - Simple moving average
- `EMA($close, n)` - Exponential moving average
- `RSI($close, n)` - Relative Strength Index
- `MACD($close, fast, slow, signal)` - MACD indicator

### Mathematical Operations
- `ADD($a, $b)` - Addition
- `SUBTRACT($a, $b)` - Subtraction
- `MULTIPLY($a, $b)` - Multiplication
- `DIVIDE($a, $b)` - Division

### Cross-sectional Operations
- `RANK($close)` - Cross-sectional ranking
- `ZSCORE($close)` - Cross-sectional z-score
- `SCALE($close)` - Cross-sectional scaling

## Creating Your Own Configuration

1. Start with a template:
```bash
quant-stream init --output my_workflow.yaml
```

2. Edit the configuration to match your needs

3. Validate the configuration:
```bash
quant-stream validate --config my_workflow.yaml
```

4. Run the workflow:
```bash
quant-stream run --config my_workflow.yaml --output results.csv
```

## Tips

1. **Start Simple**: Begin with `basic_momentum.yaml` and gradually add complexity
2. **Date Ranges**: Adjust date ranges based on your data availability
3. **Running Without a Model**: 
   - Omit the entire `model:` section to use raw factor values as trading signals
   - This is useful for testing pure alpha factors without ML
   - Example: Comment out or remove the `model:` section from any config
4. **Model Selection**: 
   - LightGBM: Best for most cases, fast and accurate
   - Linear: Good for interpretability and speed
   - XGBoost: Alternative to LightGBM
   - RandomForest: Good for non-linear patterns
5. **Strategy Parameters**:
   - Increase `topk` for more diversification
   - Adjust `n_drop` to control turnover
   - Use `signal` method for concentration in high-confidence signals
6. **Backtesting**:
   - Set realistic commission and slippage rates
   - Consider transaction costs carefully
   - Use `rebalance_frequency > 1` to reduce turnover

## Experiment Tracking

All runs are logged to MLflow. View results:
```bash
mlflow ui --backend-store-uri sqlite:///mlruns.db
```

Navigate to http://localhost:5000 to explore experiments, compare runs, and analyze performance.

## Data Requirements

The data CSV file should have the following columns:
- `symbol`: Stock ticker
- `date`: Trading date (YYYY-MM-DD)
- `timestamp`: Unix timestamp
- `open`, `high`, `low`, `close`: OHLC prices
- `volume`: Trading volume

Place your data at the path specified in the `data.path` configuration field.
