#!/bin/bash

echo "🛑 Stopping Celery workers..."
pkill -f "celery.*worker" || true
sleep 2

echo "🛑 Stopping Celery beat..."
pkill -f "celery.*beat" || true
sleep 1

echo "🛑 Stopping streaming order monitor..."
pkill -f "streaming_order_monitor" || true
sleep 1

echo "🛑 Stopping streaming risk monitor..."
pkill -f "streaming_risk_monitor" || true
sleep 1

echo "🔌 Closing all Prisma connections..."
# Kill any processes that might be holding Prisma connections
pkill -f "prisma" || true
pkill -f "uvicorn" || true  # FastAPI server holds Prisma connections
sleep 2

echo "🧹 Clearing Redis (Celery tasks & results)..."
redis-cli FLUSHDB

echo "🧹 Clearing any remaining database connections..."
# Force close any lingering connections
ps aux | grep -E "(prisma|uvicorn|celery)" | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true

echo "✅ All processes stopped and connections cleared!"
echo "Now run: pnpm dev && pnpm celery"
