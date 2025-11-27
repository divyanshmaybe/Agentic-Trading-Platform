#!/bin/bash

echo "🛑 Stopping all Celery worker pools..."
pkill -f "celery.*worker" || true
sleep 2

# Clean up PID files
if [ -d "apps/portfolio-server/logs/workers" ]; then
    echo "🧹 Removing worker PID files..."
    rm -f apps/portfolio-server/logs/workers/*.pid
fi

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
echo ""
echo "📊 Worker Pool Architecture:"
echo "   5 dedicated pools with 20 total workers"
echo "   • Trading: 8 workers | Pipeline: 4 workers"
echo "   • Allocation: 2 workers | Market: 4 workers | General: 2 workers"
echo ""
echo "🚀 Now run:"
echo "   Terminal 1: cd apps/portfolio-server && pnpm dev"
echo "   Terminal 2: cd apps/portfolio-server && pnpm celery:all"
echo ""
echo "📺 Each worker pool will show in separate Turbo panels!"
