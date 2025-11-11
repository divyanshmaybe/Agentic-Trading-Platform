# Market Data Service Configuration

## Overview

The Market Data Service uses a **persistent WebSocket connection** to stream live price data from Angel One SmartAPI. It supports **intelligent pre-fetching** of Nifty-500 stocks in a **single batch request** to eliminate latency and prevent rate limits.

---

## Configuration Options

### **1. Nifty-500 Pre-Fetch (Recommended)**

Pre-subscribe to all Nifty-500 stocks on startup in a single batch request.

```bash
# Enable Nifty-500 pre-fetch (default: true)
ENABLE_NIFTY500_PREFETCH=true
```

#### **Why Pre-Fetch?**
✅ **Instant Response**: Sub-millisecond price lookups from cache  
✅ **Single Request**: All 500 symbols in ONE WebSocket subscription  
✅ **No Rate Limits**: Single batch request, no quota concerns  
✅ **Better UX**: All prices available immediately after connection  

#### **How It Works**
- **Connection establishes**: WebSocket connects to Angel One
- **Single batch request**: All 500 symbols grouped by exchange type in one message
- **Instant streaming**: All prices start flowing immediately
- **Cache populated**: First ticks populate the price cache
- **Ready to serve**: All subsequent lookups are instant (<1ms)

---

### **2. Angel One Authentication**

Required credentials for Angel One SmartAPI access.

```bash
# Angel One client credentials
ANGELONE_CLIENT_CODE=your_client_code
ANGELONE_API_KEY=your_api_key
ANGELONE_PASSWORD=your_password
ANGELONE_TOTP_SECRET=your_totp_secret

# Session management
ANGELONE_SESSION_TTL_SECONDS=300  # Token validity (default: 5 min)
ANGELONE_LOGIN_RETRIES=3          # Login retry attempts
```

---

### **3. Historical Data API**

Configure retry behavior for Angel One Historical Candle API.

```bash
# Retry configuration for candle data
ANGELONE_HISTORICAL_RETRIES=4           # Retry attempts (default: 4)
ANGELONE_HISTORICAL_BACKOFF_SECONDS=2.0 # Exponential backoff base
```

---

### **4. WebSocket Configuration**

Advanced WebSocket tuning (usually not needed).

```bash
# WebSocket URL (default: Angel One SmartAPI)
ANGELONE_WS_URL=wss://smartapisocket.angelone.in/smart-stream

# Pathway real-time processing
PATHWAY_DISABLE_PROGRESS=1      # Disable progress UI
PATHWAY_LOG_LEVEL=warning       # Reduce log verbosity
```

---

## Performance Benchmarks

### **Without Pre-Fetch (On-Demand)**
- First price lookup: **2-5 seconds** (WebSocket subscription + first tick)
- Subsequent lookups: **Instant** (cached)
- Rate limit risk: **Medium** (burst subscriptions)

### **With Pre-Fetch (Recommended)**
- Startup time: **~1-2 seconds** (single batch subscription)
- All price lookups: **<1ms** (all cached)
- Rate limit risk: **None** (single WebSocket message)
- API quota used: **1 request total**

---

## Example: Production Configuration

```bash
# .env file for production
ENABLE_NIFTY500_PREFETCH=true

ANGELONE_CLIENT_CODE=A123456
ANGELONE_API_KEY=your_api_key
ANGELONE_PASSWORD=your_secure_password
ANGELONE_TOTP_SECRET=your_totp_secret

ANGELONE_SESSION_TTL_SECONDS=300
ANGELONE_HISTORICAL_RETRIES=4
ANGELONE_HISTORICAL_BACKOFF_SECONDS=2.0
```

---

## Monitoring & Logs

### **Successful Pre-Fetch**
```
📊 Pre-fetching ALL 500 Nifty-500 symbols in single batch...
✅ Nifty-500 pre-fetch complete! All 500 symbols subscribed and streaming.
```

### **Price Updates**
```
💰 RELIANCE: None → 2,345.60
💰 TCS: None → 3,678.90
💰 INFY: None → 1,456.30
```

---

## Troubleshooting

### **Pre-fetch disabled automatically**
```
⚠️  nifty500_symbols module not found. Nifty-500 pre-fetch disabled.
```
**Solution**: Ensure `nifty500_symbols.py` exists in `shared/py/`

### **TOTP errors**
```
Angel One login failed: Invalid TOTP
```
**Solution**: Check `ANGELONE_TOTP_SECRET` and ensure system clock is synchronized

---

## Advanced: Custom Symbol Lists

You can pre-fetch custom symbol lists beyond Nifty-500:

```python
from market_data import get_market_data_service

service = get_market_data_service()

# Subscribe to custom symbols
custom_symbols = ["BITCOIN-USD", "ETHEREUM-USD", "GOLD-EQ"]
for symbol in custom_symbols:
    service.register_symbol(symbol)
```

---

## Rate Limit Reference

| Provider   | Requests/Second | Requests/Minute | WebSocket Limit   | Nifty-500 Cost |
|------------|-----------------|-----------------|-------------------|----------------|
| Angel One  | 10              | 500             | 1 connection/user | **1 request**  |
| Finnhub    | 60              | 300             | Unlimited         | N/A            |
| 5Paisa     | Varies          | Varies          | 1 connection/user | Varies         |

**Key Benefit**: Single batch subscription uses just **1 WebSocket message** to subscribe to all 500 symbols, leaving 100% of HTTP API quota available for historical data and other requests!
