# -*- coding: utf-8 -*-
"""
Risk Agent Demo - Pathway

This demo:
1. Creates a portfolio of assets to monitor
2. Monitors stock prices in real-time
3. Detects when stocks fall below thresholds
4. Fetches news for declining stocks
5. Uses Groq LLM to assess risk and generate alerts

Usage:
  python RISK_AGENT/risk_agent_demo.py
"""

import os
import pathway as pw
from risk_agent_pipeline import (
    build_risk_agent_pipeline,
    PortfolioAssetSchema
)
from risk_agent_backtest import (
    create_risk_backtest_pipeline,
    compute_risk_metrics
)


def create_sample_portfolio() -> pw.Table:
    """Create a sample portfolio for monitoring."""
    # Sample portfolio data
    portfolio_data = [
        ("BANDHANBNK.NS", "Bandhan Bank", 10, 180.0, 6),
        ("RELIANCE.NS", "Reliance Industries", 5, 2500.0, 5),
        ("TCS.NS", "Tata Consultancy Services", 3, 3500.0, 4),
    ]
    
    return pw.debug.table_from_rows(
        schema=PortfolioAssetSchema,
        rows=portfolio_data
    )


def main():
    print("=" * 60)
    print("Risk Agent - Portfolio Monitoring Pipeline")
    print("=" * 60)
    
    # Load API keys
    news_api_key = os.getenv("NEWS_API_KEY", "")
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    
    if not news_api_key:
        print("WARNING: NEWS_API_KEY not set. News fetch will fail.")
    if not groq_api_key:
        print("WARNING: GROQ_API_KEY not set. LLM risk assessment will fail.")
    
    # Create portfolio
    print("\n[Step 1] Creating portfolio...")
    portfolio = create_sample_portfolio()
    print("✓ Portfolio created")
    
    # Build pipeline
    print("\n[Step 2] Building risk monitoring pipeline...")
    alerts = build_risk_agent_pipeline(
        portfolio=portfolio,
        news_api_key=news_api_key,
        groq_api_key=groq_api_key,
        check_interval_ms=1800000  # 30 minutes
    )
    
    # Create backtest pipeline
    print("\n[Step 3] Building backtest pipeline...")
    backtest_results = create_risk_backtest_pipeline(alerts)
    backtest_metrics = compute_risk_metrics(backtest_results)
    
    # Write outputs
    print("\n[Step 4] Setting up outputs...")
    alerts_file = "risk_alerts.jsonl"
    backtest_file = "risk_backtest_results.jsonl"
    metrics_file = "risk_backtest_metrics.jsonl"
    
    pw.io.jsonlines.write(alerts, alerts_file)
    pw.io.jsonlines.write(backtest_results, backtest_file)
    pw.io.jsonlines.write(backtest_metrics, metrics_file)
    
    print("Running pipeline (will monitor continuously)...")
    print("Press Ctrl+C to stop")
    print(f"Alerts will be written to: {alerts_file}")
    print(f"Backtest results will be written to: {backtest_file}")
    print(f"Backtest metrics will be written to: {metrics_file}")
    print("=" * 60)
    
    try:
        pw.run(monitoring_level=pw.MonitoringLevel.NONE)
    except KeyboardInterrupt:
        print("\n\nPipeline stopped by user.")
        print(f"✓ Alerts written to {alerts_file}")
        print(f"✓ Backtest results written to {backtest_file}")
        print(f"✓ Metrics written to {metrics_file}")
    except Exception as e:
        print(f"\nPipeline completed with status: {type(e).__name__}")
        if os.path.exists(alerts_file):
            print(f"✓ Alerts written to {alerts_file}")
        if os.path.exists(backtest_file):
            print(f"✓ Backtest results written to {backtest_file}")
        if os.path.exists(metrics_file):
            print(f"✓ Metrics written to {metrics_file}")


if __name__ == "__main__":
    main()

