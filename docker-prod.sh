#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to print colored output
print_header() {
    echo -e "${BLUE}🐳 Docker Management Script${NC}"
    echo -e "${BLUE}===========================${NC}"
}

print_success() {
    echo -e "   ${GREEN}✅ $1${NC}"
}

print_info() {
    echo -e "${CYAN}$1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Function to show help/usage
show_help() {
    echo ""
    echo -e "${BLUE}Usage:${NC} ./docker.sh <command> [options]"
    echo ""
    echo -e "${YELLOW}Commands:${NC}"
    echo "  start           Start all containers (builds if images don't exist)"
    echo "  stop            Stop all running containers"
    echo "  restart         Restart all containers (stop + start)"
    echo "  build           Build/rebuild all Docker images"
    echo "  logs            Show container logs (use with -f to follow)"
    echo "  status          Show status of all containers"
    echo "  clean           Stop containers and remove volumes (full reset)"
    echo "  clean-redis     Clear Redis locks and timestamps only"
    echo "  rmi             Remove all project Docker images"
    echo "  env             Generate docker.env files only"
    echo "  monitoring      Start/stop monitoring stack (Prometheus, Grafana, Loki)"
    echo "  help            Show this help message"
    echo ""
    echo -e "${YELLOW}Options:${NC}"
    echo "  --no-cache      Use with 'build' to rebuild without Docker cache"
    echo "  -f, --follow    Use with 'logs' to follow log output"
    echo "  --without-monitoring  Use with 'start' to exclude monitoring stack"
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo "  ./docker.sh start             # Start all services (with monitoring)"
    echo "  ./docker.sh start --without-monitoring  # Start without monitoring"
    echo "  ./docker.sh stop              # Stop all services (including monitoring)"
    echo "  ./docker.sh restart           # Restart all services"
    echo "  ./docker.sh build             # Rebuild images"
    echo "  ./docker.sh build --no-cache  # Rebuild without cache"
    echo "  ./docker.sh logs              # Show logs"
    echo "  ./docker.sh logs -f           # Follow logs"
    echo "  ./docker.sh status            # Show container status"
    echo "  ./docker.sh clean             # Full reset (removes data)"
    echo "  ./docker.sh clean-redis       # Clear Redis locks only"
    echo "  ./docker.sh rmi               # Remove all project images"
    echo "  ./docker.sh monitoring start  # Start monitoring only"
    echo "  ./docker.sh monitoring stop   # Stop monitoring only"
    echo ""
}

# Function to generate docker.env files with Docker-specific overrides
generate_docker_env() {
    print_info "📝 Generating docker.env files..."
    
    # Variables to exclude from source .env (we'll add Docker-specific values)
    EXCLUDE_VARS=(
        "DATABASE_URL"
        "SHADOW_DATABASE_URL"
        "REDIS_HOST"
        "REDIS_PORT"
        "CELERY_BROKER_URL"
        "CELERY_RESULT_BACKEND"
        "KAFKA_BOOTSTRAP_SERVERS"
        "AUTH_DATABASE_URL"
        "PORTFOLIO_DATABASE_URL"
        "NEXT_PUBLIC_PORTFOLIO_API_URL"
        "NEXT_PUBLIC_PORTFOLIO_SERVER_URL"
        "PORTFOLIO_SERVICE_URL"
    )
    
    # Build grep pattern to exclude these vars
    EXCLUDE_PATTERN=""
    for var in "${EXCLUDE_VARS[@]}"; do
        if [ -z "$EXCLUDE_PATTERN" ]; then
            EXCLUDE_PATTERN="^${var}="
        else
            EXCLUDE_PATTERN="${EXCLUDE_PATTERN}|^${var}="
        fi
    done
    
    # ========================================
    # Generate ROOT docker.env (shared vars)
    # ========================================
    if [ -f ".env" ]; then
        grep -v -E "$EXCLUDE_PATTERN" .env | grep -v "^#" | grep -v "^$" > docker.env
    else
        touch docker.env
    fi
    
    # Add common Docker networking overrides
    cat >> docker.env << 'EOF'

# ====== Docker Network Overrides ======
# Auth service database & redis
AUTH_DATABASE_URL=postgresql://auth_user:auth_password@auth_postgres:5432/auth_db
AUTH_REDIS_HOST=auth_redis
AUTH_REDIS_PORT=6379

# Portfolio service database & redis
PORTFOLIO_DATABASE_URL=postgresql://portfolio_user:portfolio_password@portfolio_postgres:5432/portfolio_db
PORTFOLIO_REDIS_HOST=portfolio_redis
PORTFOLIO_REDIS_PORT=6379

# Kafka
KAFKA_BOOTSTRAP_SERVERS=pathway-kafka:9092
KAFKA_ENABLED=true
EOF
    print_success "docker.env generated"
    
    # ========================================
    # Generate AUTH SERVER docker.env
    # ========================================
    if [ -f "apps/auth_server/.env" ]; then
        grep -v -E "$EXCLUDE_PATTERN" apps/auth_server/.env | grep -v "^#" | grep -v "^$" > apps/auth_server/docker.env 2>/dev/null || true
    else
        touch apps/auth_server/docker.env
    fi
    cat >> apps/auth_server/docker.env << 'EOF'

# ====== Docker Network Overrides ======
DATABASE_URL=postgresql://auth_user:auth_password@auth_postgres:5432/auth_db
REDIS_HOST=auth_redis
REDIS_PORT=6379
REDIS_URL=redis://auth_redis:6379
CELERY_BROKER_URL=redis://auth_redis:6379/0
CELERY_RESULT_BACKEND=redis://auth_redis:6379/1
PORTFOLIO_SERVICE_URL=https://portfolio.agentinvest.space
NODE_ENV=production
PORT=4000
CLIENT_URL=https://agentinvest.space
EOF
    print_success "apps/auth_server/docker.env generated"
    
    # ========================================
    # Generate PORTFOLIO SERVER docker.env
    # ========================================
    if [ -f "apps/portfolio-server/.env" ]; then
        grep -v -E "$EXCLUDE_PATTERN" apps/portfolio-server/.env | grep -v "^#" | grep -v "^$" > apps/portfolio-server/docker.env 2>/dev/null || true
    else
        touch apps/portfolio-server/docker.env
    fi
    cat >> apps/portfolio-server/docker.env << 'EOF'

# ====== Docker Network Overrides ======
DATABASE_URL=postgresql://portfolio_user:portfolio_password@portfolio_postgres:5432/portfolio_db
SHADOW_DATABASE_URL=postgresql://portfolio_user:portfolio_password@portfolio_postgres:5432/portfolio_db
REDIS_HOST=portfolio_redis
REDIS_PORT=6379
CELERY_BROKER_URL=redis://portfolio_redis:6379/0
CELERY_RESULT_BACKEND=redis://portfolio_redis:6379/1
AUTH_SERVER_URL=http://auth_server:4000
KAFKA_BOOTSTRAP_SERVERS=pathway-kafka:9092
KAFKA_ENABLED=true
PORTFOLIO_SERVICE_URL=https://portfolio.agentinvest.space
REDBEAT_REDIS_URL=redis://portfolio_redis:6379/0
AUTH_DATABASE_URL=postgresql://auth_user:auth_password@auth_postgres:5432/auth_db
ALLOWED_ORIGINS=https://agentinvest.space,http://localhost:3000,http://localhost:3001
EOF
    print_success "apps/portfolio-server/docker.env generated"
    
    # ========================================
    # Generate ALPHACOPILOT SERVER docker.env
    # ========================================
    if [ -f "apps/alphacopilot-server/.env" ]; then
        grep -v -E "$EXCLUDE_PATTERN" apps/alphacopilot-server/.env | grep -v "^#" | grep -v "^$" > apps/alphacopilot-server/docker.env 2>/dev/null || true
    else
        touch apps/alphacopilot-server/docker.env
    fi
    cat >> apps/alphacopilot-server/docker.env << 'EOF'

# ====== Docker Network Overrides ======
DATABASE_URL=postgresql://portfolio_user:portfolio_password@portfolio_postgres:5432/portfolio_db
SHADOW_DATABASE_URL=postgresql://portfolio_user:portfolio_password@portfolio_postgres:5432/portfolio_db
REDIS_HOST=portfolio_redis
REDIS_PORT=6379
CELERY_BROKER_URL=redis://portfolio_redis:6379/2
CELERY_RESULT_BACKEND=redis://portfolio_redis:6379/3
MCP_SERVER_URL=http://portfolio_server:8000/mcp
ALPHACOPILOT_HOST=0.0.0.0
ALPHACOPILOT_PORT=8069
ALPHACOPILOT_CORS_ORIGINS=https://agentinvest.space,http://localhost:3000,http://frontend:3000
EOF
    print_success "apps/alphacopilot-server/docker.env generated"
    
    # ========================================
    # Generate NOTIFICATION SERVER docker.env
    # ========================================
    if [ -f "apps/notification_server/.env" ]; then
        grep -v -E "$EXCLUDE_PATTERN" apps/notification_server/.env | grep -v "^#" | grep -v "^$" > apps/notification_server/docker.env 2>/dev/null || true
    else
        touch apps/notification_server/docker.env
    fi
    cat >> apps/notification_server/docker.env << 'EOF'

# ====== Docker Network Overrides ======
DATABASE_URL=postgresql://auth_user:auth_password@auth_postgres:5432/auth_db
REDIS_HOST=auth_redis
REDIS_PORT=6379
REDIS_URL=redis://auth_redis:6379
AUTH_SERVER_URL=http://auth_server:4000
NODE_ENV=production
KAFKA_CLIENT_ID=notification-server
KAFKA_GROUP_ID=notifications-consumer
EOF
    print_success "apps/notification_server/docker.env generated"
    
    # ========================================
    # Generate FRONTEND docker.env
    # ========================================
    if [ -f "apps/frontend/.env" ]; then
        grep -v -E "$EXCLUDE_PATTERN" apps/frontend/.env | grep -v "^#" | grep -v "^$" > apps/frontend/docker.env 2>/dev/null || true
    else
        touch apps/frontend/docker.env
    fi
    cat >> apps/frontend/docker.env << 'EOF'

# ====== Docker Network Overrides ======
DATABASE_URL=postgresql://auth_user:auth_password@auth_postgres:5432/auth_db
AUTH_SERVER_URL=http://auth_server:4000
PORTFOLIO_SERVICE_URL=https://portfolio.agentinvest.space
NEXT_PUBLIC_API_URL=https://auth.agentinvest.space
NEXT_PUBLIC_AUTH_BASE_URL=https://auth.agentinvest.space/api/auth
NEXT_PUBLIC_PORTFOLIO_API_URL=https://portfolio.agentinvest.space
NEXT_PUBLIC_PORTFOLIO_SERVER_URL=https://portfolio.agentinvest.space
NEXT_PUBLIC_ALPHACOPILOT_URL=https://alphacopilot.agentinvest.space
NEXT_PUBLIC_WS_URL=ws://localhost:4001
REDIS_HOST=auth_redis
REDIS_PORT=6379
PORT=3000
NEXT_TELEMETRY_DISABLED=1
NODE_ENV=production
EOF
    print_success "apps/frontend/docker.env generated"
}

# Function to check if images exist
check_images_exist() {
    local images=("auth_server" "notification_server" "portfolio_server" "frontend_web" "alphacopilot_server")
    for img in "${images[@]}"; do
        if ! docker image inspect "$img:latest" &>/dev/null; then
            return 1
        fi
    done
    return 0
}

# Function to build images
do_build() {
    local no_cache=$1
    print_info "🔨 Building Docker images..."
    
    # Load NEXT_PUBLIC_* environment variables from frontend docker.env for build args
    if [ -f "apps/frontend/docker.env" ]; then
        # Export NEXT_PUBLIC_* variables for docker-compose build args
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ "$key" =~ ^#.*$ ]] && continue
            [[ -z "$key" ]] && continue
            # Only export NEXT_PUBLIC_* variables
            if [[ "$key" =~ ^NEXT_PUBLIC_ ]]; then
                # Remove quotes if present
                value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
                export "$key=$value"
            fi
        done < apps/frontend/docker.env
    fi
    
    if [ "$no_cache" = true ]; then
        echo "   (using --no-cache)"
        docker compose build --no-cache
    else
        docker compose build
    fi
    print_success "Images built"
}

# Function to stop containers (including monitoring)
do_stop() {
    print_info "🛑 Stopping all containers (including monitoring)..."
    docker compose --profile monitoring down
    print_success "Containers stopped"
}

# Function to stop containers and remove volumes (including monitoring)
do_clean() {
    print_info "🧹 Stopping containers and removing volumes (including monitoring)..."
    docker compose --profile monitoring down -v
    print_success "Containers stopped and volumes removed"
}

# Function to remove Docker images
do_remove_images() {
    print_info "🗑️  Removing project Docker images..."
    
    # List of project images to remove
    local images=(
        "portfolio_server"
        "alphacopilot_server"
        "auth_server"
        "notification_server"
        "frontend_web"
    )
    
    for img in "${images[@]}"; do
        if docker images --format '{{.Repository}}' | grep -q "^${img}$"; then
            echo "   Removing ${img}..."
            docker rmi -f "${img}:latest" 2>/dev/null || true
        fi
    done
    
    # Also remove dangling images
    echo "   Removing dangling images..."
    docker image prune -f 2>/dev/null || true
    
    print_success "Docker images removed"
}

# Function to clear Redis locks
do_clean_redis() {
    print_info "🧹 Clearing Redis locks and timestamps..."
    
    # Check if containers are running
    if ! docker ps --format '{{.Names}}' | grep -q 'auth_redis'; then
        print_warning "Redis containers not running. Starting them temporarily..."
        docker compose up -d redis portfolio_redis
        sleep 3
    fi
    
    # Clear locks and timestamps from auth_redis
    docker exec auth_redis redis-cli KEYS '*lock*' | xargs -r docker exec -i auth_redis redis-cli DEL 2>/dev/null || true
    docker exec auth_redis redis-cli KEYS '*timestamp*' | xargs -r docker exec -i auth_redis redis-cli DEL 2>/dev/null || true
    docker exec auth_redis redis-cli KEYS 'redbeat:*' | xargs -r docker exec -i auth_redis redis-cli DEL 2>/dev/null || true
    
    # Clear locks and timestamps from portfolio_redis
    docker exec portfolio_redis redis-cli KEYS '*lock*' | xargs -r docker exec -i portfolio_redis redis-cli DEL 2>/dev/null || true
    docker exec portfolio_redis redis-cli KEYS '*timestamp*' | xargs -r docker exec -i portfolio_redis redis-cli DEL 2>/dev/null || true
    docker exec portfolio_redis redis-cli KEYS 'redbeat:*' | xargs -r docker exec -i portfolio_redis redis-cli DEL 2>/dev/null || true
    
    print_success "Redis locks and timestamps cleared"
}

# Function to create Kafka topics
create_kafka_topics() {
    print_info "📨 Creating Kafka topics..."
    docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic news_pipeline_stock_recomendations --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic news_pipeline_sentiment_articles --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic nse_filings_trading_signal --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic news_pipeline_sector_analysis --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic low_risk_agent_logs --partitions 1 --replication-factor 1 2>/dev/null || true
    docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic risk_agent_alerts --partitions 1 --replication-factor 1 2>/dev/null || true
    print_success "Kafka topics created"
}

# Function to start containers
do_start() {
    local without_monitoring=$1
    
    # Generate docker.env files
    echo ""
    generate_docker_env
    
    # Check if images exist, build if not
    if ! check_images_exist; then
        echo ""
        print_warning "Some images don't exist. Building..."
        do_build false
    fi
    
    # Start containers
    echo ""
    if [ "$without_monitoring" = true ]; then
        print_info "🚀 Starting all containers (without monitoring)..."
        docker compose up -d
    else
        print_info "🚀 Starting all containers with monitoring stack..."
        docker compose --profile monitoring up -d
    fi
    print_success "Containers starting..."
    
    # Wait for health checks
    echo ""
    print_info "⏳ Waiting for services to be healthy..."
    sleep 5
    
    # Create Kafka topics
    echo ""
    create_kafka_topics
    
    # Show status
    echo ""
    do_status
    
    echo ""
    echo -e "${GREEN}✅ Docker start complete!${NC}"
    echo ""
    echo "🔍 View logs:"
    echo "   pnpm docker-logs         # All logs in turbo panels"
    echo "   ./docker.sh logs -f      # Follow all logs"
    echo "   docker logs -f <name>    # Follow specific container"
    
    if [ "$without_monitoring" != true ]; then
        echo ""
        echo "📊 Monitoring URLs:"
        echo "   Prometheus: http://localhost:9090"
        echo "   Grafana:    http://localhost:3001 (admin/admin)"
        echo "   Loki:       http://localhost:3100"
    fi
}

# Function to show status
do_status() {
    print_info "📊 Container Status:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -30
}

# Function to show logs
do_logs() {
    local follow=$1
    if [ "$follow" = true ]; then
        docker compose logs -f --tail=100
    else
        docker compose logs --tail=100
    fi
}

# Function to start/stop monitoring stack
do_monitoring() {
    local action=$1
    
    case $action in
        start)
            print_info "📊 Starting monitoring stack..."
            docker compose --profile monitoring up -d prometheus grafana loki redis-exporter celery-exporter postgres-exporter promtail
            print_success "Monitoring stack started!"
            echo ""
            echo "📊 Monitoring URLs:"
            echo "   Prometheus: http://localhost:9090"
            echo "   Grafana:    http://localhost:3001 (admin/admin)"
            echo "   Loki:       http://localhost:3100"
            ;;
        stop)
            print_info "📊 Stopping monitoring stack..."
            docker compose --profile monitoring stop prometheus grafana loki redis-exporter celery-exporter postgres-exporter promtail
            print_success "Monitoring stack stopped!"
            ;;
        *)
            echo "Usage: ./docker.sh monitoring [start|stop]"
            exit 1
            ;;
    esac
}

# ========================================
# MAIN SCRIPT
# ========================================

print_header

# No arguments - show help
if [ $# -eq 0 ]; then
    show_help
    exit 0
fi

# Parse command
COMMAND=$1
shift

# Parse options
NO_CACHE=false
FOLLOW=false
WITHOUT_MONITORING=false
MONITORING_ACTION=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        -f|--follow)
            FOLLOW=true
            shift
            ;;
        --without-monitoring)
            WITHOUT_MONITORING=true
            shift
            ;;
        start|stop)
            # For monitoring command
            MONITORING_ACTION=$1
            shift
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Execute command
case $COMMAND in
    start)
        do_start $WITHOUT_MONITORING
        ;;
    stop)
        do_stop
        echo ""
        echo -e "${GREEN}✅ Docker stop complete!${NC}"
        ;;
    restart)
        do_stop
        echo ""
        do_start $WITHOUT_MONITORING
        ;;
    build)
        do_build $NO_CACHE
        echo ""
        echo -e "${GREEN}✅ Docker build complete!${NC}"
        ;;
    logs)
        do_logs $FOLLOW
        ;;
    status)
        do_status
        ;;
    clean)
        do_clean
        echo ""
        echo -e "${GREEN}✅ Docker clean complete! All data removed.${NC}"
        ;;
    clean-redis)
        do_clean_redis
        ;;
    rmi|remove-images)
        do_remove_images
        echo ""
        echo -e "${GREEN}✅ Docker images removed!${NC}"
        ;;
    env)
        generate_docker_env
        echo ""
        echo -e "${GREEN}✅ Environment files generated!${NC}"
        ;;
    monitoring)
        if [ -z "$MONITORING_ACTION" ]; then
            echo "Usage: ./docker.sh monitoring [start|stop]"
            exit 1
        fi
        do_monitoring $MONITORING_ACTION
        ;;
    help|-h|--help)
        show_help
        ;;
    *)
        echo -e "${RED}Unknown command: $COMMAND${NC}"
        show_help
        exit 1
        ;;
esac
