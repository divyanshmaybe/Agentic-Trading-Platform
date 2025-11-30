# AlphaCopilot Server

A FastAPI server for executing AlphaCopilot workflows - generating trading alphas from market hypotheses.

## Overview

This server provides REST APIs for:
- Creating and managing alpha generation runs
- Executing LangGraph-based workflows to generate factor expressions
- Backtesting generated factors with ML models (LightGBM, XGBoost)
- Streaming logs and progress updates
- Deploying successful alphas to live trading

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AlphaCopilot Server                       │
│                       (Port 8069)                           │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Endpoints:                                         │
│  - POST /runs       Create new hypothesis runs              │
│  - GET  /runs       List all runs                           │
│  - GET  /runs/{id}  Get run details                         │
│  - GET  /runs/{id}/status   Long-polling status updates     │
│  - GET  /runs/{id}/results  Get final results               │
│  - GET  /runs/{id}/logs/stream  SSE log streaming           │
│  - DELETE /runs/{id}  Cancel a run                          │
├─────────────────────────────────────────────────────────────┤
│  Workflow Engine (LangGraph):                               │
│  factor_propose → factor_construct → factor_validate →      │
│  factor_workflow → feedback → [continue?]                   │
├─────────────────────────────────────────────────────────────┤
│  MCP Integration:                                           │
│  - validate_factors: Factor expression validation           │
│  - run_ml_workflow: Backtest execution                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  quant-stream │
                    │  MCP Server   │
                    │  (Port 6969)  │
                    └───────────────┘
```

## Setup

### Prerequisites
- Python 3.11+
- PostgreSQL (via Prisma)
- Redis (optional, for caching)
- quant-stream (symlinked at project root)

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Key variables:
- `LLM_API_KEY`: OpenAI API key for hypothesis generation
- `MCP_SERVER_URL`: URL to quant-stream MCP server
- `DATABASE_URL`: PostgreSQL connection string

### Running Locally

```bash
# Start the server
cd apps/alphacopilot-server
uvicorn main:app --reload --port 8069

# Or from project root
python -m uvicorn apps.alphacopilot-server.main:app --reload --port 8069
```

### Running with Docker

```bash
docker-compose up alphacopilot_server
```

## API Usage

### Create a Run

```bash
curl -X POST http://localhost:8069/runs \
  -H "Content-Type: application/json" \
  -d '{
    "hypothesis": "Momentum predicts returns in Indian equities",
    "max_iterations": 3,
    "model_type": "LightGBM",
    "train_start_date": "2023-01-01",
    "train_end_date": "2023-06-30",
    "test_start_date": "2023-07-01",
    "test_end_date": "2023-12-31"
  }'
```

### Check Status (Long Polling)

```bash
curl "http://localhost:8069/runs/{run_id}/status?timeout=30"
```

### Get Results

```bash
curl http://localhost:8069/runs/{run_id}/results
```

### Stream Logs

```javascript
const eventSource = new EventSource(`http://localhost:8069/runs/${runId}/logs/stream`);
eventSource.onmessage = (event) => {
  console.log(JSON.parse(event.data));
};
```

## Workflow Configuration

The run config supports full quant-stream WorkflowConfig parameters:

```json
{
  "hypothesis": "Your market hypothesis",
  "model_type": "LightGBM",
  "model_params": {
    "learning_rate": 0.05,
    "num_leaves": 127,
    "max_depth": 5,
    "num_boost_round": 300
  },
  "strategy_type": "TopkDropout",
  "topk": 30,
  "n_drop": 5,
  "initial_capital": 1000000,
  "commission": 0.001,
  "slippage": 0.001
}
```

## Database Schema

Uses shared Prisma schema with these models:
- `AlphaCopilotRun`: Run records
- `AlphaCopilotIteration`: Iteration results
- `AlphaCopilotResult`: Final results with workflow_config
- `AlphaCopilotLog`: Log entries

## Integration with Portfolio Server

Results can be deployed as LiveAlpha via portfolio-server:

```bash
POST /api/alphas/live
{
  "run_id": "uuid",
  "name": "Momentum Alpha",
  "portfolio_id": "uuid",
  "allocated_amount": 100000
}
```



