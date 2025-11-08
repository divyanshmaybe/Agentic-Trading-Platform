# NSE Filings Sentiment Analysis & Trading Signals

Professional real-time trading signal generation from NSE corporate announcements using LLM-powered sentiment analysis and **Kafka streaming**.

## 🚀 Features

- **Live NSE Scraping**: Real-time monitoring of NSE corporate announcements
- **Smart Filtering**: XBRL-based relevance filtering for material events
- **PDF Analysis**: Automatic download and parsing of filing documents
- **LLM Sentiment**: Google Gemini-powered sentiment analysis
- **Trading Signals**: Automated BUY/SELL/HOLD signal generation
- **✨ Kafka Integration**: Real-time signal streaming via Kafka
- **Dual Output**: JSONL files + Kafka topics for flexible consumption

## 📋 Quick Start

### 1. Start Kafka
```bash
# From project root
./kafka.sh

# Verify Kafka is running
docker ps | grep pathway-kafka
```

### 2. Install Dependencies
```bash
cd pw-scripts/NSE_FILLINGS
pip install -r requirements.txt
```

### 3. Set API Key
```bash
export GEMINI_API_KEY='your-google-gemini-api-key'
```

### 4. Run Pipeline
```bash
python nse_live_demo.py
```

### 5. Monitor Signals
```bash
# Terminal 1: Watch JSONL file
tail -f trading_signals.jsonl | jq '.'

# Terminal 2: Subscribe to Kafka
./../../subscriber.sh --channel nse_filings_trading_signal --from-beginning
```

## 🔧 Kafka Integration

### Environment Variables

```bash
# Enable/disable Kafka output (default: true)
export KAFKA_OUTPUT_ENABLED=true

# Kafka topic name (default: nse_filings_trading_signal)
export KAFKA_TOPIC=nse_filings_trading_signal

# Kafka bootstrap servers (default: localhost:9092)
export KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Scraper interval in seconds (default: 60)
export SCRAPER_INTERVAL=60
```

### Kafka Output Configuration

The pipeline automatically publishes trading signals to Kafka with the following settings:

- **Topic**: `nse_filings_trading_signal` (configurable)
- **Format**: JSON
- **Compression**: Snappy
- **Acks**: All (for reliability)
- **Client ID**: `nse-filings-sentiment`

### Signal Format

Signals are published in JSON format:

```json
{
  "symbol": "RELIANCE",
  "filing_time": "2024-01-15T10:30:00",
  "signal": 1,
  "explanation": "Company announced acquisition of competitor..."
}
```

**Signal Values:**
- `1` = BUY (Positive sentiment)
- `-1` = SELL (Negative sentiment)
- `0` = HOLD (Neutral sentiment)

## 📊 Architecture

```
NSE API (Live)
     ↓
Live Scraper (60s interval)
     ↓
XBRL Filter (Relevance)
     ↓
PDF Parser (Extract Text)
     ↓
Gemini LLM (Sentiment)
     ↓
Signal Parser (BUY/SELL/HOLD)
     ↓
     ├─→ JSONL File (trading_signals.jsonl)
     └─→ Kafka Topic (nse_filings_trading_signal)
```

## 🧪 Testing

### Test 1: Check Kafka Connection
```bash
# List Kafka topics
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh \
  --list --bootstrap-server localhost:9092
```

### Test 2: Manual Kafka Consumer
```bash
docker run --rm -it --network host edenhill/kcat:1.7.1 \
  kcat -b localhost:9092 -t nse_filings_trading_signal -C -o beginning
```

### Test 3: Monitor Pipeline
```bash
# Terminal 1: Run pipeline
export GEMINI_API_KEY='your-key'
python nse_live_demo.py

# Terminal 2: Subscribe to signals
./../../subscriber.sh --channel nse_filings_trading_signal --from-beginning

# Terminal 3: Watch JSONL file
tail -f trading_signals.jsonl
```

## 🐛 Troubleshooting

### Issue: "Unknown topic or partition"
**Cause:** Topic doesn't exist yet  
**Solution:** Topic is created automatically when first signal is published. Wait for scraper to find a relevant filing.

### Issue: "No signals appearing in Kafka"
**Checks:**
1. Is Kafka running? `docker ps | grep pathway-kafka`
2. Is `KAFKA_OUTPUT_ENABLED=true`?
3. Check pipeline logs for errors
4. Verify NSE has new announcements (market hours: 09:15-15:30 IST)

### Issue: "JSONL file gets cleared"
**Cause:** Pathway `jsonlines.write()` operates in streaming mode  
**Solution:** This is normal behavior. Kafka provides persistent storage. Use Kafka consumer for historical data.

### Issue: "Kafka connection refused"
**Solution:**
```bash
# Stop and restart Kafka
docker rm -f pathway-kafka
./kafka.sh

# Verify Kafka is listening
docker exec pathway-kafka /opt/kafka/bin/kafka-topics.sh \
  --list --bootstrap-server localhost:9092
```

## 📚 Files

### Core Pipeline
- `nse_live_demo.py` - **Main entry point** (with Kafka)
- `nse_live_scraper.py` - Live NSE API scraper
- `nse_filings_sentiment.py` - Sentiment analysis + Kafka output
- `nse_backtest.py` - Backtesting module

### Configuration
- `requirements.txt` - Python dependencies
- `staticdata.csv` - Filing type impact scenarios (optional)
- `.env` - Environment variables (create this)

### Auto-Generated
- `trading_signals.jsonl` - JSONL output
- `processed_announcements.json` - Deduplication tracker
- `docs/` - PDF download directory (auto-cleaned)

## 🔐 Security

- **API Keys**: Never commit to git, use environment variables
- **Kafka Auth**: Use SASL/SSL in production
- **PDF Cleanup**: Auto-deleted after processing
- **Rate Limiting**: Respects NSE API limits

## 🚦 Production Deployment

### Docker Compose
```yaml
version: '3.8'
services:
  kafka:
    image: apache/kafka:3.8.0
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      # ... (see kafka.sh for full config)

  nse-filings:
    build: .
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - KAFKA_BOOTSTRAP_SERVERS=kafka:9092
      - KAFKA_OUTPUT_ENABLED=true
    depends_on:
      - kafka
    restart: unless-stopped
```

### Systemd Service
```ini
[Unit]
Description=NSE Filings Trading Signals
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=/path/to/pw-scripts/NSE_FILLINGS
Environment="GEMINI_API_KEY=your-key"
Environment="KAFKA_BOOTSTRAP_SERVERS=kafka:9092"
ExecStart=/usr/bin/python3 nse_live_demo.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## 📈 Performance

- **Scraper**: ~1-2s per poll
- **PDF Parsing**: ~2-5s per document
- **LLM Analysis**: ~3-10s per filing
- **Kafka Latency**: <100ms
- **Memory**: ~500MB base + 50MB per concurrent filing

## 📞 Support

- **Pathway Docs**: https://pathway.com/docs
- **Kafka Docs**: https://kafka.apache.org/documentation
- **Gemini API**: https://ai.google.dev/docs

---

**Built with ❤️ using Pathway, Google Gemini, and Apache Kafka**
