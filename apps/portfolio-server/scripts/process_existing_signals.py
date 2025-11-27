#!/usr/bin/env python3
"""
Process existing signals from trading_signals.jsonl that were generated
but never triggered trades because they were written before the pipeline
subscription was active.
"""

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT.parent))
sys.path.insert(0, str(PROJECT_ROOT.parent / "shared" / "py"))

from celery_app import celery_app
from datetime import datetime

def process_existing_signals():
    """Read trading_signals.jsonl and enqueue BUY signals (signal=1) to Celery."""
    
    signals_file = PROJECT_ROOT / "pipelines" / "nse" / "trading_signals.jsonl"
    
    if not signals_file.exists():
        print(f"❌ Signals file not found: {signals_file}")
        return
    
    print(f"📂 Reading signals from: {signals_file}\n")
    
    buy_signals = []
    
    # Read all signals
    with open(signals_file, 'r') as f:
        for line in f:
            try:
                signal_data = json.loads(line.strip())
                if signal_data.get('signal') == 1:  # Only BUY signals
                    buy_signals.append(signal_data)
            except json.JSONDecodeError:
                continue
    
    print(f"Found {len(buy_signals)} BUY signals in file\n")
    
    if not buy_signals:
        print("⚠️  No BUY signals to process")
        return
    
    # Process each BUY signal
    for signal_data in buy_signals:
        symbol = signal_data.get('symbol', 'UNKNOWN')
        confidence = signal_data.get('confidence', 0.7)
        filing_time = signal_data.get('filing_time', '')
        
        print(f"🚀 Processing BUY signal: {symbol}")
        print(f"   Confidence: {confidence:.2%}")
        print(f"   Filing time: {filing_time}")
        
        # Prepare signal payload for Celery
        signal_payload = {
            "symbol": symbol,
            "signal": 1,
            "explanation": signal_data.get('explanation', ''),
            "confidence": confidence,
            "reference_price": signal_data.get('reference_price'),
            "filing_time": filing_time,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "manual_reprocessing",
        }
        
        try:
            # Send to Celery task queue
            task = celery_app.send_task(
                "pipeline.trade_execution.process_signal",
                args=[signal_payload],
                queue="pipelines",
            )
            print(f"   ✅ Enqueued to Celery (Task ID: {task.id[:8]}...)\n")
        except Exception as e:
            print(f"   ❌ Failed to enqueue: {e}\n")
    
    print(f"{'='*60}")
    print(f"✅ Processed {len(buy_signals)} BUY signals")
    print(f"{'='*60}")
    print("\n💡 Check Celery worker logs to see trade execution:")
    print("   - Flower dashboard: http://localhost:5555")
    print("   - Or watch logs: docker-compose logs -f portfolio_celery")

if __name__ == "__main__":
    process_existing_signals()
