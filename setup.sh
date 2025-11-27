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
GRAFANA_CONTAINER_NAME="${GRAFANA_CONTAINER_NAME:-pathway-grafana}"

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
    
    log_success "Kafka is starting up. Use 'docker logs -f ${KAFKA_CONTAINER_NAME}' to monitor readiness."
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
    cat > devops/monitoring/grafana/provisioning/datasources/datasources.yml << 'EOF'
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://localhost:9090
    isDefault: true
    editable: true
    jsonData:
      timeInterval: "15s"
    
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
    
    # Copy Celery dashboards if they exist
    if [ -f "devops/monitoring/celery-detailed-dashboard.json" ]; then
        cp devops/monitoring/celery-detailed-dashboard.json devops/monitoring/grafana/provisioning/dashboards/
    fi
    if [ -f "devops/monitoring/celery-dashboard.json" ]; then
        cp devops/monitoring/celery-dashboard.json devops/monitoring/grafana/provisioning/dashboards/
    fi
    
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

# ============================================================================
# MAIN LOGIC
# ============================================================================

usage() {
    echo "Usage: $0 [SERVICE...]"
    echo ""
    echo "Services:"
    echo "  kafka      - Apache Kafka message broker"
    echo "  loki       - Grafana Loki log aggregation"
    echo "  prometheus - Prometheus metrics collection"
    echo "  grafana    - Grafana visualization dashboard"
    echo "  monitoring - All monitoring services (Loki, Prometheus, Grafana)"
    echo "  all        - All services (Kafka + monitoring stack)"
    echo ""
    echo "Examples:"
    echo "  $0 kafka                    # Start only Kafka"
    echo "  $0 monitoring              # Start Loki, Prometheus, Grafana"
    echo "  $0 all                      # Start everything"
    echo ""
    echo "Environment variables:"
    echo "  KAFKA_IMAGE, KAFKA_CONTAINER_NAME"
    echo "  LOKI_IMAGE, LOKI_CONTAINER_NAME"
    echo "  PROMETHEUS_IMAGE, PROMETHEUS_CONTAINER_NAME"
    echo "  GRAFANA_IMAGE, GRAFANA_CONTAINER_NAME"
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
                ;;
            all)
                setup_kafka
                setup_loki
                setup_prometheus
                setup_grafana
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
        echo "  Grafana:    http://localhost:3001 (admin/admin)"
    fi
}

# Run main function with all arguments
main "$@"
