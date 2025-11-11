# AgentInvest Platform

AgentInvest is a multi-service platform for automated portfolio management, risk monitoring, and trade execution across Indian markets. The monorepo houses backend services, frontend applications, shared tooling, and deployment assets used to run the production stack.

## Directory Guide

- `apps/portfolio-server` – FastAPI service orchestrating Pathway pipelines, market data ingestion, trading workflows, and Celery workers.
- `apps/auth_server` – Node.js authentication service with Prisma, BullMQ, and email delivery flow for user onboarding.
- `apps/frontend` – Next.js dashboard and landing experience for investors and administrators.
- `shared/` – Cross-service libraries for Python and TypeScript (Kafka, market data, email, database utilities).
- `pw-scripts/` – Standalone Pathway scripts for risk, news sentiment, and NSE filings research workflows.
- `docs/` – Architectural references, integration guides, and operational playbooks.
- `devops/` – Kubernetes manifests, ArgoCD configs, and infrastructure-as-code for cloud deployment.
- `packages/` – Shared TypeScript tooling (ESLint presets, tsconfig, UI kit) consumed by the monorepo.
- `scripts/` – Operational helpers for token generation, migrations, and automation tasks.

## Getting Started

Refer to `docs/ARCHITECTURE.md` for system design context and service-level READMEs under each app for setup specifics. Use `pnpm install` at the workspace root to install dependencies before working with individual services. 
