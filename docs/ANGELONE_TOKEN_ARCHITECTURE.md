# Angel One Token Map Generation - Architecture

## Overview
Automatically generates and caches Angel One stock token mappings for real-time market data subscriptions.

## Components

### 1. Token Generator Utility (`shared/py/angelone_token_generator.py`)
**Purpose**: Core logic for downloading and caching NSE stock tokens

**Functions**:
- `generate_angelone_token_map()` - Downloads scrip master, extracts NSE stocks
- `load_angelone_token_map()` - Loads from cache file
- `ensure_angelone_token_map()` - Smart loader (cache or generate)
- `FALLBACK_TOKEN_MAP` - Minimal mapping for 10 popular stocks

**Cache Location**: `apps/portfolio-server/docs/angelone_tokens.json`

### 2. Celery Task (`apps/portfolio-server/workers/angelone_token_task.py`)
**Purpose**: Async token generation without blocking server startup

**Task**: `generate_angelone_tokens_task`
- Runs in background Celery worker
- Retries 3 times on failure (60s delay)
- Downloads ~2,000 NSE stock tokens
- Saves to cache file

### 3. Angel One Adapter (`shared/py/market_data.py`)
**Purpose**: WebSocket adapter with token lookup

**Behavior**:
- **On startup**: Tries to load from cache
- **If cache missing**: Uses fallback (10 stocks), Celery generates full map
- **If cache exists**: Loads all ~2,000 tokens instantly

### 4. Server Startup (`apps/portfolio-server/main.py`)
**Purpose**: Dispatch Celery task on server start

**Flow**:
```python
if MARKET_DATA_PROVIDER == "angelone":
    # Dispatch async token generation
    generate_angelone_tokens_task.delay(force_refresh=False)
```

## Data Flow

```
Server Startup
    ↓
Check cache exists?
    ↓
YES → Load from cache (instant, ~2,000 stocks)
    ↓
NO → Use fallback (10 stocks)
    ↓
Dispatch Celery task (background)
    ↓
Download scrip master (30 MB, ~20 seconds)
    ↓
Extract NSE stocks (~2,000 symbols)
    ↓
Save to cache file
    ↓
Next restart uses cached file (instant)
```

## File Structure

```
shared/py/
  angelone_token_generator.py    # Core token generation logic
  market_data.py                  # Angel One adapter with token lookup

apps/portfolio-server/
  main.py                         # Dispatch Celery task on startup
  docs/
    angelone_tokens.json          # Cached token map (gitignored)
  workers/
    angelone_token_task.py        # Celery task wrapper
```

## Cache Format

```json
{
  "RELIANCE": {
    "exchangeType": 1,
    "token": "2885",
    "name": "Reliance Industries",
    "segment": "NSE"
  },
  "TCS": {
    "exchangeType": 1,
    "token": "11536",
    "name": "Tata Consultancy Services",
    "segment": "NSE"
  }
}
```

## Benefits

✅ **Fast Startup**: Fallback mapping allows instant server start
✅ **Async Generation**: Celery task doesn't block main thread
✅ **Persistent Cache**: Once generated, reused across restarts
✅ **Auto-Recovery**: Retries on failure, uses fallback on total failure
✅ **Complete Coverage**: All ~2,000 NSE stocks available
✅ **No Manual Config**: No need for `ANGELONE_TOKEN_MAP` env var

## Environment Variables

**Required**:
```properties
MARKET_DATA_PROVIDER=angelone
ANGELONE_CLIENT_CODE=AAAP585011
ANGELONE_API_KEY=doz3gLN8
ANGELONE_PASSWORD=9505
ANGELONE_TOTP_SECRET=ZHFWM22DWMOA4URESHWCP7N5UE
```

**Removed** (auto-generated now):
```properties
# ANGELONE_TOKEN_MAP - No longer needed!
```

## Monitoring

**Logs to watch**:
```
🚀 Dispatching Angel One token map generation to Celery...
✓ Angel One token task dispatched (task_id=xxx)
📥 Downloading Angel One scrip master file...
✅ Extracted 2,047 NSE stocks
💾 Saved token map to .../angelone_tokens.json
```

**On subsequent restarts**:
```
📂 Loaded 2,047 Angel One tokens from cache
```

## Fallback Stocks

If generation fails, these 10 stocks are always available:
- RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK
- HINDUNILVR, ITC, SBIN, BHARTIARTL, KOTAKBANK

## Troubleshooting

**Cache not generating?**
- Check Celery worker is running
- Check logs for download errors
- Verify network access to margincalculator.angelbroking.com

**Want to force refresh?**
```bash
rm apps/portfolio-server/docs/angelone_tokens.json
# Restart server - will regenerate
```

**Manual generation**:
```python
from angelone_token_generator import generate_angelone_token_map
tokens = generate_angelone_token_map()
print(f"Generated {len(tokens)} tokens")
```
