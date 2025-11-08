#!/bin/bash

# =============================================================================
# Trade Execution Test Script
# =============================================================================
# This script executes test trades via the Portfolio API
# Configure the variables below and run: ./scripts/test-trades.sh
# =============================================================================

# ===========================
# CONFIGURATION VARIABLES
# ===========================

# API Configuration
API_URL="http://localhost:8000"
ACCESS_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImY4MjU1OGQ3LTRjYWQtNDU4OS1iYzc1LTJjMzg4YmQ1MDUzOCIsInJvbGUiOiJhZG1pbiIsIm9yZ2FuaXphdGlvbklkIjoiN2MzNjk4MzEtYmJkMS00MTdkLWJhMzQtYzcwN2FkNTBhMTYxIiwiaWF0IjoxNzYyNTk3ODAyLCJleHAiOjE3NjI2ODQyMDJ9.8K6LQcXHhsqTAqRK4uwcwpLRCaSnv14dyZ3h8uZfVfM"

# Portfolio ID (leave empty to auto-fetch)
PORTFOLIO_ID="34ecaf30-7aaf-4153-bf7b-18e847dc98fe"

# Trade Configuration
EXCHANGE="NSE"
SEGMENT="EQUITY"
ORDER_TYPE="market"  # Options: market, limit, stop, stop_loss, take_profit
TRADE_TYPE="cash"
SOURCE="test_script"

# Stocks to Trade (Array of symbol:side:quantity)
# Format: "SYMBOL:BUY|SELL:QUANTITY"
TRADES=(
  "RELIANCE:BUY:25"
  "TCS:BUY:15"
  "INFY:BUY:40"
  "HDFCBANK:BUY:20"
  "WIPRO:BUY:30"
  "ITC:BUY:50"
)

# ===========================
# SCRIPT START
# ===========================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Portfolio Trade Execution Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to print colored messages
print_success() {
  echo -e "${GREEN}✓${NC} $1"
}

print_error() {
  echo -e "${RED}✗${NC} $1"
}

print_info() {
  echo -e "${YELLOW}ℹ${NC} $1"
}

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    print_error "jq is not installed. Installing for JSON parsing..."
    echo "Please install jq: sudo apt-get install jq"
    exit 1
fi

# Get or create portfolio if PORTFOLIO_ID is empty
if [ -z "$PORTFOLIO_ID" ]; then
  print_info "Fetching portfolio..."
  
  PORTFOLIO_RESPONSE=$(curl -s -X GET "${API_URL}/api/portfolio/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json")
  
  PORTFOLIO_ID=$(echo "$PORTFOLIO_RESPONSE" | jq -r '.id')
  
  if [ "$PORTFOLIO_ID" == "null" ] || [ -z "$PORTFOLIO_ID" ]; then
    print_error "Failed to get portfolio"
    echo "$PORTFOLIO_RESPONSE" | jq '.'
    exit 1
  fi
  
  print_success "Portfolio ID: $PORTFOLIO_ID"
else
  print_info "Using Portfolio ID: $PORTFOLIO_ID"
fi

echo ""
print_info "Starting trade execution..."
echo ""

# Counter for successful trades
SUCCESS_COUNT=0
FAIL_COUNT=0

# Execute trades
for trade_config in "${TRADES[@]}"; do
  IFS=':' read -r SYMBOL SIDE QUANTITY <<< "$trade_config"
  
  echo -e "${BLUE}----------------------------------------${NC}"
  print_info "Executing: $SIDE $QUANTITY shares of $SYMBOL"
  
  # Build the trade request payload
  PAYLOAD=$(cat <<EOF
{
  "portfolio_id": "$PORTFOLIO_ID",
  "symbol": "$SYMBOL",
  "exchange": "$EXCHANGE",
  "segment": "$SEGMENT",
  "side": "$SIDE",
  "order_type": "$ORDER_TYPE",
  "quantity": $QUANTITY,
  "trade_type": "$TRADE_TYPE",
  "source": "$SOURCE"
}
EOF
)
  
  # Execute the trade
  RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_URL}/api/trades/" \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")
  
  # Extract HTTP status code and response body
  HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
  RESPONSE_BODY=$(echo "$RESPONSE" | head -n -1)
  
  if [ "$HTTP_CODE" -eq 200 ]; then
    SUCCESS=$(echo "$RESPONSE_BODY" | jq -r '.success')
    
    if [ "$SUCCESS" == "true" ]; then
      EXECUTED_PRICE=$(echo "$RESPONSE_BODY" | jq -r '.trades[0].executed_price')
      EXECUTED_QTY=$(echo "$RESPONSE_BODY" | jq -r '.trades[0].executed_quantity')
      STATUS=$(echo "$RESPONSE_BODY" | jq -r '.trades[0].status')
      
      print_success "Trade executed: $EXECUTED_QTY shares @ ₹$EXECUTED_PRICE (Status: $STATUS)"
      ((SUCCESS_COUNT++))
    else
      MESSAGE=$(echo "$RESPONSE_BODY" | jq -r '.message')
      print_error "Trade failed: $MESSAGE"
      ((FAIL_COUNT++))
    fi
  else
    ERROR_DETAIL=$(echo "$RESPONSE_BODY" | jq -r '.detail // .message // "Unknown error"')
    print_error "HTTP $HTTP_CODE: $ERROR_DETAIL"
    ((FAIL_COUNT++))
  fi
  
  echo ""
  
  # Optional: Add a small delay between trades
  sleep 0.5
done

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Execution Summary${NC}"
echo -e "${BLUE}========================================${NC}"
print_success "Successful trades: $SUCCESS_COUNT"
if [ $FAIL_COUNT -gt 0 ]; then
  print_error "Failed trades: $FAIL_COUNT"
fi
echo ""

# Fetch and display current positions
print_info "Fetching current positions..."
echo ""

POSITIONS_RESPONSE=$(curl -s -X GET "${API_URL}/api/portfolio/positions?page=1&limit=20" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json")

TOTAL_POSITIONS=$(echo "$POSITIONS_RESPONSE" | jq -r '.total')

if [ "$TOTAL_POSITIONS" == "null" ] || [ -z "$TOTAL_POSITIONS" ]; then
  print_error "Failed to fetch positions"
else
  print_success "Total open positions: $TOTAL_POSITIONS"
  echo ""
  echo -e "${YELLOW}Current Holdings:${NC}"
  echo "$POSITIONS_RESPONSE" | jq -r '.items[] | "  • \(.symbol): \(.quantity) shares @ ₹\(.current_price) | P&L: ₹\(.pnl) (\(.pnl_percentage)%)"'
fi

echo ""
print_success "Script completed!"

