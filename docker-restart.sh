#!/bin/bash

set -e

echo "🐳 Docker Restart Script"
echo "========================"

# Parse arguments
CLEAR_VOLUMES=false
CLEAR_REDIS_ONLY=false
REBUILD=false

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
        -h|--help)
            echo "Usage: ./docker-restart.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -v, --volumes   Clear all volumes (databases + redis) - full reset"
            echo "  -r, --redis     Clear only Redis locks and timestamps"
            echo "  -b, --build     Rebuild images before starting"
            echo "  -h, --help      Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./docker-restart.sh           # Simple restart"
            echo "  ./docker-restart.sh -r        # Restart + clear Redis locks"
            echo "  ./docker-restart.sh -v        # Full reset (clears all data)"
            echo "  ./docker-restart.sh -b        # Rebuild and restart"
            echo "  ./docker-restart.sh -v -b     # Full reset with rebuild"
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
    docker compose build
    echo "   ✅ Images rebuilt"
fi

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
