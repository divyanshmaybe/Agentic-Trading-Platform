# Docker Manifests

This directory contains Docker-specific configuration files that are completely independent from Kubernetes manifests.

## Purpose

- **Separation of Concerns**: Docker and Kubernetes have different deployment requirements
- **Independent Evolution**: Docker configs can change without affecting K8s deployments
- **Local Development**: Mirrors the local dev distributed queue architecture

## Files

- `prometheus.yml` - Prometheus scraping configuration for Docker services
- `loki-config.yml` - Loki log aggregation configuration
- `promtail-config.yml` - Promtail log shipping configuration

## Architecture

The Docker setup uses **distributed Celery workers** matching local development:

1. **Trading Worker** (`-Q trading`) - Real-time trade execution (4 workers, priority=9)
2. **Pipeline Worker** (`-Q pipelines`) - NSE filings sentiment pipeline (2 workers)
3. **Allocation Worker** (`-Q allocations`) - Portfolio allocation & rebalancing (2 workers)
4. **Market Worker** (`-Q market,tokens`) - Market data & token management (4 workers)
5. **General Worker** (`-Q general,risk,orders`) - Misc tasks (4 workers)
6. **Streaming Worker** (`-Q streaming`) - Long-running streaming tasks (1 worker)

Each worker has its own Prometheus metrics port (9101-9106).
