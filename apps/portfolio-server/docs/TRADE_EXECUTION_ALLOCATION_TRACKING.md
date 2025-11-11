# Trade Execution & Allocation Tracking

## Overview

This document describes the updated trade execution system that tracks portfolio allocations and agent attribution without automatically creating take-profit/stop-loss orders.

## Key Changes

### 1. **No Automatic TP/SL Order Creation**
- Take-profit and stop-loss percentages are stored as **metadata only**
- These values are NOT used to automatically create pending orders
- TP/SL orders should only be created when explicitly requested by a trading strategy

### 2. **Agent Attribution Tracking**
- Every trade log now tracks which agent triggered it via `triggered_by` field in metadata
- For NSE pipeline trades: `triggered_by = "high_risk_agent"`
- This enables analytics and performance tracking per agent

### 3. **Portfolio Allocation Tracking**
- New field added to `Portfolio` model: `allocation_trades` (Json?)
- Each executed trade is appended to this array with details:
  ```json
  {
    "trade_log_id": "uuid",
    "symbol": "RELIANCE",
    "side": "BUY",
    "quantity": 10,
    "executed_price": 2500.50,
    "allocated_capital": 25000.00,
    "confidence": 0.85,
    "triggered_by": "high_risk_agent",
    "executed_at": "2025-11-12T..."
  }
  ```

### 4. **Portfolio Value Recalculation**
- After each trade execution, portfolio value is automatically recalculated
- Sums all open positions using current prices from market data service
- Updates `portfolio.current_value` field

## Database Schema Changes

### Portfolio Model
```prisma
model Portfolio {
  // ... existing fields ...
  allocation_trades Json?  // NEW: Array of executed trade allocations
  // ... existing fields ...
}
```

## Service Updates

### TradeExecutionService (`services/trade_execution_service.py`)

#### Modified Methods:
1. **`create_trade_log()`**
   - Now adds `triggered_by` to metadata from `job_row`
   - Default: `"high_risk_agent"` for NSE pipeline trades

2. **`execute_trade()`**
   - Removed automatic TP/SL order creation
   - Calls `_update_portfolio_allocation()` after successful execution
   - TP/SL percentages remain in metadata for future use

3. **`update_status()`**
   - Fixed JSON serialization for metadata field

#### New Methods:
1. **`_update_portfolio_allocation()`**
   - Adds executed trade to `portfolio.allocation_trades` array
   - Includes all trade details + triggered_by information
   - Calls `_recalculate_portfolio_value()` after update

2. **`_recalculate_portfolio_value()`**
   - Fetches all open positions for portfolio
   - Calculates total value from current prices
   - Updates `portfolio.current_value`

### Pipeline Service (`services/pipeline_service.py`)

#### Modified Methods:
1. **`execute_trading_signals()`**
   - Adds `triggered_by = "high_risk_agent"` to each job_row before persistence
   - Ensures all NSE pipeline trades are properly attributed

## Flow

### Trade Execution Flow (NSE Pipeline)
```
1. NSE Filing Signal Generated (high confidence)
   ↓
2. User Filtered (has 'high_risk' subscription)
   ↓
3. Portfolio Snapshot Created
   ↓
4. Trade Signal → Execution Payload
   ↓
5. Pathway Pipeline Calculates Allocation
   ↓
6. Job Row Created + triggered_by="high_risk_agent"
   ↓
7. Trade Log Persisted (with triggered_by in metadata)
   ↓
8. Trade Execution (simulated or live)
   ↓
9. Trade Added to portfolio.allocation_trades
   ↓
10. Portfolio Value Recalculated
    ↓
11. Email Notification Sent
```

## Testing

### Test File: `tests/test_trade_execution_allocation.py`

Validates:
- ✅ Trade logs track `triggered_by` agent
- ✅ Trades added to `portfolio.allocation_trades` array
- ✅ NO automatic TP/SL orders created
- ✅ Portfolio value recalculated after execution
- ✅ TP/SL percentages stored as metadata only

Run test:
```bash
cd apps/portfolio-server
export $(cat .env | grep -v '^#' | xargs)
python tests/test_trade_execution_allocation.py
```

## Migration

### Applied Changes:
1. Added `allocation_trades Json?` to Portfolio schema
2. Generated Prisma client with new field
3. Used `npx prisma db push` to sync database

### Command:
```bash
cd apps/portfolio-server
npx prisma db push
pyenv activate myenv && prisma generate
```

## Allocation Logic

Allocation percentages based on confidence:
- `confidence > 0.8` → 40% of portfolio value
- `confidence > 0.49` → 25% of portfolio value
- `confidence ≤ 0.49` → 0% (no trade)

TP/SL Configuration (metadata only):
- Take Profit: 3%
- Stop Loss: 1%

## Future Improvements

1. **Dynamic TP/SL**
   - Currently fixed at 3%/1%
   - Future: Make them confidence-based or strategy-specific

2. **Agent-Specific Strategies**
   - Different allocation logic per agent
   - Risk-adjusted sizing based on agent performance

3. **Portfolio Rebalancing**
   - Use `allocation_trades` history for rebalancing decisions
   - Track agent performance over time

4. **Advanced Order Types**
   - Trailing stop-loss
   - Bracket orders (entry + TP + SL as single atomic unit)
   - OCO (One-Cancels-Other) orders

## Related Files

- `apps/portfolio-server/services/trade_execution_service.py`
- `apps/portfolio-server/services/pipeline_service.py`
- `apps/portfolio-server/pipelines/nse/trade_execution_pipeline.py`
- `apps/portfolio-server/prisma/schema.prisma`
- `apps/portfolio-server/tests/test_trade_execution_allocation.py`
- `apps/portfolio-server/workers/trade_execution_worker.py`
- `apps/portfolio-server/emails/trade_executed.py`
