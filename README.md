# AgentInvest Platform
[![Pathway](https://img.shields.io/badge/streaming-Pathway-5b4bff)](https://pathway.com)
[![Docker](https://img.shields.io/badge/containerized-Docker-2496ed)](https://docker.com)
[![Next.js](https://img.shields.io/badge/frontend-Next.js-black)](https://nextjs.org)
[![FastAPI](https://img.shields.io/badge/api-FastAPI-05998b)](https://fastapi.tiangolo.com)
[![Celery](https://img.shields.io/badge/workers-Celery-37814a)](https://docs.celeryproject.org)
[![Kafka](https://img.shields.io/badge/event%20bus-Kafka-000000)](https://kafka.apache.org)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**AgentInvest** is an institutional-grade multi-agent investment platform that orchestrates autonomous financial agents for real-time portfolio automation. Built for modern wealth management teams, it synthesizes regulatory filings, market microstructure, and client preferences through a coordinated ecosystem of specialized agents.

## Architecture Overview

The platform implements a hierarchical agent architecture:

- **Fund Allocator**: Central agent that routes capital according to client objectives and risk limits
- **Strategic Agents**: Long-horizon optimizers maintaining portfolio alignment with investment mandates
- **Trading Agents**: Short-term agents processing NSE filings with LLM reasoning and quantitative signals
- **Execution Pipeline**: Automated trade execution with real-time risk monitoring and compliance

Powered by Pathway's low-latency ETL core, the system streams market data, regulatory events, and model outputs to ensure allocations, orders, and compliance artifacts remain explainable, auditable, and personalized.

## 🏗️ Monorepo Structure

```
├── apps/
│   ├── portfolio-server/     # FastAPI service with Pathway pipelines
│   ├── auth_server/         # Express.js authentication & email service
│   └── frontend/             # Next.js investor dashboard
├── shared/                   # Cross-language utilities (Python/TypeScript)
├── pw-scripts/               # Research-grade Pathway pipelines
├── devops/                   # Kubernetes manifests & Terraform
├── packages/                 # Reusable TypeScript toolchain
└── scripts/                  # Automation helpers
```

### Service Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Portfolio Server** | FastAPI + Pathway | Risk monitoring, trade execution, Prisma ORM |
| **Auth Server** | Express.js + Prisma | Identity management, subscriptions, email workflows |
| **Frontend** | Next.js + TypeScript | Investor analytics, signal visualization, admin tools |
| **Shared Libraries** | Python/TypeScript | Kafka schemas, market data adapters, DB utilities |
| **Research Pipelines** | Pathway | Risk agents, NSE filings, news sentiment analysis |

## 🚀 Quick Start

### Prerequisites

- **Docker & Docker Compose** for containerized services
- **Node.js 18+** and **pnpm** for JavaScript/TypeScript
- **Python 3.10+** with **pyenv** for Python services
- **PostgreSQL** and **Redis** databases

### 1. Environment Setup

```bash
# Clone the repository
# Replace YOUR_GITHUB_USERNAME with your GitHub username
git clone https://github.com/YOUR_GITHUB_USERNAME/Agentic-Trading-Platform-Pathway.git
cd Agentic-Trading-Platform-Pathway

# Install JavaScript dependencies
pnpm install

# Set up Python environments
pyenv install 3.10.14
pyenv local 3.10.14
```

### 2. Start Infrastructure

```bash
# Start Kafka (required for event streaming)
./kafka.sh

# Start PostgreSQL and Redis (via Docker Compose)
docker-compose up -d postgres redis
```

The `kafka.sh` script launches Apache Kafka 3.8.0 in KRaft mode (no ZooKeeper) on port 9092. See the [Kafka Management](#kafka-management) section for details.

### 3. Configure Environment

Create `.env` files in each service directory with required credentials:

```bash
# Database connections, API keys, broker credentials
# See individual service READMEs for complete configuration
```

## 📋 Service Configuration

### Portfolio Server (`apps/portfolio-server`)

**Technology Stack**: FastAPI, Pathway, Prisma, Celery, Kafka

```bash
cd apps/portfolio-server

# Install dependencies
pip install -r requirements.txt

# Database setup
prisma db push && prisma generate

# Start API server
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Start Celery workers
celery -A celery_app:celery_app worker -l info

# Start pipeline scheduler
celery -A celery_app:celery_app beat -l info
```

**Key Features**:
- Real-time NSE filings processing
- Automated trade execution with TP/SL orders
- Portfolio risk monitoring
- Kafka event streaming

### Auth Server (`apps/auth_server`)

**Technology Stack**: Express.js, Prisma, BullMQ, SendGrid

```bash
# Install and setup
pnpm --filter auth_server install
pnpm --filter auth_server prisma:migrate
pnpm --filter auth_server prisma:generate

# Start development server
pnpm --filter auth_server dev

# Start email worker
pnpm --filter auth_server tsx workers/emailWorker.ts
```

**Key Features**:
- User authentication & authorization
- Subscription management
- Email notifications & templates
- API rate limiting

### Frontend (`apps/frontend`)

**Technology Stack**: Next.js, TypeScript, Tailwind CSS

```bash
# Install and start
pnpm --filter frontend install
pnpm --filter frontend dev  # → http://localhost:3000
```

**Key Features**:
- Real-time portfolio analytics
- Trading signal visualization
- Administrative controls
- Responsive design

## 🔧 Development Workflow

### Kafka Management

The platform uses Apache Kafka for event-driven communication between microservices. A convenience script (`kafka.sh`) is provided to launch Kafka locally using Docker with KRaft mode (no ZooKeeper required).

#### Starting Kafka

```bash
# Start Kafka container (Apache Kafka 3.8.0 in KRaft mode)
./kafka.sh
```

**What the script does**:
- Pulls the official Apache Kafka 3.8.0 Docker image
- Removes any existing `pathway-kafka` container
- Starts Kafka on `localhost:9092` with auto-topic creation enabled
- Uses KRaft consensus protocol (eliminates ZooKeeper dependency)
- Configures single-node cluster suitable for local development

#### Managing Kafka

```bash
# Monitor Kafka logs
docker logs -f pathway-kafka

# List all topics
docker exec pathway-kafka kafka-topics.sh --bootstrap-server localhost:9092 --list

# Describe a specific topic
docker exec pathway-kafka kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic nse_pipeline_trade_logs

# Consume messages from a topic (for debugging)
docker exec pathway-kafka kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic nse_pipeline_trade_logs --from-beginning
```

#### Key Kafka Topics

| Topic | Purpose | Producer | Consumer |
|-------|---------|----------|----------|
| `nse_pipeline_trade_logs` | NSE automated trade execution events | Portfolio Server | Trade Workers, Analytics |
| `nse_filings_trading_signal` | NSE filing sentiment signals | NSE Filings Pipeline | Portfolio Server |
| `news_pipeline_stock_recomendations` | Stock recommendations from news | News Pipeline | Portfolio Server |
| `news_pipeline_sentiment_articles` | News sentiment analysis | News Pipeline | Analytics |
| `news_pipeline_sector_analysis` | Sector-level news analysis | News Pipeline | Analytics |
| `risk_agent_alerts` | Portfolio risk alerts | Risk Monitor | Notification Service |

**Monitoring Topics**: Use the `subscriber.sh` script to monitor any topic in real-time:

```bash
# Monitor NSE trading signals
./subscriber.sh --channel nse_filings_trading_signal --from-beginning

# Monitor trade execution logs
./subscriber.sh --channel nse_pipeline_trade_logs --from-beginning

# Monitor news recommendations
./subscriber.sh --channel news_pipeline_stock_recomendations --from-beginning
```

### Database Migrations

```bash
# Auth server migrations (schema located in shared/prisma/)
pnpm --filter auth_server prisma:migrate

# Portfolio server schema updates
cd apps/portfolio-server && prisma db push
```

## 🧪 Testing

```bash
# Run portfolio server tests (requires DATABASE_URL in .env)
cd apps/portfolio-server && pytest tests/ -v

# Run NSE automation demo in dry-run mode
python tests/demo_nse_automation.py --dry-run
```

See individual service READMEs for comprehensive testing documentation.

## 📚 Documentation

- **[Architecture Overview](docs/ARCHITECTURE.md)** - System design and data flows
- **[NSE Automated Trading](docs/NSE_AUTOMATED_TRADING.md)** - Filings-driven trading stack
- **[API Documentation](apps/portfolio-server/README.md)** - Portfolio service endpoints
- **[Deployment Guide](devops/README.md)** - Kubernetes and cloud deployment

## 🔒 Security & Compliance

- **Data Encryption**: All sensitive data encrypted at rest and in transit
- **API Authentication**: JWT-based authentication with role-based access control
- **Audit Logging**: Comprehensive logging of all trading activities
- **Regulatory Compliance**: Built-in compliance checks for Indian market regulations

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Standards

- **Code Quality**: ESLint, Prettier, Black, and MyPy enforced
- **Testing**: Minimum 80% test coverage required
- **Documentation**: All public APIs must be documented
- **Security**: Regular dependency updates and security audits

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Pathway** for the streaming data processing framework
- **Angel One** for market data and trading APIs
- **NSE** for regulatory filings data
- **Open source community** for the foundational libraries and tools

---

**AgentInvest Platform** - Democratizing institutional-grade investment automation for wealth management teams worldwide.
