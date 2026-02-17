# AlphaCopilot Server

FastAPI service for AI-powered hypothesis generation and automated backtesting using the Quant-Stream library.

## 🏗️ Architecture Overview

AlphaCopilot Server is an intelligent agent that transforms natural language trading hypotheses into validated alpha factors:

- **Hypothesis Input**: Natural language trading ideas from users
- **Factor Generation**: LLM-powered factor expression synthesis
- **Validation**: Syntax and semantic validation of generated factors
- **Backtesting**: Automated ML model training and performance evaluation
- **Alpha Deployment**: Integration with live trading system

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **API Framework** | FastAPI | Async REST API |
| **LLM Integration** | LangGraph | Multi-agent workflow orchestration |
| **Backtesting** | Quant-Stream | Factor backtesting library |
| **ML Models** | LightGBM, XGBoost, LSTM | Alpha signal generation |
| **Database** | PostgreSQL + Prisma | Run history and results |
| **Task Queue** | Celery + Redis | Async backtest execution |
| **Experiment Tracking** | MLflow | Model versioning and metrics |
| **Monitoring** | Prometheus | Metrics collection |

### Data Flow

```
User Hypothesis          AlphaCopilot Server        Quant-Stream Library
───────────────         ────────────────────        ────────────────────

Natural Language  ──┐   ┌────────────────┐         ┌─────────────────┐
"Momentum signals    │──▶│  LLM Agent     │────────▶│ Factor Validator│
predict returns"     │   │  (LangGraph)   │◀────────│ (Syntax Check)  │
                     │   └────────────────┘         └─────────────────┘
                     │           │                           │
                     │           ▼                           ▼
                     │   ┌────────────────┐         ┌─────────────────┐
                     │   │ Factor Library │         │  ML Backtester  │
                     │   │  (Generated)   │────────▶│  (Train/Test)   │
                     │   └────────────────┘         └─────────────────┘
                     │           │                           │
                     │           ▼                           ▼
                     │   ┌────────────────┐         ┌─────────────────┐
                     └──▶│  Run Manager   │◀────────│  Performance    │
                         │  (PostgreSQL)  │         │  Metrics        │
                         └────────────────┘         └─────────────────┘
                                 │
                                 ▼
                         ┌────────────────┐
                         │ Frontend       │
                         │ (Results UI)   │
                         └────────────────┘
```

## 🎯 Key Features

### 1. Natural Language Hypothesis Processing

**Input Examples:**
- "High momentum stocks with low volatility outperform"
- "Mean reversion occurs in oversold large-cap stocks"
- "Earnings surprises predict short-term price movements"

**Processing:**
- LLM interprets hypothesis
- Generates factor expressions (Alpha158 format)
- Validates syntax and semantics
- Iterative refinement based on feedback

### 2. Multi-Agent Workflow

**Agents:**
- **Factor Proposer**: Generates candidate factor expressions
- **Factor Constructor**: Builds complete factor libraries
- **Factor Validator**: Checks syntax and feasibility
- **Backtest Executor**: Runs ML model training
- **Performance Analyzer**: Evaluates results and provides feedback

**Workflow:**
```
Hypothesis → Propose Factors → Construct Library → Validate → Backtest
     ↑                                                           │
     └─────────────── Feedback Loop ──────────────────────────┘
```

### 3. Automated Backtesting

**Supported Models:**
- LightGBM (default)
- XGBoost
- LSTM (deep learning)

**Evaluation Metrics:**
- Information Coefficient (IC)
- Sharpe Ratio
- Maximum Drawdown
- Win Rate
- Cumulative Returns

**Data Handling:**
- Train/test split
- Cross-validation
- Walk-forward analysis
- Out-of-sample validation

### 4. Experiment Tracking

**MLflow Integration:**
- Run versioning
- Hyperparameter logging
- Metric tracking
- Model artifact storage
- Comparative analysis

**Tracking:**
- Factor expressions
- Model configurations
- Performance metrics
- Training duration
- Resource usage

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

## ⚙️ Setup

### Prerequisites
- Python 3.10+
- PostgreSQL 16
- Redis 7
- Quant-Stream library

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Install quant-stream
cd ../../quant-stream
pip install -e .
cd ../apps/alphacopilot-server

# Generate Prisma client
prisma generate
```

### Environment Variables

Create `.env` file in `apps/alphacopilot-server/`:

```env
PORT=8069
HOST=0.0.0.0

# Database
DATABASE_URL=postgresql://portfolio_user:portfolio_password@localhost:5434/portfolio_db

# Redis
REDIS_URL=redis://localhost:6381
CELERY_BROKER_URL=redis://localhost:6381/0
CELERY_RESULT_BACKEND=redis://localhost:6381/1

# MLflow
MLFLOW_TRACKING_URI=./mlruns

# LLM Configuration
LLM_API_KEY=your-openai-api-key
LLM_MODEL=gpt-4
LLM_TEMPERATURE=0.7

# Authentication
INTERNAL_SERVICE_SECRET=your-internal-secret

# Monitoring
PROMETHEUS_ENABLED=true
```

### Running Locally

```bash
# Start API server
cd apps/alphacopilot-server
uvicorn main:app --reload --port 8069

# Start Celery worker (separate terminal)
cd quant-stream
celery -A quant_stream.mcp_server.core.celery_config worker \
  --loglevel=info -Q backtest --concurrency=2

# Start MLflow UI (optional)
mlflow ui --backend-store-uri ./mlruns --port 5000
```

### Docker

```bash
# Build and run
docker-compose up alphacopilot_server alphacopilot_celery

# View logs
docker logs alphacopilot_server -f
```

---

## 🔄 Important Flows

### Hypothesis to Alpha Flow

```
1. User Input
   └─▶ Natural language hypothesis → API request

2. Factor Generation (LLM Agent)
   └─▶ Parse hypothesis → Generate factor expressions → Validate syntax

3. Backtest Preparation
   └─▶ Create factor library → Load market data → Configure ML model

4. Model Training (Celery Worker)
   └─▶ Train/test split → Model fitting → Performance evaluation

5. Results Analysis
   └─▶ Calculate metrics → Generate visualizations → Store in MLflow

6. Feedback Loop (if needed)
   └─▶ Analyze failures → Refine factors → Retry workflow
```

### Iteration Loop

```
Iteration 1: Initial factor generation
   ├─▶ If performance good (IC > 0.05) → Success, deploy
   └─▶ If performance poor → Feedback analysis

Iteration 2: Refined factors based on feedback
   ├─▶ Adjust factor combinations
   ├─▶ Add/remove features
   └─▶ Backtest again

Iteration 3: Final attempt
   └─▶ Best effort factors → Deploy or mark as failed
```

### Deployment Flow

```
1. Successful Backtest
   └─▶ IC > threshold → Sharpe > 1.0 → Approved for deployment

2. Factor Export
   └─▶ Save factor library → Generate production code

3. Integration
   └─▶ Add to Portfolio Server → Assign to trading strategy

4. Monitoring
   └─▶ Track live performance → Compare with backtest → Alert on degradation
```

---

## 📊 Monitoring & Metrics

Prometheus metrics exposed at `/metrics` (port 8069):

**Key Metrics:**
- `alphacopilot_runs_total` - Total runs by status (success/failure)
- `alphacopilot_run_duration_seconds` - Run execution time
- `alphacopilot_backtest_duration_seconds` - Backtest execution time
- `alphacopilot_iterations_per_run` - Average iterations needed
- `alphacopilot_model_performance` - IC and Sharpe metrics

**MLflow UI:**
Access experiment tracking at http://localhost:5000 (when MLflow server running)

**Grafana Dashboard:**
Pre-configured dashboard at http://localhost:3001 (AlphaCopilot Dashboard)

---

## 🧪 Testing

```bash
# Run unit tests
pytest tests/ -v

# Test with sample hypothesis
curl -X POST http://localhost:8069/runs \
  -H "Content-Type: application/json" \
  -d '{
    "hypothesis": "Momentum predicts returns in Indian equities",
    "max_iterations": 3,
    "model_type": "LightGBM"
  }'

# Monitor run status
curl http://localhost:8069/runs/{run_id}/status

# Get results
curl http://localhost:8069/runs/{run_id}/results
```

### Check Status (Long Polling)

```bash
curl "http://localhost:8069/runs/{run_id}/status?timeout=30"
```

### Get Results

```bash
curl http://localhost:8069/runs/{run_id}/results
```

---

## 🔐 Security Considerations

1. **API Authentication**: All endpoints require JWT validation
2. **LLM API Keys**: Securely stored in environment variables
3. **Database Access**: Connection pooling with SSL
4. **Resource Limits**: Configurable max iterations and timeout
5. **Experiment Isolation**: MLflow runs isolated per user

---

## 🐛 Troubleshooting

### Backtest Failures

```bash
# Check Celery worker status
celery -A quant_stream.mcp_server.core.celery_config inspect active

# View worker logs
docker logs alphacopilot_celery -f

# Check Redis queue
redis-cli -p 6381 llen celery
```

### Factor Validation Errors

```bash
# Test factor syntax manually
python -c "from quant_stream import validate_factors; print(validate_factors(['your_factor']))"

# Check quant-stream library
pip show quant-stream
```

### Database Connection Issues

```bash
# Test database
psql -h localhost -p 5434 -U portfolio_user -d portfolio_db

# Check Prisma client
prisma generate
```

---

## 📚 Related Documentation

- [Architecture Overview](../../docs/ARCHITECTURE.md)
- [Quant-Stream Library](../../quant-stream/README.md)
- [Portfolio Server Integration](../portfolio-server/README.md)
- [API Documentation](http://localhost:8069/docs) (when server running)

---

**Built with ❤️ for AI-powered alpha generation**
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



