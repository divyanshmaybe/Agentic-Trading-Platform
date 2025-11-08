# Market Candles API Documentation

## Overview

The Market Quotes API provides real-time stock prices and historical OHLCV (Open, High, Low, Close, Volume) candle data for Indian stocks (NSE) using Angel One SmartAPI.

## Endpoint

```
GET /api/market/quotes
```

## Authentication

Requires JWT authentication token in `Authorization` header:
```
Authorization: Bearer <your_jwt_token>
```

## Query Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `symbols` | string[] | Yes | Stock symbols (can be repeated) | `RELIANCE`, `TCS`, `INFY` |
| `candle` | string | No | Candle period/interval | `1h`, `1d`, `5d`, `7d`, `30d`, `1y` |
| `start` | datetime | No | Custom start datetime (ISO 8601) | `2024-01-01T09:15:00Z` |
| `end` | datetime | No | Custom end datetime (ISO 8601) | `2024-01-01T15:30:00Z` |

## Supported Candle Periods

| Period | Description | Angel One Interval | Max Data Points |
|--------|-------------|-------------------|-----------------|
| `1h` | Last 1 hour | ONE_MINUTE (1-min candles) | ~60 candles |
| `1d` | Last 1 day | FIVE_MINUTE (5-min candles) | ~75 candles |
| `5d` | Last 5 days | FIFTEEN_MINUTE (15-min candles) | ~150 candles |
| `7d` | Last 7 days | FIFTEEN_MINUTE (15-min candles) | ~210 candles |
| `30d` | Last 30 days | ONE_HOUR (1-hour candles) | ~150 candles |
| `1y` | Last 1 year | ONE_DAY (daily candles) | ~252 candles |

## Response Schema

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

## Usage Examples

### 1. Get Current Price Only

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=RELIANCE&symbols=TCS" \
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
    },
    {
      "symbol": "TCS",
      "price": "3678.90",
      "provider": "angelone",
      "source": "cache"
    }
  ],
  "count": 2,
  "requested_at": "2024-01-15T10:30:00.123456Z",
  "missing": null,
  "metadata": null
}
```

### 2. Get Price + Last 1 Hour Candles (1-min intervals)

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1h" \
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
  "missing": null,
  "metadata": {
    "candles": {
      "RELIANCE": [
        {
          "timestamp": "2024-01-15T09:30:00",
          "open": "2450.00",
          "high": "2452.50",
          "low": "2449.00",
          "close": "2451.25",
          "volume": "12500"
        },
        {
          "timestamp": "2024-01-15T09:31:00",
          "open": "2451.25",
          "high": "2454.00",
          "low": "2450.50",
          "close": "2453.75",
          "volume": "15200"
        },
        {
          "timestamp": "2024-01-15T09:32:00",
          "open": "2453.75",
          "high": "2456.00",
          "low": "2453.00",
          "close": "2455.50",
          "volume": "18900"
        }
        // ... up to 60 candles
      ]
    }
  }
}
```

### 3. Get Price + Last 1 Day Candles (5-min intervals)

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=TCS&candle=1d" \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "data": [
    {
      "symbol": "TCS",
      "price": "3678.90",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 1,
  "requested_at": "2024-01-15T10:30:00Z",
  "missing": null,
  "metadata": {
    "candles": {
      "TCS": [
        {
          "timestamp": "2024-01-14T09:15:00",
          "open": "3650.00",
          "high": "3660.75",
          "low": "3648.25",
          "close": "3658.50",
          "volume": "245000"
        },
        {
          "timestamp": "2024-01-14T09:20:00",
          "open": "3658.50",
          "high": "3665.00",
          "low": "3656.00",
          "close": "3662.25",
          "volume": "198500"
        }
        // ... approximately 75 candles (5-min intervals for 1 day)
      ]
    }
  }
}
```

### 4. Get Price + Last 7 Days Candles (15-min intervals)

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=INFY&candle=7d" \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "data": [
    {
      "symbol": "INFY",
      "price": "1456.30",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 1,
  "requested_at": "2024-01-15T10:30:00Z",
  "missing": null,
  "metadata": {
    "candles": {
      "INFY": [
        {
          "timestamp": "2024-01-08T09:15:00",
          "open": "1450.00",
          "high": "1455.50",
          "low": "1448.75",
          "close": "1453.25",
          "volume": "856000"
        },
        {
          "timestamp": "2024-01-08T09:30:00",
          "open": "1453.25",
          "high": "1458.00",
          "low": "1452.00",
          "close": "1456.75",
          "volume": "742500"
        }
        // ... approximately 210 candles (15-min intervals for 7 days)
      ]
    }
  }
}
```

### 5. Get Price + Last 30 Days Candles (1-hour intervals)

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=HDFCBANK&candle=30d" \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "data": [
    {
      "symbol": "HDFCBANK",
      "price": "1678.45",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 1,
  "requested_at": "2024-01-15T10:30:00Z",
  "missing": null,
  "metadata": {
    "candles": {
      "HDFCBANK": [
        {
          "timestamp": "2023-12-15T09:15:00",
          "open": "1650.00",
          "high": "1658.75",
          "low": "1648.50",
          "close": "1656.25",
          "volume": "1250000"
        },
        {
          "timestamp": "2023-12-15T10:15:00",
          "open": "1656.25",
          "high": "1662.00",
          "low": "1654.00",
          "close": "1660.50",
          "volume": "986500"
        }
        // ... approximately 150 candles (1-hour intervals for 30 days)
      ]
    }
  }
}
```

### 6. Get Price + Last 1 Year Candles (daily intervals)

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=SBIN&candle=1y" \
  -H "Authorization: Bearer <token>"
```

**Response:**
```json
{
  "data": [
    {
      "symbol": "SBIN",
      "price": "625.75",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 1,
  "requested_at": "2024-01-15T10:30:00Z",
  "missing": null,
  "metadata": {
    "candles": {
      "SBIN": [
        {
          "timestamp": "2023-01-16T00:00:00",
          "open": "580.00",
          "high": "586.50",
          "low": "578.25",
          "close": "584.75",
          "volume": "25600000"
        },
        {
          "timestamp": "2023-01-17T00:00:00",
          "open": "584.75",
          "high": "592.00",
          "low": "583.50",
          "close": "590.25",
          "volume": "28400000"
        }
        // ... approximately 252 candles (daily for 1 year)
      ]
    }
  }
}
```

### 7. Get Price + Custom Date Range Candles

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1d&start=2024-01-10T09:15:00Z&end=2024-01-15T15:30:00Z" \
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
  "missing": null,
  "metadata": {
    "candles": {
      "RELIANCE": [
        {
          "timestamp": "2024-01-10T09:15:00",
          "open": "2400.00",
          "high": "2415.50",
          "low": "2398.25",
          "close": "2412.75",
          "volume": "1856000"
        },
        {
          "timestamp": "2024-01-10T09:20:00",
          "open": "2412.75",
          "high": "2420.00",
          "low": "2410.50",
          "close": "2418.25",
          "volume": "1542500"
        }
        // ... candles between specified dates
      ]
    }
  }
}
```

### 8. Multiple Symbols with Candles

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=RELIANCE&symbols=TCS&symbols=INFY&candle=1d" \
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
    },
    {
      "symbol": "TCS",
      "price": "3678.90",
      "provider": "angelone",
      "source": "cache"
    },
    {
      "symbol": "INFY",
      "price": "1456.30",
      "provider": "angelone",
      "source": "live-stream"
    }
  ],
  "count": 3,
  "requested_at": "2024-01-15T10:30:00Z",
  "missing": null,
  "metadata": {
    "candles": {
      "RELIANCE": [
        {
          "timestamp": "2024-01-14T09:15:00",
          "open": "2450.00",
          "high": "2460.50",
          "low": "2445.25",
          "close": "2456.75",
          "volume": "1250000"
        }
        // ... more candles
      ],
      "TCS": [
        {
          "timestamp": "2024-01-14T09:15:00",
          "open": "3650.00",
          "high": "3660.75",
          "low": "3648.25",
          "close": "3658.50",
          "volume": "245000"
        }
        // ... more candles
      ],
      "INFY": [
        {
          "timestamp": "2024-01-14T09:15:00",
          "open": "1450.00",
          "high": "1455.50",
          "low": "1448.75",
          "close": "1453.25",
          "volume": "856000"
        }
        // ... more candles
      ]
    }
  }
}
```

## Error Responses

### Invalid Candle Period

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=3h" \
  -H "Authorization: Bearer <token>"
```

**Response (400 Bad Request):**
```json
{
  "detail": "Invalid candle interval. Supported: 1h, 1d, 5d, 7d, 30d, 1y"
}
```

### Invalid Date Range

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=RELIANCE&candle=1d&start=2024-01-15T10:00:00Z&end=2024-01-14T10:00:00Z" \
  -H "Authorization: Bearer <token>"
```

**Response (400 Bad Request):**
```json
{
  "detail": "start must be earlier than end"
}
```

### Symbol Not Found

**Request:**
```bash
curl -X GET "http://localhost:8000/api/market/quotes?symbols=INVALID" \
  -H "Authorization: Bearer <token>"
```

**Response (200 OK with missing field):**
```json
{
  "data": [
    {
      "symbol": "INVALID",
      "price": "105.00",
      "provider": "fallback",
      "source": "deterministic-fallback"
    }
  ],
  "count": 1,
  "requested_at": "2024-01-15T10:30:00Z",
  "missing": null,
  "metadata": null
}
```

## Technical Details

### Angel One API Integration

- **WebSocket**: Real-time LTP (Last Traded Price) streaming
- **Historical API**: OHLCV candle data via REST endpoint
- **Authentication**: TOTP-based JWT token generation
- **Token Mapping**: Auto-generated cache of 8,688+ NSE stocks

### Interval Mapping

| User Period | Angel One Interval | Candle Size | Max Range |
|-------------|-------------------|-------------|-----------|
| 1h | ONE_MINUTE | 1 minute | 30 days |
| 1d | FIVE_MINUTE | 5 minutes | 30 days |
| 5d | FIFTEEN_MINUTE | 15 minutes | 30 days |
| 7d | FIFTEEN_MINUTE | 15 minutes | 30 days |
| 30d | ONE_HOUR | 1 hour | 100 days |
| 1y | ONE_DAY | 1 day | 2000 days |

### Performance Considerations

1. **Caching**: Current prices cached in-memory, refreshed every second via WebSocket
2. **Parallel Fetching**: Historical candles fetched in parallel for multiple symbols
3. **Fallback**: Deterministic price generation for symbols not in Angel One token map
4. **Error Handling**: Graceful degradation if candle data unavailable

## Rate Limits

Angel One API rate limits (as per their documentation):
- **Historical API**: 10 requests per second
- **WebSocket**: 1 connection per user, unlimited symbol subscriptions

## Best Practices

1. **Request only needed data**: Avoid fetching 1-year candles if you need 1-day data
2. **Use WebSocket prices**: Current prices from WebSocket are faster than REST
3. **Cache candle data**: Client-side caching recommended for historical data
4. **Handle missing symbols**: Check `missing` field in response for unavailable symbols
5. **Respect market hours**: NSE trading hours are 09:15 - 15:30 IST (Mon-Fri)

## Python Client Example

```python
import httpx
from datetime import datetime, timedelta

async def get_market_candles(symbols: list[str], period: str = "1d", token: str = ""):
    """Fetch market quotes with candle data."""
    base_url = "http://localhost:8000/api/market/quotes"
    
    params = {"candle": period}
    for symbol in symbols:
        params.setdefault("symbols", []).append(symbol)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(base_url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

# Usage
result = await get_market_candles(["RELIANCE", "TCS"], period="1d", token="your_jwt_token")
print(result)
```

## JavaScript/TypeScript Client Example

```typescript
interface CandleData {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

interface MarketQuote {
  symbol: string;
  price: string;
  provider: string;
  source: string;
}

interface MarketQuoteResponse {
  data: MarketQuote[];
  count: number;
  requested_at: string;
  missing: string[] | null;
  metadata?: {
    candles?: Record<string, CandleData[]>;
  };
}

async function getMarketCandles(
  symbols: string[],
  period: string = "1d",
  token: string
): Promise<MarketQuoteResponse> {
  const params = new URLSearchParams();
  params.append("candle", period);
  symbols.forEach(symbol => params.append("symbols", symbol));
  
  const response = await fetch(
    `http://localhost:8000/api/market/quotes?${params}`,
    {
      headers: {
        "Authorization": `Bearer ${token}`
      }
    }
  );
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
}

// Usage
const result = await getMarketCandles(["RELIANCE", "TCS"], "1d", "your_jwt_token");
console.log(result);
```

## Notes

- All prices and OHLCV values are returned as strings to maintain precision
- Timestamps in candle data are ISO 8601 format strings
- Volume is in number of shares traded
- Market data is subject to Angel One API availability
- Candle data may have gaps during non-trading hours or market holidays
