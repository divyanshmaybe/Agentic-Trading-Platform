# Portfolio Server

FastAPI service powering the trading engine, risk management, and Pathway streaming pipelines.

## 🏗️ Architecture Overview

The Portfolio Server is the core trading and risk management service that orchestrates:

- **Pathway Streaming Pipelines**: Real-time NSE filings, news sentiment, and market regime analysis
- **Trade Execution Engine**: Automated order placement with broker integration (Angel One)
- **Risk Monitoring**: Real-time position monitoring with sub-second alert latency
- **Portfolio Allocation**: AI-driven capital allocation across trading strategies
- **Market Data Aggregation**: WebSocket-based real-time price feeds

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **API Framework** | FastAPI | High-performance async REST API |
| **Streaming Engine** | Pathway | Real-time data pipeline processing |
| **Task Queue** | Celery + Redis | Async job processing and scheduling |
| **Database** | PostgreSQL + Prisma | Relational data with type-safe ORM |
| **Caching** | Redis | Price cache and session storage |
| **Event Bus** | Kafka | Inter-service event streaming |
| **Monitoring** | Prometheus | Metrics collection and alerting |

### Data Flow

```
External Data Sources                Portfolio Server                 Consumers
─────────────────────              ──────────────────               ───────────
                                   
NSE Filings ─────┐                ┌──────────────┐                ┌──────────────┐
News APIs ───────┼───Pathway──────▶│  Processing  │───Kafka────────▶│  Frontend    │
Market Data ─────┘   Pipelines    │   Pipelines  │   Events       │  Dashboard   │
                                   └──────────────┘                └──────────────┘
                                          │                                │
                                          ▼                                ▼
REST API Calls ───────────────────▶ ┌──────────────┐             ┌──────────────┐
(Portfolio/Trades)                  │   FastAPI    │─────────────▶│ Angel One    │
                                   │   Endpoints  │   Orders      │   Broker     │
                                   └──────────────┘             └──────────────┘
                                          │
                                          ▼
                                   ┌──────────────┐
                                   │  PostgreSQL  │
                                   │   Database   │
                                   └──────────────┘
```

## 🎯 Key Features

### 1. Pathway Streaming Pipelines

#### NSE Filings Sentiment Pipeline
- Scrapes NSE/MCA regulatory filings every 60 seconds
- LLM-based sentiment analysis (Gemini/Groq)
- Generates trading signals with confidence scores
- Publishes to Kafka topic: `nse_filings_trading_signal`

#### News Sentiment Pipeline
- Hourly news fetching from NewsAPI
- Multi-source aggregation and deduplication
- Sector-wise sentiment analysis
- Stock recommendations published to Kafka

#### Risk Agent Pipeline
- Real-time position monitoring (<1s latency)
- Stop-loss and take-profit threshold tracking
- Immediate Kafka alerts on breach
- Integrates with WebSocket price cache

### 2. Trade Execution Engine

**Order Types:**
- Market orders (immediate execution)
- Limit orders (price-conditional)
- Stop-loss orders (risk management)
- Take-profit orders (profit booking)

**Broker Integration:**
- Angel One API (primary)
- Simulation mode for testing
- Automatic position tracking

### 3. Portfolio Allocation System

**Allocation Triggers:**
- API-triggered (immediate on portfolio creation)
- Startup sweep (pending portfolios)
- Scheduled rebalancing (daily at 5:00 AM)

**Regime-Based Allocation:**
- Bull market strategy allocation
- Bear market hedging
- Sideways market neutral strategies
- Dynamic weight adjustment

### 4. Real-Time Risk Monitoring

**Streaming Risk Monitor** (Recommended):
- <1 second alert latency
- Continuous WebSocket-based monitoring
- Symbol-based price fetching
- Immediate Kafka alert publishing

**Batch Risk Monitor** (Legacy):
- 15-minute intervals via Celery Beat
- Backward compatible for testing
- Email + Kafka alerts

## ⚙️ Setup

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

---

## 🔄 Important Flows

### Trade Execution Flow

```
1. Signal Generation (Pathway Pipeline)
   └─▶ NSE filing detected → LLM sentiment analysis → Trading signal

2. Signal Validation
   └─▶ Confidence threshold check → Risk limits → Position sizing

3. Order Creation
   └─▶ Portfolio allocation → Order params (symbol, qty, type) → Trade queue

4. Order Execution (Celery Worker)
   └─▶ Broker API call → Order placement → Position update → Kafka log

5. Position Monitoring (Streaming Risk Monitor)
   └─▶ Price updates → Threshold checks → Alert generation (if needed)
```

### Portfolio Allocation Flow

```
1. Regime Detection
   └─▶ Market indicators → Regime classification (Bull/Bear/Sideways)

2. Strategy Selection
   └─▶ User objectives → Risk profile → Regime → Strategy weights

3. Capital Allocation
   └─▶ Total capital → Strategy weights → Per-strategy allocation

4. Trading Agent Assignment
   └─▶ Allocated capital → Agent creation → Symbol assignment

5. Rebalancing Schedule
   └─▶ Frequency setting → Next rebalance date → Celery Beat task
```

### Risk Alert Flow

```
1. Price Update (WebSocket)
   └─▶ Real-time price → Pathway cache → Risk monitor fetch

2. Threshold Evaluation
   └─▶ Current price vs stop-loss/take-profit → Breach detection

3. Alert Generation
   └─▶ Alert creation → Kafka publish → Database log

4. Notification Delivery
   └─▶ Notification Server → Redis pub/sub → Frontend real-time update
```

---

## 📊 Monitoring & Metrics

The service exposes Prometheus metrics at `/metrics`:

**Key Metrics:**
- `http_requests_total` - Total API requests by endpoint
- `http_request_duration_seconds` - Request latency histogram
- `trade_executions_total` - Trade count by status (success/failure)
- `portfolio_positions_total` - Active positions count
- `risk_alerts_total` - Risk alerts by severity
- `celery_task_duration_seconds` - Task execution time

**Health Checks:**
- `GET /health` - Service health status
- `GET /api/pipeline/status` - Pipeline execution status

**Grafana Dashboard:**
Access pre-configured dashboard at http://localhost:3001 (Portfolio Server Dashboard)

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov --cov-report=html

# Run specific test file
pytest tests/test_trade_execution.py -v

# Run integration tests
pytest tests/integration/ -v
```

---

## 🔐 Security Considerations

1. **API Authentication**: All endpoints require JWT validation via Auth Server
2. **Broker Credentials**: Stored securely in environment variables
3. **Database Access**: Connection pooling with SSL enabled
4. **Kafka Security**: SASL authentication for production
5. **Rate Limiting**: Implemented at API gateway level

---

## 🐛 Troubleshooting

### Pipeline Not Running
```bash
# Check Celery worker status
pnpm celery

# View pipeline logs
docker logs portfolio_celery_nse -f

# Check Kafka topics
docker exec pathway-kafka kafka-topics.sh --list --bootstrap-server localhost:9092
```

### Trade Execution Failures
```bash
# Check broker connection
# View trade execution logs
docker logs portfolio_celery_trading -f

# Verify market data cache
redis-cli -p 6381 keys "price:*"
```

### Database Connection Issues
```bash
# Test database connection
psql -h localhost -p 5434 -U portfolio_user -d portfolio_db

# View connection pool stats
curl http://localhost:8000/metrics | grep postgres
```

---

## 📚 Related Documentation

- [Architecture Overview](../../docs/ARCHITECTURE.md)
- [NSE Automated Trading](../../docs/NSE_AUTOMATED_TRADING.md)
- [Market Data Configuration](../../shared/py/MARKET_DATA_CONFIG.md)
- [API Documentation](http://localhost:8000/docs) (when server is running)

---

**Built with ❤️ for algorithmic trading**
