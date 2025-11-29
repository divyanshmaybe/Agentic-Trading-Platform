#!/usr/bin/env python3
"""
Standalone script to run Industry Indicators Pipeline with Angel One API

This script initializes the pipeline, fetches real data from Angel One,
computes indicators, and displays the results.
"""

import sys
import logging
import os
from pathlib import Path

# Add server directory and project root to path
server_dir = Path(__file__).resolve().parent
project_root = server_dir.parent.parent
sys.path.insert(0, str(server_dir))
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "shared" / "py"))
sys.path.insert(0, str(project_root / "middleware" / "py"))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Run the industry indicators pipeline with Angel One API"""
    
    print("=" * 80)
    print("🚀 Industry Indicators Pipeline - Angel One API")
    print("=" * 80)
    
    try:
        # Import required modules
        from pipelines.low_risk.industry_indicators_pipeline import IndustryIndicatorsPipeline
        from pipelines.low_risk.angelone_batch_fetcher import create_fetcher_from_market_service
        from shared.py.market_data import MarketDataService
        
        logger.info("✅ Modules imported successfully")
        
        # Initialize Angel One API
        logger.info("🔧 Initializing Angel One API connection...")
        market_service = MarketDataService()
        fetcher = create_fetcher_from_market_service(market_service)
        logger.info("✅ Angel One fetcher created (rate limited: 1 req/sec)")
        
        # CSV path
        csv_path = server_dir.parent.parent / "scripts" / "nifty_500_stats.csv"
        logger.info(f"📂 Using CSV: {csv_path}")
        
        if not csv_path.exists():
            logger.error(f"❌ CSV file not found: {csv_path}")
            return 1
        
        # Initialize pipeline
        logger.info("📈 Initializing Industry Indicators Pipeline...")
        pipeline = IndustryIndicatorsPipeline(
            stocks_csv_path=str(csv_path),
            angel_one_fetcher=fetcher,
            period="1y",           # 1 year of historical data
            interval="1d",          # Daily candles
            benchmark_ticker="^CRSLDX",
            rsi_length=14
        )
        
        logger.info(f"✅ Pipeline initialized")
        logger.info(f"   Total industries: {len(pipeline.industry_ticker_map)}")
        logger.info(f"   Total tickers: {len(pipeline.ticker_industry_map)}")
        
        # Compute indicators
        print("\n" + "=" * 80)
        print("🚀 Computing Industry Indicators (this may take 1-2 minutes)...")
        print("=" * 80)
        
        per_ticker_df, industry_summary_df = pipeline.compute()
        
        print("\n✅ Computation Complete!")
        
        # Display results
        print("\n" + "=" * 80)
        print("📈 PER-TICKER RESULTS")
        print("=" * 80)
        print(f"Total rows: {len(per_ticker_df)}")
        print(f"Unique tickers: {per_ticker_df['Ticker'].n_unique()}")
        print(f"Columns: {per_ticker_df.columns}")
        
        # Show rows with RSI values (skip warm-up period)
        rows_with_rsi = per_ticker_df.filter(pl.col('RSI').is_not_null())
        print(f"\nRows with RSI values: {len(rows_with_rsi)} (warm-up period: {len(per_ticker_df) - len(rows_with_rsi)} rows)")
        print("\nSample (rows 15-20 with RSI values):")
        print(rows_with_rsi.head(5))
        
        print("\n" + "=" * 80)
        print("🏭 INDUSTRY SUMMARY RESULTS")
        print("=" * 80)
        print(f"Total industries: {len(industry_summary_df)}")
        print("\nAll Industries:")
        print(industry_summary_df.select([
            'industry', 'pct_above_ema50', 'pct_above_ema200', 
            'median_rsi', 'industry_ret_6m', 'industry_ret_12m', 'avg_volatility'
        ]))
        
        # Top industries by 6-month return
        print("\n" + "=" * 80)
        print("🏆 TOP 10 INDUSTRIES BY 6-MONTH RETURN")
        print("=" * 80)
        
        top_industries = (
            industry_summary_df
            .filter(pl.col('industry_ret_6m').is_not_null())
            .sort('industry_ret_6m', descending=True)
            .head(10)
        )
        
        print(f"\n{'Industry':<30} | {'6M Return':>10} | {'RSI':>6} | {'Above EMA50':>12}")
        print("-" * 80)
        
        for row in top_industries.iter_rows(named=True):
            industry = row['industry']
            ret_6m = row.get('industry_ret_6m', 0) * 100
            rsi = row.get('median_rsi', 0)
            pct_ema50 = row.get('pct_above_ema50', 0) * 100
            print(f"{industry:<30} | {ret_6m:>9.2f}% | {rsi:>6.1f} | {pct_ema50:>11.1f}%")
        
        # Bottom industries
        print("\n" + "=" * 80)
        print("📉 BOTTOM 5 INDUSTRIES BY 6-MONTH RETURN")
        print("=" * 80)
        
        bottom_industries = (
            industry_summary_df
            .filter(pl.col('industry_ret_6m').is_not_null())
            .sort('industry_ret_6m', descending=False)
            .head(5)
        )
        
        print(f"\n{'Industry':<30} | {'6M Return':>10} | {'RSI':>6} | {'Above EMA50':>12}")
        print("-" * 80)
        
        for row in bottom_industries.iter_rows(named=True):
            industry = row['industry']
            ret_6m = row.get('industry_ret_6m', 0) * 100
            rsi = row.get('median_rsi', 0)
            pct_ema50 = row.get('pct_above_ema50', 0) * 100
            print(f"{industry:<30} | {ret_6m:>9.2f}% | {rsi:>6.1f} | {pct_ema50:>11.1f}%")
        
        # Breadth signals
        print("\n" + "=" * 80)
        print("📊 BREADTH SIGNALS (% Stocks Above EMA50)")
        print("=" * 80)
        
        breadth = (
            industry_summary_df
            .filter(pl.col('pct_above_ema50').is_not_null())
            .sort('pct_above_ema50', descending=True)
            .select(['industry', 'pct_above_ema50', 'median_rsi'])
        )
        
        print(f"\n{'Industry':<30} | {'% Above EMA50':>15} | {'Median RSI':>12}")
        print("-" * 80)
        
        for row in breadth.head(10).iter_rows(named=True):
            industry = row['industry']
            pct = row.get('pct_above_ema50', 0) * 100
            rsi = row.get('median_rsi', 0)
            print(f"{industry:<30} | {pct:>14.1f}% | {rsi:>12.1f}")
        
        # Summary statistics
        print("\n" + "=" * 80)
        print("📊 SUMMARY STATISTICS")
        print("=" * 80)
        
        stats = pipeline.summary_statistics()
        print(f"\nTotal Industries: {stats['total_industries']}")
        print(f"Total Tickers: {stats['total_tickers']}")
        print(f"Date Range: {stats['date_range'][0]} to {stats['date_range'][1]}")
        print(f"Benchmark: {stats['benchmark_ticker']}")
        
        # RSI distribution
        rsi_data = industry_summary_df.filter(pl.col('median_rsi').is_not_null())
        if not rsi_data.is_empty():
            avg_rsi = rsi_data['median_rsi'].mean()
            overbought = len(rsi_data.filter(pl.col('median_rsi') > 70))
            oversold = len(rsi_data.filter(pl.col('median_rsi') < 30))
            
            print(f"\nAverage Industry RSI: {avg_rsi:.2f}")
            print(f"Overbought Industries (RSI > 70): {overbought}")
            print(f"Oversold Industries (RSI < 30): {oversold}")
        
        # Export results to CSV
        print("\n" + "=" * 80)
        print("💾 EXPORTING RESULTS TO CSV")
        print("=" * 80)
        
        output_dir = server_dir / "test_output"
        output_dir.mkdir(exist_ok=True)
        
        # Save per-ticker results
        ticker_csv = output_dir / "per_ticker_indicators.csv"
        per_ticker_df.write_csv(str(ticker_csv))
        print(f"✅ Per-ticker results saved: {ticker_csv}")
        print(f"   Shape: {per_ticker_df.shape}")
        
        # Save industry summary
        industry_csv = output_dir / "industry_summary.csv"
        industry_summary_df.write_csv(str(industry_csv))
        print(f"✅ Industry summary saved: {industry_csv}")
        print(f"   Shape: {industry_summary_df.shape}")
        
        # Save raw data if available
        if pipeline.raw_data is not None and not pipeline.raw_data.is_empty():
            raw_csv = output_dir / "raw_candle_data.csv"
            pipeline.raw_data.write_csv(str(raw_csv))
            print(f"✅ Raw candle data saved: {raw_csv}")
            print(f"   Shape: {pipeline.raw_data.shape}")
        
        print("\n" + "=" * 80)
        print("✅ Pipeline execution completed successfully!")
        print(f"📂 Results exported to: {output_dir}")
        print("=" * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Error running pipeline: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    import polars as pl  # Import here to avoid issues if not installed
    sys.exit(main())
