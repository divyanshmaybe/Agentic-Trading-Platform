# Portfolio Server

FastAPI service that integrates the NSE pipeline and now leverages the shared PostgreSQL database via Prisma.

## Features

- FastAPI server with shared utilities
- Centralized PostgreSQL access through Prisma Client Python
- Streaming market data via Pathway websocket connector and shared price cache
- Trading engine with market, limit, stop, and take-profit order support
- Celery worker for asynchronous execution of pending orders
- NSE pipeline integration (dispatched to Celery worker automatically)
- Health check endpoints and pipeline status monitoring
- Structured error handling middleware

## Setup

### Environment Variables

Create a `.env` file in the `apps/portfolio-server` directory:

```env
PORT=8000
DATABASE_URL=postgresql://auth_user:auth_password@localhost:5433/auth_db
INTERNAL_SERVICE_SECRET=super-secret
GEMINI_API_KEY=your_gemini_api_key_here
REDIS_HOST=localhost
REDIS_PORT=6379
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
MARKET_DATA_PROVIDER=finnhub  # options: finnhub, 5paisa, generic
MARKET_DATA_WS_URL=wss://ws.finnhub.io?token=YOUR_TOKEN  # set provider-specific websocket URL

# Demo Mode - Process signals 24/7 (for testing/demo only)
DEMO_MODE=false  # Set to true to bypass market hours restrictions

# Risk Monitoring Configuration
STREAMING_RISK_MONITOR_ENABLED=true  # Enable real-time streaming risk monitor
RISK_MONITOR_POLL_INTERVAL=0.5  # Polling interval in seconds (default: 500ms)
RISK_MONITOR_REFRESH_POSITIONS=30  # Position refresh interval in seconds
PORTFOLIO_RISK_MONITOR_ENABLED=false  # Disable legacy batch-based risk monitor

# Portfolio Allocation Configuration
PORTFOLIO_REBALANCE_ENABLED=true  # Enable automatic rebalancing
PORTFOLIO_REBALANCE_HOUR=5  # Rebalancing sweep time (5:00 AM = 1h before market open)
PORTFOLIO_REBALANCE_MINUTE=0
PORTFOLIO_REBALANCE_DAY_OF_WEEK=mon-fri  # Run on weekdays only
ALLOCATION_SWEEP_ON_STARTUP=true  # Run allocation sweep on startup for pending portfolios
```

**DEMO_MODE**: When enabled, the NSE pipeline will process trading signals at any time, regardless of market hours. This is useful for testing and demonstrations but should be disabled in production.

**Portfolio Allocation**: 
- **On Startup**: Allocates pending portfolios (created but not allocated yet)
- **Scheduled**: Runs daily at 5:00 AM for portfolios due for rebalancing
- **Triggered**: Via API when objectives are created/updated

### Install Dependencies

```bash
# Activate your virtualenv first
pip install -r requirements.txt

# Apply Prisma schema and generate the Python client
cd apps/portfolio-server
prisma db push
prisma generate
```

> **Tip:** Re-run `prisma generate` whenever you change `prisma/schema.prisma`.

### Running the Server

```bash
# API server
cd apps/portfolio-server
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Celery worker (second terminal, runs NSE pipeline & trade queue)
celery --workdir apps/portfolio-server -A celery_app:celery_app worker --loglevel=info

# Streaming risk monitor (third terminal, real-time position monitoring)
cd apps/portfolio-server
python -m workers.streaming_risk_monitor
```

### Risk Monitoring

The portfolio server includes **two risk monitoring modes**:

#### 1. Streaming Risk Monitor (RECOMMENDED - Real-time)
- **Latency**: <1 second from price change to alert
- **Architecture**: Continuous background service polling WebSocket price cache every 500ms
- **Alerts**: Instant Kafka publishing when threshold breached
- **Usage**: Run `python -m workers.streaming_risk_monitor`
- **Benefits**: 
  - Sub-second alert generation
  - Continuous monitoring (no 15-minute gaps)
  - Minimal resource usage (symbol-based price fetching)
  - Integrates with MarketDataService WebSocket cache

#### 2. Batch Risk Monitor (LEGACY - Backward compatible)
- **Latency**: 15 minutes (Celery Beat scheduled)
- **Architecture**: Periodic task that processes all positions in batch
- **Alerts**: Kafka + Email after each batch run
- **Usage**: Enabled via `PORTFOLIO_RISK_MONITOR_ENABLED=true`
- **Note**: Kept for backward compatibility and testing only

**Production Recommendation**: Use streaming mode for real-time alerts with <1 second latency.

### Portfolio Allocation & Rebalancing

The portfolio server handles allocation in **three scenarios**:

#### 1. API-Triggered Allocation (Immediate)
- **When**: Portfolio or objective created via API
- **Trigger**: `POST /api/portfolios` or `POST /api/objectives`
- **Behavior**: Immediate Celery task queued for allocation
- **Status**: Portfolio marked as `allocation_status="pending"` then `"ready"`

#### 2. Startup Allocation Sweep (On Service Start)
- **When**: Service starts (if `ALLOCATION_SWEEP_ON_STARTUP=true`)
- **Trigger**: FastAPI lifespan startup event
- **Behavior**: 
  - Finds portfolios with `allocation_status="pending"` (never allocated)
  - Allocates them immediately using current market regime
- **Use Case**: Handle portfolios created while service was down

#### 3. Scheduled Rebalancing (Daily)
- **When**: Daily at configured time (default: 5:00 AM, 1h before market open)
- **Trigger**: Celery Beat schedule (if `PORTFOLIO_REBALANCE_ENABLED=true`)
- **Behavior**:
  - Finds portfolios with `rebalancing_date <= today`
  - Includes overdue portfolios (catches missed rebalancing dates)
  - Re-runs allocation pipeline with latest regime
  - Calculates next rebalancing date based on frequency
- **Schedule**: Configurable via `PORTFOLIO_REBALANCE_HOUR`, `PORTFOLIO_REBALANCE_MINUTE`

**Rebalancing Logic**:
- Frequency options: `"quarterly"`, `"monthly"`, `"biannual"`, `"annual"`
- Next date calculated from portfolio's `rebalancing_frequency` setting
- Allocation weights recalculated based on current market regime
- Existing allocations updated, trading agents maintained

## API Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check
- `GET /api/pipeline/status` - Pipeline status
- `POST /api/trades` - Create a trade (market/limit/stop/take-profit)
- `GET /docs` - Swagger documentation

### Trade API Usage

```http
POST /api/trades
Headers:
  Content-Type: application/json
  Authorization: Bearer <access_token>

Body:
{
  "portfolio_id": "portfolio-xyz",
  "symbol": "AAPL",
  "side": "BUY",
  "order_type": "market",
  "quantity": 10,
  "source": "automation"
}
```

- Market orders execute immediately using the shared Pathway-backed price cache.
- Limit/stop/take-profit orders are enqueued for the Celery worker to monitor and execute when conditions are met.

## Pipeline Integration

The NSE pipeline is queued to the Celery worker when the API starts. The worker process runs the Pathway pipeline and:

1. Scrapes NSE announcements every 60 seconds
2. Analyzes sentiment using LLM
3. Generates trading signals
4. Runs backtesting
5. Outputs results to JSONL files

Output files are written to `apps/portfolio-server/pipelines/nse/`:
- `trading_signals.jsonl`
- `backtest_results.jsonl`
- `backtest_metrics.jsonl`

## Market Data Service

**Real-time price streaming with intelligent Nifty-500 pre-fetching**

- Backed by `shared/py/market_data.py` using Pathway WebSocket connector for real-time price streams
- **Pre-fetches all Nifty-500 symbols in a single batch** on startup for instant price lookups
- All services call `await await_live_price(symbol)` or `get_live_price(symbol)` for latest prices
- **Zero rate limit concerns**: Single WebSocket subscription message for all 500 symbols
- Configure via environment variables (see `shared/py/MARKET_DATA_CONFIG.md`)

### Quick Start
```bash
# Enable Nifty-500 pre-fetch (recommended)
ENABLE_NIFTY500_PREFETCH=true

# Angel One credentials
ANGELONE_CLIENT_CODE=your_client_code
ANGELONE_API_KEY=your_api_key
ANGELONE_PASSWORD=your_password
ANGELONE_TOTP_SECRET=your_totp_secret
```

### Performance
- **Startup**: ~1-2 seconds (single batch subscription)
- **Price lookups**: <1ms (all 500 stocks cached)
- **API quota**: 1 WebSocket message total (100% HTTP quota available for historical data)

### Provider Support
- **Angel One** (default): `MARKET_DATA_PROVIDER=angelone` - Supports Nifty-500 pre-fetch
- **Finnhub**: `MARKET_DATA_PROVIDER=finnhub` - Real-time trades (token required)
- **5Paisa**: `MARKET_DATA_PROVIDER=5paisa` - Custom stream configuration

📖 **Full documentation**: `shared/py/MARKET_DATA_CONFIG.md`

