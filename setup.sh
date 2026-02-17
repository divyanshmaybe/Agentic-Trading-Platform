#!/usr/bin/env bash

set -euo pipefail

#!/usr/bin/env bash

set -euo pipefail

# Configuration
KAFKA_IMAGE="${KAFKA_IMAGE:-apache/kafka:3.8.0}"
KAFKA_CONTAINER_NAME="${KAFKA_CONTAINER_NAME:-pathway-kafka}"

LOKI_IMAGE="${LOKI_IMAGE:-grafana/loki:latest}"
LOKI_CONTAINER_NAME="${LOKI_CONTAINER_NAME:-pathway-loki}"

PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-prom/prometheus:latest}"
PROMETHEUS_CONTAINER_NAME="${PROMETHEUS_CONTAINER_NAME:-pathway-prometheus}"

GRAFANA_IMAGE="${GRAFANA_IMAGE:-grafana/grafana:latest}"
GRAFANA_CONTAINER_NAME="${GRAFANA_CONTAINER_NAME:-grafana}"

CELERY_EXPORTER_IMAGE="${CELERY_EXPORTER_IMAGE:-danihodovic/celery-exporter:latest}"
CELERY_EXPORTER_CONTAINER_NAME="${CELERY_EXPORTER_CONTAINER_NAME:-pathway-celery-exporter}"

REDIS_EXPORTER_IMAGE="${REDIS_EXPORTER_IMAGE:-oliver006/redis_exporter:latest}"
REDIS_EXPORTER_CONTAINER_NAME="${REDIS_EXPORTER_CONTAINER_NAME:-pathway-redis-exporter}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo -e "${RED}❌ Docker is required to launch services${NC}" >&2
        exit 1
    fi
}

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# ============================================================================
# SERVICE FUNCTIONS
# ============================================================================

setup_kafka() {
    log_info "Setting up Apache Kafka (KRaft mode)..."
    
    # Pull image
    log_info "Pulling Kafka image ${KAFKA_IMAGE}..."
    docker pull "${KAFKA_IMAGE}" >/dev/null
    
    # Remove existing container
    if docker ps -a --format '{{.Names}}' | grep -q "^${KAFKA_CONTAINER_NAME}$"; then
        log_warning "Removing existing container ${KAFKA_CONTAINER_NAME}..."
        docker rm -f "${KAFKA_CONTAINER_NAME}" >/dev/null
    fi
    
    # Start Kafka
    log_info "Starting Kafka container ${KAFKA_CONTAINER_NAME}..."
    docker run -d --name "${KAFKA_CONTAINER_NAME}" \
        -p 9092:9092 \
        -e KAFKA_NODE_ID=1 \
        -e KAFKA_PROCESS_ROLES=broker,controller \
        -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093 \
        -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
        -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
        -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT \
        -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
        -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
        -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
        -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
        -e KAFKA_AUTO_CREATE_TOPICS_ENABLE=true \
        -e CLUSTER_ID=MkU3OEVBNTcwNTJENDM2Qk \
        "${KAFKA_IMAGE}" >/dev/null
    
    log_info "Waiting for Kafka to be ready..."
    sleep 10
    
    # Create required Kafka topics
    log_info "Creating Kafka topics..."
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic news_pipeline_stock_recomendations --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic news_pipeline_sentiment_articles --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic news_pipeline_sector_analysis --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic nse_filings_trading_signal --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic low_risk_agent_logs --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic risk_agent_alerts --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic nse_pipeline_trade_logs --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic alpha_signals --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec "${KAFKA_CONTAINER_NAME}" /opt/kafka/bin/kafka-topics.sh \
        --create --if-not-exists --bootstrap-server localhost:9092 \
        --topic nse_agent_observability_logs --partitions 1 --replication-factor 1 2>/dev/null || true
    
    log_success "Kafka topics created successfully"
    log_success "Kafka is ready. Use 'docker logs -f ${KAFKA_CONTAINER_NAME}' to monitor."
}

setup_loki() {
    log_info "Setting up Grafana Loki (log aggregation)..."
    
    # Pull image
    log_info "Pulling Loki image ${LOKI_IMAGE}..."
    docker pull "${LOKI_IMAGE}" >/dev/null
    
    # Remove existing container
    if docker ps -a --format '{{.Names}}' | grep -q "^${LOKI_CONTAINER_NAME}$"; then
        log_warning "Removing existing container ${LOKI_CONTAINER_NAME}..."
        docker rm -f "${LOKI_CONTAINER_NAME}" >/dev/null
    fi
    
    # Create config directory if it doesn't exist
    mkdir -p devops/monitoring/loki
    
    # Create Loki config file
    cat > devops/monitoring/loki/local-config.yaml << 'EOF'
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  instance_addr: 127.0.0.1
  path_prefix: /tmp/loki
  storage:
    filesystem:
      chunks_directory: /tmp/loki/chunks
      rules_directory: /tmp/loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

query_range:
  results_cache:
    cache:
      embedded_cache:
        enabled: true
        max_size_mb: 100

limits_config:
  allow_structured_metadata: false

schema_config:
  configs:
    - from: 2020-10-24
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

ruler:
  alertmanager_url: http://localhost:9093

analytics:
  reporting_enabled: false
EOF
    
    # Start Loki with host network (for local development)
    log_info "Starting Loki container ${LOKI_CONTAINER_NAME}..."
    docker run -d --name "${LOKI_CONTAINER_NAME}" \
        --network=host \
        -v "$(pwd)/devops/monitoring/loki:/etc/loki" \
        "${LOKI_IMAGE}" \
        -config.file=/etc/loki/local-config.yaml >/dev/null
    
    log_success "Loki is running on http://localhost:3100"
}

setup_prometheus() {
    log_info "Setting up Prometheus (metrics collection)..."
    
    # Pull image
    log_info "Pulling Prometheus image ${PROMETHEUS_IMAGE}..."
    docker pull "${PROMETHEUS_IMAGE}" >/dev/null
    
    # Remove existing container
    if docker ps -a --format '{{.Names}}' | grep -q "^${PROMETHEUS_CONTAINER_NAME}$"; then
        log_warning "Removing existing container ${PROMETHEUS_CONTAINER_NAME}..."
        docker rm -f "${PROMETHEUS_CONTAINER_NAME}" >/dev/null
    fi
    
    # Ensure Prometheus config exists
    if [ ! -f "devops/monitoring/prometheus.yml" ]; then
        log_error "Prometheus config file not found at devops/monitoring/prometheus.yml"
        exit 1
    fi
    
    # Start Prometheus with host network (for local development)
    log_info "Starting Prometheus container ${PROMETHEUS_CONTAINER_NAME}..."
    docker run -d --name "${PROMETHEUS_CONTAINER_NAME}" \
        --network=host \
        -v "$(pwd)/devops/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
        -v "$(pwd)/devops/monitoring/alert-rules.yml:/etc/prometheus/alert-rules.yml:ro" \
        -v prometheus_data:/prometheus \
        "${PROMETHEUS_IMAGE}" \
        --config.file=/etc/prometheus/prometheus.yml \
        --storage.tsdb.path=/prometheus \
        --web.enable-lifecycle >/dev/null
    
    log_success "Prometheus is running on http://localhost:9090"
}

setup_grafana() {
    log_info "Setting up Grafana (visualization dashboard)..."
    
    # Pull image
    log_info "Pulling Grafana image ${GRAFANA_IMAGE}..."
    docker pull "${GRAFANA_IMAGE}" >/dev/null
    
    # Remove existing container
    if docker ps -a --format '{{.Names}}' | grep -q "^${GRAFANA_CONTAINER_NAME}$"; then
        log_warning "Removing existing container ${GRAFANA_CONTAINER_NAME}..."
        docker rm -f "${GRAFANA_CONTAINER_NAME}" >/dev/null
    fi
    
    # Ensure Grafana data directory exists
    mkdir -p devops/monitoring/grafana/provisioning/datasources
    mkdir -p devops/monitoring/grafana/provisioning/dashboards
    
    # Create Grafana datasource config for Prometheus and Loki
    # Using localhost since we use --network=host mode
    cat > devops/monitoring/grafana/provisioning/datasources/datasources.yml << 'EOF'
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    uid: PBFA97CFB590B2093
    access: proxy
    url: http://localhost:9090
    isDefault: true
    editable: true
    jsonData:
      timeInterval: "15s"
      httpMethod: "POST"
      manageAlerts: true
    
  - name: Loki
    type: loki
    access: proxy
    url: http://localhost:3100
    editable: true
    jsonData:
      maxLines: 1000
EOF
    
    # Create Grafana dashboard config
    cat > devops/monitoring/grafana/provisioning/dashboards/dashboard.yml << 'EOF'
apiVersion: 1

providers:
  - name: 'Celery Monitoring'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
EOF
    
    # Dashboards are already in grafana/provisioning/dashboards/ - no copy needed
    
    # Start Grafana with host network and custom HTTP port
    log_info "Starting Grafana container ${GRAFANA_CONTAINER_NAME}..."
    docker run -d --name "${GRAFANA_CONTAINER_NAME}" \
        --network=host \
        -e GF_SERVER_HTTP_PORT=3001 \
        -e GF_SECURITY_ADMIN_PASSWORD=admin \
        -e GF_USERS_ALLOW_SIGN_UP=false \
        -e GF_SERVER_ROOT_URL=http://localhost:3001 \
        -v "$(pwd)/devops/monitoring/grafana/provisioning:/etc/grafana/provisioning:ro" \
        -v grafana_data:/var/lib/grafana \
        "${GRAFANA_IMAGE}" >/dev/null
    
    log_success "Grafana is running on http://localhost:3001 (admin/admin)"
}

setup_celery_exporter() {
    log_info "Setting up Celery Exporter (Prometheus metrics for Celery)..."
    
    # Pull image
    log_info "Pulling Celery Exporter image ${CELERY_EXPORTER_IMAGE}..."
    docker pull "${CELERY_EXPORTER_IMAGE}" >/dev/null
    
    # Remove existing container
    if docker ps -a --format '{{.Names}}' | grep -q "^${CELERY_EXPORTER_CONTAINER_NAME}$"; then
        log_warning "Removing existing container ${CELERY_EXPORTER_CONTAINER_NAME}..."
        docker rm -f "${CELERY_EXPORTER_CONTAINER_NAME}" >/dev/null
    fi
    
    # Get Redis URL from environment or use default
    local redis_url="${CELERY_BROKER_URL:-redis://localhost:6379/0}"
    
    # Start Celery Exporter with host network
    log_info "Starting Celery Exporter container ${CELERY_EXPORTER_CONTAINER_NAME}..."
    docker run -d --name "${CELERY_EXPORTER_CONTAINER_NAME}" \
        --network=host \
        -e CE_BROKER_URL="${redis_url}" \
        -e CE_LISTEN_ADDRESS="0.0.0.0:9808" \
        -e CE_NAMESPACE="celery" \
        -e CE_MAX_TASKS="10000" \
        -e CE_RETRY_INTERVAL="5" \
        "${CELERY_EXPORTER_IMAGE}" >/dev/null
    
    log_success "Celery Exporter is running on http://localhost:9808/metrics"
}

setup_redis_exporter() {
    log_info "Setting up Redis Exporter (Prometheus metrics for Redis)..."
    
    # Pull image
    log_info "Pulling Redis Exporter image ${REDIS_EXPORTER_IMAGE}..."
    docker pull "${REDIS_EXPORTER_IMAGE}" >/dev/null
    
    # Remove existing container
    if docker ps -a --format '{{.Names}}' | grep -q "^${REDIS_EXPORTER_CONTAINER_NAME}$"; then
        log_warning "Removing existing container ${REDIS_EXPORTER_CONTAINER_NAME}..."
        docker rm -f "${REDIS_EXPORTER_CONTAINER_NAME}" >/dev/null
    fi
    
    # Get Redis address from environment or use default (portfolio_redis port)
    local redis_addr="${REDIS_ADDR:-redis://localhost:6379}"
    
    # Start Redis Exporter with host network
    log_info "Starting Redis Exporter container ${REDIS_EXPORTER_CONTAINER_NAME}..."
    docker run -d --name "${REDIS_EXPORTER_CONTAINER_NAME}" \
        --network=host \
        -e REDIS_ADDR="${redis_addr}" \
        "${REDIS_EXPORTER_IMAGE}" >/dev/null
    
    log_success "Redis Exporter is running on http://localhost:9121/metrics"
}

# ============================================================================
# MAIN LOGIC
# ============================================================================

usage() {
    echo "Usage: $0 [SERVICE...]"
    echo ""
    echo "Services:"
    echo "  kafka           - Apache Kafka message broker"
    echo "  loki            - Grafana Loki log aggregation"
    echo "  prometheus      - Prometheus metrics collection"
    echo "  grafana         - Grafana visualization dashboard"
    echo "  celery-exporter - Celery Prometheus exporter (port 9808)"
    echo "  redis-exporter  - Redis Prometheus exporter (port 9121)"
    echo "  monitoring      - All monitoring services (Loki, Prometheus, Grafana, Celery Exporter, Redis Exporter)"
    echo "  all             - All services (Kafka + monitoring stack)"
    echo ""
    echo "Examples:"
    echo "  $0 kafka                    # Start only Kafka"
    echo "  $0 monitoring               # Start Loki, Prometheus, Grafana, Celery Exporter, Redis Exporter"
    echo "  $0 celery-exporter          # Start only Celery Exporter"
    echo "  $0 all                      # Start everything"
    echo ""
    echo "Environment variables:"
    echo "  KAFKA_IMAGE, KAFKA_CONTAINER_NAME"
    echo "  LOKI_IMAGE, LOKI_CONTAINER_NAME"
    echo "  PROMETHEUS_IMAGE, PROMETHEUS_CONTAINER_NAME"
    echo "  GRAFANA_IMAGE, GRAFANA_CONTAINER_NAME"
    echo "  CELERY_EXPORTER_IMAGE, CELERY_EXPORTER_CONTAINER_NAME"
    echo "  REDIS_EXPORTER_IMAGE, REDIS_EXPORTER_CONTAINER_NAME"
  echo "  CELERY_BROKER_URL           # Redis URL for Celery Exporter (default: redis://localhost:6379/0)"
  echo "  REDIS_ADDR                  # Redis address for Redis Exporter (default: redis://localhost:6379)"
}

main() {
    # Check if Docker is available
    check_docker
    
    # Parse arguments
    if [ $# -eq 0 ]; then
        usage
        exit 1
    fi
    
    local services=("$@")
    
    # Process services
    for service in "${services[@]}"; do
        case $service in
            kafka)
                setup_kafka
                ;;
            loki)
                setup_loki
                ;;
            prometheus)
                setup_prometheus
                ;;
            grafana)
                setup_grafana
                ;;
            monitoring)
                setup_loki
                setup_prometheus
                setup_grafana
                setup_celery_exporter
                setup_redis_exporter
                ;;
            celery-exporter)
                setup_celery_exporter
                ;;
            redis-exporter)
                setup_redis_exporter
                ;;
            all)
                setup_kafka
                setup_loki
                setup_prometheus
                setup_grafana
                setup_celery_exporter
                setup_redis_exporter
                ;;
            *)
                log_error "Unknown service: $service"
                usage
                exit 1
                ;;
        esac
    done
    
    log_success "Setup complete!"
    
    # Show status
    echo ""
    log_info "Service URLs:"
    if docker ps --format '{{.Names}}' | grep -q "^${KAFKA_CONTAINER_NAME}$"; then
        echo "  Kafka:      localhost:9092"
    fi
    if docker ps --format '{{.Names}}' | grep -q "^${LOKI_CONTAINER_NAME}$"; then
        echo "  Loki:       http://localhost:3100"
    fi
    if docker ps --format '{{.Names}}' | grep -q "^${PROMETHEUS_CONTAINER_NAME}$"; then
        echo "  Prometheus: http://localhost:9090"
    fi
    if docker ps --format '{{.Names}}' | grep -q "^${GRAFANA_CONTAINER_NAME}$"; then
        echo "  Grafana:         http://localhost:3001 (admin/admin)"
    fi
    if docker ps --format '{{.Names}}' | grep -q "^${CELERY_EXPORTER_CONTAINER_NAME}$"; then
        echo "  Celery Exporter: http://localhost:9808/metrics"
    fi
    if docker ps --format '{{.Names}}' | grep -q "^${REDIS_EXPORTER_CONTAINER_NAME}$"; then
        echo "  Redis Exporter:  http://localhost:9121/metrics"
    fi
}

# Run main function with all arguments
main "$@"
