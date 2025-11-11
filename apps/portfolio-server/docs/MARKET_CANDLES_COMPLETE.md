# 🚀 Market Candles API - Complete Implementation

## ✅ Implementation Complete!

A professional, production-ready market data API with historical OHLCV candle data support has been successfully implemented using Angel One SmartAPI.

---

## 📋 What's New

### Features Implemented

1. **Historical Candle Data (OHLCV)** 
   - Open, High, Low, Close, Volume data points
   - Integrated with Angel One Historical API
   - 6 predefined periods: `1h`, `1d`, `5d`, `7d`, `30d`, `1y`
   - Custom date ranges via `start` and `end` parameters

2. **Flexible Time Periods**
   - **1h**: Last 1 hour (1-minute candles, ~60 data points)
   - **1d**: Last 1 day (5-minute candles, ~75 data points)
   - **5d**: Last 5 days (15-minute candles, ~150 data points)
   - **7d**: Last 7 days (15-minute candles, ~210 data points)
   - **30d**: Last 30 days (1-hour candles, ~150 data points)
   - **1y**: Last 1 year (daily candles, ~252 data points)

3. **Smart API Design**
   - Backwards compatible (existing endpoints work unchanged)
   - Candle data optional (parameters are all optional)
   - Single endpoint for price + historical data
   - Parallel fetching for multiple symbols

4. **Professional Implementation**
   - Type-safe schemas with Pydantic
   - Proper error handling and validation
   - Comprehensive logging
   - Performance optimized (caching, async)

---

## 🔧 Modified Files

### Core Implementation
1. **`/shared/py/market_data.py`**
   - Added `AngelOneAdapter.get_historical_candles()` method
   - Integrates with Angel One Historical API
   - Handles TOTP authentication, token lookup, API requests

2. **`/apps/portfolio-server/controllers/market_controller.py`**
   - Updated `get_quotes()` to accept candle parameters
   - Replaced Finnhub candles with Angel One implementation
   - Added support for `30d` period
   - Enhanced `_fetch_candles()` and `_resolve_time_range()`

3. **`/apps/portfolio-server/routes/market_routes.py`**
   - Added query parameters: `candle`, `start`, `end`
   - All parameters optional for backwards compatibility

4. **`/apps/portfolio-server/schemas/market.py`**
   - New `CandleData` schema for OHLCV data points
   - Enhanced `MarketQuoteResponse` to include candles in metadata

5. **`/apps/portfolio-server/schemas/__init__.py`**
   - Exported `CandleData` schema

### Documentation
1. **`/apps/portfolio-server/docs/MARKET_CANDLES_API.md`**
   - Comprehensive API documentation
   - 8 example requests with full responses
   - Error handling examples
   - Python and JavaScript client examples

2. **`/apps/portfolio-server/docs/CANDLES_QUICK_REFERENCE.md`**
   - Quick reference guide
   - Common commands
   - Period mapping table
   - One-liner examples

3. **`/apps/portfolio-server/docs/CANDLES_IMPLEMENTATION.md`**
   - Implementation details
   - Architecture documentation
   - Technical specifications
   - Testing checklist

### Tools & Testing
1. **`/apps/portfolio-server/test_candles_api.py`**
   - Comprehensive test suite
   - Tests all periods and edge cases
   - Validates error handling
   - Executable test runner

2. **`/apps/portfolio-server/candles_client.py`**
   - Python client library
   - Convenience functions
   - Type hints
   - Example usage

---

## 📖 Quick Start

### 1. Basic Usage - Current Price Only

```bash
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE" \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "data": [
    {
      "symbol": "RELIANCE",
      "price": "2456.75",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 1,
  "requested_at": "2024-01-15T10:30:00Z"
}
```

### 2. Get Price + Last 1 Day Candles

```bash
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1d" \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "data": [
    {
      "symbol": "RELIANCE",
      "price": "2456.75",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 1,
  "requested_at": "2024-01-15T10:30:00Z",
  "metadata": {
    "candles": {
      "RELIANCE": [
        {
          "timestamp": "2024-01-14T09:15:00",
          "open": "2450.00",
          "high": "2460.50",
          "low": "2445.25",
          "close": "2456.75",
          "volume": "125000"
        }
        // ... more candles
      ]
    }
  }
}
```

### 3. Python Client Example

```python
from candles_client import CandlesClient

client = CandlesClient(base_url="http://localhost:8000", token="your_jwt_token")

# Get current price
price = await client.get_current_price("RELIANCE")
print(f"RELIANCE: ₹{price}")

# Get 1-day candles
candles = await client.get_candles("RELIANCE", period="1d")
print(f"Got {len(candles)} candles")

# Get summary statistics
summary = await client.get_summary("RELIANCE", period="1d")
print(f"High: ₹{summary['high']}, Low: ₹{summary['low']}")
```

---

## 🎯 All Supported Periods

| Period | Description | Interval | Typical Data Points |
|--------|-------------|----------|---------------------|
| **1h** | Last 1 hour | 1-minute candles | ~60 |
| **1d** | Last 1 day | 5-minute candles | ~75 |
| **5d** | Last 5 days | 15-minute candles | ~150 |
| **7d** | Last 7 days | 15-minute candles | ~210 |
| **30d** | Last 30 days | 1-hour candles | ~150 |
| **1y** | Last 1 year | Daily candles | ~252 |

---

## 🧪 Testing

### Run Comprehensive Test Suite

```bash
cd apps/portfolio-server
python test_candles_api.py
```

**Tests Include:**
- ✅ Current price only
- ✅ All 6 periods (1h, 1d, 5d, 7d, 30d, 1y)
- ✅ Custom date ranges
- ✅ Multiple symbols
- ✅ Invalid period error handling
- ✅ Invalid date range error handling

### Manual Testing

```bash
# Test 1h period
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1h"

# Test 1d period
curl "http://localhost:8000/api/market/quotes?symbols=TCS&candle=1d"

# Test 7d period
curl "http://localhost:8000/api/market/quotes?symbols=INFY&candle=7d"

# Test 1y period
curl "http://localhost:8000/api/market/quotes?symbols=SBIN&candle=1y"

# Test multiple symbols
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&symbols=TCS&symbols=INFY&candle=1d"

# Test custom range
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1d&start=2024-01-10T09:15:00Z&end=2024-01-15T15:30:00Z"
```

---

## 📚 Documentation

### Main Documentation
- **`MARKET_CANDLES_API.md`** - Complete API reference with examples
- **`CANDLES_QUICK_REFERENCE.md`** - Quick reference guide
- **`CANDLES_IMPLEMENTATION.md`** - Technical implementation details

### Client Libraries
- **`candles_client.py`** - Python client with convenience functions
- **`test_candles_api.py`** - Comprehensive test suite

---

## 🔐 Authentication

All endpoints require JWT authentication:

```bash
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1d" \
  -H "Authorization: Bearer <your_jwt_token>"
```

---

## ⚙️ Environment Variables

**Required for Angel One:**
```bash
MARKET_DATA_PROVIDER=angelone
ANGELONE_CLIENT_CODE=<your_client_code>
ANGELONE_API_KEY=<your_api_key>
ANGELONE_PASSWORD=<your_password>
ANGELONE_TOTP_SECRET=<your_totp_secret>
```

**Optional:**
```bash
MARKET_DATA_ENABLE_FALLBACK=true
MARKET_DATA_FALLBACK_BASE=100.00
MARKET_DATA_FALLBACK_STEP=5.00
```

---

## 🚦 API Response Schema

```typescript
interface MarketQuoteResponse {
  data: Array<{
    symbol: string;
    price: string;
    provider: string;
    source: string;
  }>;
  count: number;
  requested_at: string;
  missing?: string[];
  metadata?: {
    candles?: {
      [symbol: string]: Array<{
        timestamp: string;
        open: string;
        high: string;
        low: string;
        close: string;
        volume: string;
      }>;
    };
  };
}
```

---

## 🎨 Example Use Cases

### 1. Real-Time Dashboard
```python
# Get current prices for watchlist
quotes = await client.get_quotes(["RELIANCE", "TCS", "INFY", "HDFCBANK"])
for quote in quotes["data"]:
    print(f"{quote['symbol']}: ₹{quote['price']}")
```

### 2. Intraday Chart
```python
# Get 1-hour candles for intraday analysis
candles = await client.get_candles("RELIANCE", period="1h")
timestamps = [c["timestamp"] for c in candles]
closes = [float(c["close"]) for c in candles]

import matplotlib.pyplot as plt
plt.plot(timestamps, closes)
plt.title("RELIANCE - Last 1 Hour")
plt.show()
```

### 3. Historical Analysis
```python
# Get 1-year daily candles for technical analysis
opens, highs, lows, closes, volumes = await client.get_ohlcv("RELIANCE", "1y")

# Calculate 50-day moving average
import numpy as np
ma_50 = np.convolve(closes, np.ones(50)/50, mode='valid')
```

### 4. Multiple Stock Comparison
```python
# Compare multiple stocks over 7 days
symbols = ["RELIANCE", "TCS", "INFY"]
quotes = await client.get_quotes(symbols, candle="7d")

for symbol in symbols:
    candles = quotes["metadata"]["candles"][symbol]
    first_close = float(candles[0]["close"])
    last_close = float(candles[-1]["close"])
    change_pct = ((last_close - first_close) / first_close) * 100
    print(f"{symbol}: {change_pct:+.2f}%")
```

---

## 📊 Angel One API Details

### Historical API Endpoint
```
POST https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData
```

### Request Format
```json
{
  "exchange": "NSE",
  "symboltoken": "2885",
  "interval": "FIVE_MINUTE",
  "fromdate": "2024-01-14 09:15",
  "todate": "2024-01-15 15:30"
}
```

### Response Format
```json
{
  "status": true,
  "message": "SUCCESS",
  "data": [
    ["2024-01-14T09:15:00", 2450.0, 2460.5, 2445.25, 2456.75, 125000]
  ]
}
```

### Supported Intervals
- ONE_MINUTE
- THREE_MINUTE
- FIVE_MINUTE
- TEN_MINUTE
- FIFTEEN_MINUTE
- THIRTY_MINUTE
- ONE_HOUR
- ONE_DAY

---

## ⚡ Performance

- **Caching**: Current prices cached in-memory, updated via WebSocket
- **Parallel Fetching**: Candles for multiple symbols fetched concurrently
- **Smart Intervals**: Optimized candle granularity per period
- **Token Cache**: 8,688 NSE stocks cached, instant lookup
- **Async Processing**: Non-blocking Celery workers for token generation

---

## 🛡️ Error Handling

### Invalid Period
```json
{
  "detail": "Invalid candle interval. Supported: 1h, 1d, 5d, 7d, 30d, 1y"
}
```

### Invalid Date Range
```json
{
  "detail": "start must be earlier than end"
}
```

### Symbol Not Found
```json
{
  "data": [
    {
      "symbol": "INVALID",
      "price": "105.00",
      "provider": "fallback",
      "source": "deterministic-fallback"
    }
  ]
}
```

---

## 🎓 Best Practices

1. **Request Only What You Need**
   - Don't fetch 1-year data if you only need 1 day
   - Use appropriate periods for your use case

2. **Cache Candle Data**
   - Historical data doesn't change
   - Cache on client side to reduce API calls

3. **Handle Errors Gracefully**
   - Check `missing` field for unavailable symbols
   - Handle network timeouts and API errors

4. **Respect Market Hours**
   - NSE: 09:15 - 15:30 IST (Mon-Fri)
   - Expect gaps outside trading hours

5. **Use WebSocket for Real-Time**
   - Current prices from WebSocket are faster
   - Historical API for analysis only

---

## 🔮 Future Enhancements

- [ ] Additional exchanges (BSE, MCX, NFO)
- [ ] More candle intervals (expose all Angel One intervals)
- [ ] Candle data caching (reduce API calls)
- [ ] WebSocket candle updates (real-time candles)
- [ ] Technical indicators (SMA, EMA, RSI, MACD)
- [ ] Export formats (CSV, Excel)
- [ ] Charting library integration examples

---

## 📞 Support

For issues or questions:
1. Check documentation: `MARKET_CANDLES_API.md`
2. Review examples: `test_candles_api.py`
3. Consult implementation details: `CANDLES_IMPLEMENTATION.md`

---

## ✨ Summary

✅ **Professional Implementation**
- Angel One Historical API integration
- 6 predefined periods + custom ranges
- Type-safe schemas
- Comprehensive error handling
- Performance optimized

✅ **Complete Documentation**
- API reference with 8 examples
- Quick reference guide
- Implementation details
- Test suite

✅ **Developer Tools**
- Python client library
- Test runner
- Example code

✅ **Production Ready**
- Backwards compatible
- Well-tested
- Properly documented
- Secure authentication

**🚀 Ready to use in production!**

---

*Implementation completed successfully. All features tested and documented.*
