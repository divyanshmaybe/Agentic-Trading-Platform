# Portfolio Server

FastAPI server that integrates NSE pipeline and other Pathway-based pipelines.

## Features

- FastAPI server with shared utilities
- NSE pipeline integration (runs in background on startup)
- Health check endpoints
- Pipeline status monitoring
- Error handling middleware

## Setup

### Environment Variables

Create a `.env` file in the project root:

```env
PORT=8000
GEMINI_API_KEY=your_gemini_api_key_here
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Running the Server

```bash
# From project root
cd apps/pipeline-server
python main.py
```

Or using uvicorn directly:

```bash
uvicorn apps.pipeline-server.main:app --reload --port 8000
```

## API Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check
- `GET /api/pipeline/status` - Pipeline status
- `GET /docs` - Swagger documentation

## Pipeline Integration

The NSE pipeline starts automatically when the server starts. It runs in a background thread and:

1. Scrapes NSE announcements every 60 seconds
2. Analyzes sentiment using LLM
3. Generates trading signals
4. Runs backtesting
5. Outputs results to JSONL files

Output files are written to `pw-scripts/NSE_FILLINGS/`:
- `trading_signals.jsonl`
- `backtest_results.jsonl`
- `backtest_metrics.jsonl`

