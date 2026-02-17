"""Fundamental analysis pipeline for the low-risk stack.

This module provides two pieces:

1. ``FundamentalAnalyzer`` – a feature extractor that computes a basket of
   fundamental, quality, and technical indicators for a single ticker using
   Yahoo Finance data plus optional OHLCV history supplied by the caller.
2. ``FundamentalAnalyzerPipeline`` – orchestrates fetching statements for a
   universe of tickers (defaults to the Nifty 500 list), caches those
   statements through :class:`utils.financial_statements_storage.
   FinancialStatementsStorage`, and returns a consolidated DataFrame with all
   computed indicators.

The pipeline also caches the final computed metrics DataFrame in a pickle file,
so subsequent runs can skip recomputation if nothing has changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from utils.financial_statements_storage import FinancialStatementsStorage

logger = logging.getLogger(__name__)

# Cache file for final computed metrics
METRICS_CACHE_FILE = "fundamental_metrics.pkl"
METRICS_METADATA_FILE = "fundamental_metrics_metadata.json"

# Default number of parallel workers - adapts to machine capabilities
# Use min of (cpu_count * 2, 8) to balance performance and API rate limits
# For I/O bound tasks like network requests, 2x CPU count is generally optimal
def _get_default_workers() -> int:
    cpu_count = os.cpu_count() or 2
    # Cap at 8 to avoid hitting Yahoo Finance rate limits
    return min(cpu_count * 2, 8)

DEFAULT_MAX_WORKERS = _get_default_workers()


class FundamentalAnalyzer:
    """Compute fundamental/technical indicators for a single ticker."""

    def __init__(self, ticker_symbol: str, raw: Optional[pd.DataFrame] = None):
        self.ticker_symbol = ticker_symbol
        self.ticker = yf.Ticker(ticker_symbol)

        self._balance_sheet = None
        self._income_stmt = None
        self._cashflow = None
        self._info = None
        self._financials_loaded = False
        self.raw = raw

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    def _fetch_financials(self):
        if self._financials_loaded:
            return True
        try:
            self._balance_sheet = self.ticker.get_balance_sheet(freq="yearly")
            self._income_stmt = self.ticker.income_stmt
            self._cashflow = self.ticker.get_cashflow(freq="yearly")
            self._info = self.ticker.get_info()
            self._financials = self.ticker.financials
            self._financials_loaded = True
            return True
        except Exception as e:
            print(f"Error fetching financials for {self.ticker_symbol}: {e}")
            return False

    def populate_financials(
        self,
        *,
        balance_sheet: pd.DataFrame,
        income_statement: pd.DataFrame,
        cashflow: pd.DataFrame,
        info: Dict[str, Any],
        financials: pd.DataFrame,
    ) -> None:
        """Inject already-fetched statements/info and flag as loaded."""
        self._balance_sheet = balance_sheet
        self._income_stmt = income_statement
        self._cashflow = cashflow
        self._info = info or {}
        self._financials = financials
        self._financials_loaded = True

    def _get(self, df, field, col=0, default=pd.NA):
        try:
            if df is None or field not in df.index:
                return default
            if col >= len(df.columns):
                return default
            val = df.loc[field, df.columns[col]]
            return val if pd.notna(val) else default
        except:
            return default

    def _prev(self, df, field, col=1, default=pd.NA):
        return self._get(df, field, col, default)

    # ------------------------------------------------------------------
    # Indicator computations (subset of common quant factors)
    # ------------------------------------------------------------------

    def compute_piotroski_fscore(self):
        if not self._fetch_financials():
            return pd.NA

        score = 0

        NI = self._get(self._income_stmt, "Net Income")
        TA = self._get(self._balance_sheet, "TotalAssets")
        CFO = self._get(self._cashflow, "OperatingCashFlow")
        REV = self._get(self._income_stmt, "Total Revenue")
        GP = self._get(self._income_stmt, "Gross Profit")
        CA = self._get(self._balance_sheet, "CurrentAssets")
        CL = self._get(self._balance_sheet, "CurrentLiabilities")
        LTD = self._get(
            self._balance_sheet,
            "LongTermDebtAndCapitalLeaseObligation",
            default=0,
        )
        SH = self._get(self._balance_sheet, "OrdinarySharesNumber")

        NI_prev = self._prev(self._income_stmt, "Net Income")
        TA_prev = self._prev(self._balance_sheet, "TotalAssets")
        REV_prev = self._prev(self._income_stmt, "Total Revenue")
        GP_prev = self._prev(self._income_stmt, "Gross Profit")
        CA_prev = self._prev(self._balance_sheet, "CurrentAssets")
        CL_prev = self._prev(self._balance_sheet, "CurrentLiabilities")
        LTD_prev = self._prev(
            self._balance_sheet,
            "LongTermDebtAndCapitalLeaseObligation",
            default=0,
        )
        SH_prev = self._prev(self._balance_sheet, "OrdinarySharesNumber")

        # ROA > 0
        if pd.notna(NI) and pd.notna(TA) and TA > 0 and NI / TA > 0:
            score += 1

        # CFO > 0
        if pd.notna(CFO) and CFO > 0:
            score += 1

        # ΔROA > 0
        if all(pd.notna(v) for v in [NI, TA, NI_prev, TA_prev]):
            if TA > 0 and TA_prev > 0:
                if (NI / TA) > (NI_prev / TA_prev):
                    score += 1

        # CFO > NI (accruals)
        if pd.notna(CFO) and pd.notna(NI) and CFO > NI:
            score += 1

        # Debt decreasing
        if pd.notna(LTD) and pd.notna(LTD_prev) and LTD <= LTD_prev:
            score += 1

        # Current Ratio improving
        if all(pd.notna(v) for v in [CA, CL, CA_prev, CL_prev]) and CL > 0 and CL_prev > 0:
            if (CA/CL) > (CA_prev/CL):
                score += 1

        # No equity issuance
        if pd.notna(SH) and pd.notna(SH_prev) and SH <= SH_prev:
            score += 1

        # Gross Margin increasing
        if all(pd.notna(v) for v in [GP, REV, GP_prev, REV_prev]) and REV > 0 and REV_prev > 0:
            if (GP / REV) > (GP_prev / REV_prev):
                score += 1

        # Asset Turnover increasing
        if all(pd.notna(v) for v in [REV, TA, REV_prev, TA_prev]) and TA > 0 and TA_prev > 0:
            if (REV / TA) > (REV_prev / TA_prev):
                score += 1

        return int(score)

    def compute_volatility(self):
        """Compute Volatility as the standard deviation of daily returns over the past year.
        
        Note: Requires at least 90 trading days of data (the tail used for calculation).
        The annualized volatility is computed as: std(daily_returns) * sqrt(252)
        """
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            # Need at least 90 days for meaningful volatility calculation
            # (previously required 252, but data files may have ~248 trading days per year)
            if len(stock_data) < 90:
                return pd.NA

            stock_data = stock_data.tail(90).copy()
            stock_data['Return'] = stock_data['Close'].pct_change()
            volatility = stock_data['Return'].std() * np.sqrt(252)

            return float(volatility)
        except:
            return pd.NA



    def compute_sloan_ratio(self):
        if not self._fetch_financials():
            return pd.NA

        NI = self._get(self._income_stmt, "Net Income")
        CFO = self._get(self._cashflow, "OperatingCashFlow")
        TA = self._get(self._balance_sheet, "TotalAssets")
        TA_prev = self._prev(self._balance_sheet, "TotalAssets")

        if any(pd.isna(v) for v in [NI, CFO, TA, TA_prev]):
            return pd.NA

        avg_assets = (TA + TA_prev) / 2
        if avg_assets == 0:
            return pd.NA

        return float((NI - CFO) / avg_assets)


    def compute_ccc(self):
        if not self._fetch_financials():
            return pd.NA

        inventory = self._get(self._balance_sheet, "Inventory", default=0)
        receivables = self._get(self._balance_sheet, "AccountsReceivable", default=0)
        payables = self._get(self._balance_sheet, "AccountsPayable", default=0)

        revenue = self._get(self._income_stmt, "Total Revenue")
        cogs = self._get(self._income_stmt, "Cost Of Revenue")

        if pd.isna(revenue) or revenue == 0:
            return pd.NA

        if pd.isna(cogs) or cogs == 0:
            cogs = revenue * 0.7

        dio = (inventory / cogs) * 365
        dso = (receivables / revenue) * 365
        dpo = (payables / cogs) * 365

        return float(dio + dso - dpo)

    def compute_beneish_mscore(self):
        if not self._fetch_financials():
            return pd.NA

        AR = self._get(self._balance_sheet, "AccountsReceivable", default=0)
        REV = self._get(self._income_stmt, "Total Revenue")
        GP = self._get(self._income_stmt, "Gross Profit")
        CA = self._get(self._balance_sheet, "CurrentAssets")
        TA = self._get(self._balance_sheet, "TotalAssets")
        PPE = self._get(self._balance_sheet, "NetPPE", default=0)
        DEP = self._get(self._income_stmt, "Reconciled Depreciation", default=0)
        SGA = self._get(
            self._income_stmt,
            "Selling General And Administration",
            default=0,
        )
        TL = self._get(self._balance_sheet, "TotalLiabilitiesNetMinorityInterest")
        NI = self._get(self._income_stmt, "Net Income")
        CFO = self._get(self._cashflow, "OperatingCashFlow")

        ARp = self._prev(self._balance_sheet, "AccountsReceivable", default=0)
        REVp = self._prev(self._income_stmt, "Total Revenue")
        GPp = self._prev(self._income_stmt, "Gross Profit")
        CAp = self._prev(self._balance_sheet, "CurrentAssets")
        TAp = self._prev(self._balance_sheet, "TotalAssets")
        PPEp = self._prev(self._balance_sheet, "NetPPE", default=0)
        DEPp = self._prev(self._income_stmt, "Reconciled Depreciation", default=0)
        SGAp = self._prev(
            self._income_stmt,
            "Selling General And Administration",
            default=0,
        )
        TLp = self._prev(self._balance_sheet, "TotalLiabilitiesNetMinorityInterest")

        if any(pd.isna(v) or v == 0 for v in [REV, REVp, TA, TAp]):
            return pd.NA

        dsri = (AR / REV) / (ARp / REVp) if ARp > 0 and REVp > 0 else 1
        gm = GP / REV if pd.notna(GP) and REV > 0 else 0.3
        gmp = GPp / REVp if pd.notna(GPp) and REVp > 0 else 0.3
        gmi = gmp / gm if gm > 0 else 1
        aqi = (1 - (CA + PPE) / TA) / (1 - (CAp + PPEp) / TAp)
        sgi = REV / REVp
        depr = DEP / (PPE + DEP) if (PPE + DEP) > 0 else 0.1
        depr_p = DEPp / (PPEp + DEPp) if (PPEp + DEPp) > 0 else 0.1
        depi = depr_p / depr if depr > 0 else 1
        sgai = (SGA / REV) / (SGAp / REVp) if SGAp > 0 and REVp > 0 else 1
        lvgi = (TL / TA) / (TLp / TAp)
        tata = (NI - CFO) / TA if pd.notna(NI) and pd.notna(CFO) else 0

        m = (
            -4.84
            + 0.920 * dsri
            + 0.528 * gmi
            + 0.404 * aqi
            + 0.892 * sgi
            + 0.115 * depi
            - 0.172 * sgai
            + 4.679 * tata
            - 0.327 * lvgi
        )

        if pd.isna(m):
            return pd.NA

        return float(m)

    def compute_shareholder_yield(self):
        """Shareholder Yield = Dividend Yield + (FCF / Market Cap)"""
        if not self._fetch_financials():
            return pd.NA

        div_yield = self._info.get("dividendYield", 0)
        fcf = self._info.get("freeCashflow", 0)
        market_cap = self._info.get("marketCap")

        if not market_cap or market_cap == 0:
            return pd.NA

        fcf_yield = fcf / market_cap if fcf else 0
        return float(div_yield + fcf_yield)

    def compute_roic(self):
        """Return on Invested Capital = EBIT * (1 - Tax Rate) / Invested Capital"""
        if not self._fetch_financials():
            return pd.NA

        ebit = self._get(self._income_stmt, "EBIT")
        tax_rate = self._get(self._income_stmt, "Tax Rate For Calcs", default=0.25)

        # Try to get InvestedCapital directly, otherwise calculate it
        invested_capital = self._get(self._balance_sheet, "InvestedCapital")

        if pd.isna(invested_capital):
            # Calculate as Total Debt + Stockholders Equity - Cash
            total_debt = self._get(self._balance_sheet, "TotalDebt", default=0)
            equity = self._get(self._balance_sheet, "StockholdersEquity", default=0)
            cash = self._get(self._balance_sheet, "CashAndCashEquivalents", default=0)
            invested_capital = total_debt + equity - cash

        if pd.isna(ebit) or pd.isna(invested_capital) or invested_capital == 0:
            return pd.NA

        nopat = ebit * (1 - tax_rate)
        return float(nopat / invested_capital)

    def compute_rs_ratio(self):
        """Relative Strength Ratio = Stock Price / Nifty 500 Index"""
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            # Get stock data
            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol]
            if stock_data.empty:
                return pd.NA

            # Get Nifty 500 index data
            index_data = self.raw[self.raw["Ticker"] == "Nifty 500"]
            if index_data.empty:
                return pd.NA

            # Get latest prices
            latest_stock_price = stock_data["Close"].iloc[-1]
            latest_index_price = index_data["Close"].iloc[-1]

            if pd.isna(latest_stock_price) or pd.isna(latest_index_price) or latest_index_price == 0:
                return pd.NA

            return float(latest_stock_price / latest_index_price)
        except:
            return pd.NA

    def compute_momentum_6_1(self):
        """Momentum 6-1 = (P_t-1 / P_t-6) - 1"""
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            # Need at least 126 trading days (6 months)
            if len(stock_data) < 126:
                return pd.NA

            # Price 1 month ago (21 trading days)
            if len(stock_data) < 21:
                return pd.NA
            price_t_1 = stock_data["Close"].iloc[-21]

            # Price 6 months ago (126 trading days)
            price_t_6 = stock_data["Close"].iloc[-126]

            if pd.isna(price_t_1) or pd.isna(price_t_6) or price_t_6 == 0:
                return pd.NA

            return float((price_t_1 / price_t_6) - 1)
        except:
            return pd.NA

    def compute_rsi_14(self):
        """RSI (14-day) using Wilder's smoothing method"""
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            if len(stock_data) < 15:
                return pd.NA

            close_prices = stock_data["Close"].values

            # Calculate price changes
            deltas = np.diff(close_prices)

            # Separate gains and losses
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)

            # Wilder's smoothing (14-period)
            avg_gain = np.mean(gains[-14:])
            avg_loss = np.mean(losses[-14:])

            if avg_loss == 0:
                return 100.0

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return float(rsi)
        except:
            return pd.NA

    def _compute_sma(self, length: int):
        """Helper to compute Simple Moving Average"""
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            if len(stock_data) < length:
                return pd.NA

            sma_series = stock_data["Close"].rolling(window=length).mean()
            return float(sma_series.iloc[-1])
        except:
            return pd.NA

    def compute_sma50(self):
        """Compute 50-day Simple Moving Average"""
        return self._compute_sma(50)
    def compute_sma200(self):
        """Compute 200-day Simple Moving Average"""
        return self._compute_sma(200)


    def _compute_ema(self, length: int):
        """Helper to compute Exponential Moving Average"""
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            if len(stock_data) < length:
                return pd.NA

            # Calculate EMA
            ema_series = stock_data["Close"].ewm(span=length, adjust=False).mean()
            return float(ema_series.iloc[-1])
        except:
            return pd.NA

    def compute_ema50(self):
        """Compute 50-day Exponential Moving Average"""
        return self._compute_ema(50)

    def compute_ema200(self):
        """Compute 200-day Exponential Moving Average"""
        return self._compute_ema(200)

    def compute_price_to_ema50(self):
        """Compute Price-to-50-day EMA Ratio"""
        current_price = self._info.get('currentPrice', self._info.get('regularMarketPrice', pd.NA))
        ema50 = self._compute_ema(50)

        if pd.isna(current_price) or pd.isna(ema50) or ema50 == 0:
            return pd.NA

        return float(current_price / ema50)
    def compute_price_to_ema200(self):
        """Compute Price-to-50-day EMA Ratio"""
        current_price = self._info.get('currentPrice', self._info.get('regularMarketPrice', pd.NA))
        ema200 = self._compute_ema(200)

        if pd.isna(current_price) or pd.isna(ema200) or ema200 == 0:
            return pd.NA

        return float(current_price / ema200)


    def compute_gross_profit_growth(self):
        """Compute Gross Profit Growth from income statement"""
        gp = self._get(self._income_stmt, "Gross Profit")
        gp_prev = self._prev(self._income_stmt, "Gross Profit")

        if pd.isna(gp) or pd.isna(gp_prev) or gp_prev == 0:
            return pd.NA

        return float((gp - gp_prev) / gp_prev)

    def compute_live_price(self):
        """Fetch live price from market data service."""
        try:
            from market_data import get_market_data_service

            # Get the service and fetch price
            service = get_market_data_service()

            # Try to get cached price first (non-blocking)
            price = service.get_latest_price(self.ticker_symbol)
            if price is not None:
                return float(price)

            # If not cached, try synchronous fetch with better error handling
            try:
                # This may fail in thread pool executor context
                price = service.get_or_fetch_price(self.ticker_symbol)
                return float(price)
            except RuntimeError as e:
                # Running in async context or price not available
                logger.debug(f"Could not fetch live price for {self.ticker_symbol}: {e}")
            except Exception as e:
                # Log other errors but don't fail
                logger.warning(f"Failed to fetch live price for {self.ticker_symbol}: {e}")

            # Fallback: try to get from yfinance info
            if self._info:
                current_price = self._info.get('currentPrice') or self._info.get('regularMarketPrice')
                if current_price:
                    return float(current_price)

            return pd.NA
        except ImportError:
            # market_data module not available, use yfinance
            if self._info:
                current_price = self._info.get('currentPrice') or self._info.get('regularMarketPrice')
                if current_price:
                    return float(current_price)
            return pd.NA
        except Exception as e:
            logger.warning(f"Failed to fetch live price for {self.ticker_symbol}: {e}")
            return pd.NA


    def get_valuation_metrics(self):
        """Extract valuation metrics from ticker.info"""
        if not self._fetch_financials():
            return {}

        return {
            "forward_pe": self._info.get("forwardPE", pd.NA),
            "price_to_book": self._info.get("priceToBook", pd.NA),
            "ev_to_ebitda": self._info.get("enterpriseToEbitda", pd.NA),
            'pe_ratio': self._info.get('trailingPE', pd.NA),
        }

    def get_cash_flow_metrics(self):
        """Extract cash flow metrics from ticker.info"""
        if not self._fetch_financials():
            return {}

        return {
            'operating_cashflow': self._info.get('operatingCashflow', pd.NA),
        }

    def get_net_income_metrics(self):
        """Extract net income metrics from ticker.info"""
        if not self._fetch_financials():
            return {}

        return {
            'net_income': self._get(self._financials, "Net Income", default=pd.NA),
        }



    def get_growth_metrics(self):
        """Extract growth metrics from ticker.info"""
        if not self._fetch_financials():
            return {}

        return {
            "revenue_growth": self._info.get("revenueGrowth", pd.NA),
            "earnings_growth": self._info.get("earningsGrowth", pd.NA),
            "earnings_quarterly_growth": self._info.get("earningsQuarterlyGrowth", pd.NA),
        }

    def get_financial_health_metrics(self):
        """Extract financial health metrics from ticker.info"""
        if not self._fetch_financials():
            return {}

        return {
            "debt_to_equity": self._info.get("debtToEquity", pd.NA),
        }

    def get_profitability_metrics(self):
        """Extract profitability metrics from ticker.info"""
        if not self._fetch_financials():
            return {}

        return {
            'roe': self._info.get('returnOnEquity', pd.NA),
        }


    def get_price_metrics(self):
        """Extract price-related metrics from ticker.info"""
        if not self._fetch_financials():
            return {}


        return {
            "fifty_two_week_change": self._info.get("52WeekChange", pd.NA),
        }



    def compute_all_indicators(self) -> Dict[str, Any]:
        """Compute all fundamental, quality, market, and technical indicators"""
        result = {
            "ticker": self.ticker_symbol,
            "piotroski_fscore": self.compute_piotroski_fscore(),
            "sloan_ratio": self.compute_sloan_ratio(),
            "ccc": self.compute_ccc(),
            "shareholder_yield": self.compute_shareholder_yield(),
            "roic": self.compute_roic(),
            "momentum_6_1": self.compute_momentum_6_1(),
            "rsi_14": self.compute_rsi_14(),
            'gross_profit_growth': self.compute_gross_profit_growth(),
            "price_to_ema50": self.compute_price_to_ema50(),
            "price_to_ema200": self.compute_price_to_ema200(),
            "sma50": self.compute_sma50(),
            "sma200": self.compute_sma200(),
            "volatility": self.compute_volatility(),
            "current_price": self.compute_live_price(),
        }

        # Add all info-based metrics
        result.update(self.get_valuation_metrics())
        result.update(self.get_growth_metrics())
        result.update(self.get_financial_health_metrics())
        result.update(self.get_price_metrics())
        result.update(self.get_profitability_metrics())
        result.update(self.get_cash_flow_metrics())
        result.update(self.get_net_income_metrics())

        return result


@dataclass
class PipelineResult:
    """Container for pipeline outputs."""

    tickers_analyzed: List[str]
    dataframe: pd.DataFrame
    from_cache: bool = False


class FundamentalAnalyzerPipeline:
    """Run FundamentalAnalyzer across a universe with cached statements.

    This pipeline caches both:
    1. Financial statements (balance_sheet, income_statement, cashflow) per ticker
    2. Final computed metrics DataFrame for all tickers

    On subsequent runs, if nothing has changed (same tickers, no force_refresh),
    it returns the cached metrics directly without recomputation.

    OHLCV data is automatically loaded from the industry candles CSV file at:
    data/market_data/industry_cache/industry_candles_ONE_DAY_365.csv
    """

    # Default path for OHLCV data (always updated)
    DEFAULT_OHLCV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "market_data" / "industry_cache" / "industry_candles_ONE_DAY_365.csv"

    def __init__(
        self,
        *,
        storage: Optional[FinancialStatementsStorage] = None,
        raw_data: Optional[pd.DataFrame] = None,
        ohlcv_path: Optional[Path] = None,
        max_tickers: int = 500,
        max_workers: int = DEFAULT_MAX_WORKERS,
        force_refresh: bool = False,
    ) -> None:
        self.storage = storage or FinancialStatementsStorage()
        self.max_tickers = max_tickers
        self.max_workers = max_workers
        self.force_refresh = force_refresh
        self._metrics_df: Optional[pd.DataFrame] = None

        # Cache paths
        self._cache_dir = self.storage.data_dir
        self._metrics_cache_path = self._cache_dir / METRICS_CACHE_FILE
        self._metrics_metadata_path = self._cache_dir / METRICS_METADATA_FILE

        # Load OHLCV data: use provided raw_data, or load from file
        if raw_data is not None:
            self.raw_data = raw_data
        else:
            ohlcv_file = ohlcv_path or self.DEFAULT_OHLCV_PATH
            self.raw_data = self._load_ohlcv_data(ohlcv_file)

    def _load_ohlcv_data(self, ohlcv_path: Path) -> Optional[pd.DataFrame]:
        """Load and normalize OHLCV data from the industry candles CSV."""
        if not ohlcv_path.exists():
            logger.warning("OHLCV file not found: %s. Technical indicators will be unavailable.", ohlcv_path)
            return None

        try:
            logger.info("Loading OHLCV data from %s", ohlcv_path)
            df = pd.read_csv(ohlcv_path)

            # Normalize column names to expected format
            df = df.rename(columns={
                'timestamp': 'Date',
                'symbol': 'Ticker',
                'close': 'Close',
                'open': 'Open',
                'high': 'High',
                'low': 'Low',
                'volume': 'Volume'
            })

            # Add .NS suffix to stock tickers (but not to index like 'Nifty 500')
            df['Ticker'] = df['Ticker'].apply(
                lambda x: x if x == 'Nifty 500' else (
                    f'{x}.NS' if not str(x).endswith('.NS') else x
                )
            )

            # Parse dates
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

            logger.info("Loaded OHLCV data: %d rows, %d tickers", len(df), df['Ticker'].nunique())
            return df

        except Exception as e:
            logger.warning("Failed to load OHLCV data from %s: %s", ohlcv_path, e)
            return None

    def run(
        self,
        tickers: Optional[Iterable[str]] = None,
        *,
        max_tickers: Optional[int] = None,
        max_workers: Optional[int] = None,
        force_refresh: Optional[bool] = None,
    ) -> PipelineResult:
        symbols = list(tickers) if tickers else self.storage.load_nifty500_symbols()
        if not symbols:
            raise ValueError("No tickers provided and no symbols available from Nifty 500 list")

        limit = max_tickers or self.max_tickers
        symbols = symbols[:limit]
        refresh = self.force_refresh if force_refresh is None else force_refresh
        workers = max_workers or self.max_workers

        # Ensure workers is at least 1 and doesn't exceed symbol count
        workers = max(1, min(workers, len(symbols)))

        # Check if we can use cached metrics
        if not refresh:
            cached_df = self._load_cached_metrics(symbols)
            if cached_df is not None:
                logger.info("[METRICS CACHE HIT] Returning cached metrics for %d tickers", len(symbols))
                self._metrics_df = cached_df
                return PipelineResult(
                    tickers_analyzed=symbols,
                    dataframe=cached_df,
                    from_cache=True
                )

        # Step 1: Fetch financials sequentially (to respect Yahoo Finance rate limits)
        logger.info("[FETCHING] Fetching financials for %d tickers...", len(symbols))
        analyzers: List[tuple] = []  # (symbol, analyzer) pairs
        failures: List[str] = []

        for symbol in symbols:
            analyzer = FundamentalAnalyzer(symbol, raw=self.raw_data)
            try:
                self._load_financials(analyzer, force_refresh=refresh)
                analyzers.append((symbol, analyzer))
                logger.info("[FETCHED] %s", symbol)
            except Exception as exc:
                logger.warning("Failed to fetch financials for %s: %s", symbol, exc)
                failures.append(symbol)

        if not analyzers:
            raise RuntimeError("Fundamental analyzer pipeline could not fetch any tickers")

        # Step 2: Compute indicators in parallel (CPU-bound, no API calls)
        logger.info("[COMPUTING] Computing indicators for %d tickers using %d workers...", len(analyzers), workers)
        records: List[Dict[str, Any]] = []

        def compute_indicators(item: tuple) -> tuple:
            """Compute indicators for a single ticker and return (symbol, record, error)."""
            symbol, analyzer = item
            try:
                record = analyzer.compute_all_indicators()
                return (symbol, record, None)
            except Exception as exc:
                return (symbol, None, str(exc))

        # Process indicator computation in parallel using ThreadPoolExecutor
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Submit all computation tasks
                future_to_symbol = {
                    executor.submit(compute_indicators, item): item[0]
                    for item in analyzers
                }

                # Collect results as they complete
                completed = 0
                for future in as_completed(future_to_symbol):
                    try:
                        symbol, record, error = future.result(timeout=30)  # 30s timeout per computation
                        completed += 1

                        if error:
                            logger.warning("Failed to compute indicators for %s: %s", symbol, error)
                            failures.append(symbol)
                        else:
                            records.append(record)
                            logger.info("[%d/%d] Computed indicators for %s", completed, len(analyzers), symbol)
                    except Exception as exc:
                        symbol = future_to_symbol.get(future, "unknown")
                        logger.warning("Thread error for %s: %s", symbol, exc)
                        failures.append(symbol)
        except Exception as exc:
            logger.error("ThreadPoolExecutor error: %s", exc)
            # If threading fails, fall back to sequential computation
            if not records:
                logger.info("Falling back to sequential computation...")
                for symbol, analyzer in analyzers:
                    try:
                        record = analyzer.compute_all_indicators()
                        records.append(record)
                    except Exception as e:
                        logger.warning("Failed for %s: %s", symbol, e)
                        failures.append(symbol)

        if not records:
            raise RuntimeError("Fundamental analyzer pipeline could not compute any tickers")

        df = pd.DataFrame(records)
        if failures:
            df.attrs["failed_tickers"] = failures

        # Cache the computed metrics
        self._save_cached_metrics(df, symbols)
        self._metrics_df = df

        logger.info("[COMPLETED] Processed %d tickers (%d successful, %d failed)",
                    len(symbols), len(records), len(failures))

        return PipelineResult(
            tickers_analyzed=symbols,
            dataframe=df,
            from_cache=False
        )

    def get_metrics(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get computed metrics for a specific ticker as JSON.

        Args:
            ticker: The ticker symbol (with or without .NS suffix)

        Returns:
            Dict with all computed metrics for the ticker (NaN replaced with "NOT_AVAILABLE"),
            or None if not found.
        """
        ticker_fmt = ticker.upper()
        if not ticker_fmt.endswith(".NS"):
            ticker_fmt = f"{ticker_fmt}.NS"

        row = None

        # Load from memory if available
        if self._metrics_df is not None:
            mask = self._metrics_df["ticker"] == ticker_fmt
            if mask.any():
                row = self._metrics_df[mask].iloc[0]

        # Try loading from cache
        if row is None and self._metrics_cache_path.exists():
            try:
                df = pd.read_pickle(self._metrics_cache_path)
                df.to_csv("metrics_cache.csv")
                mask = df["ticker"] == ticker_fmt
                if mask.any():
                    self._metrics_df = df  # Cache in memory
                    row = df[mask].iloc[0]
            except Exception as e:
                logger.warning("Failed to load metrics cache: %s", e)

        if row is None:
            return None

        # Convert to dict, replace NaN with "NOT_AVAILABLE", and round numbers to 3 decimal places
        result = row.to_dict()
        for key, value in result.items():
            if pd.isna(value):
                result[key] = None
            elif isinstance(value, float):
                result[key] = round(value, 3)

        return result

    def get_all_metrics(self) -> Optional[pd.DataFrame]:
        """Get the full metrics DataFrame for all tickers.

        Returns:
            pd.DataFrame with all computed metrics, or None if not available.
        """
        if self._metrics_df is not None:
            return self._metrics_df.copy()

        # Try loading from cache
        if self._metrics_cache_path.exists():
            try:
                df = pd.read_pickle(self._metrics_cache_path)
                self._metrics_df = df
                return df.copy()
            except Exception as e:
                logger.warning("Failed to load metrics cache: %s", e)

        return None

    # ------------------------------------------------------------------
    # Metrics caching helpers
    # ------------------------------------------------------------------

    def _compute_tickers_hash(self, tickers: List[str]) -> str:
        """Compute a hash of the ticker list for cache validation."""
        tickers_str = ",".join(sorted(tickers))
        return hashlib.md5(tickers_str.encode()).hexdigest()

    def _load_cached_metrics(self, tickers: List[str]) -> Optional[pd.DataFrame]:
        """Load cached metrics if valid and up-to-date."""
        if not self._metrics_cache_path.exists() or not self._metrics_metadata_path.exists():
            logger.debug("Metrics cache files not found")
            return None

        try:
            # Load and validate metadata
            metadata = json.loads(self._metrics_metadata_path.read_text())

            # Check if ticker list matches
            expected_hash = self._compute_tickers_hash(tickers)
            if metadata.get("tickers_hash") != expected_hash:
                logger.debug("Metrics cache ticker hash mismatch")
                return None

            # Check if underlying statements have been updated
            statements_updated = metadata.get("statements_last_updated", "")
            current_statements_ts = self._get_statements_timestamp()

            if current_statements_ts and statements_updated != current_statements_ts:
                logger.debug("Underlying statements have been updated, recomputing metrics")
                return None

            # Load the cached DataFrame
            df = pd.read_pickle(self._metrics_cache_path)

            # Verify all requested tickers are present
            cached_tickers = set(df["ticker"].tolist())
            requested_tickers = set(tickers)
            if not requested_tickers.issubset(cached_tickers):
                logger.debug("Cached metrics missing some tickers")
                return None

            # Filter to only requested tickers (in case cache has more)
            df = df[df["ticker"].isin(requested_tickers)]

            logger.info(
                "[METRICS CACHE] Loaded from cache (last_updated: %s)",
                metadata.get("last_updated", "unknown")
            )
            return df

        except Exception as e:
            logger.warning("Failed to load metrics cache: %s", e)
            return None

    def _save_cached_metrics(self, df: pd.DataFrame, tickers: List[str]) -> None:
        """Save computed metrics to cache."""
        try:
            # Save DataFrame
            df.to_pickle(self._metrics_cache_path)

            # Save metadata
            metadata = {
                "last_updated": datetime.utcnow().isoformat(),
                "tickers_hash": self._compute_tickers_hash(tickers),
                "tickers_count": len(tickers),
                "statements_last_updated": self._get_statements_timestamp(),
            }
            self._metrics_metadata_path.write_text(json.dumps(metadata, indent=2))

            logger.info(
                "[METRICS CACHED] Saved %d tickers to %s (%.2f MB)",
                len(tickers),
                self._metrics_cache_path.name,
                self._metrics_cache_path.stat().st_size / (1024 * 1024)
            )
        except Exception as e:
            logger.warning("Failed to save metrics cache: %s", e)

    def _get_statements_timestamp(self) -> str:
        """Get a combined timestamp of all statement files for cache validation."""
        timestamps = []
        for stmt_type in ["balance_sheet", "income_statement", "cashflow"]:
            meta_file = self._cache_dir / f"{stmt_type}_metadata.json"
            if meta_file.exists():
                try:
                    # Use file modification time as a simple proxy
                    timestamps.append(str(meta_file.stat().st_mtime))
                except Exception:
                    pass
        return "|".join(sorted(timestamps)) if timestamps else ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_financials(self, analyzer: FundamentalAnalyzer, *, force_refresh: bool) -> None:
        """Load financial statements for a ticker, using cache if available.

        The cache automatically updates when:
        1. force_refresh=True is passed
        2. Cache is older than max_age_days (default 30 days)
        3. Ticker not found in cache

        When fetching new data, it also checks for new periods (dates) and
        merges them into the existing cache.

        Caches: balance_sheet, income_statement, cashflow, financials, info
        """
        ticker = analyzer.ticker_symbol
        yf_ticker = analyzer.ticker

        # Try to get from cache first (unless force_refresh)
        if not force_refresh:
            try:
                bs_record = self.storage.get_balance_sheet(ticker)
                income_record = self.storage.get_income_statement(ticker)
                cash_record = self.storage.get_cashflow(ticker)
                fin_record = self.storage.get_financials(ticker)
                cached_info = self.storage.get_info(ticker)

                # If all core statements cached, use them
                if (not bs_record.dataframe.empty and
                    not income_record.dataframe.empty and
                    not cash_record.dataframe.empty):

                    # Log cache hit with details
                    logger.info(
                        "[CACHE HIT] %s - loaded from cache (updated: %s, source: %s)",
                        ticker,
                        bs_record.last_updated.strftime("%Y-%m-%d %H:%M"),
                        bs_record.source
                    )
                    logger.debug(
                        "  Balance sheet periods: %s",
                        list(bs_record.dataframe.columns[:4])
                    )

                    # Use cached info or fetch fresh if missing
                    info = cached_info if cached_info else (yf_ticker.info or {})
                    # Use cached financials or empty df if missing
                    financials_df = fin_record.dataframe if not fin_record.dataframe.empty else pd.DataFrame()

                    analyzer.populate_financials(
                        balance_sheet=bs_record.dataframe,
                        income_statement=income_record.dataframe,
                        cashflow=cash_record.dataframe,
                        info=info,
                        financials=financials_df,
                    )
                    return
            except Exception as e:
                logger.debug("Cache miss for %s: %s", ticker, e)

        # Fetch directly from yfinance (simple approach like original)
        logger.info("[FETCHING] %s - downloading from Yahoo Finance...", ticker)
        if not analyzer._fetch_financials():
            raise ValueError(f"Failed to fetch financials for {ticker}")

        # Log fetched data periods
        if analyzer._balance_sheet is not None:
            periods = list(analyzer._balance_sheet.columns[:4])
            logger.info("[FETCHED] %s - balance sheet periods: %s", ticker, periods)

        # Cache the fetched data for next time (with automatic period merging)
        try:
            if analyzer._balance_sheet is not None and not analyzer._balance_sheet.empty:
                self.storage.cache_statement("balance_sheet", ticker, analyzer._balance_sheet)
            if analyzer._income_stmt is not None and not analyzer._income_stmt.empty:
                self.storage.cache_statement("income_statement", ticker, analyzer._income_stmt)
            if analyzer._cashflow is not None and not analyzer._cashflow.empty:
                self.storage.cache_statement("cashflow", ticker, analyzer._cashflow)
            if analyzer._financials is not None and not analyzer._financials.empty:
                self.storage.cache_statement("financials", ticker, analyzer._financials)
            if analyzer._info:
                self.storage.cache_info(ticker, analyzer._info)
            logger.info("[CACHED] %s - statements and info saved to cache", ticker)
        except Exception as e:
            logger.warning("Failed to cache statements for %s: %s", ticker, e)


__all__ = [
    "FundamentalAnalyzer",
    "FundamentalAnalyzerPipeline",
    "PipelineResult",
]
