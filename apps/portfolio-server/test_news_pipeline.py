#!/usr/bin/env python3
"""
Test script to manually run the news sentiment pipeline ONCE
and see all the Gemini API calls and Kafka publishes.
"""

import os
import sys
import logging
from pathlib import Path

# Setup paths
SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))

# Setup logging to see everything
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s: %(message)s'
)

from dotenv import load_dotenv
load_dotenv(SERVER_DIR / ".env")

from services.pipeline_service import PipelineService

if __name__ == "__main__":
    print("=" * 80)
    print("MANUAL NEWS SENTIMENT PIPELINE TEST")
    print("=" * 80)
    
    # Check API keys
    news_key = os.getenv("NEWS_ORG_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    
    print(f"\nAPI Keys:")
    print(f"  NEWS_ORG_API_KEY: {'✓ Present' if news_key else '✗ Missing'} ({len(news_key) if news_key else 0} chars)")
    print(f"  GEMINI_API_KEY: {'✓ Present' if gemini_key else '✗ Missing'} ({len(gemini_key) if gemini_key else 0} chars)")
    
    if not news_key or not gemini_key:
        print("\n⚠️  WARNING: Missing API keys - pipeline will use placeholders!")
    
    print("\n" + "=" * 80)
    print("Starting pipeline execution...")
    print("=" * 80 + "\n")
    
    # Run the pipeline
    logger = logging.getLogger("test")
    service = PipelineService(str(SERVER_DIR), logger=logger)
    metadata = service.run_news_sentiment_pipeline(top_k=3)
    
    print("\n" + "=" * 80)
    print("PIPELINE EXECUTION COMPLETE")
    print("=" * 80)
    print("\nMetadata:")
    import json
    print(json.dumps(metadata, indent=2))
    
    # Check output files
    news_dir = SERVER_DIR / "pipelines" / "news"
    print("\n" + "=" * 80)
    print("OUTPUT FILES")
    print("=" * 80)
    
    files_to_check = [
        "sentiment_articles.jsonl",
        "sector_analysis.json",
        "stock_recommendations.json",
        "news_pipeline_summary.json"
    ]
    
    for filename in files_to_check:
        filepath = news_dir / filename
        if filepath.exists():
            size = filepath.stat().st_size
            print(f"  ✓ {filename} ({size} bytes)")
            
            if filename == "sector_analysis.json":
                with open(filepath) as f:
                    data = json.load(f)
                    print(f"    Provider: {data.get('provider')}")
                    print(f"    Analysis length: {len(data.get('analysis', ''))} chars")
            
            elif filename == "stock_recommendations.json":
                with open(filepath) as f:
                    data = json.load(f)
                    print(f"    Recommendations count: {len(data) if isinstance(data, list) else 'N/A'}")
                    if isinstance(data, list) and len(data) > 0:
                        print(f"    First recommendation: {data[0].get('stock_name', 'N/A')}")
        else:
            print(f"  ✗ {filename} (NOT FOUND)")
    
    print("\n" + "=" * 80)
