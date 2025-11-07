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
```

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
```

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

- Backed by `shared/py/market_data.py` which uses a Pathway websocket connector to stream ticks into a shared cache.
- All services can call `await await_live_price(symbol)` or `get_live_price(symbol)` to retrieve the latest price without managing sockets individually.
- Configure provider behaviour via `MARKET_DATA_*` environment variables (defaults target the generic websocket connector).
- To use Finnhub real-time trades set `MARKET_DATA_PROVIDER=finnhub` and ensure `MARKET_DATA_WS_URL` includes your API token query string (Finnhub allows only one connection per key).
- To use 5paisa set `MARKET_DATA_PROVIDER=5paisa`, point `MARKET_DATA_WS_URL` at the 5paisa websocket endpoint, and optionally configure `FIVEPAISA_AUTH_MESSAGE`, `FIVEPAISA_SUBSCRIBE_TEMPLATE`, and `FIVEPAISA_PRICE_KEYS` to match your stream configuration.

