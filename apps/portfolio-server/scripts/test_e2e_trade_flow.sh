#!/bin/bash
# End-to-End Trade Flow Test
# Tests the complete flow: Signal → Trade Creation → Execution → TP/SL → Auto-Sell

set -e

echo "================================================================================================"
echo "🧪 END-TO-END TRADE EXECUTION TEST"
echo "================================================================================================"
echo ""
echo "This test will:"
echo "  1. Send a fake NSE signal (BUY INFY)"
echo "  2. Verify trade creation with TP/SL prices"
echo "  3. Wait for Celery worker to execute the trade"
echo "  4. Verify TP/SL orders were created"
echo "  5. Check auto-sell configuration"
echo ""
echo "Prerequisites:"
echo "  ✅ Celery worker running: pnpm celery"
echo "  ✅ USE_CELERY_FOR_TRADES=true in .env"
echo ""
read -p "Press Enter to start test..."

# Step 1: Clear any pending trades from queue
echo ""
echo "📋 Step 1: Clearing pending trades from queue..."
redis-cli -n 0 del trading > /dev/null
echo "✅ Queue cleared"

# Step 2: Send fake signal
echo ""
echo "📋 Step 2: Sending fake BUY signal for INFY..."
cd /home/manav/dev_ws/Pathway-Inter-IIT/apps/portfolio-server
PYTHONPATH=../..:../../shared/py python3 pipelines/nse/push_fake_signal.py --symbol INFY --signal 1 --confidence 0.90 --price 1800

# Step 3: Wait for signal processing
echo ""
echo "⏳ Waiting 5 seconds for signal processing..."
sleep 5

# Step 4: Check if trade was created
echo ""
echo "📋 Step 3: Checking if trade was created..."
TRADE_ID=$(PYTHONPATH=../..:../../shared/py python3 -c "
from prisma import Prisma
import asyncio
import sys

async def check():
    client = Prisma()
    await client.connect()
    
    trade = await client.trade.find_first(
        where={'symbol': 'INFY', 'side': 'BUY', 'source': 'nse_pipeline'},
        order={'created_at': 'desc'},
    )
    
    if trade:
        print(trade.id)
        sys.exit(0)
    else:
        sys.exit(1)
    
    await client.disconnect()

asyncio.run(check())
" 2>/dev/null)

if [ -z "$TRADE_ID" ]; then
    echo "❌ Trade creation failed - no trade found for INFY"
    exit 1
fi

echo "✅ Trade created: $TRADE_ID"

# Step 5: Check if trade is in queue
echo ""
echo "📋 Step 4: Checking Celery queue..."
QUEUE_LENGTH=$(redis-cli -n 0 llen trading)
echo "   Queue length: $QUEUE_LENGTH"

if [ "$QUEUE_LENGTH" -gt 0 ]; then
    echo "   ✅ Trade execution task is queued"
else
    echo "   ⚠️  Queue is empty - task may have been processed already"
fi

# Step 6: Wait for execution
echo ""
echo "⏳ Waiting 10 seconds for trade execution..."
sleep 10

# Step 7: Verify trade was executed
echo ""
echo "📋 Step 5: Verifying trade execution..."
PYTHONPATH=../..:../../shared/py python3 scripts/test_trade_execution_complete.py

echo ""
echo "================================================================================================"
echo "✅ TEST COMPLETE"
echo "================================================================================================"
echo ""
echo "Next steps:"
echo "  1. Check Celery worker logs for errors"
echo "  2. If TP/SL orders weren't created, check TradeExecutionService logs"
echo "  3. To monitor orders: pnpm streaming:orders"
echo "  4. To test auto-sell: Wait 15 minutes or manually trigger with celery call"
echo ""
