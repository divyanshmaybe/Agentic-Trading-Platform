# Market Candles API - Quick Reference

## Endpoint
```
GET /api/market/quotes
```

## Parameters

### Required
- `symbols` (string[]): Stock symbols (e.g., `RELIANCE`, `TCS`)

### Optional
- `candle` (string): Period - `1h`, `1d`, `5d`, `7d`, `30d`, `1y`
- `start` (datetime): Custom start date (ISO 8601)
- `end` (datetime): Custom end date (ISO 8601)

## Quick Examples

### 1. Current Price Only
```bash
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE" \
  -H "Authorization: Bearer <token>"
```

### 2. Last 1 Hour (1-min candles)
```bash
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1h" \
  -H "Authorization: Bearer <token>"
```

### 3. Last 1 Day (5-min candles)
```bash
curl "http://localhost:8000/api/market/quotes?symbols=TCS&candle=1d" \
  -H "Authorization: Bearer <token>"
```

### 4. Last 7 Days (15-min candles)
```bash
curl "http://localhost:8000/api/market/quotes?symbols=INFY&candle=7d" \
  -H "Authorization: Bearer <token>"
```

### 5. Last 30 Days (1-hour candles)
```bash
curl "http://localhost:8000/api/market/quotes?symbols=HDFCBANK&candle=30d" \
  -H "Authorization: Bearer <token>"
```

### 6. Last 1 Year (daily candles)
```bash
curl "http://localhost:8000/api/market/quotes?symbols=SBIN&candle=1y" \
  -H "Authorization: Bearer <token>"
```

### 7. Custom Date Range
```bash
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1d&start=2024-01-10T09:15:00Z&end=2024-01-15T15:30:00Z" \
  -H "Authorization: Bearer <token>"
```

### 8. Multiple Symbols
```bash
curl "http://localhost:8000/api/market/quotes?symbols=RELIANCE&symbols=TCS&symbols=INFY&candle=1d" \
  -H "Authorization: Bearer <token>"
```

## Period Mapping

| Period | Interval | Candle Size | Typical Count |
|--------|----------|-------------|---------------|
| 1h | ONE_MINUTE | 1 min | ~60 |
| 1d | FIVE_MINUTE | 5 min | ~75 |
| 5d | FIFTEEN_MINUTE | 15 min | ~150 |
| 7d | FIFTEEN_MINUTE | 15 min | ~210 |
| 30d | ONE_HOUR | 1 hour | ~150 |
| 1y | ONE_DAY | 1 day | ~252 |

## Response Structure

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
  "missing": null,
  "metadata": {
    "candles": {
      "RELIANCE": [
        {
          "timestamp": "2024-01-15T09:15:00",
          "open": "2450.00",
          "high": "2460.50",
          "low": "2445.25",
          "close": "2456.75",
          "volume": "125000"
        }
      ]
    }
  }
}
```

## Common Errors

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

## Testing Tips

1. **Market Hours**: NSE trades 09:15 - 15:30 IST (Mon-Fri)
2. **Best Time**: Test during market hours for real-time data
3. **Candle Gaps**: Expect gaps during non-trading hours
4. **Weekend Data**: Historical data available, but no new candles

## Python One-Liner

```python
import httpx
result = httpx.get(
    "http://localhost:8000/api/market/quotes",
    params={"symbols": "RELIANCE", "candle": "1d"},
    headers={"Authorization": "Bearer <token>"}
).json()
print(result["metadata"]["candles"]["RELIANCE"])
```

## JavaScript One-Liner

```javascript
const result = await fetch(
  "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1d",
  { headers: { "Authorization": "Bearer <token>" } }
).then(r => r.json());
console.log(result.metadata.candles.RELIANCE);
```

## Notes

- All decimal values returned as strings for precision
- Timestamps in ISO 8601 format
- Candles fetched from Angel One Historical API
- Current price from WebSocket (real-time) or cache
