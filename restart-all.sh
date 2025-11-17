#!/bin/bash

echo "🛑 Stopping all services..."

# Stop Celery workers
echo "Stopping Celery workers..."
pkill -f "celery.*worker" || true

# Stop Kafka
echo "Stopping Kafka..."
docker stop kafka 2>/dev/null || true

# Stop Redis
echo "Stopping Redis..."
docker stop redis 2>/dev/null || true

echo ""
echo "🧹 Cleaning up..."

# Clear Redis data
echo "Clearing Redis data..."
docker rm redis 2>/dev/null || true

# Clear Kafka data (optional - uncomment if you want fresh Kafka)
# echo "Clearing Kafka data..."
# docker rm kafka 2>/dev/null || true
# rm -rf /tmp/kafka-logs

# Clear Celery task results
echo "Clearing Celery results from Redis..."
docker run --rm --network host redis:7-alpine redis-cli FLUSHDB || true

echo ""
echo "🚀 Starting services..."

# Start Redis
echo "Starting Redis..."
docker run -d --name redis --network host redis:7-alpine

# Wait for Redis
echo "Waiting for Redis to be ready..."
sleep 2

# Start Kafka (assuming you have it in docker-compose or similar)
echo "Starting Kafka..."
docker start kafka 2>/dev/null || echo "⚠️  Kafka not found as docker container, skipping..."

echo ""
echo "✅ All services restarted!"
echo ""
echo "📋 Next steps:"
echo "   1. Start server: pnpm dev"
echo "   2. Start workers: pnpm celery"
echo ""
