# Notification Server

Real-time notification ingestion and distribution service for the platform.

## 🏗️ Architecture Overview

The Notification Server is a Node.js/TypeScript service that:

- **Consumes Kafka Events**: Listens to trading signals, risk alerts, and system notifications
- **Redis Pub/Sub**: Publishes to Redis channels for real-time frontend delivery
- **Database Logging**: Persists notifications for history and audit trails
- **Multi-Channel Routing**: Routes notifications based on user subscriptions

### Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Runtime** | Node.js 18+ | JavaScript runtime |
| **Language** | TypeScript | Type-safe development |
| **Event Consumer** | KafkaJS | Kafka message consumption |
| **Pub/Sub** | Redis | Real-time message broadcasting |
| **Database** | PostgreSQL + Prisma | Notification persistence |
| **Monitoring** | Prometheus | Metrics collection |

### Data Flow

```
Kafka Topics              Notification Server          Frontend Clients
────────────              ───────────────────          ────────────────

nse_trade_logs ───┐      ┌───────────────┐           ┌──────────────┐
risk_alerts ──────┼─────▶│ Kafka Consumer│──Parse────▶│   Validator  │
low_risk_signals ─┘      └───────────────┘            └──────────────┘
                                 │                            │
                                 ▼                            ▼
                          ┌───────────────┐           ┌──────────────┐
                          │   PostgreSQL  │◀──Store───│   Database   │
                          │  Notification │            │    Logger    │
                          └───────────────┘            └──────────────┘
                                                              │
                                                              ▼
                                                       ┌──────────────┐
                                                       │ Redis Pub/Sub│
                                                       │   Publisher  │
                                                       └──────────────┘
                                                              │
                                                              ▼
                                                       ┌──────────────┐
                                                       │  WebSocket   │──▶ Clients
                                                       │  Subscribers │
                                                       └──────────────┘
```

## 🎯 Key Features

### 1. Kafka Event Consumption

**Monitored Topics:**
- `nse_pipeline_trade_logs` - Automated trade execution events
- `risk_agent_alerts` - Portfolio risk threshold breaches
- `low_risk_notifications` - Low-risk trading opportunities
- `news_pipeline_stock_recomendations` - AI stock recommendations

**Message Handling:**
- Schema validation with Zod
- Duplicate detection
- Error handling with retry logic
- Dead letter queue for failed messages

### 2. Redis Pub/Sub Distribution

**Channels:**
- `notifications:{userId}` - User-specific notifications
- `trades:{userId}` - Trade execution updates
- `alerts:{userId}` - Risk alert notifications
- `signals:all` - Broadcast trading signals

**Features:**
- Real-time message delivery
- Multi-subscriber support
- Persistent connection management

### 3. Notification Persistence

**Database Schema:**
```typescript
Notification {
  id: string
  userId: string
  type: 'TRADE' | 'ALERT' | 'SIGNAL' | 'SYSTEM'
  title: string
  message: string
  data: JSON
  read: boolean
  createdAt: DateTime
}
```

**Queries:**
- Fetch unread notifications
- Mark as read
- Delete old notifications (retention policy)

### 4. User Subscription Management

**Subscription Types:**
- Low-risk alerts
- High-risk alerts
- Algorithmic trading signals
- System notifications

**Routing Logic:**
- Check user subscription preferences
- Filter notifications by type
- Apply delivery rules

## ⚙️ Setup

### Prerequisites
- Node.js 18+
- PostgreSQL 16
- Redis 7
- Kafka 3.8.0

### Installation

```bash
# Install dependencies
pnpm install --filter notification_server

# Generate Prisma client
pnpm --filter notification_server prisma:generate
```

### Environment Variables

Create `.env` file in `apps/notification_server/`:

```env
NODE_ENV=development
PORT=8099
METRICS_PORT=9201

# Database
DATABASE_URL=postgresql://portfolio_user:portfolio_password@localhost:5434/portfolio_db

# Redis
REDIS_HOST=localhost
REDIS_PORT=6381
REDIS_URL=redis://localhost:6381

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
KAFKA_GROUP_ID=notification-service
KAFKA_CLIENT_ID=notification-server

# Monitoring
PROMETHEUS_ENABLED=true
```

### Running Locally

```bash
# Development mode
pnpm --filter notification_server dev

# Production mode
pnpm --filter notification_server build
pnpm --filter notification_server start
```

### Docker

```bash
# Using docker-compose
docker-compose up notification_server

# View logs
docker logs notification_server -f
```

## 🔄 Important Flows

### Trade Notification Flow

```
1. Trade Execution (Portfolio Server)
   └─▶ Order placed → Broker confirmation → Kafka publish

2. Kafka Consumption (Notification Server)
   └─▶ Message received → Schema validation → Trade log parsed

3. User Lookup
   └─▶ Portfolio ID → User ID → Subscription check

4. Notification Creation
   └─▶ Database insert → Redis publish → Frontend delivery

5. Frontend Display
   └─▶ WebSocket receive → Toast notification → Update history
```

### Risk Alert Flow

```
1. Risk Monitor Detection (Portfolio Server)
   └─▶ Price breach → Alert generation → Kafka publish

2. Event Processing
   └─▶ Alert received → Severity check → User notification

3. Multi-Channel Delivery
   └─▶ Redis pub/sub (real-time)
   └─▶ Database (history)
   └─▶ Email (optional, high-severity)

4. Acknowledgment
   └─▶ User reads notification → Mark as read → Update database
```

### Low-Risk Signal Flow

```
1. Signal Generation (Pathway Pipeline)
   └─▶ Market analysis → Low-risk opportunity → Kafka publish

2. Subscription Filter
   └─▶ Get subscribed users → Filter by preferences

3. Batch Notification
   └─▶ Create notifications for all subscribers
   └─▶ Redis pub/sub broadcast
   └─▶ Database bulk insert

4. User Action
   └─▶ View signal → Review details → Optional trade execution
```

## 📊 Monitoring & Metrics

Prometheus metrics exposed at `/metrics` (port 9201):

**Key Metrics:**
- `kafka_messages_consumed_total` - Total messages by topic
- `kafka_consumer_lag` - Consumer lag per partition
- `redis_publishes_total` - Redis pub/sub message count
- `notifications_created_total` - Notifications by type
- `notification_processing_duration_seconds` - Processing latency
- `nodejs_heap_size_used_bytes` - Memory usage

**Health Checks:**
- Kafka connection status
- Redis connection status
- Database connection status

**Grafana Dashboard:**
Access at http://localhost:3001 (Notification Server Dashboard)

## 🧪 Testing

```bash
# Run tests
pnpm --filter notification_server test

# Integration tests
pnpm --filter notification_server test:integration

# Test Kafka consumption
# Publish test message to topic
docker exec pathway-kafka kafka-console-producer.sh \
  --bootstrap-server localhost:9092 \
  --topic nse_pipeline_trade_logs
```

## 🔐 Security Considerations

1. **Message Validation**: Zod schema validation for all Kafka messages
2. **User Privacy**: Notifications scoped to user context
3. **Data Retention**: Automatic deletion of old notifications (90 days)
4. **Redis Security**: Password-protected Redis instances
5. **Database Access**: Connection pooling with SSL

## 🐛 Troubleshooting

### Kafka Consumer Not Receiving Messages

```bash
# Check consumer group status
docker exec pathway-kafka kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --group notification-service \
  --describe

# View topic messages
docker exec pathway-kafka kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 \
  --topic risk_agent_alerts \
  --from-beginning
```

### Redis Connection Issues

```bash
# Test Redis connection
redis-cli -h localhost -p 6381 ping

# Monitor pub/sub activity
redis-cli -p 6381 pubsub channels "notifications:*"

# Check subscribers
redis-cli -p 6381 pubsub numsub notifications:user123
```

### Missing Notifications

```bash
# Check database records
psql -h localhost -p 5434 -U portfolio_user -d portfolio_db \
  -c "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 10;"

# View service logs
docker logs notification_server -f | grep ERROR

# Check metrics
curl http://localhost:9201/metrics | grep notifications_created
```

## 📚 Related Documentation

- [Architecture Overview](../../docs/ARCHITECTURE.md)
- [Kafka Topics](../../docs/README.md#event-schemas)
- [Portfolio Server Integration](../portfolio-server/README.md)

---

**Built with ❤️ for real-time notifications**
