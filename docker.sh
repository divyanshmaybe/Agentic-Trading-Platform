#!/bin/bash

set -e

echo "🐳 Docker Management Script"
echo "==========================="

# Function to generate docker.env files with Docker-specific overrides
generate_docker_env() {
    echo "📝 Generating docker.env files..."
    
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
    echo "   ✅ docker.env generated"
    
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
PORTFOLIO_SERVICE_URL=http://portfolio_server:8000
NODE_ENV=production
PORT=4000
CLIENT_URL=http://localhost:3000
EOF
    echo "   ✅ apps/auth_server/docker.env generated"
    
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
PORTFOLIO_SERVICE_URL=http://portfolio_server:8000
REDBEAT_REDIS_URL=redis://portfolio_redis:6379/0
EOF
    echo "   ✅ apps/portfolio-server/docker.env generated"
    
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
ALPHACOPILOT_CORS_ORIGINS=http://localhost:3000,http://frontend:3000
EOF
    echo "   ✅ apps/alphacopilot-server/docker.env generated"
    
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
    echo "   ✅ apps/notification_server/docker.env generated"
    
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
PORTFOLIO_SERVICE_URL=http://portfolio_server:8000
NEXT_PUBLIC_API_URL=http://localhost:4000
NEXT_PUBLIC_AUTH_BASE_URL=http://localhost:4000/api/auth
NEXT_PUBLIC_PORTFOLIO_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:4001
REDIS_HOST=auth_redis
REDIS_PORT=6379
PORT=3000
NEXT_TELEMETRY_DISABLED=1
NODE_ENV=production
EOF
    echo "   ✅ apps/frontend/docker.env generated"
}

# Parse arguments
CLEAR_VOLUMES=false
CLEAR_REDIS_ONLY=false
REBUILD=false
NO_CACHE=false
STOP_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -v|--volumes)
            CLEAR_VOLUMES=true
            shift
            ;;
        -r|--redis)
            CLEAR_REDIS_ONLY=true
            shift
            ;;
        -b|--build)
            REBUILD=true
            shift
            ;;
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        -s|--stop)
            STOP_ONLY=true
            shift
            ;;
        -h|--help)
            echo "Usage: ./docker.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -v, --volumes   Clear all volumes (databases + redis) - full reset"
            echo "  -r, --redis     Clear only Redis locks and timestamps"
            echo "  -b, --build     Rebuild images before starting"
            echo "  --no-cache      Use with --build to rebuild without cache"
            echo "  -s, --stop      Stop containers only (don't restart)"
            echo "  -h, --help      Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./docker.sh               # Simple restart"
            echo "  ./docker.sh -s            # Stop only"
            echo "  ./docker.sh -r            # Restart + clear Redis locks"
            echo "  ./docker.sh -v            # Full reset (clears all data)"
            echo "  ./docker.sh -b            # Rebuild and restart"
            echo "  ./docker.sh -b --no-cache # Rebuild without cache and restart"
            echo "  ./docker.sh -v -b         # Full reset with rebuild"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Stop all containers
echo ""
echo "🛑 Stopping all containers..."
if [ "$CLEAR_VOLUMES" = true ]; then
    docker compose down -v
    echo "   ✅ Containers stopped and volumes removed"
else
    docker compose down
    echo "   ✅ Containers stopped"
fi

# Exit early if stop-only mode
if [ "$STOP_ONLY" = true ]; then
    echo ""
    echo "✅ Docker stop complete!"
    exit 0
fi

# Clear Redis locks only (if requested and not doing full volume clear)
if [ "$CLEAR_REDIS_ONLY" = true ] && [ "$CLEAR_VOLUMES" = false ]; then
    echo ""
    echo "🧹 Clearing Redis locks and timestamps..."
    # Start redis containers temporarily
    docker compose up -d redis portfolio_redis
    sleep 3
    
    # Clear locks and timestamps
    docker exec auth_redis redis-cli KEYS '*lock*' | xargs -r docker exec -i auth_redis redis-cli DEL 2>/dev/null || true
    docker exec auth_redis redis-cli KEYS '*timestamp*' | xargs -r docker exec -i auth_redis redis-cli DEL 2>/dev/null || true
    docker exec auth_redis redis-cli KEYS 'redbeat:*' | xargs -r docker exec -i auth_redis redis-cli DEL 2>/dev/null || true
    
    docker exec portfolio_redis redis-cli KEYS '*lock*' | xargs -r docker exec -i portfolio_redis redis-cli DEL 2>/dev/null || true
    docker exec portfolio_redis redis-cli KEYS '*timestamp*' | xargs -r docker exec -i portfolio_redis redis-cli DEL 2>/dev/null || true
    docker exec portfolio_redis redis-cli KEYS 'redbeat:*' | xargs -r docker exec -i portfolio_redis redis-cli DEL 2>/dev/null || true
    
    echo "   ✅ Redis locks and timestamps cleared"
    
    # Stop redis containers (will be started again with all services)
    docker compose down
fi

# Rebuild if requested
if [ "$REBUILD" = true ]; then
    echo ""
    echo "🔨 Rebuilding images..."
    if [ "$NO_CACHE" = true ]; then
        echo "   (using --no-cache)"
        docker compose build --no-cache
    else
        docker compose build
    fi
    echo "   ✅ Images rebuilt"
fi

# Generate docker.env files before starting
echo ""
generate_docker_env

# Start all containers
echo ""
echo "🚀 Starting all containers..."
docker compose up -d
echo "   ✅ Containers starting..."

# Wait for health checks
echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 5

# Create Kafka topics
echo ""
echo "📨 Creating Kafka topics..."
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic news_pipeline_stock_recomendations --partitions 1 --replication-factor 1 2>/dev/null || true
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic news_pipeline_sentiment_articles --partitions 1 --replication-factor 1 2>/dev/null || true
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic nse_filings_trading_signal --partitions 1 --replication-factor 1 2>/dev/null || true
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic news_pipeline_sector_analysis --partitions 1 --replication-factor 1 2>/dev/null || true
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic low_risk_agent_logs --partitions 1 --replication-factor 1 2>/dev/null || true
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic risk_agent_alerts --partitions 1 --replication-factor 1 2>/dev/null || true
echo "   ✅ Kafka topics created"

# Show status
echo ""
echo "📊 Container Status:"
docker ps --format "table {{.Names}}\t{{.Status}}" | head -25

echo ""
echo "✅ Docker restart complete!"
echo ""
echo "🔍 View logs:"
echo "   pnpm docker-logs    # All logs in turbo panels"
echo "   docker logs -f <container_name>"
