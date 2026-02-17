"""
Simple test script for Stock Selection Pipeline

Runs the complete stock selection pipeline with real data.

Usage:
    python scripts/test_stock_selection_pipeline.py --fund 100000 --user test_user
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add server directory and project root to path
server_dir = Path(__file__).resolve().parent
project_root = server_dir.parent.parent
sys.path.insert(0, str(server_dir.parent))  # portfolio-server
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "shared" / "py"))
sys.path.insert(0, str(project_root / "middleware" / "py"))

PROJECT_ROOT = server_dir.parent  # For backwards compatibility

import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Import pipeline components
from pipelines.low_risk.stock_selection_pipeline import StockSelectionPipeline
from pipelines.low_risk.industry_pipeline import IndustrySelectionPipeline
from pipelines.low_risk.industry_indicators_pipeline import IndustryIndicatorsPipeline
from pipelines.low_risk.fundamental_analyzer_pipeline import FundamentalAnalyzerPipeline
from utils.economic_indicators_storage import get_storage


def load_company_data() -> pd.DataFrame:
    """Load company data from CSV."""
    # Load from root scripts directory
    nifty_500_path = PROJECT_ROOT.parent.parent / "scripts" / "ind_nifty500listbrief.csv"

    if not nifty_500_path.exists():
        raise FileNotFoundError(
            f"Company data file not found at {nifty_500_path}. "
            f"Please ensure ind_nifty500listbrief.csv exists in the scripts directory."
        )

    logger.info(f"Loading company data from {nifty_500_path}")
    df = pd.read_csv(nifty_500_path)

    # Ensure required columns exist
    if "Company Name" not in df.columns or "Industry" not in df.columns:
        raise ValueError(
            f"CSV must contain 'Company Name' and 'Industry' columns. "
            f"Found columns: {df.columns.tolist()}"
        )

    logger.info(f"✓ Loaded {len(df)} companies from NIFTY 500 dataset")
    return df


def main():
    """Main entry point for test script."""
    parser = argparse.ArgumentParser(
        description="Test Stock Selection Pipeline"
    )

    parser.add_argument(
        "--fund",
        type=float,
        default=100000.0,
        help="Fund amount to allocate (default: 100000)"
    )
    parser.add_argument(
        "--user",
        type=str,
        default="test_user",
        help="User ID for the pipeline (default: test_user)"
    )

    args = parser.parse_args()

    logger.info("="*70)
    logger.info("STOCK SELECTION PIPELINE TEST")
    logger.info("="*70)
    logger.info(f"Fund Allocated: ₹{args.fund:,.2f}")
    logger.info(f"User ID: {args.user}")
    logger.info("="*70)

    try:
        # Get Gemini API key
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        if not gemini_api_key:
            logger.error("GEMINI_API_KEY not found in environment variables")
            return 1

        # Load company data
        logger.info("\n📊 Loading company data...")
        company_df = load_company_data()
        nifty_500_path = PROJECT_ROOT.parent.parent / "scripts" / "ind_nifty500listbrief.csv"

        # Initialize storage
        logger.info("\n🗄️ Initializing economic indicators storage...")
        storage = get_storage()

        # Check if economic data exists, if not, populate it
        logger.info("\n📥 Checking economic indicators data...")
        from pipelines.low_risk.india_economic_scraper import IndiaEconomicScraper
        from pipelines.low_risk.cpi_scraper import CPIScraperFixed

        # Check if trading economics data exists
        te_data = storage.read_indicators_df("trading_economics")
        if te_data is None or te_data.empty:
            logger.info("Trading economics data not found. Scraping...")
            try:
                scraper = IndiaEconomicScraper()
                te_df = scraper.scrape()
                storage.write_indicators("trading_economics", te_df)
                logger.info(f"✓ Scraped and saved {len(te_df)} trading economics indicators")
            except Exception as e:
                logger.error(f"Failed to scrape trading economics data: {e}")
                raise
        else:
            logger.info(f"✓ Trading economics data exists ({len(te_data)} indicators)")

        # Check if CPI data exists
        cpi_data = storage.read_indicators_df("cpi")
        if cpi_data is None or cpi_data.empty:
            logger.info("CPI data not found. Scraping...")
            try:
                cpi_scraper = CPIScraperFixed()
                cpi_df = cpi_scraper.scrape()
                storage.write_indicators("cpi", cpi_df)
                logger.info(f"✓ Scraped and saved {len(cpi_df)} CPI data points")
            except Exception as e:
                logger.error(f"Failed to scrape CPI data: {e}")
                raise
        else:
            logger.info(f"✓ CPI data exists ({len(cpi_data)} data points)")

        # Create market data service and AngelOne fetcher
        logger.info("\n🔧 Initializing market data service and AngelOne fetcher...")
        from market_data import get_market_data_service
        from pipelines.low_risk.angelone_batch_fetcher import create_fetcher_from_market_service

        logger.info("✅ Modules imported successfully")

        # Initialize Angel One API
        logger.info("🔧 Initializing Angel One API connection...")
        market_service = get_market_data_service()
        angel_fetcher = create_fetcher_from_market_service(market_service)
        logger.info("✅ Angel One fetcher created (rate limited: 1 req/sec)")

        # Create industry indicators pipeline
        logger.info("\n📈 Computing industry indicators...")
        industry_indicators = IndustryIndicatorsPipeline(
            stocks_csv_path=str(nifty_500_path),
            angel_one_fetcher=angel_fetcher,
            Demo=True
        )
        industry_indicators.compute()

        # Run fundamental analyzer pipeline
        logger.info("\n📊 Running fundamental analyzer pipeline...")
        fundamental_pipeline = FundamentalAnalyzerPipeline()
        fundamental_result = fundamental_pipeline.run()
        logger.info(f"✓ Computed fundamental metrics for {len(fundamental_result.dataframe)} tickers")

        # Create industry selection pipeline
        logger.info("\n🏭 Creating industry selection pipeline...")
        industry_pipeline = IndustrySelectionPipeline(
            industry_pipeline=industry_indicators,
            user_id=args.user,
            gemini_api_key=gemini_api_key,
            storage=storage
        )
        industry_list = industry_pipeline.run()
        print(industry_list)
        # Create stock selection pipeline
        logger.info("\n📈 Creating stock selection pipeline...")
        stock_pipeline = StockSelectionPipeline(
            pipeline=fundamental_pipeline,
            company_df=company_df,
            industry_list=industry_list,
            gemini_api_key=gemini_api_key,
            user_id=args.user,
        )

        # Run pipeline
        logger.info("\n🚀 Running stock selection pipeline...")
        result = stock_pipeline.run(fund_allocated=args.fund)

        # Display results
        logger.info("\n" + "="*70)
        logger.info("RESULTS")
        logger.info("="*70)

        summary = result["summary"]
        logger.info(f"✓ Industries Selected: {len(result['industry_list'])}")
        logger.info(f"✓ Stocks Selected: {summary['total_stocks']}")
        logger.info(f"✓ Trades Generated: {summary['total_trades']}")
        logger.info(f"✓ Total Invested: ₹{summary['total_invested']:,.2f}")
        logger.info(f"✓ Fund Utilization: {summary['utilization_rate']:.2f}%")

        # Show industry allocations
        logger.info("\n" + "-"*70)
        logger.info("INDUSTRY ALLOCATIONS")
        logger.info("-"*70)
        for ind in result['industry_list']:
            logger.info(f"  {ind['name']}: {ind['percentage']:.2f}%")

        # Show top stocks
        logger.info("\n" + "-"*70)
        logger.info("TOP STOCK ALLOCATIONS")
        logger.info("-"*70)
        sorted_portfolio = sorted(
            result['final_portfolio'],
            key=lambda x: x['percentage'],
            reverse=True
        )
        for stock in sorted_portfolio[:10]:
            logger.info(f"  {stock['ticker']}: {stock['percentage']:.2f}%")

        # Show trade details
        logger.info("\n" + "-"*70)
        logger.info("TRADE DETAILS")
        logger.info("-"*70)
        for trade in result['trade_list'][:10]:
            logger.info(
                f"  {trade['ticker']}: {trade['no_of_shares_bought']} shares @ "
                f"₹{trade['price_bought']:.2f} = ₹{trade['amount_invested']:,.2f}"
            )

        # Save results to file
        output_file = PROJECT_ROOT / "test_stock_selection_output.json"
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"\n💾 Full results saved to: {output_file}")

        logger.info("\n" + "="*70)
        logger.info("✅ PIPELINE TEST COMPLETED SUCCESSFULLY")
        logger.info("="*70)

        return 0

    except Exception as e:
        logger.error(f"\n❌ Pipeline test failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
