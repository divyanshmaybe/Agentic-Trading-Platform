# -*- coding: utf-8 -*-
"""
Complete News Sentiment Based Trading Demo - Pathway

This demo:
1. Fetches news for all 23 sectors
2. Analyzes sentiment with FinBERT
3. Calls Gemini trading agent for sector signals
4. Fetches technical indicators for Nifty 500 stocks
5. Calls Gemini stock recommender for final recommendations

Usage:
  python NEWS_SENTIMENT/news_sentiment_demo.py
"""

import os
import json
import pathway as pw
from news_sentiment_pipeline import (
    NEWS_STREAMS,
    build_news_sentiment_pipeline,
    trading_agent_llm,
    compute_technical_indicators,
    stock_recommender,
    StreamSchema,
    StockSchema
)


def create_all_streams() -> pw.Table:
    """Create table with all 23 news streams."""
    rows = [(stream, query, 3) for stream, query in NEWS_STREAMS.items()]
    return pw.debug.table_from_rows(
        schema=StreamSchema,
        rows=rows
    )


def load_nifty500_stocks() -> pw.Table:
    """Load Nifty 500 stocks. For demo, using a sample. In production, load from CSV."""
    # Sample stocks - in production, load from ind_nifty500list.csv
    sample_stocks = [
        ("RELIANCE", "Oil Gas & Consumable Fuels"),
        ("TCS", "Information Technology"),
        ("HDFCBANK", "Financial Services"),
        ("INFY", "Information Technology"),
        ("ICICIBANK", "Financial Services"),
        ("HINDUNILVR", "Fast Moving Consumer Goods"),
        ("SBIN", "Financial Services"),
        ("BHARTIARTL", "Telecommunication"),
        ("KOTAKBANK", "Financial Services"),
        ("LT", "Construction"),
    ]
    # For full demo, uncomment and load from CSV:
    # import pandas as pd
    # df = pd.read_csv('ind_nifty500list.csv')
    # sample_stocks = [(row['Symbol'], row['Industry']) for _, row in df.iterrows()]
    
    return pw.debug.table_from_rows(
        schema=StockSchema,
        rows=sample_stocks
    )


def main():
    print("=" * 60)
    print("Complete News Sentiment Trading Pipeline")
    print("=" * 60)
    
    # Load API keys
    news_api_key = os.getenv("NEWS_ORG_API_KEY")
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    print(f"News API Key: {news_api_key}")
    print(f"Gemini API Key: {gemini_api_key}")
    if not news_api_key:
        print("WARNING: NEWS_ORG_API_KEY not set. News fetch will fail.")
    if not gemini_api_key:
        print("WARNING: GEMINI_API_KEY not set. LLM calls will fail.")
    
    # Step 1: Create streams and stocks tables
    print("\n[Step 1] Creating news streams and stock tables...")
    streams = create_all_streams()
    stocks = load_nifty500_stocks()
    print(f"✓ Created {len(NEWS_STREAMS)} news streams")
    print(f"✓ Loaded stocks table (sample - 10 stocks)")
    
    # Step 2: Build sentiment pipeline
    print("\n[Step 2] Building news sentiment pipeline...")
    
    if not news_api_key:
        print("ERROR: NEWS_ORG_API_KEY not set!")
        return
    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY not set!")
        return
    
    sentiment_articles = build_news_sentiment_pipeline(streams, news_api_key, top_k_default=3)
    
    # Write sentiment articles to file
    print("\n[Step 3] Running sentiment pipeline...")
    sentiment_output = "sentiment_articles.jsonl"
    pw.io.jsonlines.write(sentiment_articles, sentiment_output)
    pw.run(monitoring_level=pw.MonitoringLevel.NONE)
    
    print(f"✓ Sentiment analysis complete! Articles written to {sentiment_output}")
    
    # Step 4: Aggregate sentiment data and call trading agent
    print("\n[Step 4] Aggregating sentiment data and calling Gemini trading agent...")
    import pandas as pd
    try:
        df = pd.read_json(sentiment_output, lines=True)
        print(f"  Loaded {len(df)} sentiment-analyzed articles")
        
        # Aggregate by stream
        sentiment_by_stream = {}
        for _, row in df.iterrows():
            stream = row['stream']
            if stream not in sentiment_by_stream:
                sentiment_by_stream[stream] = []
            sentiment_by_stream[stream].append({
                'title': row['title'],
                'content': row['content'],
                'sentiment': row['sentiment'],
                'url': row.get('url')
            })
        
        print(f"  Aggregated into {len(sentiment_by_stream)} streams")
        
        # Call trading agent
        sector_analysis = trading_agent_llm(json.dumps(sentiment_by_stream), gemini_api_key)
        print("✓ Trading agent analysis complete")
        
        # Step 5: Fetch technical indicators
        print("\n[Step 5] Fetching technical indicators for stocks...")
        tech_indicators_list = []
        sample_stocks = [
            ("RELIANCE", "Oil Gas & Consumable Fuels"),
            ("TCS", "Information Technology"),
            ("HDFCBANK", "Financial Services"),
            ("INFY", "Information Technology"),
            ("ICICIBANK", "Financial Services"),
            ("HINDUNILVR", "Fast Moving Consumer Goods"),
            ("SBIN", "Financial Services"),
            ("BHARTIARTL", "Telecommunication"),
            ("KOTAKBANK", "Financial Services"),
            ("LT", "Construction"),
        ]

        for symbol, industry in sample_stocks:
            print(f"  Fetching indicators for {symbol}...")
            try:
                indicators = compute_technical_indicators(symbol)
                if not indicators:
                    continue
                indicators["Industry"] = industry
                tech_indicators_list.append(indicators)
            except Exception as exc:
                print(f"    Error fetching {symbol}: {exc}")
                continue

        tech_json_str = json.dumps(tech_indicators_list)
        print(f"✓ Fetched indicators for {len(tech_indicators_list)} stocks")
        
        # Step 6: Call stock recommender
        print("\n[Step 6] Calling Gemini stock recommender...")
        final_recommendations = stock_recommender(sector_analysis, tech_json_str, gemini_api_key=gemini_api_key)
        print("✓ Stock recommendations complete")

        if isinstance(final_recommendations, list):
            final_recommendations_str = json.dumps(final_recommendations, indent=2)
        else:
            final_recommendations_str = (
                json.dumps(final_recommendations, indent=2)
                if isinstance(final_recommendations, dict)
                else str(final_recommendations)
            )

        # Write recommendations to file
        output_file = "stock_recommendations.txt"
        print(f"\n[Step 7] Writing recommendations to {output_file}...")
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("STOCK RECOMMENDATIONS\n")
            f.write("=" * 60 + "\n\n")
            f.write("SECTOR ANALYSIS:\n")
            f.write("-" * 60 + "\n")
            f.write(sector_analysis)
            f.write("\n\n" + "=" * 60 + "\n")
            f.write("STOCK RECOMMENDATIONS:\n")
            f.write("-" * 60 + "\n")
            f.write(final_recommendations_str)
            f.write("\n")

        print(f"✓ Recommendations written to {output_file}")
        print(f"   File location: {os.path.abspath(output_file)}")

        # Print preview
        print("\n" + "=" * 60)
        print("Pipeline Complete!")
        print("=" * 60)
        print("\nRecommendations Preview:")
        print("-" * 60)
        print(final_recommendations_str[:1000] + "..." if len(final_recommendations_str) > 1000 else final_recommendations_str)
                
    except Exception as e:
        print(f"Error processing data: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
