# Agentic Trading Platform

A multi-service platform for trading research, signal processing, portfolio automation, and monitored paper-trading workflows.

The project is built around one core question:

> How can market disclosures, news, portfolio data, and trading signals be processed in a structured and auditable way?

This repository is not a brokerage product and is not investment advice. It is a backend-focused system for research, simulation, signal generation, portfolio automation, and trade execution workflows.

## Problem We Are Solving

Indian markets are becoming more digital, and retail participation has increased significantly. Demat accounts crossed the 20 crore mark in 2025, and NSE reported over 11 crore unique registered investors around the same period. This creates a practical information problem: public market information is available, but it is spread across filings, announcements, news, market data, and portfolio records.

This project focuses on the following problems:

- Corporate announcements are public, but they still need to be detected, classified, read, and interpreted.
- Investors cannot manually monitor filings, news, live prices, risk, and allocation changes throughout the day.
- Trading decisions need guardrails: position sizing, opt-in controls, paper/live execution modes, stop-loss logic, audit logs, and monitoring.
- ML or LLM outputs need to be converted into traceable backend workflows before they can be used safely.
- Trading systems require multiple services to work together: APIs, workers, queues, databases, market feeds, broker integrations, and monitoring.

External context:

- [Economic Times: demat accounts crossed 20 crore in India](https://economictimes.indiatimes.com/markets/stocks/news/indias-demat-accounts-cross-20-crore-mark-led-by-young-investors-under-30/articleshow/123129245.cms)
- [NSE overview and investor base context](https://www.nseindia.com/)
- [BSE corporate announcements](https://www.bseindia.com/corporates/ann.html)
- [SEBI investor protection and market regulation](https://www.sebi.gov.in/)

## Approach

The platform combines backend services, event processing, LLM-based analysis, quantitative logic, and portfolio execution controls.

At a high level:

```text
Market disclosures/news/market data
  -> ingestion pipelines
  -> LLM + quantitative signal generation
  -> portfolio and agent eligibility checks
  -> deterministic trade sizing
  -> paper/live trade execution service
  -> position, risk, audit, and monitoring updates
  -> frontend dashboards and notifications
```

The system covers the full path from input data to monitored execution:

1. Detect relevant information.
2. Convert it into a structured signal.
3. Check whether a user/portfolio/agent is eligible.
4. Size the position.
5. Execute or simulate the trade.
6. Track positions, risk, and logs.
7. Show the result in dashboards, logs, and monitoring tools.

## Main Capabilities

### Filings-Driven Trading

The codebase has an older "NSE pipeline" naming convention. The current live filings path mainly uses BSE corporate announcements, which feed into the same high-risk trade execution flow.

The filings pipeline:

- polls exchange announcements,
- detects relevant order-win or "bagging" announcements,
- processes other relevant filings through an LLM analysis path,
- creates structured BUY/SELL/HOLD-style signals,
- routes actionable signals into Celery,
- sizes trades for active high-risk trading agents,
- persists trade logs,
- executes in paper mode by default.

For the current implementation details, read:

- [.codex/NSE_PIPELINE_CONTEXT.md](.codex/NSE_PIPELINE_CONTEXT.md)
- [docs/NSE_AUTOMATED_TRADING.md](docs/NSE_AUTOMATED_TRADING.md)

### Portfolio and Agent Automation

The backend models portfolios as capital controlled by different strategy agents:

- `high_risk` agents for filing-driven short-term trades,
- `low_risk` pipelines for conservative stock selection,
- `alpha` agents for AlphaCopilot-generated strategy ideas,
- allocation and rebalancing services for portfolio-level decisions.

### Trade Execution

Trade execution is handled as a backend workflow rather than a standalone action.

Key safety controls include:

- paper trading by default,
- market-hours checks,
- active-agent opt-in,
- allocation cash checks,
- max concurrent high-risk positions,
- duplicate signal protection,
- trade and execution logs,
- position and P&L updates,
- end-of-day high-risk position closure.

### AlphaCopilot

AlphaCopilot supports research workflows such as hypothesis generation and backtesting using the `quant-stream` library.

### Observability

The repository includes monitoring support for:

- Celery queues,
- FastAPI metrics,
- Node.js service metrics,
- Kafka event flow,
- Prometheus,
- Grafana,
- Flower,
- optional Phoenix tracing for LLM workflows.

## Architecture

```text
apps/frontend
  Next.js investor dashboard

apps/auth_server
  Express + TypeScript authentication service
  Prisma-backed users, sessions, subscriptions, email flows

apps/portfolio-server
  FastAPI trading backend
  Portfolio APIs, market data, trade execution, Celery tasks, pipelines

apps/notification_server
  Kafka consumer and notification bridge

apps/alphacopilot-server
  FastAPI service for AI strategy research and backtesting

shared/
  Shared Prisma schema plus Python/TypeScript utilities

quant-stream/
  Quant research and backtesting library
```

Core infrastructure:

| Layer | Technology |
| --- | --- |
| Frontend | Next.js, TypeScript |
| Auth API | Express.js, Prisma |
| Portfolio API | FastAPI, Python |
| Background jobs | Celery |
| Event bus | Kafka |
| Databases | PostgreSQL |
| Cache/queues | Redis |
| ML/LLM workflows | Gemini/OpenAI-compatible integrations, Quant-Stream |
| Monitoring | Prometheus, Grafana, Flower |

## Repository Structure

```text
apps/
  auth_server/           Express auth and email workflows
  frontend/              Next.js dashboard
  portfolio-server/      Main trading backend and pipelines
  notification_server/   Kafka notification consumer
  alphacopilot-server/   AI strategy research API

shared/
  prisma/                Shared Prisma schema
  py/                    Python service utilities
  js/                    TypeScript service utilities

quant-stream/            Quant research and backtesting code
packages/                Shared frontend/tooling packages
docs/                    Deeper architecture and feature notes
docker_manifests/        Prometheus/Grafana/Loki config
devops/                  Deployment and monitoring assets
scripts/                 Operational helper scripts
```

## Current Local Setup

Docker Compose is the preferred setup path for this repository. Older VM-specific instructions have been removed from this README because they do not match the current local workflow.

### Prerequisites

- Docker Desktop or Docker Engine with Compose
- Node.js 18+
- pnpm 9+
- Python 3.10+

### 1. Install Node Dependencies

```bash
pnpm install
```

### 2. Configure Environment Files

Most services already have `docker.env` or `.env.example` files. The root `docker.env` is the shared Compose environment file. If it is missing in your clone, create it manually from the values used by your team.

For service-level env files, create the missing `docker.env` files from examples where available:

```bash
copy apps\portfolio-server\.env.example apps\portfolio-server\docker.env
copy apps\auth_server\.env.example apps\auth_server\docker.env
copy apps\frontend\.env.example apps\frontend\docker.env
copy apps\notification_server\.env.example apps\notification_server\docker.env
copy apps\alphacopilot-server\.env.example apps\alphacopilot-server\docker.env
```

On macOS/Linux, use `cp` instead of `copy`.

Minimum values to check:

- database URLs,
- Redis URLs,
- JWT/internal service secrets,
- Gemini or other LLM API keys,
- optional NewsAPI key,
- optional SendGrid key,
- optional Angel One credentials.

For development, keep live trading disabled unless broker execution is being tested intentionally:

```env
ANGELONE_TRADING_ENABLED=false
CFDT_PAPER_TRADING_ONLY=true
```

### 3. Start The Platform

Start the services with Docker Compose:

```bash
docker compose up -d
```

You can also use the helper script if your shell supports it:

```bash
./docker.sh start
```

Useful optional profiles:

```bash
docker compose --profile monitoring up -d
docker compose --profile debug up -d
```

### 4. Open Services

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| Auth Server | http://localhost:4000 |
| Portfolio Server | http://localhost:8000 |
| AlphaCopilot Server, not started by default | http://localhost:8069 |
| Flower, monitoring profile | http://localhost:5555 |
| Grafana, monitoring profile | http://localhost:3001 |
| Prometheus, monitoring profile | http://localhost:9090 |
| pgAdmin, debug profile | http://localhost:5050 |
| Redis Commander, debug profile | http://localhost:8081 |

### 5. Check Container Health

```bash
docker compose ps
```

For logs:

```bash
docker compose logs -f portfolio_server
docker compose logs -f portfolio_celery_trading
docker compose logs -f portfolio_celery_nse_pipeline
docker compose logs -f auth_server
```

## Local Development Without Full Docker

Use this path only when actively editing a service and PostgreSQL, Redis, and Kafka are already running.

Start app servers:

```bash
pnpm dev
```

Start Celery workers:

```bash
pnpm celery
```

Open Prisma/Kafka tools:

```bash
pnpm studio
```

Run checks:

```bash
pnpm lint
pnpm check-types
pnpm test
```

Portfolio-server tests:

```bash
cd apps/portfolio-server
pnpm test
```

Auth-server tests:

```bash
cd apps/auth_server
pnpm test
```

## Important Backend Flows to Study

If you are learning the codebase, use this order:

1. `apps/auth_server/server.ts`
   - authentication, Express middleware, Prisma access

2. `shared/prisma/schema.prisma`
   - users, portfolios, agents, trades, positions

3. `apps/portfolio-server/main.py`
   - FastAPI app startup, route registration, pipeline startup behavior

4. `apps/portfolio-server/workers/pipeline_tasks.py`
   - Celery task entrypoints

5. `apps/portfolio-server/services/pipeline_service.py`
   - portfolio automation orchestration

6. `apps/portfolio-server/services/trade_sizing_service.py`
   - deterministic trade sizing

7. `apps/portfolio-server/services/trade_execution_service.py`
   - persistence, execution, cash checks, positions, P&L

8. `apps/portfolio-server/pipelines/nse/bse_scraper.py`
   - current exchange announcement ingestion

9. `apps/portfolio-server/pipelines/nse/bse_sentiment.py`
   - LLM-based signal generation for relevant filings

10. `apps/notification_server/src`
    - Kafka notification consumption

## Common Commands

```bash
# Start everything
docker compose up -d

# Stop everything
docker compose down

# Rebuild after dependency or Dockerfile changes
docker compose build

# Show status
docker compose ps

# Follow all logs
docker compose logs -f

# Run monorepo dev servers
pnpm dev

# Run all configured Celery workers locally
pnpm celery

# Format TypeScript/Markdown
pnpm format
```

## Key Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [NSE / automated trading docs](docs/NSE_AUTOMATED_TRADING.md)
- [Current NSE/BSE pipeline context](.codex/NSE_PIPELINE_CONTEXT.md)
- [Angel One setup](docs/ANGELONE_SETUP.md)

## Safety Notes

- Keep paper trading enabled by default during development.
- Do not commit real broker, database, JWT, SendGrid, or LLM secrets.
- Treat exchange filings and LLM output as inputs for review, not guaranteed truth.
- Verify all trading changes with tests and paper execution before considering live mode.
- This project is for research and controlled demonstrations unless production controls are added and reviewed.

## License

Proprietary and confidential unless stated otherwise by the project owner.
