#!/bin/bash

# Test script to verify trading signal flow from generation to execution
# This tests the complete pipeline: Signal → Trade Creation → Market Data Fetch → Execution

set -e

echo "=========================================="
echo "Trading Signal Flow Test"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Check if containers are running
echo -e "${YELLOW}Step 1: Checking Docker containers...${NC}"
if docker ps | grep -q portfolio_server; then
    echo -e "${GREEN}✓ portfolio_server is running${NC}"
else
    echo -e "${RED}✗ portfolio_server is NOT running${NC}"
    exit 1
fi

if docker ps | grep -q portfolio_celery_trading; then
    echo -e "${GREEN}✓ portfolio_celery_trading worker is running${NC}"
else
    echo -e "${RED}✗ portfolio_celery_trading worker is NOT running${NC}"
    exit 1
fi

echo ""

# Step 2: Test market data API accessibility
echo -e "${YELLOW}Step 2: Testing market data API accessibility...${NC}"
MARKET_RESPONSE=$(curl -s -w "%{http_code}" -o /tmp/market_response.json \
    "http://localhost:8000/api/market/quotes?symbols=RELIANCE" || echo "000")

if [ "$MARKET_RESPONSE" = "200" ]; then
    echo -e "${GREEN}✓ Market API is accessible${NC}"
    cat /tmp/market_response.json | jq '.' 2>/dev/null || cat /tmp/market_response.json
else
    echo -e "${RED}✗ Market API returned status: $MARKET_RESPONSE${NC}"
    cat /tmp/market_response.json 2>/dev/null || echo "No response"
fi

echo ""

# Step 3: Check Celery worker environment
echo -e "${YELLOW}Step 3: Checking Celery worker environment...${NC}"
docker exec portfolio_celery_trading printenv | grep -E "CELERY_WORKER_RUNNING|PORTFOLIO_SERVER_URL" || echo "Environment variables not set"

echo ""

# Step 4: Push a test trading signal
echo -e "${YELLOW}Step 4: Pushing test trading signal...${NC}"
cd /root/app/Agentic-Trading-Platform-Pathway/apps/portfolio-server

# Use the existing push_fake_signal script
python3 -c "
import sys
sys.path.insert(0, '/root/app/Agentic-Trading-Platform-Pathway/apps/portfolio-server')
from pipelines.nse.push_fake_signal import push_fake_signal

print('Pushing test signal for RELIANCE...')
push_fake_signal(
    symbol='RELIANCE',
    signal=1,  # BUY
    confidence=0.85,
    reference_price=2500.0
)
print('Signal pushed!')
"

echo ""

# Step 5: Monitor Celery logs for trade execution
echo -e "${YELLOW}Step 5: Monitoring Celery worker logs (30 seconds)...${NC}"
echo "Looking for market data fetch and trade execution..."
timeout 30 docker logs -f portfolio_celery_trading 2>&1 | grep -E "Fetched live price|Trade execution|HTTP|WebSocket|market" || true

echo ""

# Step 6: Check database for created trades
echo -e "${YELLOW}Step 6: Checking database for trades...${NC}"
docker exec portfolio_postgres psql -U portfolio_user -d portfolio_db -c \
    "SELECT id, symbol, side, quantity, price, status, created_at 
     FROM trades 
     WHERE symbol = 'RELIANCE' 
     ORDER BY created_at DESC 
     LIMIT 5;" 2>/dev/null || echo "Could not query database"

echo ""
echo "=========================================="
echo -e "${GREEN}Test Complete!${NC}"
echo "=========================================="
echo ""
echo "Summary:"
echo "1. If you see 'Fetched live price via HTTP' in logs → HTTP market data is working ✓"
echo "2. If you see 'Fetched live price via WebSocket' in logs → WebSocket is used (should only be in main server)"
echo "3. Check database for new RELIANCE trades with status='executed' or 'pending'"
echo ""
echo "If trades are not executing, check:"
echo "  - Is there an active trading agent in the portfolio?"
echo "  - Does the portfolio have sufficient capital?"
echo "  - Are there any errors in Celery worker logs?"
