# Agentic Trading Platform
[![Pathway](https://img.shields.io/badge/streaming-Pathway-5b4bff)](https://pathway.com)
[![Docker](https://img.shields.io/badge/containerized-Docker-2496ed)](https://docker.com)
[![Next.js](https://img.shields.io/badge/frontend-Next.js-black)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/api-FastAPI-05998b)](https://fastapi.tiangolo.com)
[![Celery](https://img.shields.io/badge/workers-Celery-37814a)](https://docs.celeryproject.org)
[![Kafka](https://img.shields.io/badge/event%20bus-Kafka-000000)](https://kafka.apache.org)

An institutional-grade multi-agent investment platform that orchestrates autonomous financial agents for real-time portfolio automation. Built with Pathway's streaming data processing framework, the platform synthesizes regulatory filings, market microstructure, and quantitative signals through a coordinated ecosystem of specialized agents.

**Production URLs**
- Frontend: https://agentinvest.space
- Grafana: https://grafana.agentinvest.space
- Prometheus: https://prometheus.agentinvest.space
- Flower (Celery): https://flower.agentinvest.space

**Access (admin user for both Grafana & Flower)**
- Grafana: user `admin` / pass `agentinvest-pathway`
- Flower: user `admin` / pass `admin123`

**Demo testing accounts** (restricted; for QA only)
- user1@demo.com / User1DemoPassword1@3$
- user2@demo.com / User2DemoPassword##2@!
- user3@demo.com / User3!!Pass#$%#word

## 🏗️ Architecture Overview

The platform implements a hierarchical agent architecture with specialized components:

- **AlphaCopilot Agent**: AI-powered hypothesis generation and backtesting system that continuously scans for new alpha sources.
- **Fund Allocator**: Central agent routing capital according to client objectives and risk limits.
- **Strategic Agents**: Long-horizon optimizers maintaining portfolio alignment with investment mandates.
- **Trading Agents**: Short-term agents processing NSE filings with LLM reasoning and quantitative signals.
- **Execution Pipeline**: Automated trade execution with real-time risk monitoring, compliance checks, and smart order routing.

The system is powered by several dedicated pipelines:
- **NSE Pipeline**: Processes regulatory filings in real-time to generate trading signals based on sentiment and fundamental analysis.
- **Low Risk Pipeline**: Monitors conservative assets and executes low-volatility strategies for capital preservation.
- **Regime Detection Pipeline**: Analyzes market conditions to dynamically adjust strategy parameters based on the current market regime (bull, bear, volatile).
- **Real-time Monitoring**: A dedicated risk engine that tracks positions tick-by-tick, automatically triggering Take Profit (TP), Stop Loss (SL), or emergency auto-sell protocols if risk thresholds are breached.


All agents communicate through Kafka event streams and are monitored via Prometheus/Grafana for production observability.

### System Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Portfolio Server** | FastAPI + Pathway | Risk monitoring, trade execution, Pathway pipelines |
| **Auth Server** | Express.js + Prisma | Identity management, subscriptions, email workflows |
| **Notification Server** | Node.js + Kafka | Real-time notification ingestion and distribution |
| **AlphaCopilot Server** | FastAPI + Quant-Stream | AI hypothesis generation and backtesting |
| **Frontend** | Next.js + TypeScript | Investor analytics, signal visualization, admin tools |
| **Celery Workers** | Python | Async task processing, pipeline execution |
| **Kafka** | Apache Kafka 3.8.0 | Event streaming and inter-service communication |
| **PostgreSQL** | PostgreSQL 16 | Relational data storage |
| **Redis** | Redis 7 | Caching, session storage, task queuing |

## 📚 Documentation

- **[Complete Documentation](docs/README.md)** - Comprehensive platform documentation
- **[Architecture Overview](docs/ARCHITECTURE.md)** - System design and data flows
- **[NSE Automated Trading](docs/NSE_AUTOMATED_TRADING.md)** - Filings-driven trading stack
- **[Angel One Setup](docs/ANGELONE_SETUP.md)** - Broker integration guide

## 🏗️ Monorepo Structure
```
├── apps/
│   ├── portfolio-server/     # FastAPI service with Pathway pipelines
│   ├── auth_server/          # Express.js authentication & email service
│   ├── notification-server/  # Node.js Kafka consumer for real-time notifications
│   ├── alphacopilot-server/  # FastAPI AI hypothesis generation and backtesting
│   └── frontend/             # Next.js investor dashboard
├── quant-stream/             # Quantitative analysis library for strategy development
├── shared/                   # Cross-language utilities (Python/TypeScript)
├── pw-scripts/               # Research-grade Pathway pipelines
├── devops/                   # Kubernetes manifests & Terraform
├── docker-manifest/          # Docker Compose configurations and container orchestration
├── packages/                 # Reusable TypeScript toolchain
└── scripts/                  # Automation helpers
```

## 🚀 Quick Start

### Prerequisites

- **Docker & Docker Compose** (v20.10+)
- **Node.js 18+** and **pnpm** (v9.0+)
- **Python 3.10+**
- **PostgreSQL 16** and **Redis 7**

---

## 🐳 Option 1: Docker Setup (Recommended)

Docker setup provides a fully containerized environment with all services, databases, and monitoring stack.

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/Agentic-Trading-Platform-Pathway.git
cd Agentic-Trading-Platform-Pathway
```

### 2. Configure Environment

Create environment files for each service. See `.env.example` files in respective service directories:

```bash
# Root level docker.env
cp docker.env.example docker.env

# Service-specific configurations
cp apps/portfolio-server/docker.env.example apps/portfolio-server/docker.env
cp apps/auth_server/docker.env.example apps/auth_server/docker.env
cp apps/alphacopilot-server/docker.env.example apps/alphacopilot-server/docker.env
cp apps/notification_server/.env.example apps/notification_server/.env
cp apps/frontend/.env.example apps/frontend/.env
cp shared/prisma/.env.example shared/prisma/.env
cp quant-stream/alphacopilot/.env.example quant-stream/alphacopilot/.env
```

Edit these files with your:
- API keys (Gemini, NewsAPI, broker APIs)
- Database credentials
- Email service credentials (SendGrid)
- JWT secrets
- Optional pipeline/risk/observability toggles live in `apps/portfolio-server/.env.example` (news & NSE pipelines, auto-sell queues, monitoring, market-data aliases). Keep defaults unless enabling those features.

**API keys to gather (with links)**
- Google Gemini: https://aistudio.google.com/app/apikey
- LangSmith (tracing): https://smith.langchain.com/ → Settings → API keys
- Angel One SmartAPI (broker): https://smartapi.angelone.in/ → My Apps (get API key), client code/password/TOTP
- Groww API (broker access): https://groww.in → Developer/Broker portal (obtain client API credentials and TOTP)
- NewsAPI/NewsOrg: https://newsapi.org/
- SendGrid (email): https://app.sendgrid.com/settings/api_keys

### 3. Start All Services

```bash
# Start all services with monitoring stack (Recommended)
./docker.sh start

# Or start without monitoring
./docker.sh start --without-monitoring
```

**What this does:**
- Builds all Docker images (first run)
- Starts PostgreSQL, Redis, Kafka
- Launches all application servers (Auth, Portfolio, Notification, AlphaCopilot, Frontend)
- Starts Celery workers for all queues
- Initializes Prometheus, Grafana, and Loki (with monitoring profile)

### 4. Monitor Logs

```bash
# View logs from all containers
./docker.sh logs -f

# Or use the pnpm command for organized logs
pnpm docker-logs
```

### 5. Access Services

| Service | URL | Description |
|---------|-----|-------------|
| **Frontend** | http://localhost:3000 | Main application UI |
| **Auth Server** | http://localhost:4000 | Authentication API |
| **Portfolio Server** | http://localhost:8000 | Trading & Portfolio API |
| **Notification Server** | http://localhost:8099 | Notification ingestion |
| **AlphaCopilot Server** | http://localhost:8069 | AI Copilot API |
| **Flower** | http://localhost:5555 | Celery task monitoring |
| **Grafana** | http://localhost:3001 | Monitoring dashboards (admin/admin) |
| **Prometheus** | http://localhost:9090 | Metrics collection |

### 6. Other Docker Commands

```bash
# Stop all services
./docker.sh stop

# Restart all services
./docker.sh restart

# Rebuild images (after code changes)
./docker.sh build
./docker.sh build --no-cache  # Force complete rebuild

# View service status
./docker.sh status

# Clean Redis locks and timestamps
./docker.sh clean-redis

# Complete cleanup (removes all data volumes)
./docker.sh clean

# Start/stop monitoring stack separately
./docker.sh monitoring start
./docker.sh monitoring stop
```

---

## 💻 Option 2: Local Development Setup

For active development with hot-reloading and direct debugging.

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/Agentic-Trading-Platform-Pathway.git
cd Agentic-Trading-Platform-Pathway
```

### 2. Install Dependencies

```bash
# Install Node.js dependencies
pnpm install

# Install Python dependencies (recommended: use virtualenv)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Install quant-stream library
cd quant-stream
pip install -e .
cd ..
```

### 3. Setup Infrastructure

Run the setup script to initialize Kafka and databases:

```bash
# Setup all infrastructure (Kafka, PostgreSQL, Redis, Monitoring)
./setup.sh all

# Or setup individual components
./setup.sh kafka      # Start Kafka only
./setup.sh postgres   # Start PostgreSQL only
./setup.sh redis      # Start Redis only
./setup.sh monitoring # Start Prometheus, Grafana, Loki
```
### 4. Setup PostgreSQL and Redis with Docker

```bash
# Start PostgreSQL and Redis containers
docker-compose up -d postgres portfolio_postgres redis portfolio_redis

# Verify databases are running
docker ps | grep -E "postgres|redis"
```

**Database URLs:**
- Auth DB: `postgresql://auth_user:auth_password@localhost:5432/auth_db`
- Portfolio DB: `postgresql://portfolio_user:portfolio_password@localhost:5434/portfolio_db`

**Redis URLs:**
- Auth Redis: `redis://localhost:6379`
- Portfolio Redis: `redis://localhost:6381`

### 5. Configure Environment Variables

Create `.env` files in each service directory:

#### Auth Server (`apps/auth_server/.env`)
```env
NODE_ENV=development
PORT=4000
DATABASE_URL=postgresql://auth_user:auth_password@localhost:5432/auth_db
SHADOW_DATABASE_URL=postgresql://auth_user:auth_password@localhost:5432/auth_db_shadow
JWT_SECRET_ACCESS=your-secret-access-key
JWT_SECRET_REFRESH=your-secret-refresh-key
JWT_SECRET_EMAIL=your-secret-email-key
INTERNAL_SERVICE_SECRET=your-internal-secret
CLIENT_URL=http://localhost:3000
AUTH_SERVER_URL=http://localhost:4000
SENDGRID_API_KEY=your-sendgrid-key
SENDER_EMAIL_ADDRESS=your-sender-email
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_URL=redis://localhost:6379
```

#### Portfolio Server (`apps/portfolio-server/.env`)
```env
PORT=8000
DATABASE_URL=postgresql://portfolio_user:portfolio_password@localhost:5434/portfolio_db
INTERNAL_SERVICE_SECRET=your-internal-secret
GEMINI_API_KEY=your-gemini-api-key
NEWSAPI_KEY=your-newsapi-key
REDIS_HOST=localhost
REDIS_PORT=6381
CELERY_BROKER_URL=redis://localhost:6381/0
CELERY_RESULT_BACKEND=redis://localhost:6381/1
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
MARKET_DATA_PROVIDER=angelone
ANGEL_ONE_API_KEY=your-angelone-key
ANGEL_ONE_CLIENT_CODE=your-client-code
ANGEL_ONE_PASSWORD=your-password
ANGEL_ONE_TOTP_SECRET=your-totp-secret
```

#### Frontend (`apps/frontend/.env`)
```env
NEXT_PUBLIC_AUTH_SERVER_URL=http://localhost:4000
NEXT_PUBLIC_PORTFOLIO_SERVER_URL=http://localhost:8000
NEXT_PUBLIC_KAFKA_BOOTSTRAP_SERVERS=localhost:9092
```

#### AlphaCopilot Server (`apps/alphacopilot-server/.env`)
```env
PORT=8069
HOST=0.0.0.0
DATABASE_URL=postgresql://portfolio_user:portfolio_password@localhost:5434/portfolio_db
REDIS_URL=redis://localhost:6381
CELERY_BROKER_URL=redis://localhost:6381/0
CELERY_RESULT_BACKEND=redis://localhost:6381/1
MLFLOW_TRACKING_URI=./mlruns
INTERNAL_SERVICE_SECRET=your-internal-secret
```

### 6. Run Database Migrations

```bash
# Auth Server (uses shared Prisma schema)
cd apps/auth_server
pnpm prisma:generate
pnpm prisma:migrate
cd ../..

# Portfolio Server
cd apps/portfolio-server
prisma generate
prisma db push
cd ../..

### 7. Start Services

Open multiple terminal windows/tabs:

#### Terminal 1: Celery Workers
```bash
pnpm celery
```

This starts all Celery workers:
- Trading agent worker
- NSE filings worker
- News sentiment worker
- Low-risk alerts worker
- Portfolio allocation worker
- Market data worker
- General worker
- Streaming risk monitor
- Regime detection worker
- Celery beat scheduler
- Order execution worker

#### Terminal 2: Development Servers
```bash
pnpm dev
```

This starts:
- Frontend (Next.js) on port 3000
- Auth Server (Express) on port 4000
- Portfolio Server (FastAPI) on port 8000
- Notification Server on port 8099
- AlphaCopilot Server on port 8069

#### Terminal 3: Prisma Studio & Kafka UI (Optional)
```bash
pnpm studio
```

Opens Prisma Studio for database inspection and Kafka UI for stream monitoring:
- Auth DB: http://localhost:5555
- Portfolio DB: http://localhost:5556
- Kafka UI: http://localhost:8501/

---


## 📊 Monitoring & Observability

The platform includes comprehensive monitoring with Prometheus, Grafana, and Loki.

### Accessing Grafana

1. Start monitoring stack:
   ```bash
   ./docker.sh monitoring start
   # Or with ./setup.sh
   ./setup.sh monitoring
   ```

2. Access Grafana at http://localhost:3001
   - Default credentials: `admin` / `admin`

### Available Dashboards

Our Grafana setup includes pre-configured dashboards for:

#### 1. **Celery Workers Dashboard**
- Task execution metrics (success/failure rates)
- Queue lengths and processing times
- Worker health and utilization
- Task distribution across queues

#### 2. **Portfolio Server Dashboard**
- API request rates and latencies
- Trade execution metrics (success/failure)
- Position monitoring alerts
- Database query performance
- Python process metrics (memory, CPU)

#### 3. **Auth Server Dashboard**
- Authentication flow metrics
- API endpoint performance
- Session management statistics
- Node.js runtime metrics (event loop lag, memory)

#### 4. **AlphaCopilot Dashboard**
- Backtest execution metrics
- Hypothesis generation rates
- Model training statistics
- Resource utilization

#### 5. **Notification Server Dashboard**
- Kafka consumption rates
- Redis pub/sub metrics
- Notification delivery statistics

#### 6. **Trading KPIs Dashboard**
- Real-time P&L tracking
- Win rate and Sharpe ratios
- Position distribution
- Risk metrics and drawdowns

### Prometheus Metrics

Access raw metrics at:
- Portfolio Server: http://localhost:8000/metrics
- Auth Server: http://localhost:4000/metrics
- AlphaCopilot Server: http://localhost:8069/metrics
- Notification Server: http://localhost:9201/metrics
- Celery Workers: http://localhost:9808/metrics
- Prometheus UI: http://localhost:9090

---

## 🔧 Development Workflow

### Kafka Topic Management

```bash
# List all topics
docker exec pathway-kafka kafka-topics.sh \
  --bootstrap-server localhost:9092 --list

# View messages from a topic
docker exec pathway-kafka kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic nse_pipeline_trade_logs \
  --from-beginning

# Key topics:
# - nse_pipeline_trade_logs: Automated trade execution logs
# - nse_filings_trading_signal: NSE filing sentiment signals
# - news_pipeline_stock_recomendations: AI stock recommendations
# - risk_agent_alerts: Portfolio risk alerts
```

### Running Tests

```bash
# Portfolio Server tests
cd apps/portfolio-server
pytest tests/ -v --cov

# Auth Server tests
cd apps/auth_server
pnpm test

# Frontend tests
cd apps/frontend
pnpm test
```

### Code Quality

```bash
# Format code
pnpm format

# Lint all projects
pnpm lint

# Type checking
pnpm check-types
```

---

// ...existing code...
## 🌐 Current Deployment

The platform is currently deployed on a cloud VM for production use.

### Production Access

**Note:** Access credentials and endpoints are provided separately to authorized users.

- **Frontend Application**: https://agentinvest.space
- **API Gateway**: Protected by JWT authentication (same domain)
- **Monitoring Dashboard**: https://grafana.agentinvest.space
- **Prometheus**: https://prometheus.agentinvest.space
- **Celery/Flower**: https://flower.agentinvest.space
- **Credentials (admin user)**
  - Grafana: `admin` / `agentinvest-pathway`
  - Flower: `admin` / `admin123`

### Access Restrictions

For testing and demonstration purposes, the platform currently has **restricted access** with three hardcoded user accounts. This limitation exists due to:
// ...existing code...

- Limited availability of LLM API tokens
- Controlled testing environment
- Resource optimization

**Testing accounts (demo only):**
- user1@demo.com / User1DemoPassword1@3$
- user2@demo.com / User2DemoPassword##2@!
- user3@demo.com / User3!!Pass#$%#word

**Production credentials will be provided separately to authorized users.**

---

## 🚢 Deployment Options

### Docker Production Deployment

```bash
# Build and push images to registry
./build-and-push.sh

# Deploy with production compose file
./docker-prod.sh start
```

### Kubernetes Deployment (Future Scope)

Complete Kubernetes manifests are available in the `devops/kubernetes/` directory for future production deployments:

- Deployment configurations for all services
- Service mesh setup with Istio
- Horizontal Pod Autoscaling (HPA)
- Persistent volume claims for databases
- ConfigMaps and Secrets management
- Ingress configurations with TLS

**Note:** Kubernetes deployment is planned for future scaling requirements. Current production deployment uses Docker Compose on cloud VMs.

---

## 🔒 Security & Compliance

- **Data Encryption**: All sensitive data encrypted at rest and in transit
- **API Authentication**: JWT-based authentication with role-based access control
- **Audit Logging**: Comprehensive logging of all trading activities
- **Regulatory Compliance**: Built-in compliance checks for Indian market regulations
- **Secret Management**: Environment-based configuration with secure secret storage

---

## 📄 License

This project is proprietary and confidential. All rights reserved.

---

## 🙏 Acknowledgments

- **Pathway** for the streaming data processing framework
- **Angel One** for market data and trading APIs
- **NSE** for regulatory filings data
- **Open source community** for the foundational libraries and tools

---

**Built with ❤️ for modern algorithmic trading**
