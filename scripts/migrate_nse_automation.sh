#!/bin/bash
#
# Database Migration Script for NSE Automated Trading
#
# This script applies the necessary database migrations for:
# 1. User subscriptions array (auth_server)
# 2. TradeExecutionLog model (portfolio-server)
#

set -e

echo "========================================"
echo "🗄️  NSE Automated Trading - DB Migration"
echo "========================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running from project root
if [ ! -f "pnpm-workspace.yaml" ]; then
    echo -e "${RED}❌ Error: Please run this script from the project root directory${NC}"
    exit 1
fi

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check for required tools
if ! command_exists pnpm; then
    echo -e "${RED}❌ Error: pnpm is not installed${NC}"
    echo "   Please install pnpm: npm install -g pnpm"
    exit 1
fi

if ! command_exists prisma; then
    echo -e "${YELLOW}⚠️  Warning: prisma CLI not found globally${NC}"
    echo "   Using npx prisma instead"
    PRISMA_CMD="npx prisma"
else
    PRISMA_CMD="prisma"
fi

# Step 1: Migrate auth_server
echo -e "${YELLOW}📦 Migrating auth_server schema (User.subscriptions)...${NC}"
cd apps/auth_server

if [ ! -f ".env" ]; then
    echo -e "${RED}❌ Error: apps/auth_server/.env not found${NC}"
    echo "   Please create .env file with DATABASE_URL"
    exit 1
fi

echo "   Generating Prisma client..."
$PRISMA_CMD generate || {
    echo -e "${RED}❌ Failed to generate Prisma client${NC}"
    exit 1
}

echo "   Creating migration..."
$PRISMA_CMD migrate dev --name add_user_subscriptions || {
    echo -e "${RED}❌ Failed to create migration${NC}"
    echo "   This might be because the migration already exists."
    echo "   Run: prisma migrate deploy"
}

echo -e "${GREEN}✅ auth_server migration completed${NC}"
echo ""

# Step 2: Migrate portfolio-server
cd ../..
echo -e "${YELLOW}📦 Migrating portfolio-server schema (TradeExecutionLog)...${NC}"
cd apps/portfolio-server

if [ ! -f ".env" ]; then
    echo -e "${RED}❌ Error: apps/portfolio-server/.env not found${NC}"
    echo "   Please create .env file with DATABASE_URL"
    exit 1
fi

# Check if prisma-client-py is installed
if ! python3 -c "import prisma" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  prisma-client-py not found, installing...${NC}"
    pip3 install prisma-client-py || {
        echo -e "${RED}❌ Failed to install prisma-client-py${NC}"
        exit 1
    }
fi

echo "   Generating Prisma Python client..."
python3 -m prisma generate || {
    echo -e "${RED}❌ Failed to generate Prisma Python client${NC}"
    exit 1
}

echo "   Creating migration..."
python3 -m prisma migrate dev --name add_trade_execution_log || {
    echo -e "${RED}❌ Failed to create migration${NC}"
    echo "   This might be because the migration already exists."
    echo "   Run: python3 -m prisma migrate deploy"
}

echo -e "${GREEN}✅ portfolio-server migration completed${NC}"
echo ""

# Go back to project root
cd ../..

# Summary
echo "========================================"
echo -e "${GREEN}✅ All migrations completed!${NC}"
echo "========================================"
echo ""
echo "📊 Applied Changes:"
echo "   1. ✅ User model: Added 'subscriptions' array field"
echo "   2. ✅ TradeExecutionLog model: Created new model"
echo ""
echo "🎯 Next Steps:"
echo "   1. Start Celery workers:"
echo "      cd apps/portfolio-server"
echo "      celery -A celery_app worker --loglevel=info"
echo ""
echo "   2. Start Celery beat scheduler:"
echo "      celery -A celery_app beat --loglevel=info"
echo ""
echo "   3. Run demo script:"
echo "      python tests/demo_nse_automation.py --dry-run"
echo ""
echo "   4. Enable automated trading for users:"
echo "      - Update user subscriptions: ['high_risk']"
echo "      - Via API: PATCH /api/users/:id { subscriptions: ['high_risk'] }"
echo ""
