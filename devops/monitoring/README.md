# Prometheus & Grafana Monitoring for Celery Workers

This directory contains monitoring setup for the Celery worker pools using Prometheus and Grafana.

## Architecture

Each Celery worker pool exposes Prometheus metrics on a dedicated port:
- **Trading workers**: `http://localhost:9101/metrics`
- **Pipeline workers**: `http://localhost:9102/metrics`
- **Allocation workers**: `http://localhost:9103/metrics`
- **Market workers**: `http://localhost:9104/metrics`
- **General workers**: `http://localhost:9105/metrics`

## Setup

### 1. Install Prometheus Client

```bash
cd apps/portfolio-server
pip install -r requirements.txt  # includes prometheus-client
```

### 2. Start Prometheus & Grafana

```bash
cd devops/monitoring
docker-compose -f docker-compose.monitoring.yml up -d
```

This starts:
- **Prometheus**: `http://localhost:9090`
- **Grafana**: `http://localhost:3001` (admin/admin)
- **Redis Exporter**: `http://localhost:9121`
- **PostgreSQL Exporter**: `http://localhost:9187`

### 3. Start Celery Workers with Monitoring

Workers automatically expose metrics when `PROMETHEUS_ENABLED=true`:

```bash
cd /path/to/project
pnpm celery  # Starts all workers with Prometheus enabled
```

## Metrics Exposed

### Worker Health
- `celery_worker_up` - Worker is running (1) or down (0)
- `celery_worker_tasks_active` - Number of tasks currently executing

### Task Execution
- `celery_tasks_total` - Total tasks processed (by status: success/failure)
- `celery_task_received_total` - Tasks received by worker
- `celery_task_started_total` - Tasks started
- `celery_task_succeeded_total` - Tasks completed successfully
- `celery_task_failed_total` - Tasks that failed
- `celery_task_retried_total` - Tasks retried
- `celery_task_rejected_total` - Tasks rejected

### Performance
- `celery_task_duration_seconds` - Task execution duration histogram
- `celery_task_runtime_seconds` - Task runtime histogram

## Grafana Dashboard

The included dashboard (`grafana_dashboards.json`) provides:
1. **Worker Status** - All worker pools health
2. **Active Tasks** - Real-time task execution
3. **Task Success Rate** - Success rate per worker/task
4. **Task Failure Rate** - Failure rate per worker/task
5. **Task Duration (p95)** - 95th percentile task duration
6. **Tasks Received** - Incoming task rate
7. **Task Retries** - Retry patterns
8. **Total Tasks by Status** - Pie chart of task outcomes

### Import Dashboard

1. Open Grafana: `http://localhost:3001`
2. Login: `admin/admin`
3. Go to **Dashboards** → **Import**
4. Upload `grafana_dashboards.json`
5. Select Prometheus as data source

## Querying Metrics

### Example Prometheus Queries

**Active tasks per worker:**
```promql
celery_worker_tasks_active
```

**Task success rate (5m):**
```promql
rate(celery_task_succeeded_total[5m])
```

**p95 task duration:**
```promql
histogram_quantile(0.95, rate(celery_task_duration_seconds_bucket[5m]))
```

**Worker pool utilization:**
```promql
celery_worker_tasks_active / 8  # Replace 8 with pool concurrency
```

## Alerting

Add alerts to `prometheus.yml`:

```yaml
rule_files:
  - 'alerts.yml'

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']
```

Example alert (`alerts.yml`):

```yaml
groups:
  - name: celery
    interval: 30s
    rules:
      - alert: CeleryWorkerDown
        expr: celery_worker_up == 0
        for: 1m
        annotations:
          summary: "Celery worker {{ $labels.worker }} is down"
          
      - alert: HighTaskFailureRate
        expr: rate(celery_task_failed_total[5m]) > 0.1
        for: 5m
        annotations:
          summary: "High failure rate for {{ $labels.task_name }}"
```

## Production Considerations

1. **Persistent Storage**: Volumes are already configured for Prometheus and Grafana data
2. **Retention**: Default Prometheus retention is 15 days
3. **Security**: 
   - Change Grafana admin password
   - Add authentication to Prometheus
   - Use reverse proxy (nginx) for production
4. **High Availability**: Consider Prometheus HA setup for production
5. **Remote Storage**: Configure remote write for long-term storage (Thanos, Cortex, etc.)

## Troubleshooting

### Metrics not appearing

1. Check worker logs for Prometheus initialization:
   ```
   📊 Prometheus metrics server started on port 9101 for worker trading@localhost
   ```

2. Verify port is accessible:
   ```bash
   curl http://localhost:9101/metrics
   ```

3. Check Prometheus targets: `http://localhost:9090/targets`

### Port conflicts

If ports are in use, set different ports in `package.json`:
```json
"PROMETHEUS_PORT=9201"  // Instead of 9101
```

Update `prometheus.yml` accordingly.
