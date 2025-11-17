#!/bin/bash

echo "🛑 Stopping Celery workers..."
pkill -f "celery.*worker" || true
sleep 2

echo "🧹 Clearing Redis (Celery tasks & results)..."
redis-cli FLUSHDB

echo "✅ Done! Now run: pnpm celery"
