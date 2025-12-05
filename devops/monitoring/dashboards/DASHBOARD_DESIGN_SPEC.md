# Prometheus + Grafana Dashboard Design Specification

This document provides the complete dashboard design for the four trading platform services.

---

## 1. auth_server Dashboard

**Service**: Express.js on port 4000, `/metrics` via prom-client  
**UID**: `auth-server-dashboard`

### Row 1: Auth API Health

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 1 | **Request Rate** | Total HTTP requests/sec across all endpoints | `sum(rate(http_requests_total{job="auth_server"}[5m]))` | Stat | Green |
| 2 | **Error Rate (4xx/5xx)** | Percentage of failed requests | `sum(rate(http_requests_total{job="auth_server",status_code=~"4..|5.."}[5m])) / sum(rate(http_requests_total{job="auth_server"}[5m])) * 100` | Gauge | <1% Green, 1-5% Yellow, >5% Red |
| 3 | **In-Flight Requests** | Currently processing requests | `sum(http_requests_in_progress{job="auth_server"})` | Stat | <50 Green, 50-100 Yellow, >100 Red |
| 4 | **P95 Latency (All Endpoints)** | 95th percentile response time | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="auth_server"}[5m])) by (le))` | Gauge | <200ms Green, 200-500ms Yellow, >500ms Red |

### Row 2: Login & Token Validation

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 5 | **Login Requests/sec** | Rate of login attempts | `sum(rate(http_requests_total{job="auth_server",endpoint="/api/auth/login",method="POST"}[5m]))` | Timeseries | - |
| 6 | **Login P95 Latency** | 95th percentile login latency | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="auth_server",endpoint="/api/auth/login",method="POST"}[5m])) by (le))` | Gauge | <300ms Green, 300-800ms Yellow, >800ms Red |
| 7 | **Login P99 Latency** | 99th percentile login latency | `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{job="auth_server",endpoint="/api/auth/login",method="POST"}[5m])) by (le))` | Gauge | <500ms Green, 500-1s Yellow, >1s Red |
| 8 | **Login Success vs Failure** | Login success/failure breakdown | `sum by (status_code) (rate(http_requests_total{job="auth_server",endpoint="/api/auth/login",method="POST"}[5m]))` | Timeseries (stacked) | - |
| 9 | **Token Validation Requests/sec** | Rate of internal token validation | `sum(rate(http_requests_total{job="auth_server",endpoint="/api/internal/validate-token",method="POST"}[5m]))` | Timeseries | - |
| 10 | **Token Validation P95 Latency** | 95th percentile validate-token latency | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="auth_server",endpoint="/api/internal/validate-token",method="POST"}[5m])) by (le))` | Gauge | <50ms Green, 50-150ms Yellow, >150ms Red |

### Row 3: Password & Email Flows

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 11 | **Password Reset Requests/sec** | Rate of password reset requests | `sum(rate(http_requests_total{job="auth_server",endpoint="/api/auth/request-password-mail",method="POST"}[5m]))` | Timeseries | - |
| 12 | **4xx/5xx by Endpoint** | Error breakdown by endpoint | `sum by (endpoint, status_code) (rate(http_requests_total{job="auth_server",status_code=~"4..|5.."}[5m]))` | Table | - |

#### Suggested Custom Metric for Email Queue

Add to auth_server's `prometheusMetrics.ts`:

```typescript
export const authPasswordEmailsTotal = new client.Counter({
  name: "auth_password_emails_total",
  help: "Total password reset emails queued",
  labelNames: ["status"], // "queued", "sent", "failed"
  registers: [register],
});
```

Then add panel:
| 13 | **Password Emails Queued** | Emails sent via BullMQ | `sum by (status) (rate(auth_password_emails_total{job="auth_server"}[5m]))` | Timeseries | - |

---

## 2. notification_server Dashboard

**Service**: Node.js Kafka consumer, no HTTP  
**UID**: `notification-server-dashboard`

### Metrics to Instrument

Add a new file `apps/notification_server/src/metrics.ts`:

```typescript
import client from "prom-client";
import http from "http";

export const register = new client.Registry();
client.collectDefaultMetrics({ register });

// Kafka consumption metrics
export const notificationKafkaMessagesTotal = new client.Counter({
  name: "notification_kafka_messages_total",
  help: "Total Kafka messages consumed",
  labelNames: ["topic", "status"], // status: "processed", "failed", "skipped"
  registers: [register],
});

export const notificationKafkaLag = new client.Gauge({
  name: "notification_kafka_lag",
  help: "Consumer lag by topic and partition",
  labelNames: ["topic", "partition"],
  registers: [register],
});

export const notificationProcessingDurationSeconds = new client.Histogram({
  name: "notification_processing_duration_seconds",
  help: "Time to process a Kafka message",
  labelNames: ["topic"],
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
  registers: [register],
});

// Delivery metrics
export const notificationDeliveryTotal = new client.Counter({
  name: "notification_delivery_total",
  help: "Notifications delivered by channel",
  labelNames: ["channel", "status"], // channel: "redis", "postgres"; status: "success", "failed"
  registers: [register],
});

export const notificationErrorsTotal = new client.Counter({
  name: "notification_errors_total",
  help: "Total notification processing errors",
  labelNames: ["topic", "error_type"], // error_type: "parse_error", "db_error", "redis_error"
  registers: [register],
});

// Low-risk event metrics
export const notificationLowRiskEventsTotal = new client.Counter({
  name: "notification_low_risk_events_total",
  help: "Low-risk events processed",
  labelNames: ["event_type", "status"],
  registers: [register],
});

// Batch processing metrics
export const notificationBatchSize = new client.Histogram({
  name: "notification_batch_size",
  help: "Size of processed message batches",
  labelNames: ["topic"],
  buckets: [1, 5, 10, 25, 50, 100, 250, 500],
  registers: [register],
});

// Start metrics HTTP server on port 9101
export function startMetricsServer(port: number = 9101): void {
  const server = http.createServer(async (req, res) => {
    if (req.url === "/metrics") {
      res.setHeader("Content-Type", register.contentType);
      res.end(await register.metrics());
    } else {
      res.statusCode = 404;
      res.end("Not Found");
    }
  });
  server.listen(port, () => console.log(`[Metrics] Prometheus metrics on :${port}/metrics`));
}
```

### Panels

#### Row 1: Kafka Throughput

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 1 | **Messages/sec by Topic** | Kafka consumption rate per topic | `sum by (topic) (rate(notification_kafka_messages_total{job="notification_server"}[5m]))` | Timeseries | - |
| 2 | **Consumer Lag by Topic** | Current lag across partitions | `sum by (topic) (notification_kafka_lag{job="notification_server"})` | Timeseries | <1000 Green, 1000-10000 Yellow, >10000 Red |
| 3 | **Total Messages Processed (24h)** | Daily volume | `sum(increase(notification_kafka_messages_total{job="notification_server",status="processed"}[24h]))` | Stat | - |

#### Row 2: Processing Performance

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 4 | **Processing Latency P95 by Topic** | 95th percentile processing time | `histogram_quantile(0.95, sum by (topic, le) (rate(notification_processing_duration_seconds_bucket{job="notification_server"}[5m])))` | Timeseries | <500ms Green, 500ms-2s Yellow, >2s Red |
| 5 | **Processing Latency P99** | 99th percentile overall | `histogram_quantile(0.99, sum(rate(notification_processing_duration_seconds_bucket{job="notification_server"}[5m])) by (le))` | Gauge | <1s Green, 1-5s Yellow, >5s Red |
| 6 | **Batch Size Distribution** | Messages processed per batch | `histogram_quantile(0.5, sum by (topic, le) (rate(notification_batch_size_bucket{job="notification_server"}[5m])))` | Timeseries | - |

#### Row 3: Delivery & Errors

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 7 | **Delivery Success Rate** | % of successful deliveries | `sum(rate(notification_delivery_total{job="notification_server",status="success"}[5m])) / sum(rate(notification_delivery_total{job="notification_server"}[5m])) * 100` | Gauge | >99% Green, 95-99% Yellow, <95% Red |
| 8 | **Deliveries by Channel** | Redis vs Postgres write rate | `sum by (channel) (rate(notification_delivery_total{job="notification_server"}[5m]))` | Timeseries (stacked) | - |
| 9 | **Errors by Type** | Error breakdown | `sum by (error_type) (rate(notification_errors_total{job="notification_server"}[5m]))` | Timeseries | - |
| 10 | **Failed Messages by Topic** | Failed message rate per topic | `sum by (topic) (rate(notification_kafka_messages_total{job="notification_server",status="failed"}[5m]))` | Timeseries | - |

#### Row 4: Low-Risk Events

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 11 | **Low-Risk Events/sec** | Low-risk event throughput | `sum(rate(notification_low_risk_events_total{job="notification_server"}[5m]))` | Timeseries | - |
| 12 | **Low-Risk Events by Type** | Breakdown by event type | `sum by (event_type) (rate(notification_low_risk_events_total{job="notification_server"}[5m]))` | Bar chart | - |

---

## 3. portfolio_server Dashboard

**Service**: FastAPI on port 8000, `/metrics`  
**UID**: `portfolio-server-dashboard`

### Row 1: API Health

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 1 | **Request Rate** | Total HTTP requests/sec | `sum(rate(http_requests_total{job="portfolio_server"}[5m]))` | Stat | - |
| 2 | **Error Rate (4xx/5xx)** | % failed requests | `sum(rate(http_requests_total{job="portfolio_server",status_code=~"4..|5.."}[5m])) / sum(rate(http_requests_total{job="portfolio_server"}[5m])) * 100` | Gauge | <1% Green, 1-5% Yellow, >5% Red |
| 3 | **P95 API Latency** | 95th percentile response time | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="portfolio_server"}[5m])) by (le))` | Gauge | <500ms Green, 500ms-1s Yellow, >1s Red |
| 4 | **In-Flight Requests** | Currently processing | `sum(http_requests_in_progress{job="portfolio_server"})` | Stat | - |

### Row 2: Trade Execution

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 5 | **Trade Executions/sec** | Rate of trade executions | `sum(rate(portfolio_trade_executions_total{job="portfolio_server"}[5m]))` | Timeseries | - |
| 6 | **Trade Success vs Failure** | Execution status breakdown | `sum by (status) (rate(portfolio_trade_executions_total{job="portfolio_server"}[5m]))` | Timeseries (stacked) | - |
| 7 | **Trades by Strategy** | Volume per strategy | `sum by (strategy) (rate(portfolio_trade_executions_total{job="portfolio_server"}[5m]))` | Bar chart | - |
| 8 | **Trade Execution P99 Latency** | 99th percentile signal-to-execution | `histogram_quantile(0.99, sum by (le, strategy) (rate(portfolio_trade_execution_latency_seconds_bucket{job="portfolio_server"}[5m])))` | Timeseries | <10s Green, 10-60s Yellow, >60s Red |
| 9 | **Active Trades** | Trades currently processing | `sum by (queue) (portfolio_active_trades{job="portfolio_server"})` | Stat | - |
| 10 | **Trade Errors by Type** | Error breakdown | `sum by (error_type) (rate(portfolio_trade_errors_total{job="portfolio_server"}[5m]))` | Timeseries | - |

### Row 3: Pipelines & Queues

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 11 | **Pipeline Runs (Success/Failure)** | Pipeline execution status | `sum by (pipeline_type, status) (rate(portfolio_pipeline_runs_total{job="portfolio_server"}[5m]))` | Timeseries (stacked) | - |
| 12 | **Pipeline Duration P95** | 95th percentile pipeline duration | `histogram_quantile(0.95, sum by (pipeline_type, le) (rate(portfolio_pipeline_duration_seconds_bucket{job="portfolio_server"}[5m])))` | Timeseries | nse_pipeline <300s, news_pipeline <120s |
| 13 | **Pipeline Errors by Type** | Error breakdown per pipeline | `sum by (pipeline_type, error_type) (rate(portfolio_pipeline_errors_total{job="portfolio_server"}[5m]))` | Heatmap/Table | - |
| 14 | **Queue Depth** | Pending items per queue | `portfolio_queue_depth{job="portfolio_server"}` | Timeseries | <100 Green, 100-500 Yellow, >500 Red |

### Row 4: Risk & Alerts

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 15 | **Pending Risk Alerts** | Unprocessed risk alerts | `sum by (alert_type, severity) (portfolio_risk_alerts_pending{job="portfolio_server"})` | Stat/Table | 0 Green, 1-5 Yellow, >5 Red |
| 16 | **Risk Alerts Sent/sec** | Alert dispatch rate | `sum by (alert_type, channel) (rate(portfolio_risk_alerts_sent_total{job="portfolio_server"}[5m]))` | Timeseries | - |
| 17 | **Risk Alert Processing Latency** | Time to process alerts | `histogram_quantile(0.95, sum by (le) (rate(portfolio_risk_alert_processing_seconds_bucket{job="portfolio_server"}[5m])))` | Gauge | <30s Green, 30-120s Yellow, >120s Red |
| 18 | **Risk Check Failures** | Failed risk checks | `sum by (check_type) (rate(portfolio_risk_check_failures_total{job="portfolio_server"}[5m]))` | Timeseries | - |

### Row 5: Allocation & Regime

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 19 | **Allocations Performed** | Portfolio allocation count | `sum(increase(portfolio_allocations_total{job="portfolio_server"}[1h]))` | Stat | - |
| 20 | **Allocation Duration P95** | 95th percentile allocation time | `histogram_quantile(0.95, sum by (le) (rate(portfolio_allocation_duration_seconds_bucket{job="portfolio_server"}[5m])))` | Gauge | <120s Green, 120-300s Yellow, >300s Red |
| 21 | **Regime Changes** | Detected regime transitions | `sum by (from_regime, to_regime) (increase(portfolio_regime_changes_total{job="portfolio_server"}[24h]))` | Table | - |
| 22 | **Rebalances by Trigger** | Rebalancing operations | `sum by (trigger, status) (rate(portfolio_rebalances_total{job="portfolio_server"}[5m]))` | Timeseries | - |

### Row 6: Alpha Signals

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 23 | **Alpha Signals Generated** | Signal generation rate | `sum by (alpha_type, direction) (rate(portfolio_alpha_signals_total{job="portfolio_server"}[5m]))` | Timeseries | - |
| 24 | **Alpha Signal Strength Distribution** | Strength histogram | `histogram_quantile(0.5, sum by (alpha_type, le) (rate(portfolio_alpha_signal_strength_bucket{job="portfolio_server"}[5m])))` | Heatmap | - |

### Row 7: Market Data & External APIs

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 25 | **Market Data Latency P95** | Data fetch latency by source | `histogram_quantile(0.95, sum by (source, le) (rate(portfolio_market_data_latency_seconds_bucket{job="portfolio_server"}[5m])))` | Timeseries | AngelOne <2s, News <5s |
| 26 | **Market Data Errors** | Errors by source | `sum by (source, error_type) (rate(portfolio_market_data_errors_total{job="portfolio_server"}[5m]))` | Timeseries | - |
| 27 | **External API Health** | API health status | `portfolio_external_api_health{job="portfolio_server"}` | Stat (colored) | 1=Green, 0=Red |
| 28 | **DB Connections Active** | Database pool usage | `portfolio_db_connections_active{job="portfolio_server"}` | Timeseries | <80% pool Green |

---

## 4. alphacopilot_server Dashboard

**Service**: FastAPI on port 8069, `/health` only  
**UID**: `alphacopilot-server-dashboard`

### Metrics to Instrument

Add to `apps/alphacopilot-server/metrics.py`:

```python
"""Prometheus metrics for AlphaCopilot Server."""

from prometheus_client import Counter, Histogram, Gauge, Info, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

# Run metrics
alphacopilot_runs_total = Counter(
    'alphacopilot_runs_total',
    'Total AlphaCopilot workflow runs',
    ['status']  # "created", "running", "completed", "failed", "cancelled"
)

alphacopilot_run_duration_seconds = Histogram(
    'alphacopilot_run_duration_seconds',
    'Workflow run duration',
    ['workflow_type'],  # "full", "validation_only", "backtest_only"
    buckets=(10, 30, 60, 120, 300, 600, 1200, 1800, 3600)
)

alphacopilot_concurrent_runs = Gauge(
    'alphacopilot_concurrent_runs',
    'Number of concurrent workflow runs'
)

# Iteration metrics
alphacopilot_iterations_total = Counter(
    'alphacopilot_iterations_total',
    'Total workflow iterations',
    ['iteration_type', 'status']  # iteration_type: "factor_gen", "validation", "refinement"
)

alphacopilot_iteration_duration_seconds = Histogram(
    'alphacopilot_iteration_duration_seconds',
    'Duration of each iteration',
    ['iteration_type'],
    buckets=(5, 10, 30, 60, 120, 300, 600)
)

# LLM metrics
alphacopilot_llm_requests_total = Counter(
    'alphacopilot_llm_requests_total',
    'Total LLM API requests',
    ['model', 'endpoint', 'status']  # status: "success", "error", "timeout"
)

alphacopilot_llm_latency_seconds = Histogram(
    'alphacopilot_llm_latency_seconds',
    'LLM API response latency',
    ['model', 'endpoint'],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60)
)

alphacopilot_llm_tokens_total = Counter(
    'alphacopilot_llm_tokens_total',
    'Total LLM tokens used',
    ['model', 'token_type']  # token_type: "input", "output"
)

# Factor validation metrics
alphacopilot_factor_validations_total = Counter(
    'alphacopilot_factor_validations_total',
    'Total factor expression validations',
    ['status']  # "valid", "invalid", "error"
)

alphacopilot_factors_generated_total = Counter(
    'alphacopilot_factors_generated_total',
    'Total alpha factors generated',
    ['factor_type']
)

# Backtest metrics (if Celery queue enabled)
alphacopilot_backtest_jobs_total = Counter(
    'alphacopilot_backtest_jobs_total',
    'Total backtest jobs',
    ['status']  # "queued", "running", "completed", "failed"
)

alphacopilot_backtest_duration_seconds = Histogram(
    'alphacopilot_backtest_duration_seconds',
    'Backtest execution duration',
    buckets=(30, 60, 120, 300, 600, 1200, 1800)
)

# System metrics
alphacopilot_db_queries_total = Counter(
    'alphacopilot_db_queries_total',
    'Total database queries',
    ['operation', 'table']  # operation: "select", "insert", "update"
)

alphacopilot_service_info = Info(
    'alphacopilot_service',
    'AlphaCopilot service information'
)


def metrics_endpoint():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
```

### Panels

#### Row 1: Run Volume & Success

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 1 | **Runs Created (1h)** | Recent run volume | `sum(increase(alphacopilot_runs_total{job="alphacopilot_server",status="created"}[1h]))` | Stat | - |
| 2 | **Run Success Rate** | % completed successfully | `sum(rate(alphacopilot_runs_total{job="alphacopilot_server",status="completed"}[1h])) / sum(rate(alphacopilot_runs_total{job="alphacopilot_server",status=~"completed|failed"}[1h])) * 100` | Gauge | >90% Green, 70-90% Yellow, <70% Red |
| 3 | **Concurrent Runs** | Currently executing | `alphacopilot_concurrent_runs{job="alphacopilot_server"}` | Stat | <10 Green, 10-20 Yellow, >20 Red |
| 4 | **Runs by Status** | Status breakdown | `sum by (status) (increase(alphacopilot_runs_total{job="alphacopilot_server"}[6h]))` | Pie chart | - |

#### Row 2: Latency & SLAs

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 5 | **Run Duration P50** | Median workflow duration | `histogram_quantile(0.5, sum by (le) (rate(alphacopilot_run_duration_seconds_bucket{job="alphacopilot_server"}[1h])))` | Gauge | - |
| 6 | **Run Duration P95** | 95th percentile duration | `histogram_quantile(0.95, sum by (le) (rate(alphacopilot_run_duration_seconds_bucket{job="alphacopilot_server"}[1h])))` | Gauge | <600s Green, 600-1200s Yellow, >1200s Red |
| 7 | **Iteration Duration by Type** | Duration per iteration type | `histogram_quantile(0.95, sum by (iteration_type, le) (rate(alphacopilot_iteration_duration_seconds_bucket{job="alphacopilot_server"}[1h])))` | Timeseries | - |
| 8 | **Iterations per Run** | Avg iterations to complete | `sum(rate(alphacopilot_iterations_total{job="alphacopilot_server"}[1h])) / sum(rate(alphacopilot_runs_total{job="alphacopilot_server",status="created"}[1h]))` | Stat | - |

#### Row 3: LLM Usage & Errors

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 9 | **LLM Requests/min** | LLM API call rate | `sum(rate(alphacopilot_llm_requests_total{job="alphacopilot_server"}[5m])) * 60` | Timeseries | - |
| 10 | **LLM Error Rate** | % failed LLM calls | `sum(rate(alphacopilot_llm_requests_total{job="alphacopilot_server",status="error"}[5m])) / sum(rate(alphacopilot_llm_requests_total{job="alphacopilot_server"}[5m])) * 100` | Gauge | <1% Green, 1-5% Yellow, >5% Red |
| 11 | **LLM Latency P95** | 95th percentile LLM response | `histogram_quantile(0.95, sum by (le) (rate(alphacopilot_llm_latency_seconds_bucket{job="alphacopilot_server"}[5m])))` | Gauge | <10s Green, 10-30s Yellow, >30s Red |
| 12 | **Token Usage (Input/Output)** | Token consumption | `sum by (token_type) (rate(alphacopilot_llm_tokens_total{job="alphacopilot_server"}[1h]))` | Timeseries | - |

#### Row 4: Factor Generation

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 13 | **Factor Validations** | Validation success rate | `sum by (status) (rate(alphacopilot_factor_validations_total{job="alphacopilot_server"}[1h]))` | Pie chart | - |
| 14 | **Factors Generated** | Total factors created | `sum(increase(alphacopilot_factors_generated_total{job="alphacopilot_server"}[24h]))` | Stat | - |

#### Row 5: Backtests (if enabled)

| # | Title | Purpose | PromQL | Type | Thresholds |
|---|-------|---------|--------|------|------------|
| 15 | **Backtest Jobs by Status** | Job status breakdown | `sum by (status) (rate(alphacopilot_backtest_jobs_total{job="alphacopilot_server"}[1h]))` | Timeseries | - |
| 16 | **Backtest Duration P95** | 95th percentile backtest time | `histogram_quantile(0.95, sum by (le) (rate(alphacopilot_backtest_duration_seconds_bucket{job="alphacopilot_server"}[1h])))` | Gauge | <600s Green, 600-1200s Yellow, >1200s Red |

---

## Prometheus Scrape Configuration

Add to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'auth_server'
    static_configs:
      - targets: ['auth_server:4000']
    metrics_path: /metrics

  - job_name: 'notification_server'
    static_configs:
      - targets: ['notification_server:9101']
    metrics_path: /metrics

  - job_name: 'portfolio_server'
    static_configs:
      - targets: ['portfolio_server:8000']
    metrics_path: /metrics

  - job_name: 'alphacopilot_server'
    static_configs:
      - targets: ['alphacopilot_server:8069']
    metrics_path: /metrics

  - job_name: 'celery_exporter'
    static_configs:
      - targets: ['celery-exporter:9540']

  - job_name: 'celery_workers'
    static_configs:
      - targets:
        - 'celery-worker-1:9101'
        - 'celery-worker-2:9102'
        - 'celery-worker-3:9103'
        - 'celery-worker-4:9104'
```
