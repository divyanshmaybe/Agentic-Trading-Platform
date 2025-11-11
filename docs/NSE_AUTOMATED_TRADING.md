# NSE Automated Trading System

Complete documentation for the automated trade execution system that processes NSE filing signals and executes trades for subscribed users.

## 🎯 Overview

The NSE Automated Trading System is a fully automated pipeline that:

1. **Monitors NSE filings** via the NSE filings sentiment pipeline
2. **Generates trading signals** using LLM-based sentiment analysis
3. **Allocates capital** based on signal confidence tiers
4. **Executes trades** automatically for subscribed users
5. **Creates protective orders** (take-profit +3%, stop-loss -1%)
6. **Monitors orders continuously** using the order monitoring worker
7. **Logs all trades** to database and Kafka for audit trails

## 📋 Architecture

```
NSE Filing → LLM Analysis → Trading Signal → Pathway Pipeline → Trade Execution
                                  ↓                    ↓                ↓
                          Kafka Topic         Capital Allocation   Order Creation
                                                     ↓                ↓
                                              High-Risk Users     TP/SL Orders
                                                     ↓                ↓
                                              Trade Execution    Order Monitor
                                                     ↓                ↓
                                              Portfolio Update  Condition Check
```

### Key Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **NSE Filings Pipeline** | Pathway | Scrapes and analyzes NSE filings |
| **Signal Generation** | Gemini/Groq LLM | Generates BUY/SELL signals with confidence |
| **Trade Execution Pipeline** | Pathway | Processes signals, allocates capital, creates trade jobs |
| **Trade Execution Service** | Python/FastAPI | Persists trades, publishes to Kafka |
| **Order Monitor Worker** | Celery + Pathway | Continuously monitors pending TP/SL orders |
| **Trade Execution Worker** | Celery | Executes trades (simulated or live broker) |

## 🔑 Key Features

### 1. User Subscription Model

Users opt-in to automated trading via the `subscriptions` array:

```typescript
// User model (auth_server)
model User {
  subscriptions String[] @default([])  // ["low_risk", "high_risk", "algo"]
}
```

**Subscription Types:**
- `high_risk`: NSE filing signals (high volatility, quick trades)
- `low_risk`: Conservative signals (future implementation)
- `algo`: Algorithm-based signals (future implementation)

### 2. Allocation Logic

Capital allocation is **deterministic** and based on signal confidence:

```python
def get_allocation(capital: float, confidence: float) -> float:
    if confidence > 0.8:    # 80%+
        return capital * 0.40  # 40% allocation
    elif confidence > 0.49:  # 49%-80%
        return capital * 0.25  # 25% allocation
    else:
        return 0.0  # No trade
```

**Example:**
- Portfolio value: ₹500,000
- Signal confidence: 85%
- Allocation: ₹200,000 (40%)
- Stock price: ₹2,500
- Quantity: 80 shares

### 3. Risk Management

Every executed trade automatically creates two protective orders:

**Take-Profit Order (+3%)**
- Locks in profits when price rises 3%
- Automatically executes SELL when target hit

**Stop-Loss Order (-1%)**
- Limits losses to 1% of entry price
- Automatically executes SELL when triggered

**Example:**
```
Entry Price: ₹2,500
Take-Profit: ₹2,575 (+3%)
Stop-Loss:   ₹2,475 (-1%)
```

### 4. Pathway Integration

The system uses **Pathway** extensively for:

**Trade Execution Pipeline** (`pipelines/nse/trade_execution_pipeline.py`):
- Queue-based subject for incoming signals
- Deterministic allocation calculation
- Quantity resolution based on price
- Filtering of actionable trades (confidence > 0.49, qty > 0)
- Real-time processing with incremental computation

**Order Monitoring** (`workers/order_monitor_worker.py`):
- Live price streaming via WebSocket
- Continuous condition checking (every 5 seconds)
- Batch processing of pending orders
- Stale order cleanup (24-hour timeout)

## 🚀 Setup & Deployment

### Prerequisites

```bash
# Install dependencies
cd apps/portfolio-server
pip install -r requirements.txt

# Install Prisma clients
cd ../auth_server
npm install
npx prisma generate

cd ../portfolio-server
python -m prisma generate
```

### Database Migration

```bash
# Run migration script from project root
chmod +x scripts/migrate_nse_automation.sh
./scripts/migrate_nse_automation.sh
```

This creates:
1. `User.subscriptions` array in auth_server
2. `TradeExecutionLog` model in portfolio-server

### Environment Variables

**portfolio-server/.env**:
```bash
# Database
DATABASE_URL="postgresql://user:pass@localhost:5432/portfolio"
SHADOW_DATABASE_URL="postgresql://user:pass@localhost:5432/portfolio_shadow"

# Market Data
MARKET_DATA_WEBSOCKET_URL="ws://localhost:8080/ws"

# Trading
ANGELONE_TRADING_ENABLED=false  # Set to true for live trading
TRADE_FEE_RATE=0.0005           # 0.05%
TRADE_TAX_RATE=0.00025          # 0.025%

# Order Monitor
ORDER_MONITOR_ENABLED=true
ORDER_MONITOR_INTERVAL=5         # Check every 5 seconds
ORDER_MONITOR_BATCH_SIZE=100

# Kafka
KAFKA_BOOTSTRAP_SERVERS="localhost:9092"
TRADE_EXECUTION_TOPIC="trade_execution_requests"
NSE_FILINGS_SIGNAL_TOPIC="nse_filings_trading_signal"

# LLM
GEMINI_API_KEY="your_gemini_key"
OPENAI_API_KEY="your_openai_key"
```

### Starting Services

```bash
# Terminal 1: Redis (required for Celery)
redis-server

# Terminal 2: Celery Worker
cd apps/portfolio-server
celery -A celery_app worker --loglevel=info

# Terminal 3: Celery Beat (scheduler)
celery -A celery_app beat --loglevel=info

# Terminal 4: FastAPI Server
python main.py

# Terminal 5: NSE Pipeline (optional, for live filings)
python pipelines/nse/nse_live_scraper.py
```

## 📊 Usage

### 1. Enable Automated Trading for a User

**Via API**:
```bash
curl -X PATCH http://localhost:3001/api/users/USER_ID \
  -H "Content-Type: application/json" \
  -d '{"subscriptions": ["high_risk"]}'
```

**Via Database**:
```sql
UPDATE users
SET subscriptions = ARRAY['high_risk']
WHERE email = 'user@example.com';
```

### 2. Run Demo Script

```bash
cd apps/portfolio-server
python tests/demo_nse_automation.py --dry-run
```

**Expected Output:**
```
🚀 NSE Automated Trading Demo
========================================

🔧 Setting up test user with high_risk subscription...
✅ Created demo portfolio with ₹500,000 capital

📊 Simulating NSE filing signal...
   Symbol: RELIANCE
   Signal: BUY
   Confidence: 85.0%

💰 Allocation Logic Demonstration
   Available Capital: ₹500,000.00
   Signal Confidence: 85.0%
   ✅ Allocated Capital: ₹200,000.00 (40.0%)

⚙️  Processing signal through automation pipeline...
   Jobs Created: 1
   Celery Tasks Dispatched: 1

✅ Found 1 trade execution log(s)
   Trade ID: abc-123
   Symbol: RELIANCE
   Quantity: 80
   Status: simulated_executed

🎯 Found 2 pending TP/SL order(s)
   Order ID: tp-123
   Type: TAKE_PROFIT
   Trigger Price: ₹2,575.00

   Order ID: sl-456
   Type: STOP_LOSS
   Trigger Price: ₹2,475.00
```

### 3. Monitor Order Execution

Orders are monitored continuously by the Celery beat scheduler:

```bash
# Check Celery logs
tail -f celery.log

# Expected log output:
📊 Order Monitor Worker started (checking every 5s)
👀 Monitoring 2 pending orders for portfolio abc-123
📡 Subscribing to live prices: RELIANCE
🎯 Executing order tp-123 (RELIANCE): condition met (price ₹2,580 >= ₹2,575)
✅ Successfully executed order tp-123
✅ Trade execution email sent to user@example.com
```

## 🧪 Testing

### Unit Tests

```bash
cd apps/portfolio-server
pytest tests/test_trade_execution_pipeline.py -v
```

### Integration Tests

```bash
# Requires live database
export ENABLE_DB_TESTS=true
pytest tests/test_order_monitoring.py -v
```

### Full System Test

```bash
# 1. Start all services (Redis, Celery, FastAPI)
# 2. Run demo script
python tests/demo_nse_automation.py --live

# 3. Watch logs for:
#    - Signal processed
#    - Trade created
#    - TP/SL orders created
#    - Orders monitored
#    - Email notifications sent
```

## 📈 Database Schema

### TradeExecutionLog

```prisma
model TradeExecutionLog {
  id                String   @id @default(uuid())
  request_id        String   @unique
  user_id           String
  portfolio_id      String?
  symbol            String
  side              String   // "BUY" | "SELL"
  quantity          Int
  allocated_capital Decimal  @db.Decimal(20, 4)
  confidence        Decimal  @db.Decimal(9, 6)
  take_profit_pct   Decimal  @db.Decimal(9, 6)
  stop_loss_pct     Decimal  @db.Decimal(9, 6)
  reference_price   Decimal  @db.Decimal(20, 4)
  status            String   @default("pending")
  signal_id         String?
  broker_order_id   String?
  executed_price    Decimal? @db.Decimal(20, 4)
  executed_quantity Int      @default(0)
  error_message     String?
  metadata          Json?    @default("{}")
  created_at        DateTime @default(now())
  updated_at        DateTime @updatedAt
  
  portfolio Portfolio? @relation(fields: [portfolio_id], references: [id])
}
```

## 🔍 Monitoring & Debugging

### Check Trade Execution Logs

```sql
SELECT 
  id,
  symbol,
  side,
  quantity,
  allocated_capital,
  confidence,
  status,
  created_at
FROM trade_execution_logs
WHERE user_id = 'USER_ID'
ORDER BY created_at DESC
LIMIT 10;
```

### Check Pending Orders

```sql
SELECT 
  id,
  symbol,
  order_type,
  side,
  quantity,
  trigger_price,
  status,
  source
FROM trades
WHERE 
  portfolio_id = 'PORTFOLIO_ID'
  AND status = 'pending'
  AND source = 'auto_tp_sl'
ORDER BY created_at DESC;
```

### Check Kafka Topics

```bash
# List topics
kafka-topics.sh --bootstrap-server localhost:9092 --list

# Consume signals
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic nse_filings_trading_signal \
  --from-beginning

# Consume trade requests
kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic trade_execution_requests \
  --from-beginning
```

## 🛡️ Safety Features

1. **Subscription-based opt-in**: Users must explicitly enable automated trading
2. **Confidence thresholds**: Only trades with confidence > 49% are executed
3. **Allocation limits**: Maximum 40% of portfolio per trade
4. **Automatic TP/SL**: Every trade has protective orders
5. **Stale order cleanup**: Orders older than 24 hours are auto-cancelled
6. **Simulation mode**: Default mode prevents accidental live trading
7. **Error handling**: Retry logic with exponential backoff
8. **Audit trails**: All trades logged to database and Kafka

## 🚦 Production Checklist

- [ ] Enable live trading: `ANGELONE_TRADING_ENABLED=true`
- [ ] Configure broker credentials (AngelOne API keys)
- [ ] Set up monitoring alerts (email, Slack, PagerDuty)
- [ ] Configure backup database (for SHADOW_DATABASE_URL)
- [ ] Set up Kafka replication (min 3 brokers)
- [ ] Enable SSL/TLS for database and Kafka
- [ ] Configure rate limiting for LLM APIs
- [ ] Set up log aggregation (ELK stack)
- [ ] Configure auto-scaling for Celery workers
- [ ] Test disaster recovery procedures

## 📞 Support

For issues or questions:
- Check logs: `celery.log`, `fastapi.log`
- Run diagnostics: `python tests/verify_workers.py`
- Review architecture: `docs/ARCHITECTURE.md`

## 🔄 Future Enhancements

- [ ] Support for options trading
- [ ] Multi-broker integration (Zerodha, Upstox)
- [ ] Machine learning-based allocation
- [ ] Dynamic TP/SL based on volatility
- [ ] Portfolio rebalancing integration
- [ ] Real-time P&L tracking
- [ ] Mobile push notifications
- [ ] Advanced risk metrics (VaR, Sharpe ratio)
