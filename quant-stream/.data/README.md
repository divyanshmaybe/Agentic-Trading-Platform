# Market Data Requirements

This directory contains market data files used by the Quant-Stream examples and tests.

## Data Format Requirements

### Required Schema

The data must be in CSV format with the following columns:

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | string | Stock ticker/symbol (e.g., "AAPL", "RELIANCE.NS") |
| `date` | string | Trading date in YYYY-MM-DD format |
| `timestamp` | integer | Unix timestamp (seconds since epoch) |
| `open` | float | Opening price for the period |
| `high` | float | Highest price during the period |
| `low` | float | Lowest price during the period |
| `close` | float | Closing price for the period |
| `volume` | float | Trading volume for the period |

### Example File Format

```csv
symbol,date,timestamp,open,high,low,close,volume
AAPL,2024-01-02,1704153600,185.56,186.89,184.23,185.92,45234567.0
MSFT,2024-01-02,1704153600,374.58,376.23,373.45,375.92,23456789.0
AAPL,2024-01-03,1704240000,186.12,187.45,185.78,186.89,38765432.0
MSFT,2024-01-03,1704240000,376.12,378.45,375.23,377.89,21234567.0
```

### Data Quality Requirements

1. **Temporal Order**: Data should be sorted by `timestamp` in ascending order (symbol order doesn't matter)
2. **No Missing Values**: All columns must have valid values (no nulls/NaN)
3. **Price Consistency**: Ensure `low ≤ open, close ≤ high` for each row
4. **Multiple Instruments**: Include data for multiple symbols to test cross-sectional operations
5. **Sufficient History**: Include enough historical data (recommended: 252+ trading days) for rolling window operations

## Expected File Location

By default, examples look for data at:

```text
.data/indian_stock_market_nifty500.csv
```

You can customize the path when using the data replayer:

```python
from quant_stream.data.replayer import replay_market_data

# Use default path
table = replay_market_data()

# Use custom path
table = replay_market_data(data_path="path/to/your/data.csv")
```
