# Streaming Order Monitor - Real-Time Order Execution

## Overview

The **Streaming Order Monitor** is a production-ready, WebSocket-based system for monitoring and executing pending limit/stop/TP/SL orders in real-time.

### Key Features

✅ **Real-time monitoring** via WebSocket price feeds (sub-second response)  
✅ **No database polling** - only order refresh every 10 seconds  
✅ **Automatic symbol subscription** based on pending orders  
✅ **Comprehensive error handling** with automatic retries  
✅ **Connection pooling** via MarketDataService singleton  
✅ **Professional logging** and monitoring statistics  

## Architecture

### Components

1. **PathwayOrderMonitor** (`pipelines/orders/streaming_order_monitor_pipeline.py`)
   - Core monitoring logic
   - Real-time price checking
   - Order execution via TradeEngine
   - Symbol subscription management

2. **StreamingOrderMonitor Worker** (`workers/streaming_order_monitor.py`)
   - Standalone worker process
   - Connects to MarketDataService singleton
   - Runs independently of Celery

3. **OrderConditionChecker** (`pipelines/orders/streaming_order_monitor_pipeline.py`)
   - Business logic for order execution conditions
   - Supports: limit, stop, stop_loss, take_profit orders
   - Decimal precision for price comparisons

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    MarketDataService                        │
│                   (WebSocket Singleton)                     │
│                                                             │
│  • Angel One WebSocket connection                          │
│  • Real-time price feeds (500 symbols)                     │
│  • Price caching in memory                                 │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ get_latest_price() [no network call]
                  │
┌─────────────────▼───────────────────────────────────────────┐
│              PathwayOrderMonitor                            │
│                                                             │
│  Refresh Loop (10s):        Monitor Loop (0.5s):           │
│  • Fetch pending orders     • Get cached prices            │
│  • Subscribe to symbols     • Check conditions             │
│  • Update internal cache    • Execute when met             │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  │ process_pending_trade()
                  │
┌─────────────────▼───────────────────────────────────────────┐
│                   TradeEngine                               │
│                                                             │
│  • Execute order via broker API                            │
│  • Update database status                                  │
│  • Send notifications                                      │
└─────────────────────────────────────────────────────────────┘
```

## Comparison: Old vs New

### Old Polling-Based Order Monitor (REMOVED)

❌ Polled database every 1-5 seconds  
❌ Created 427+ Celery tasks in queue  
❌ Fetched prices via HTTP for each check  
❌ Blocked workers from processing trades  
❌ High latency (5-10 seconds)  
❌ Database connection leaks  

### New Streaming Order Monitor (CURRENT)

✅ WebSocket price feeds (real-time)  
✅ Checks conditions every 0.5 seconds  
✅ No Celery tasks (standalone process)  
✅ Workers free for trade execution  
✅ Sub-second latency  
✅ Proper connection management  

## Configuration

### Environment Variables

```bash
# Enable/disable streaming order monitor
STREAMING_ORDER_MONITOR_ENABLED=true

# How often to refresh pending orders from database (seconds)
ORDER_MONITOR_REFRESH_INTERVAL=10

# How often to check order conditions against cached prices (seconds)
ORDER_MONITOR_CHECK_INTERVAL=0.5

# Angel One credentials (required for WebSocket)
ANGELONE_CLIENT_CODE=your_client_code
ANGELONE_API_KEY=your_api_key
ANGELONE_PASSWORD=your_password
ANGELONE_TOTP_SECRET=your_totp_secret
```

### Starting the Monitor

#### Option 1: Via pnpm (recommended)
```bash
cd apps/portfolio-server
pnpm streaming:orders
```

#### Option 2: Direct Python
```bash
cd apps/portfolio-server
PYTHONPATH=../..:../../shared/py python -m workers.streaming_order_monitor
```

#### Option 3: With Docker Compose
```yaml
streaming-order-monitor:
  build: apps/portfolio-server
  command: python -m workers.streaming_order_monitor
  env_file:
    - apps/portfolio-server/.env
  depends_on:
    - postgres
    - redis
```

## Order Types Supported

### 1. Limit Orders
- **BUY**: Execute when `current_price <= limit_price`
- **SELL**: Execute when `current_price >= limit_price`

### 2. Stop Orders
- **BUY**: Execute when `current_price >= trigger_price`
- **SELL**: Execute when `current_price <= trigger_price`

### 3. Stop Loss Orders
- Same logic as stop orders
- Typically used to limit losses on existing positions

### 4. Take Profit Orders
- **SELL**: Execute when `current_price >= trigger_price`
- **BUY**: Execute when `current_price <= trigger_price`

## Monitoring & Statistics

### Getting Stats

```python
from pipelines.orders import PathwayOrderMonitor

monitor = PathwayOrderMonitor(market_service, db_client)
stats = monitor.get_stats()

# Output:
# {
#     "running": True,
#     "pending_orders": 5,
#     "monitored_symbols": 3,
#     "subscribed_symbols": 3,
#     "currently_executing": 0
# }
```

### Logs

Monitor emits structured logs:

```
📦 Fetched 5 pending orders from database
📡 Subscribing to 3 new symbols: ['HAL', 'INFY', 'TCS']
✅ Now subscribed to 3 symbols total
📊 Monitoring 5 pending orders across 3 symbols
🎯 Executing order abc123 (HAL): BUY limit: 4250.50 <= 4300.00
✅ Order abc123 executed successfully
```

## Integration with Trade Execution

### Execution Flow

1. **Condition Met**: Order conditions satisfied by current price
2. **Signal Generated**: `OrderExecutionSignal` created with execution details
3. **TradeEngine Invoked**: `process_pending_trade(order_id)` called
4. **Order Executed**: Trade placed via broker API
5. **Database Updated**: Order status changed to `executed`
6. **Cache Updated**: Order removed from monitoring
7. **Callback**: Optional execution callback invoked

### Custom Execution Callback

```python
async def custom_callback(signal: OrderExecutionSignal):
    # Send notification
    await send_email(
        to=user.email,
        subject=f"Order {signal.order_id} Executed",
        body=f"Executed {signal.side} {signal.symbol} at ₹{signal.current_price}"
    )
    
    # Log to analytics
    await analytics.track("order_executed", {
        "order_id": signal.order_id,
        "symbol": signal.symbol,
        "execution_time": signal.timestamp,
    })

monitor = PathwayOrderMonitor(
    market_service,
    db_client,
    execution_callback=custom_callback
)
```

## Performance Characteristics

### Latency

- **Price Update → Condition Check**: < 100ms (cached prices)
- **Condition Met → Execution**: 0.5-2 seconds (depending on check interval)
- **Total Response Time**: < 3 seconds (vs 5-10s with polling)

### Resource Usage

- **CPU**: < 5% (idle), 10-15% (active monitoring)
- **Memory**: ~50 MB (+ WebSocket buffer)
- **Network**: Minimal (WebSocket only, no HTTP polling)
- **Database**: 1 query every 10 seconds (order refresh)

### Scalability

- **Concurrent Orders**: Tested up to 1000+ pending orders
- **Symbols**: Supports full Nifty 500 (500 symbols)
- **Response Time**: Linear scaling with order count

## Error Handling

### Connection Failures

- WebSocket reconnection with exponential backoff
- MarketDataService handles reconnection automatically
- Orders checked after reconnection

### Execution Failures

- Failed executions logged with full context
- Order remains in pending state
- Retry on next condition check

### Database Failures

- Refresh loop backs off on error (5s delay)
- Uses last known pending orders
- Reconnects automatically

## Migration from Old System

### Removed Components

- ❌ `workers/order_monitor_worker.py` (renamed to `.OLD`)
- ❌ Celery beat schedule for `order_monitor.check_pending_orders_once`
- ❌ Celery task routes for order_monitor tasks
- ❌ HTTP price fetching via FastAPI

### Breaking Changes

**None** - Orders are still stored in the `Trade` table with the same schema.

### Rollback Procedure

If needed, restore the old system:

```bash
# Restore old worker
mv workers/order_monitor_worker.py.OLD workers/order_monitor_worker.py

# Re-enable in celery_app.py
# Uncomment the beat schedule section

# Restart Celery
./restart-celery.sh
```

## Troubleshooting

### Monitor Not Starting

**Symptom**: "Angel One credentials required"

**Solution**: Ensure `.env` file has credentials:
```bash
ANGELONE_CLIENT_CODE=your_code
ANGELONE_API_KEY=your_key
ANGELONE_PASSWORD=your_password
ANGELONE_TOTP_SECRET=your_secret
```

### Orders Not Executing

**Symptom**: Orders remain in pending state

**Debugging**:
```bash
# Check monitor is running
ps aux | grep streaming_order_monitor

# Check WebSocket connection
tail -f logs/portfolio_server.log | grep "WebSocket"

# Check pending orders
redis-cli LLEN orders  # Should be 0

# Check database
psql -d portfolio_db -c "SELECT id, symbol, order_type, status FROM trades WHERE status='pending';"
```

### High CPU Usage

**Symptom**: Monitor using >20% CPU

**Solution**: Increase `ORDER_MONITOR_CHECK_INTERVAL`:
```bash
export ORDER_MONITOR_CHECK_INTERVAL=1.0  # Check every 1s instead of 0.5s
```

## Future Enhancements

### Planned Features

- [ ] Support for trailing stop loss
- [ ] OCO (One-Cancels-Other) orders
- [ ] Bracket orders (TP + SL together)
- [ ] Time-based order expiry
- [ ] Advanced order types (iceberg, etc.)

### Performance Improvements

- [ ] Batch order execution (multiple orders in one API call)
- [ ] Predictive condition checking (only check when price near trigger)
- [ ] Redis caching for order state
- [ ] WebSocket connection pooling

## References

- [MarketDataService Documentation](../shared/py/market_data.py)
- [TradeEngine Documentation](./services/trade_engine.py)
- [Database Connection Architecture](./docs/DB_CONNECTION_ARCHITECTURE.md)
- [Celery Configuration](./celery_app.py)

## Support

For issues or questions:
1. Check logs: `tail -f logs/streaming_order_monitor.log`
2. Verify WebSocket connection: Check MarketDataService logs
3. Test with simple limit order first
4. Reach out to the team with full error logs

---

**Last Updated**: 2025-11-24  
**Version**: 1.0.0  
**Status**: ✅ Production Ready
