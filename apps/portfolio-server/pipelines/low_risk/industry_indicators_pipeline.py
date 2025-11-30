"""
Industry Indicators Pipeline

A comprehensive pipeline for computing and retrieving industry-wise technical indicators.
Uses Polars for fast DataFrame operations and Angel One API for data fetching.
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import polars as pl
import pandas as pd
import numpy as np
from .angelone_batch_fetcher import AngelOneBatchFetcher
logger = logging.getLogger(__name__)


class IndustryIndicatorsPipeline:
    """
    A comprehensive pipeline for computing and retrieving industry-wise technical indicators.

    Features:
    - Computes technical indicators (EMA, RSI, SMA, Drawdown, Volatility, Returns)
    - Aggregates metrics per industry
    - Caches results for efficient retrieval
    - Provides flexible query interface
    - Uses Polars for 5-15x faster processing
    """

    def __init__(
        self,
        stocks_csv_path: str,
        angel_one_fetcher=None, 
        period: str = "1y",
        interval: str = "1d",
        benchmark_ticker: str = "Nifty 500",
        rsi_length: int = 14,
        Demo: bool = False
    ):
        """
        Initialize the pipeline with stock data and parameters.

        Args:
            stocks_csv_path: Path to CSV file containing stock symbols and industries
            angel_one_fetcher: AngelOneBatchFetcher instance (required for data fetching)
            period: Historical data period (e.g., '1y', '6mo', '2y')
            interval: Data interval (e.g., '1d', '1h')
            benchmark_ticker: Benchmark ticker for relative strength calculation
            rsi_length: RSI calculation period
        """
        self.period = period
        self.interval = interval
        self.benchmark_ticker = benchmark_ticker
        self.rsi_length = rsi_length
        self.angel_one_fetcher = angel_one_fetcher
        self.Demo = Demo
        if not self.angel_one_fetcher:
            raise ValueError("angel_one_fetcher is required (AngelOneBatchFetcher instance)")

        # Load stock data - try multiple delimiters (semicolon, comma)
        logger.info(f"Loading stocks from {stocks_csv_path}")
        try:
            # First try comma delimiter (default)
            stocks_df_pd = pd.read_csv(stocks_csv_path)
            
            # If only one column, try semicolon delimiter
            if len(stocks_df_pd.columns) == 1:
                stocks_df_pd = pd.read_csv(stocks_csv_path, sep=';')
            
            logger.info(f"Loaded {len(stocks_df_pd)} stocks with columns: {stocks_df_pd.columns.tolist()}")
        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            raise
        
        # Normalize column names - strip whitespace and convert to lowercase
        stocks_df_pd.columns = stocks_df_pd.columns.str.strip().str.lower().str.replace(' ', '_')
        
        # Verify required columns exist
        required_cols = ['symbol', 'industry']
        missing_cols = [col for col in required_cols if col not in stocks_df_pd.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}. Available: {stocks_df_pd.columns.tolist()}")
        
        # Filter out dummy/invalid symbols
        stocks_df_pd = stocks_df_pd[
            (stocks_df_pd['symbol'].notna()) & 
            (stocks_df_pd['symbol'] != '') &
            (stocks_df_pd['symbol'] != 'DUMMYSKFIN') &
            (stocks_df_pd['industry'].notna())
        ].reset_index(drop=True)
        
        logger.info(f"After filtering: {len(stocks_df_pd)} valid stocks")
        
        # Convert to Polars
        self.stocks_df = pl.from_pandas(stocks_df_pd)

        # Create mappings (symbols are plain, no .NS suffix for Angel One)
        self.industry_ticker_map = self._create_industry_ticker_map()
        self.ticker_industry_map = self._create_ticker_industry_map()

        logger.info(f"Total industries: {len(self.industry_ticker_map)}")
        logger.info(f"Total tickers: {len(self.ticker_industry_map)}")
        logger.info(f"Note: Token validation will happen during data fetch (with EQ→BE fallback)")

        # Cached results (Polars DataFrames)
        self.per_ticker_df: Optional[pl.DataFrame] = None
        self.industry_summary_df: Optional[pl.DataFrame] = None
        self.raw_data: Optional[pl.DataFrame] = None
        self._is_computed = False

    def _create_industry_ticker_map(self) -> Dict[str, List[str]]:
        """Create mapping from industry to list of tickers."""
        industry_ticker_map = {}
        
        # Convert to pandas for easier iteration (small dataset)
        stocks_pd = self.stocks_df.to_pandas()
        
        # Column names are already normalized to lowercase with underscores
        industry_col = 'industry'
        symbol_col = 'symbol'
        
        if industry_col not in stocks_pd.columns or symbol_col not in stocks_pd.columns:
            logger.error(f"Required columns missing. Available: {stocks_pd.columns.tolist()}")
            raise ValueError(f"Columns 'symbol' and 'industry' required after normalization")
        
        for _, row in stocks_pd.iterrows():
            industry = row[industry_col]
            ticker = row[symbol_col]  # Keep without .NS suffix for Angel One
            if pd.isna(industry) or pd.isna(ticker):
                continue
            if industry not in industry_ticker_map:
                industry_ticker_map[industry] = []
            industry_ticker_map[industry].append(ticker)
        
        return industry_ticker_map

    def _create_ticker_industry_map(self) -> Dict[str, str]:
        """Create mapping from ticker to industry."""
        ticker_industry_map = {}
        
        # Convert to pandas for easier iteration
        stocks_pd = self.stocks_df.to_pandas()
        
        # Column names are already normalized to lowercase with underscores
        industry_col = 'industry'
        symbol_col = 'symbol'
        
        if industry_col not in stocks_pd.columns or symbol_col not in stocks_pd.columns:
            logger.error(f"Required columns missing. Available: {stocks_pd.columns.tolist()}")
            raise ValueError(f"Columns 'symbol' and 'industry' required after normalization")
        
        for _, row in stocks_pd.iterrows():
            ticker = row[symbol_col]
            industry = row[industry_col]
            if pd.isna(ticker) or pd.isna(industry):
                continue
            ticker_industry_map[ticker] = industry
        
        return ticker_industry_map

    @staticmethod
    def _rsi_wilder_polars(close_series: pl.Series, length: int = 14) -> pl.Series:
        """
        Calculate RSI using Wilder's smoothing method with Polars.
        
        Args:
            close_series: Polars Series of closing prices
            length: RSI period
            
        Returns:
            Polars Series with RSI values
        """
        # Need at least length+1 points to calculate RSI
        if len(close_series) < length + 1:
            # Not enough data, return nulls
            return pl.Series([None] * len(close_series))
        
        # Calculate price changes
        delta = close_series.diff()
        
        # Separate gains and losses
        gains = delta.clip(lower_bound=0)
        losses = (-delta).clip(lower_bound=0)
        
        # Calculate rolling averages
        avg_gain = gains.rolling_mean(window_size=length, min_periods=length)
        avg_loss = losses.rolling_mean(window_size=length, min_periods=length)
        
        # Calculate RS (relative strength)
        rs = avg_gain / avg_loss
        
        # Handle division by zero (when avg_loss is 0, RSI = 100)
        # Replace inf with large number, then calculate RSI
        rs = rs.fill_nan(0.0)
        rs = pl.when(rs.is_infinite()).then(100.0).otherwise(rs)
        
        # Calculate RSI
        rsi = 100 - (100 / (1 + rs))
        
        return rsi  # Keep nulls for warm-up period

    @staticmethod
    def _ensure_tidy_polars(raw: pl.DataFrame) -> pl.DataFrame:
        """
        Ensure data is in tidy format (Polars).
        
        Args:
            raw: Polars DataFrame with columns: timestamp, symbol, open, high, low, close, volume
            
        Returns:
            Tidy Polars DataFrame
        """
        if raw.is_empty():
            return raw
        
        # Ensure required columns exist
        required_cols = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in raw.columns]
        
        if missing_cols:
            logger.warning(f"Missing columns in raw data: {missing_cols}")
            return pl.DataFrame()
        
        # Rename timestamp to Date for compatibility
        df = raw.rename({"timestamp": "Date"})
        
        # Ensure Date is datetime
        df = df.with_columns([
            pl.col("Date").cast(pl.Datetime).alias("Date")
        ])
        
        # Rename symbol to Ticker for compatibility
        df = df.rename({"symbol": "Ticker"})
        
        # Ensure Close column exists (use close)
        if "Close" not in df.columns and "close" in df.columns:
            df = df.rename({"close": "Close"})
        
        return df

    def _compute_ticker_indicators_polars(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Compute technical indicators for ticker data using Polars.
        
        Args:
            df: Polars DataFrame with columns: Date, Ticker, Close, etc.
            
        Returns:
            Polars DataFrame with indicators added
        """
        if df.is_empty():
            return df
        
        df = df.sort("Date")
        
        # Ensure Close column exists
        if "Close" not in df.columns:
            logger.warning("Close column not found")
            return df
        
        # Compute indicators using Polars expressions
        df = df.with_columns([
            # EMAs
            pl.col("Close").ewm_mean(span=50, adjust=False, min_periods=20).alias("EMA50"),
            pl.col("Close").ewm_mean(span=200, adjust=False, min_periods=100).alias("EMA200"),
            
            # SMAs
            pl.col("Close").rolling_mean(window_size=50).alias("SMA50"),
            pl.col("Close").rolling_mean(window_size=200).alias("SMA200"),
            
            # Volatility (rolling std of returns * sqrt(252))
            (
                pl.col("Close").pct_change().rolling_std(window_size=20) * (252 ** 0.5)
            ).alias("Volatility"),
            
            # Drawdown
            (
                (pl.col("Close") - pl.col("Close").rolling_max(window_size=252)) 
                / pl.col("Close").rolling_max(window_size=252)
            ).alias("Drawdown"),
        ])
        
        # Calculate RSI (needs to be done after other columns are computed)
        rsi_values = IndustryIndicatorsPipeline._rsi_wilder_polars(df["Close"], length=self.rsi_length)
        df = df.with_columns([
            rsi_values.alias("RSI")
        ])
        
        # Calculate multi-period returns
        # Get last date and close
        last_row = df.tail(1)
        if not last_row.is_empty():
            last_date = last_row["Date"][0]
            last_close = last_row["Close"][0]
            
            # Calculate returns for different periods
            for months, col_name in [(3, "ret_3m"), (6, "ret_6m"), (12, "ret_12m")]:
                start_date = last_date - timedelta(days=months * 30)
                
                # Filter data from start_date
                filtered = df.filter(pl.col("Date") >= start_date)
                
                if not filtered.is_empty():
                    first_close = filtered["Close"][0]
                    if first_close and first_close > 0:
                        ret_val = (last_close / first_close) - 1
                    else:
                        ret_val = None
                else:
                    ret_val = None
                
                # Add return column (same value for all rows)
                df = df.with_columns([
                    pl.lit(ret_val).alias(col_name)
                ])
        
        return df

    def _compute_industry_aggregates_polars(
        self,
        per_ticker: pl.DataFrame,
        tidy: pl.DataFrame
    ) -> pl.DataFrame:
        """
        Aggregate ticker-level indicators to industry-level metrics using Polars.
        
        Args:
            per_ticker: Per-ticker indicator DataFrame (Polars)
            tidy: Tidy raw data DataFrame (Polars)
            
        Returns:
            Industry summary DataFrame (Polars)
        """
        if per_ticker.is_empty() or tidy.is_empty():
            return pl.DataFrame()
        
        # Add industry column to tidy data
        tidy = tidy.with_columns([
            pl.col("Ticker").replace(self.ticker_industry_map, default="Unknown").alias("Industry")
        ])
        
        # Compute date-wise median close per industry
        industry_close = (
            tidy
            .group_by(["Industry", "Date"])
            .agg(pl.col("Close").median().alias("median_close"))
            .sort(["Industry", "Date"])
        )
        
        # Get last row per ticker (most recent data)
        last_rows = (
            per_ticker
            .sort("Date")
            .group_by("Ticker", maintain_order=True)
            .tail(1)
        )
        
        # Get benchmark return
        benchmark_ret_6m = None
        
        if self.benchmark_ticker:
            bench_rows = last_rows.filter(pl.col("Ticker") == self.benchmark_ticker)
            if not bench_rows.is_empty():
                benchmark_ret_6m = bench_rows["ret_6m"][0]
                logger.info(f"✓ Benchmark {self.benchmark_ticker} return (6m): {benchmark_ret_6m}")
            else:
                logger.warning(f"⚠️ Benchmark {self.benchmark_ticker} not found in ticker data")
                # Debug: show available tickers
                available_tickers = last_rows["Ticker"].unique().to_list()
                logger.debug(f"Available tickers: {available_tickers[:10]}...")
        
        # Aggregate per industry
        rows = []
        
        for industry, tickers in self.industry_ticker_map.items():
            # Filter last rows for this industry's tickers
            industry_last_rows = last_rows.filter(pl.col("Ticker").is_in(tickers))
            
            if industry_last_rows.is_empty():
                rows.append(self._create_empty_industry_row(industry, benchmark_ret_6m))
                continue
            
            # Compute industry-level metrics
            industry_row = self._compute_industry_metrics_polars(
                industry_last_rows, industry, benchmark_ret_6m, industry_close
            )
            rows.append(industry_row)
        
        # Create DataFrame from rows
        if not rows:
            return pl.DataFrame()
        
        industry_summary = pl.DataFrame(rows)
        return industry_summary.set_sorted("industry")

    def _create_empty_industry_row(
        self,
        industry: str,
        benchmark_ret_6m: Optional[float]
    ) -> Dict:
        """Create an empty row for industries with no valid data."""
        return {
            "industry": industry,
            "n_tickers": 0,
            "pct_above_ema50": None,
            "pct_above_ema200": None,
            "median_rsi": None,
            "ema50": None,
            "ema200": None,
            "pct_rsi_overbought": None,
            "pct_rsi_oversold": None,
            "industry_ret_3m": None,
            "industry_ret_6m": None,
            "industry_ret_12m": None,
            "median_sma50": None,
            "median_sma200": None,
            "avg_drawdown": None,
            "avg_volatility": None,
            "benchmark_ret_6m": benchmark_ret_6m,
            "RS": None
        }

    def _compute_industry_metrics_polars(
        self,
        last_rows: pl.DataFrame,
        industry: str,
        benchmark_ret_6m: Optional[float],
        industry_close: pl.DataFrame
    ) -> Dict:
        """Compute aggregated metrics for a single industry using Polars."""
        
        # Breadth signals
        pct_above_ema50 = (last_rows["Close"] > last_rows["EMA50"]).mean()
        pct_above_ema200 = (last_rows["Close"] > last_rows["EMA200"]).mean()
        
        # RSI aggregation
        rsi_series = last_rows["RSI"].drop_nulls()
        median_rsi = rsi_series.median() if not rsi_series.is_empty() else None
        pct_overbought = (rsi_series > 70).mean() if not rsi_series.is_empty() else None
        pct_oversold = (rsi_series < 30).mean() if not rsi_series.is_empty() else None
        
        # Multi-period returns
        ret_3m_series = last_rows["ret_3m"].drop_nulls()
        ret_6m_series = last_rows["ret_6m"].drop_nulls()
        ret_12m_series = last_rows["ret_12m"].drop_nulls()
        
        industry_ret_3m = ret_3m_series.mean() if not ret_3m_series.is_empty() else None
        industry_ret_6m = ret_6m_series.mean() if not ret_6m_series.is_empty() else None
        industry_ret_12m = ret_12m_series.mean() if not ret_12m_series.is_empty() else None
        
        # Average volatility
        vol_series = last_rows["Volatility"].drop_nulls()
        avg_volatility = vol_series.mean() if not vol_series.is_empty() else None
        
        # Relative Strength
        RS = None
        if benchmark_ret_6m is not None and industry_ret_6m is not None:
            try:
                if float(benchmark_ret_6m) != 0:
                    RS = float(industry_ret_6m) / float(benchmark_ret_6m)
                    logger.debug(f"{industry}: RS = {RS:.4f} (industry_ret_6m={industry_ret_6m:.4f}, benchmark_ret_6m={benchmark_ret_6m:.4f})")
                else:
                    logger.warning(f"{industry}: Benchmark return is zero, cannot compute RS")
            except Exception as e:
                logger.error(f"{industry}: RS calculation failed: {e}")
                RS = None
        else:
            if benchmark_ret_6m is None:
                logger.debug(f"{industry}: RS is None (benchmark_ret_6m is None)")
            if industry_ret_6m is None:
                logger.debug(f"{industry}: RS is None (industry_ret_6m is None)")
        
        # Industry-level EMA (from median close time series)
        industry_close_filtered = industry_close.filter(pl.col("Industry") == industry)
        if not industry_close_filtered.is_empty():
            close_series = industry_close_filtered["median_close"]
            ema50 = close_series.ewm_mean(span=50, adjust=False, min_periods=20)
            ema200 = close_series.ewm_mean(span=200, adjust=False, min_periods=100)
            ema50_val = ema50[-1] if len(ema50) > 0 else None
            ema200_val = ema200[-1] if len(ema200) > 0 else None
        else:
            ema50_val = None
            ema200_val = None
        
        return {
            "industry": industry,
            "pct_above_ema50": float(pct_above_ema50) if pct_above_ema50 is not None else None,
            "pct_above_ema200": float(pct_above_ema200) if pct_above_ema200 is not None else None,
            "median_rsi": float(median_rsi) if median_rsi is not None else None,
            "ema50": float(ema50_val) if ema50_val is not None else None,
            "ema200": float(ema200_val) if ema200_val is not None else None,
            "pct_rsi_overbought": float(pct_overbought) if pct_overbought is not None else None,
            "pct_rsi_oversold": float(pct_oversold) if pct_oversold is not None else None,
            "industry_ret_3m": float(industry_ret_3m) if industry_ret_3m is not None else None,
            "industry_ret_6m": float(industry_ret_6m) if industry_ret_6m is not None else None,
            "industry_ret_12m": float(industry_ret_12m) if industry_ret_12m is not None else None,
            "avg_volatility": float(avg_volatility) if avg_volatility is not None else None,
            "RS": float(RS) if RS is not None else None
        }

    async def compute_async(self, force_recompute: bool = False) -> Tuple[pl.DataFrame, pl.DataFrame]:
        """
        Download data and compute all indicators (async version).
        
        Args:
            force_recompute: If True, recompute even if already computed
            
        Returns:
            Tuple of (per_ticker_df, industry_summary_df) as Polars DataFrames
        """
        if self._is_computed and not force_recompute:
            return self.per_ticker_df, self.industry_summary_df
        
        logger.info("📡 Downloading market data from Angel One API...")
        
        # Prepare ticker list
        all_tickers = sorted({
            t for ts in self.industry_ticker_map.values()
            for t in ts if t
        })
        
        # Add benchmark if specified (Nifty 500 with token 99926004)
        download_tickers = list(all_tickers)
        if self.benchmark_ticker and self.benchmark_ticker not in download_tickers:
            # For Nifty 500, use exact symbol from Angel One
            # Symbol: "Nifty 500", Token: 99926004
            benchmark_clean = self.benchmark_ticker.replace("^", "").strip()
            if benchmark_clean not in download_tickers:
                download_tickers.append(benchmark_clean)
                logger.info(f"📍 Added benchmark ticker: {benchmark_clean}")
                # Verify token exists
                token_info = self.angel_one_fetcher._get_token_info(benchmark_clean)
                if token_info:
                    logger.info(f"✓ Benchmark token verified: {token_info.get('token')} for {benchmark_clean}")
                else:
                    logger.error(f"❌ Benchmark token NOT FOUND for {benchmark_clean}")
        
        # Map period to days
        period_days_map = {
            "1y": 365,
            "6mo": 180,
            "2y": 730,
            "3mo": 90,
            "1mo": 30
        }
        period_days = period_days_map.get(self.period, 365)
        
        # Map interval to Angel One format
        interval_map = {
            "1d": "ONE_DAY",
            "1h": "ONE_HOUR",
            "5m": "FIVE_MINUTE",
            "15m": "FIFTEEN_MINUTE"
        }
        angel_interval = interval_map.get(self.interval, "ONE_DAY")
        

        data_dir = Path(__file__).resolve().parents[2] / "data" / "market_data"
        data_dir.mkdir(parents=True, exist_ok=True)
        if self.Demo:
            csv_path = data_dir / "debug_raw_data_20251130_062228.csv"
            self.raw_data = pl.read_csv(csv_path, try_parse_dates=True)
        else :
            # Fetch data using Angel One batch fetcher
            self.raw_data = await self.angel_one_fetcher.fetch_all_batched(
                all_symbols=download_tickers,
                interval=angel_interval,
                period_days=period_days
            )

        if self.raw_data.is_empty():
            logger.warning("⚠️ No data fetched from Angel One API")
            return pl.DataFrame(), pl.DataFrame()
        
        logger.info("🔧 Computing technical indicators...")
        
        # Log fetched symbols
        if not self.raw_data.is_empty():
            fetched_symbols = self.raw_data["symbol"].unique().to_list()
            logger.info(f"📊 Fetched data for {len(fetched_symbols)} symbols")
            if self.benchmark_ticker in fetched_symbols:
                logger.info(f"✓ Benchmark '{self.benchmark_ticker}' found in fetched data")
            else:
                logger.warning(f"⚠️ Benchmark '{self.benchmark_ticker}' NOT in fetched data")
                logger.debug(f"Available symbols: {fetched_symbols[:10]}...")
        
        # Convert to tidy format
        tidy = self._ensure_tidy_polars(self.raw_data)
        
        if tidy.is_empty():
            logger.warning("⚠️ Tidy data is empty after conversion")
            return pl.DataFrame(), pl.DataFrame()
        
        # Compute per-ticker indicators
        # Process each ticker group separately
        ticker_groups = []
        for ticker in tidy["Ticker"].unique().to_list():
            ticker_data = tidy.filter(pl.col("Ticker") == ticker)
            ticker_indicators = self._compute_ticker_indicators_polars(ticker_data)
            if not ticker_indicators.is_empty():
                ticker_groups.append(ticker_indicators)
        
        if ticker_groups:
            self.per_ticker_df = pl.concat(ticker_groups)
            # Verify benchmark is in per_ticker_df
            if self.benchmark_ticker:
                tickers_with_data = self.per_ticker_df["Ticker"].unique().to_list()
                if self.benchmark_ticker in tickers_with_data:
                    logger.info(f"✓ Benchmark '{self.benchmark_ticker}' has computed indicators")
                    # Check if benchmark has return data
                    bench_data = self.per_ticker_df.filter(pl.col("Ticker") == self.benchmark_ticker)
                    if not bench_data.is_empty():
                        last_bench = bench_data.tail(1)
                        ret_6m = last_bench["ret_6m"][0] if "ret_6m" in last_bench.columns else None
                        logger.info(f"📈 Benchmark ret_6m preview: {ret_6m}")
                else:
                    logger.error(f"❌ Benchmark '{self.benchmark_ticker}' NOT in computed indicators!")
        else:
            self.per_ticker_df = pl.DataFrame()
        
        logger.info("📊 Aggregating industry-level metrics...")
        
        # Compute industry aggregates
        self.industry_summary_df = self._compute_industry_aggregates_polars(
            self.per_ticker_df, tidy
        )
        
        self._is_computed = True
        logger.info("✅ Computation complete!")
        
        return self.per_ticker_df, self.industry_summary_df

    def compute(self, force_recompute: bool = False) -> Tuple[pl.DataFrame, pl.DataFrame]:
        """
        Download data and compute all indicators (synchronous wrapper).
        
        Args:
            force_recompute: If True, recompute even if already computed
            
        Returns:
            Tuple of (per_ticker_df, industry_summary_df) as Polars DataFrames
        """
        import asyncio
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, create new task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self.compute_async(force_recompute))
                    return future.result()
            else:
                return loop.run_until_complete(self.compute_async(force_recompute))
        except RuntimeError:
            # No event loop, create new one
            return asyncio.run(self.compute_async(force_recompute))

    def get_industry_indicators(
        self,
        industries: Optional[List[str]] = None
    ) -> pl.DataFrame:
        """
        Retrieve industry indicators for specified industries.
        
        Args:
            industries: List of industry names. If None, returns all industries.
            
        Returns:
            Polars DataFrame with industry indicators
        """
        if not self._is_computed:
            raise RuntimeError("Data not computed yet. Call compute() first.")
        
        if industries is None:
            return self.industry_summary_df.clone()
        
        # Filter for requested industries
        available_industries = self.industry_summary_df["industry"].unique().to_list()
        valid_industries = [ind for ind in industries if ind in available_industries]
        
        if not valid_industries:
            logger.warning(f"None of the requested industries found in data.")
            logger.warning(f"Available industries: {available_industries[:10]}...")
            return pl.DataFrame()
        
        missing = set(industries) - set(valid_industries)
        if missing:
            logger.warning(f"Industries not found: {missing}")
        
        return self.industry_summary_df.filter(pl.col("industry").is_in(valid_industries))

    def get_ticker_data(
        self,
        tickers: Optional[List[str]] = None,
        industries: Optional[List[str]] = None
    ) -> pl.DataFrame:
        """
        Retrieve per-ticker data, optionally filtered by tickers or industries.
        
        Args:
            tickers: List of ticker symbols (e.g., ['RELIANCE', 'TCS'])
            industries: List of industry names
            
        Returns:
            Polars DataFrame with per-ticker indicators
        """
        if not self._is_computed:
            raise RuntimeError("Data not computed yet. Call compute() first.")
        
        result = self.per_ticker_df.clone()
        
        if tickers is not None:
            result = result.filter(pl.col("Ticker").is_in(tickers))
        
        if industries is not None:
            industry_tickers = []
            for industry in industries:
                if industry in self.industry_ticker_map:
                    industry_tickers.extend(self.industry_ticker_map[industry])
            result = result.filter(pl.col("Ticker").is_in(industry_tickers))
        
        return result

    def get_top_industries(
        self,
        metric: str = "industry_ret_6m",
        n: int = 10,
        ascending: bool = False
    ) -> pl.DataFrame:
        """
        Get top N industries based on a specific metric.
        
        Args:
            metric: Column name to sort by (e.g., 'industry_ret_6m', 'RS', 'median_rsi')
            n: Number of top industries to return
            ascending: If True, return bottom N instead
            
        Returns:
            Polars DataFrame with top N industries
        """
        if not self._is_computed:
            raise RuntimeError("Data not computed yet. Call compute() first.")
        
        if metric not in self.industry_summary_df.columns:
            raise ValueError(
                f"Metric '{metric}' not found. Available metrics: "
                f"{self.industry_summary_df.columns.tolist()}"
            )
        
        return (
            self.industry_summary_df
            .filter(pl.col(metric).is_not_null())
            .sort(metric, descending=not ascending)
            .head(n)
        )

    def get_available_industries(self) -> List[str]:
        """Get list of all available industries."""
        return list(self.industry_ticker_map.keys())

    def get_industry_tickers(self, industry: str) -> List[str]:
        """Get list of tickers for a specific industry."""
        return self.industry_ticker_map.get(industry, [])

    def summary_statistics(self) -> Dict:
        """Get summary statistics about the data."""
        if not self._is_computed:
            raise RuntimeError("Data not computed yet. Call compute() first.")
        
        per_ticker_pd = self.per_ticker_df.to_pandas()
        
        return {
            "total_industries": len(self.industry_summary_df),
            "total_tickers": len(per_ticker_pd['Ticker'].unique()),
            "date_range": (
                per_ticker_pd['Date'].min(),
                per_ticker_pd['Date'].max()
            ),
            "benchmark_ticker": self.benchmark_ticker
        }

