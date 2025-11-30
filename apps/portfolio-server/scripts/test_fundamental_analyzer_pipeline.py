#!/usr/bin/env python3
"""Ad-hoc test runner for the FundamentalAnalyzerPipeline.

Example usage:
    python scripts/test_fundamental_analyzer_pipeline.py \
        --tickers RELIANCE.NS TCS.NS INFY.NS \
        --max-tickers 3 --output data/fundamental_sample.csv

By default the script pulls the Nifty-500 universe from the shared CSV and
processes the first ``max-tickers`` entries. Pass ``--tickers`` to override the
universe manually.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Ensure repository modules resolve when script is executed directly.
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SERVER_ROOT = SCRIPT_DIR.parent
REPO_ROOT = SERVER_ROOT.parent.parent
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared" / "py"))
sys.path.insert(0, str(REPO_ROOT / "middleware" / "py"))

from pipelines.low_risk import FundamentalAnalyzerPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("fundamental_runner")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the FundamentalAnalyzerPipeline and display the output.",
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=None,
        help="Explicit list of NSE tickers (with or without .NS suffix)."
    )
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=5,
        help="Maximum number of tickers to process (default: 5).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass the cached statements and refetch from Yahoo Finance.",
    )
    parser.add_argument(
        "--raw-csv",
        type=Path,
        default=None,
        help="Optional CSV containing OHLCV data with columns Date,Ticker,Close.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to export the resulting DataFrame as CSV.",
    )
    return parser.parse_args()


def _load_raw_dataframe(csv_path: Optional[Path]) -> Optional[pd.DataFrame]:
    if csv_path is None:
        return None
    if not csv_path.exists():
        raise FileNotFoundError(f"Raw data CSV not found: {csv_path}")
    logger.info("Loading supplemental OHLCV data from %s", csv_path)
    df = pd.read_csv(csv_path)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df


def _describe_result(tickers: List[str], df: pd.DataFrame) -> None:
    logger.info("\n======== FUNDAMENTAL ANALYZER REPORT ========")
    logger.info("Analyzed tickers: %s", ", ".join(tickers))
    logger.info("Columns returned: %d", len(df.columns))
    logger.info("Rows returned: %d", len(df))
    preview = df.head()
    logger.info("\nTop rows:\n%s", preview.to_string(index=False))
    failed = df.attrs.get("failed_tickers")
    if failed:
        logger.warning("Tickers failed and skipped: %s", ", ".join(failed))


def main() -> int:
    args = _parse_args()
    raw_df = _load_raw_dataframe(args.raw_csv)

    pipeline = FundamentalAnalyzerPipeline(
        raw_data=raw_df,
        max_tickers=args.max_tickers,
        force_refresh=args.force_refresh,
    )

    logger.info(
        "Running pipeline (max_tickers=%d, force_refresh=%s)...",
        args.max_tickers,
        args.force_refresh,
    )

    result = pipeline.run(
        tickers=args.tickers,
        max_tickers=args.max_tickers,
        force_refresh=args.force_refresh,
    )

    _describe_result(result.tickers_analyzed, result.dataframe)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.dataframe.to_csv(args.output, index=False)
        logger.info("Saved results to %s", args.output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
