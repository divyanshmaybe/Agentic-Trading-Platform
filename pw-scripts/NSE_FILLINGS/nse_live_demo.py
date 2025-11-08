#!/usr/bin/env python3
"""
NSE Live Filings Demo with Kafka Integration

This script demonstrates the complete end-to-end pipeline:
1. Scrape live NSE announcements
2. Filter relevant filings
3. Analyze sentiment with LLM
4. Generate trading signals
5. Publish to Kafka topic
6. Write to JSONL file

Usage:
    python nse_live_demo.py

Environment Variables:
    KAFKA_OUTPUT_ENABLED - Enable Kafka output (default: true)
    KAFKA_TOPIC - Kafka topic name (default: nse_filings_trading_signal)
    KAFKA_BOOTSTRAP_SERVERS - Kafka servers (default: localhost:9092)
    SCRAPER_INTERVAL - Scraping interval in seconds (default: 60)
    GEMINI_API_KEY - Google Gemini API key (required)
"""

import os
import sys
import pathway as pw
from dotenv import load_dotenv

# Import pipeline components
from nse_live_scraper import create_nse_scraper_input
from nse_filings_sentiment import create_nse_filings_pipeline

# Load environment variables
load_dotenv()


def main():
    """Run the complete NSE filings analysis pipeline with Kafka integration"""
    
    # Configuration
    scraper_interval = int(os.getenv("SCRAPER_INTERVAL", "60"))
    kafka_enabled = os.getenv("KAFKA_OUTPUT_ENABLED", "true").lower() in ("true", "1", "yes")
    kafka_topic = os.getenv("KAFKA_TOPIC", "nse_filings_trading_signal")
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    
    # Validate Gemini API key
    if not os.getenv("GEMINI_API_KEY"):
        print("❌ ERROR: GEMINI_API_KEY environment variable is required!")
        print("   Please set your Google Gemini API key:")
        print("   export GEMINI_API_KEY='your-api-key-here'")
        sys.exit(1)
    
    # Print configuration
    print("=" * 80)
    print("NSE FILINGS LIVE ANALYSIS - KAFKA INTEGRATION")
    print("=" * 80)
    print(f"📊 Scraper Interval: {scraper_interval} seconds")
    print(f"📁 JSONL Output: trading_signals.jsonl")
    print(f"🔌 Kafka Output: {'ENABLED' if kafka_enabled else 'DISABLED'}")
    if kafka_enabled:
        print(f"   📡 Kafka Topic: {kafka_topic}")
        print(f"   🌐 Kafka Servers: {kafka_servers}")
    print("=" * 80)
    print()
    
    # Step 1: Create scraper input
    print("🔍 Step 1: Initializing NSE live scraper...")
    filings_input = create_nse_scraper_input(refresh_interval=scraper_interval)
    print("✅ Scraper initialized")
    print()
    
    # Step 2: Create sentiment analysis pipeline
    print("🧠 Step 2: Creating sentiment analysis pipeline...")
    trading_signals = create_nse_filings_pipeline(
        filings_source=filings_input,
        static_data_path="staticdata.csv",
        output_path="trading_signals.jsonl",
        kafka_output=kafka_enabled,
        kafka_topic=kafka_topic,
        kafka_servers=kafka_servers
    )
    print("✅ Pipeline created")
    print()
    
    # Step 3: Run the pipeline
    print("🚀 Step 3: Starting pipeline...")
    print("=" * 80)
    print("Pipeline is now running. Press Ctrl+C to stop.")
    print("=" * 80)
    print()
    print("📌 What's happening:")
    print("   1. Scraping NSE announcements every", scraper_interval, "seconds")
    print("   2. Filtering relevant filings (acquisitions, board meetings, etc.)")
    print("   3. Downloading and parsing PDF attachments")
    print("   4. Analyzing sentiment with Google Gemini LLM")
    print("   5. Generating trading signals (BUY/SELL/HOLD)")
    print("   6. Writing to trading_signals.jsonl")
    if kafka_enabled:
        print(f"   7. Publishing to Kafka topic: {kafka_topic}")
    print()
    print("💡 Monitor signals:")
    print(f"   - JSONL: tail -f trading_signals.jsonl")
    if kafka_enabled:
        print(f"   - Kafka: ./subscriber.sh --channel {kafka_topic} --from-beginning")
    print()
    print("=" * 80)
    print()
    
    try:
        pw.run()
    except KeyboardInterrupt:
        print()
        print("=" * 80)
        print("⚠️  Pipeline stopped by user")
        print("=" * 80)
        sys.exit(0)


if __name__ == "__main__":
    main()
