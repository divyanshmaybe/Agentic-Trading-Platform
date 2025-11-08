# Market Candles API Architecture

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT APPLICATION                              │
│                    (Browser, Mobile App, Python Script)                      │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
                    HTTP GET /api/market/quotes
                    ?symbols=RELIANCE&candle=1d
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FASTAPI APPLICATION LAYER                            │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Route Handler: market_routes.py                                      │  │
│  │  - Validates query parameters (symbols, candle, start, end)           │  │
│  │  - Authenticates JWT token                                            │  │
│  │  - Calls MarketController                                             │  │
│  └─────────────────────────────────┬─────────────────────────────────────┘  │
│                                    │                                         │
│  ┌─────────────────────────────────▼─────────────────────────────────────┐  │
│  │  Controller: market_controller.py                                     │  │
│  │  - Normalizes symbols (RELIANCE → RELIANCE-EQ)                        │  │
│  │  - Resolves time range (1d → last 24 hours)                           │  │
│  │  - Orchestrates price + candle fetching                               │  │
│  └──────────────────┬────────────────────────────┬───────────────────────┘  │
│                     │                            │                           │
└─────────────────────┼────────────────────────────┼───────────────────────────┘
                      │                            │
        ┌─────────────▼─────────────┐   ┌─────────▼──────────────┐
        │  Get Current Price        │   │  Get Historical Candles │
        │  (Real-time)              │   │  (OHLCV data)           │
        └─────────────┬─────────────┘   └─────────┬──────────────┘
                      │                           │
                      ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      MARKET DATA SERVICE LAYER                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  MarketDataService (shared/py/market_data.py)                       │    │
│  │  - Singleton instance                                               │    │
│  │  - Manages WebSocket connection                                     │    │
│  │  - In-memory price cache                                            │    │
│  │  - Symbol registration & subscription                               │    │
│  └─────────────────────────────────┬───────────────────────────────────┘    │
│                                    │                                         │
│  ┌─────────────────────────────────▼───────────────────────────────────┐    │
│  │  AngelOneAdapter                                                    │    │
│  │  - WebSocket client for real-time prices                            │    │
│  │  - get_historical_candles() for OHLCV data                          │    │
│  │  - Token map (8,688 NSE stocks cached)                              │    │
│  │  - TOTP authentication                                              │    │
│  └──────────────────┬────────────────────────────┬───────────────────┘      │
└─────────────────────┼────────────────────────────┼─────────────────────────┘
                      │                            │
        ┌─────────────▼─────────────┐   ┌─────────▼──────────────┐
        │  WebSocket Stream         │   │  HTTP REST API         │
        │  (Real-time LTP)          │   │  (Historical Candles)  │
        └─────────────┬─────────────┘   └─────────┬──────────────┘
                      │                           │
                      │                           │
┌─────────────────────┼───────────────────────────┼─────────────────────────────┐
│                     │   ANGEL ONE SMARTAPI      │                             │
│  ┌──────────────────▼────────────┐  ┌──────────▼──────────────────────────┐  │
│  │  WebSocket Endpoint           │  │  Historical API Endpoint            │  │
│  │  wss://smartapisocket         │  │  POST /getCandleData                │  │
│  │    .angelone.in/smart-stream  │  │  - TOTP + JWT authentication        │  │
│  │                               │  │  - NSE symbol token                 │  │
│  │  - Binary LTP updates         │  │  - Interval (ONE_MINUTE to ONE_DAY) │  │
│  │  - Exchange type              │  │  - Date range (fromdate, todate)    │  │
│  │  - Symbol token               │  │  - Returns OHLCV array              │  │
│  └───────────────────────────────┘  └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow Sequence

### 1. Current Price Only (No Candles)

```
Client → GET /api/market/quotes?symbols=RELIANCE
    ↓
Route Handler (Authentication)
    ↓
MarketController.get_quotes(symbols=["RELIANCE"])
    ↓
MarketDataService.get_latest_price("RELIANCE")
    ↓
Check in-memory cache
    ↓
[Cache Hit] → Return cached price
[Cache Miss] → Register symbol → Subscribe via WebSocket → Wait for price
    ↓
Response: {"data": [{"symbol": "RELIANCE", "price": "2456.75"}]}
```

### 2. Current Price + Candles

```
Client → GET /api/market/quotes?symbols=RELIANCE&candle=1d
    ↓
Route Handler (Authentication)
    ↓
MarketController.get_quotes(symbols=["RELIANCE"], candle="1d")
    ↓
┌─────────────────────────┬─────────────────────────┐
│  Get Current Price      │  Get Candle Data        │
│  (from WebSocket cache) │  (from Angel One API)   │
└──────────┬──────────────┴──────────┬──────────────┘
           │                         │
           │                  AngelOneAdapter.get_historical_candles()
           │                         │
           │                  - Map "1d" → "FIVE_MINUTE"
           │                  - Calculate time range (last 24h)
           │                  - Lookup symbol token
           │                  - POST to Angel One Historical API
           │                  - Parse OHLCV response
           │                         │
           └──────────┬──────────────┘
                      ↓
Response: {
  "data": [{"symbol": "RELIANCE", "price": "2456.75"}],
  "metadata": {
    "candles": {
      "RELIANCE": [
        {"timestamp": "...", "open": "...", "high": "...", ...}
      ]
    }
  }
}
```

## Component Responsibilities

### 1. Route Handler (`market_routes.py`)
- ✅ HTTP request validation
- ✅ Query parameter parsing
- ✅ JWT authentication
- ✅ Delegates to controller

### 2. Controller (`market_controller.py`)
- ✅ Business logic orchestration
- ✅ Symbol normalization
- ✅ Time range resolution
- ✅ Parallel fetching (price + candles)
- ✅ Error handling
- ✅ Response formatting

### 3. Market Data Service (`market_data.py`)
- ✅ WebSocket connection management
- ✅ Real-time price streaming
- ✅ In-memory price cache
- ✅ Symbol subscription
- ✅ Adapter pattern (Finnhub, Angel One, 5Paisa)

### 4. Angel One Adapter (`market_data.py`)
- ✅ TOTP authentication
- ✅ JWT token management
- ✅ WebSocket binary parsing
- ✅ Token map (8,688 NSE stocks)
- ✅ Historical candle fetching
- ✅ Symbol normalization (RELIANCE → RELIANCE-EQ)

### 5. Schemas (`schemas/market.py`)
- ✅ Type-safe request/response models
- ✅ Validation rules
- ✅ JSON serialization
- ✅ API documentation

## Caching Strategy

```
┌───────────────────────────────────────────────────────────────┐
│  In-Memory Cache (Redis-like, but in-process)                 │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Price Cache (Latest LTP)                                │ │
│  │  - Key: Symbol (e.g., "RELIANCE")                        │ │
│  │  - Value: Decimal price                                  │ │
│  │  - TTL: Until WebSocket disconnects                      │ │
│  │  - Update: Real-time via WebSocket                       │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Token Map Cache (Symbol → Angel One Token)             │ │
│  │  - Key: Symbol (e.g., "RELIANCE-EQ")                     │ │
│  │  - Value: {token: "2885", exchangeType: 1}               │ │
│  │  - TTL: Persisted to disk (docs/angelone_tokens.json)   │ │
│  │  - Update: Daily via Celery worker                       │ │
│  │  - Size: 8,688 NSE stocks                                │ │
│  └──────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

## Period to Interval Mapping

```
User Request     Angel One Interval    Candle Size    Typical Count
-----------      ------------------    -----------    -------------
candle=1h   →    ONE_MINUTE           1 minute       ~60 candles
candle=1d   →    FIVE_MINUTE          5 minutes      ~75 candles
candle=5d   →    FIFTEEN_MINUTE       15 minutes     ~150 candles
candle=7d   →    FIFTEEN_MINUTE       15 minutes     ~210 candles
candle=30d  →    ONE_HOUR             1 hour         ~150 candles
candle=1y   →    ONE_DAY              1 day          ~252 candles
```

## Authentication Flow

```
┌──────────────────────────────────────────────────────────────┐
│  TOTP-Based Authentication                                   │
│                                                              │
│  1. Generate TOTP                                            │
│     pyotp.TOTP(ANGELONE_TOTP_SECRET).now()                   │
│     → Returns 6-digit code (e.g., "123456")                  │
│                                                              │
│  2. Login Request                                            │
│     POST /rest/auth/angelbroking/user/v1/loginByPassword     │
│     Body: {                                                  │
│       "clientcode": "<client_code>",                         │
│       "password": "<password>",                              │
│       "totp": "123456"                                       │
│     }                                                        │
│                                                              │
│  3. Receive Tokens                                           │
│     Response: {                                              │
│       "jwtToken": "eyJhbGc...",    ← For REST API            │
│       "feedToken": "0123456789",   ← For WebSocket           │
│       "refreshToken": "abc..."     ← For token refresh       │
│     }                                                        │
│                                                              │
│  4. Use Tokens                                               │
│     WebSocket: ?feedToken=0123456789                         │
│     HTTP: Authorization: Bearer eyJhbGc...                   │
└──────────────────────────────────────────────────────────────┘
```

## Error Handling Flow

```
Request → Validation
             │
             ├─ Invalid period → 400 Bad Request
             │
             ├─ Invalid date range → 400 Bad Request
             │
             └─ Valid → Continue
                          │
                          ▼
                   Fetch Current Price
                          │
                          ├─ Cache hit → Success
                          │
                          ├─ WebSocket timeout → Try REST API
                          │
                          └─ All failed → Use fallback price
                                             │
                                             ▼
                                    Fetch Candles (if requested)
                                             │
                                             ├─ Success → Include in metadata
                                             │
                                             ├─ API error → Log & omit candles
                                             │
                                             └─ Symbol not found → Log & omit
                                                                      │
                                                                      ▼
                                                                Return Response
```

## Performance Optimizations

1. **WebSocket Streaming**
   - Persistent connection for real-time prices
   - No API rate limits on WebSocket
   - Sub-second latency

2. **In-Memory Cache**
   - Instant price lookups
   - No database queries
   - Thread-safe with locks

3. **Parallel Fetching**
   - Multiple symbols processed concurrently
   - Candles fetched in parallel (asyncio)
   - Non-blocking I/O

4. **Smart Intervals**
   - Optimized candle granularity per period
   - Avoids excessive data transfer
   - Balances detail vs. performance

5. **Token Caching**
   - 8,688 symbols loaded at startup (~1s)
   - Async regeneration via Celery
   - Persisted to disk (JSON file)

## Security

1. **Authentication**
   - JWT token required for all endpoints
   - TOTP-based Angel One login
   - Tokens expire (refresh mechanism)

2. **Validation**
   - Input sanitization (symbols, dates)
   - Query parameter validation
   - Rate limiting (future enhancement)

3. **Error Messages**
   - No sensitive data in errors
   - Generic messages for production
   - Detailed logs for debugging

## Scalability

```
Current: Single Instance
    ↓
    MarketDataService (singleton)
    ↓
    1 WebSocket connection
    ↓
    In-memory cache

Future: Multi-Instance (Horizontal Scaling)
    ↓
    MarketDataService per instance
    ↓
    Shared Redis cache
    ↓
    WebSocket connection per instance
    ↓
    Load balancer distributes requests
```

## Monitoring Points

1. **API Metrics**
   - Request count per period
   - Response time distribution
   - Error rate

2. **WebSocket Health**
   - Connection status
   - Message rate
   - Reconnection count

3. **Cache Performance**
   - Hit rate
   - Miss rate
   - Cache size

4. **Angel One API**
   - Success rate
   - Latency
   - Rate limit status

---

*Architecture designed for performance, scalability, and maintainability.*
