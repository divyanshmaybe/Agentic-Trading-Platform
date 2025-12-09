"""
Push Fake NSE Signal - Simple test script to trigger trade execution

This script directly sends a fake signal event to the Celery task queue,
bypassing the NSE scraper entirely. Just run this while your server and
Celery worker are running.

Usage:
    python push_fake_signal.py --symbol RELIANCE --signal 1 --confidence 0.85 --price 2500
"""

import argparse
import sys
import os
from datetime import datetime
import uuid

# Add parent to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from celery_app import celery_app

def push_fake_signal(
    symbol: str = "RELIANCE",
    signal: int = 1,
    confidence: float = 0.85,
    reference_price: float = 2500.0
):
    """
    Push a fake NSE signal to Celery task queue.
    
    Args:
        symbol: Stock symbol (e.g., RELIANCE, TCS, INFY)
        signal: Trading signal (-1=SELL, 0=HOLD, 1=BUY)
        confidence: Confidence score (0.0 to 1.0)
        reference_price: Mock stock price
    """
    signal_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    signal_event = {
        "signal_id": signal_id,
        "symbol": symbol,
        "trading_signal": signal,
        "confidence_score": confidence,
        "reference_price": reference_price,
        "timestamp": timestamp,
        "announcement_title": f"[FAKE TEST] {symbol} - Strategic Update",
        "announcement_desc": f"Synthetic signal for testing trade execution (signal={signal})",
        "pdf_url": f"https://fake-nse-test.example.com/{signal_id}.pdf",
        "concise_explanation": (
            f"FAKE SIGNAL for testing: {symbol} shows {'bullish' if signal > 0 else 'bearish' if signal < 0 else 'neutral'} "
            f"sentiment with {confidence:.1%} confidence."
        ),
        # Include timing metadata for consistency (0 for fake signals)
        "llm_delay_ms": 0,
        "llm_start_time": timestamp,
        "llm_end_time": timestamp,
    }
    
    print(f"\n{'='*60}")
    print(f"PUSHING FAKE NSE SIGNAL TO CELERY")
    print(f"{'='*60}")
    print(f"Symbol: {symbol}")
    print(f"Signal: {signal} ({'BUY' if signal > 0 else 'SELL' if signal < 0 else 'HOLD'})")
    print(f"Confidence: {confidence:.2%}")
    print(f"Price: ₹{reference_price}")
    print(f"Signal ID: {signal_id}")
    print(f"{'='*60}\n")
    
    # Send to Celery task queue
    try:
        task = celery_app.send_task(
            "pipeline.trade_execution.process_signal",
            args=[signal_event],
            queue="trading",  # Route to TRADING queue
        )
        print(f"✅ Signal pushed to Celery!")
        print(f"   Task ID: {task.id}")
        print(f"   Task Name: pipeline.trade_execution.process_signal")
        print(f"   Queue: trading")
        print(f"\n💡 Check your Celery worker logs to see trade execution results")
        print(f"   Look for: 'Trade execution pipeline produced X actionable job(s)'")
        return task
    except Exception as e:
        print(f"❌ Failed to push signal: {e}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Push fake NSE signal to Celery for testing trade execution"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="RELIANCE",
        help="Stock symbol (default: RELIANCE)"
    )
    parser.add_argument(
        "--signal",
        type=int,
        choices=[-1, 0, 1],
        default=1,
        help="Trading signal: -1=SELL, 0=HOLD, 1=BUY (default: 1)"
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.85,
        help="Confidence score 0.0-1.0 (default: 0.85)"
    )
    parser.add_argument(
        "--price",
        type=float,
        default=2500.0,
        help="Reference price (default: 2500.0)"
    )
    
    args = parser.parse_args()
    
    task = push_fake_signal(
        symbol=args.symbol.upper(),
        signal=args.signal,
        confidence=args.confidence,
        reference_price=args.price,
    )
    
    if task:
        print(f"\n✅ Done! Monitor your Celery worker logs for results.")
        sys.exit(0)
    else:
        sys.exit(1)
