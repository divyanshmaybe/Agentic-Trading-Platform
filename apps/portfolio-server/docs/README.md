# Portfolio Server Documentation

This directory contains comprehensive documentation for the Portfolio Server component of the AgentInvest trading platform.

---

## 📚 Documentation Index

### **Core Architecture**
- **[Risk Monitoring Architecture](./RISK_MONITORING_ARCHITECTURE.md)** ⭐
  - Symbol-based risk monitoring system
  - Pathway pipeline for batch processing
  - Kafka alert publishing
  - Email notification service
  - Performance comparisons and testing guides

### **Market Data & Candles**
- **[Market Candles Complete](./MARKET_CANDLES_COMPLETE.md)** 📘
  - Complete implementation guide
  - Angel One SmartAPI integration
  - Historical OHLCV data fetching
  - All candle endpoints and features

- **[Market Candles API](./MARKET_CANDLES_API.md)**
  - REST API endpoints for OHLCV data
  - WebSocket real-time candle streaming
  - Interval support (1m, 5m, 15m, 1h, 1d)
  
- **[Candles Architecture](./CANDLES_ARCHITECTURE.md)**
  - System design and data flow
  - Pathway pipeline implementation
  - Kafka integration
  - Storage and caching strategy
  
- **[Candles Implementation](./CANDLES_IMPLEMENTATION.md)**
  - Technical implementation details
  - Code walkthrough
  - Database schema
  
- **[Candles Quick Reference](./CANDLES_QUICK_REFERENCE.md)**
  - Quick start guide
  - Common operations
  - API examples

### **Email & Notifications**
- **[Email Service Setup](./EMAIL_SERVICE_SETUP.md)** 🔧
  - SendGrid configuration
  - Gmail SMTP setup
  - Testing email delivery
  - Troubleshooting guide

---

## 🚀 Quick Start

### **1. Setup Email Service**
```bash
# Configure environment variables
export EMAIL_HOST=smtp.sendgrid.net
export EMAIL_USERNAME=apikey
export EMAIL_PASSWORD=SG.your_api_key_here

# Test configuration
cd apps/portfolio-server
python3 << 'EOF'
import sys
sys.path.insert(0, '../../shared/py')
from emailService import EmailService
service = EmailService()
print("✅" if service.health_check() else "❌")
EOF
```

### **2. Enable Risk Monitoring**
```bash
# .env configuration
PORTFOLIO_RISK_MONITOR_ENABLED=true
PORTFOLIO_RISK_MONITOR_INTERVAL=900  # 15 minutes

# Start Celery worker
celery -A celery_app worker --loglevel=info

# Start Celery beat (scheduler)
celery -A celery_app beat --loglevel=info
```

### **3. Test Candles API**
```bash
# Start server
pnpm dev

# Fetch historical candles
curl "http://localhost:8001/api/candles/RELIANCE?interval=1h&start_time=2024-01-01T00:00:00Z&end_time=2024-01-02T00:00:00Z"

# Subscribe to WebSocket
wscat -c ws://localhost:8001/ws/candles/RELIANCE/1m
```

---

## 🏗️ Architecture Overview

```
Portfolio Server
├── Risk Monitoring Pipeline
│   ├── Symbol-based iteration (500 symbols vs 10k positions)
│   ├── Pathway batch processing
│   ├── Kafka alert publishing
│   └── Email notification batching
│
├── Market Candles System
│   ├── REST API (historical data)
│   ├── WebSocket (real-time streaming)
│   ├── Pathway aggregation pipeline
│   └── Database storage (TimescaleDB)
│
├── Portfolio Management
│   ├── Position tracking
│   ├── Trade execution
│   └── Performance analytics
│
└── Services
    ├── Prisma ORM (PostgreSQL)
    ├── Market Data (AngelOne WebSocket)
    ├── Kafka Producer/Consumer
    └── Email Service (SMTP)
```

---

## 📊 Key Features

### **Symbol-Based Risk Monitoring**
- ✅ **95% fewer price fetches** (500 vs 10,000 for 10k positions)
- ✅ **Database-level filtering** via SQL WHERE clauses
- ✅ **Only affected users processed** (not entire user base)
- ✅ **2-3x faster** processing time
- ✅ **Better scaling** with user growth

### **Market Candles System**
- ✅ **Multiple timeframes** (1m, 5m, 15m, 1h, 1d)
- ✅ **Real-time WebSocket** streaming
- ✅ **Historical data API** with time range queries
- ✅ **Pathway aggregation** for efficient OHLCV calculation
- ✅ **TimescaleDB storage** for time-series optimization

### **Email Notifications**
- ✅ **Batched alerts** (one email per user, not per holding)
- ✅ **Async delivery** via Celery tasks
- ✅ **Automatic retries** on SMTP failures
- ✅ **SendGrid integration** for production
- ✅ **HTML templates** with formatted alerts

---

## 🧪 Testing

### **Test Risk Monitoring**
```bash
cd apps/portfolio-server

# Test symbol-based logic
python3 << 'EOF'
import sys
import asyncio
sys.path.insert(0, '.')
sys.path.insert(0, '../../shared/py')

from utils.symbol_based_risk_monitor import fetch_unique_holdings
from services.prisma_client import get_prisma_client

async def test():
    client = get_prisma_client()
    await client.connect()
    symbols = await fetch_unique_holdings(client)
    print(f"✅ {len(symbols)} unique symbols found")
    await client.disconnect()

asyncio.run(test())
EOF
```

### **Test Candles API**
```bash
# Test historical data
python3 test_candles_api.py

# Test WebSocket streaming
wscat -c ws://localhost:8001/ws/candles/RELIANCE/1m
```

### **Test Email Service**
```bash
python3 << 'EOF'
import sys
import asyncio
sys.path.insert(0, '../../shared/py')
from emailService import EmailService

async def test():
    service = EmailService()
    await service.send_email(
        to="test@example.com",
        subject="Test Alert",
        body="This is a test"
    )

asyncio.run(test())
EOF
```

---

## 🔧 Configuration

### **Environment Variables**

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/agentinvest

# Redis
REDIS_URL=redis://localhost:6379/0

# Kafka
KAFKA_ENABLED=true
KAFKA_BROKER_URL=localhost:9092

# Risk Monitor
PORTFOLIO_RISK_MONITOR_ENABLED=true
PORTFOLIO_RISK_MONITOR_INTERVAL=900

# Email
EMAIL_HOST=smtp.sendgrid.net
EMAIL_USERNAME=apikey
EMAIL_PASSWORD=SG.your_api_key_here

# AngelOne
ANGELONE_API_KEY=your_api_key
ANGELONE_CLIENT_ID=your_client_id
ANGELONE_PASSWORD=your_password
ANGELONE_TOTP_SECRET=your_totp_secret

# Regime Service
REGIME_SERVICE_URL=http://localhost:8002
```

---

## 📖 Documentation Standards

### **File Naming**
- Use `UPPERCASE_SNAKE_CASE.md` for documentation files
- Keep filenames descriptive and specific
- Group related docs (e.g., `CANDLES_*.md`)

### **Structure**
Each documentation file should include:
1. **Overview**: What the system does
2. **Architecture**: How it works
3. **Implementation**: Technical details
4. **Testing**: How to test it
5. **Troubleshooting**: Common issues

### **Code Examples**
- Include working code snippets
- Use bash for terminal commands
- Show expected output
- Provide error handling examples

---

## 🤝 Contributing

When adding new features:
1. Create documentation in `docs/` folder
2. Update this README index
3. Include architecture diagrams (ASCII art)
4. Add testing instructions
5. Document configuration options

---

## 📝 Additional Resources

- **[Root Architecture](../../../docs/ARCHITECTURE.md)**: System-wide architecture
- **[AngelOne Setup](../../../docs/ANGELONE_SETUP.md)**: Broker integration guide
- **[Docker Compose](../../../docs/DOCKER_COMPOSE_README.md)**: Container orchestration
- **[Main README](../../../README.md)**: Project overview

---

## 🆘 Support

### **Common Issues**

1. **Risk monitor not running**: Check Celery beat is running
2. **No email alerts**: Verify EMAIL_* environment variables
3. **Candles not updating**: Check AngelOne WebSocket connection
4. **Database errors**: Ensure Prisma migrations are run

### **Debug Commands**

```bash
# Check Celery status
celery -A celery_app inspect active

# Test database connection
python3 -c "from db import db; print('✅' if db.is_connected() else '❌')"

# Verify Kafka connection
python3 -c "from services.kafka_service import get_kafka_service; print(get_kafka_service().health_check())"

# Check logs
tail -f logs/portfolio-server.log
```

---

**Last Updated**: November 11, 2025  
**Maintained By**: AgentInvest Team
