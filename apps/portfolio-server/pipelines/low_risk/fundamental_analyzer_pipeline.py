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
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from yfinance import data as yf_data

from utils.financial_statements_storage import FinancialStatementsStorage

logger = logging.getLogger(__name__)


_YFINANCE_PATCHED = False


def _patch_yfinance_rate_limit() -> None:
    """Monkeypatch YF crumb retrieval to retry on 429 responses."""

    global _YFINANCE_PATCHED
    if _YFINANCE_PATCHED:
        return

    original_get_crumb_basic = yf_data.YfData._get_crumb_basic

    def _resilient_get_crumb_basic(self, proxy=None, timeout=30):  # type: ignore[override]
        attempts = 0
        while True:
            crumb = original_get_crumb_basic(self, proxy, timeout)
            if crumb and "Too Many Requests" not in crumb:
                return crumb.strip()
            # Reset cached crumb and back off before re-fetching.
            self._crumb = None
            attempts += 1
            if attempts >= 6:
                return crumb
            sleep_for = min(2 ** (attempts - 1), 10)
            logger.warning(
                "Yahoo crumb request throttled (attempt %s), retrying in %.1fs",
                attempts,
                sleep_for,
            )
            time.sleep(sleep_for)

    yf_data.YfData._get_crumb_basic = _resilient_get_crumb_basic  # type: ignore[assignment]
    _YFINANCE_PATCHED = True


_patch_yfinance_rate_limit()


class FundamentalAnalyzer:
    """Compute fundamental/technical indicators for a single ticker."""

    def __init__(self, ticker_symbol: str, raw: Optional[pd.DataFrame] = None):
        self.ticker_symbol = ticker_symbol
        self.ticker = yf.Ticker(ticker_symbol)

        self._balance_sheet: Optional[pd.DataFrame] = None
        self._income_stmt: Optional[pd.DataFrame] = None
        self._cashflow: Optional[pd.DataFrame] = None
        self._info: Dict[str, Any] = {}
        self._financials_loaded = False
        self.raw = raw

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    def populate_financials(
        self,
        *,
        balance_sheet: pd.DataFrame,
        income_statement: pd.DataFrame,
        cashflow: pd.DataFrame,
        info: Dict[str, Any],
    ) -> None:
        """Inject already-fetched statements/info and flag as loaded."""
        self._balance_sheet = balance_sheet
        self._income_stmt = income_statement
        self._cashflow = cashflow
        self._info = info or {}
        self._financials_loaded = True

    def _get(self, df: Optional[pd.DataFrame], field: str, col: int = 0, default=pd.NA):
        try:
            if df is None or field not in df.index:
                return default
            if col >= len(df.columns):
                return default
            val = df.loc[field, df.columns[col]]
            return val if pd.notna(val) else default
        except Exception:
            return default

    def _prev(self, df: Optional[pd.DataFrame], field: str, col: int = 1, default=pd.NA):
        return self._get(df, field, col, default)

    # ------------------------------------------------------------------
    # Indicator computations (subset of common quant factors)
    # ------------------------------------------------------------------

    def compute_piotroski_fscore(self):
        if not self._financials_loaded:
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

        if pd.notna(NI) and pd.notna(TA) and TA > 0 and NI / TA > 0:
            score += 1
        if pd.notna(CFO) and CFO > 0:
            score += 1
        if all(pd.notna(v) for v in [NI, TA, NI_prev, TA_prev]):
            if TA > 0 and TA_prev > 0 and (NI / TA) > (NI_prev / TA_prev):
                score += 1
        if pd.notna(CFO) and pd.notna(NI) and CFO > NI:
            score += 1
        if pd.notna(LTD) and pd.notna(LTD_prev) and LTD <= LTD_prev:
            score += 1
        if all(pd.notna(v) for v in [CA, CL, CA_prev, CL_prev]) and CL > 0 and CL_prev > 0:
            if (CA / CL) > (CA_prev / CL_prev):
                score += 1
        if pd.notna(SH) and pd.notna(SH_prev) and SH <= SH_prev:
            score += 1
        if all(pd.notna(v) for v in [GP, REV, GP_prev, REV_prev]) and REV > 0 and REV_prev > 0:
            if (GP / REV) > (GP_prev / REV_prev):
                score += 1
        if all(pd.notna(v) for v in [REV, TA, REV_prev, TA_prev]) and TA > 0 and TA_prev > 0:
            if (REV / TA) > (REV_prev / TA_prev):
                score += 1

        return int(score)

    def compute_sloan_ratio(self):
        if not self._financials_loaded:
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
        if not self._financials_loaded:
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
        if not self._financials_loaded:
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
        if not self._financials_loaded:
            return pd.NA

        div_yield = self._info.get("dividendYield", 0)
        fcf = self._info.get("freeCashflow", 0)
        market_cap = self._info.get("marketCap")

        if not market_cap or market_cap == 0:
            return pd.NA

        fcf_yield = fcf / market_cap if fcf else 0
        return float((div_yield or 0) + fcf_yield)

    def compute_roic(self):
        if not self._financials_loaded:
            return pd.NA

        ebit = self._get(self._income_stmt, "EBIT")
        tax_rate = self._get(self._income_stmt, "Tax Rate For Calcs", default=0.25)
        invested_capital = self._get(self._balance_sheet, "InvestedCapital")

        if pd.isna(invested_capital):
            total_debt = self._get(self._balance_sheet, "TotalDebt", default=0)
            equity = self._get(self._balance_sheet, "StockholdersEquity", default=0)
            cash = self._get(self._balance_sheet, "CashAndCashEquivalents", default=0)
            invested_capital = total_debt + equity - cash

        if pd.isna(ebit) or pd.isna(invested_capital) or invested_capital == 0:
            return pd.NA

        nopat = ebit * (1 - tax_rate)
        return float(nopat / invested_capital)

    def compute_rs_ratio(self):
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol]
            if stock_data.empty:
                return pd.NA

            index_data = self.raw[self.raw["Ticker"] == "^CRSLDX"]
            if index_data.empty:
                return pd.NA

            latest_stock_price = stock_data["Close"].iloc[-1]
            latest_index_price = index_data["Close"].iloc[-1]

            if pd.isna(latest_stock_price) or pd.isna(latest_index_price) or latest_index_price == 0:
                return pd.NA

            return float(latest_stock_price / latest_index_price)
        except Exception:
            return pd.NA

    def compute_momentum_6_1(self):
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            if len(stock_data) < 126:
                return pd.NA

            if len(stock_data) < 21:
                return pd.NA
            price_t_1 = stock_data["Close"].iloc[-21]
            price_t_6 = stock_data["Close"].iloc[-126]

            if pd.isna(price_t_1) or pd.isna(price_t_6) or price_t_6 == 0:
                return pd.NA

            return float((price_t_1 / price_t_6) - 1)
        except Exception:
            return pd.NA

    def compute_rsi_14(self):
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            if len(stock_data) < 15:
                return pd.NA

            close_prices = stock_data["Close"].values
            deltas = np.diff(close_prices)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)

            avg_gain = np.mean(gains[-14:])
            avg_loss = np.mean(losses[-14:])

            if avg_loss == 0:
                return 100.0

            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

            return float(rsi)
        except Exception:
            return pd.NA

    def _compute_ema(self, length: int):
        try:
            if self.raw is None or self.raw.empty:
                return pd.NA

            stock_data = self.raw[self.raw["Ticker"] == self.ticker_symbol].sort_values("Date")

            if len(stock_data) < length:
                return pd.NA

            ema_series = stock_data["Close"].ewm(span=length, adjust=False).mean()
            return float(ema_series.iloc[-1])
        except Exception:
            return pd.NA

    def compute_ema50(self):
        return self._compute_ema(50)

    def compute_ema200(self):
        return self._compute_ema(200)

    def get_valuation_metrics(self):
        if not self._financials_loaded:
            return {}

        return {
            "forward_pe": self._info.get("forwardPE", pd.NA),
            "price_to_book": self._info.get("priceToBook", pd.NA),
            "ev_to_ebitda": self._info.get("enterpriseToEbitda", pd.NA),
        }

    def get_growth_metrics(self):
        if not self._financials_loaded:
            return {}

        return {
            "revenue_growth": self._info.get("revenueGrowth", pd.NA),
            "earnings_growth": self._info.get("earningsGrowth", pd.NA),
            "earnings_quarterly_growth": self._info.get("earningsQuarterlyGrowth", pd.NA),
        }

    def get_financial_health_metrics(self):
        if not self._financials_loaded:
            return {}

        return {
            "debt_to_equity": self._info.get("debtToEquity", pd.NA),
        }

    def get_price_metrics(self):
        if not self._financials_loaded:
            return {}

        return {
            "current_price": self._info.get("currentPrice", self._info.get("regularMarketPrice", pd.NA)),
            "fifty_two_week_change": self._info.get("52WeekChange", pd.NA),
        }

    def get_volume_metrics(self):
        if not self._financials_loaded:
            return {}

        return {
            "volume": self._info.get("volume", pd.NA),
        }

    def compute_all_indicators(self) -> Dict[str, Any]:
        result = {
            "ticker": self.ticker_symbol,
            "piotroski_fscore": self.compute_piotroski_fscore(),
            "sloan_ratio": self.compute_sloan_ratio(),
            "ccc": self.compute_ccc(),
            "beneish_mscore": self.compute_beneish_mscore(),
            "shareholder_yield": self.compute_shareholder_yield(),
            "roic": self.compute_roic(),
            "rs_ratio": self.compute_rs_ratio(),
            "momentum_6_1": self.compute_momentum_6_1(),
            "rsi_14": self.compute_rsi_14(),
            "ema50": self.compute_ema50(),
            "ema200": self.compute_ema200(),
        }

        result.update(self.get_valuation_metrics())
        result.update(self.get_growth_metrics())
        result.update(self.get_financial_health_metrics())
        result.update(self.get_price_metrics())
        result.update(self.get_volume_metrics())
        return result


@dataclass
class PipelineResult:
    """Container for pipeline outputs."""

    tickers_analyzed: List[str]
    dataframe: pd.DataFrame


class FundamentalAnalyzerPipeline:
    """Run FundamentalAnalyzer across a universe with cached statements."""

    def __init__(
        self,
        *,
        storage: Optional[FinancialStatementsStorage] = None,
        raw_data: Optional[pd.DataFrame] = None,
        max_tickers: int,
        force_refresh: bool = False,
    ) -> None:
        self.storage = storage or FinancialStatementsStorage()
        self.raw_data = raw_data
        self.max_tickers = max_tickers
        self.force_refresh = force_refresh

    def run(
        self,
        tickers: Optional[Iterable[str]] = None,
        *,
        max_tickers: Optional[int] = None,
        force_refresh: Optional[bool] = None,
    ) -> PipelineResult:
        symbols = list(tickers) if tickers else self.storage.load_nifty500_symbols()
        if not symbols:
            raise ValueError("No tickers provided and no symbols available from Nifty 500 list")

        limit = max_tickers or self.max_tickers
        symbols = symbols[:limit]
        refresh = self.force_refresh if force_refresh is None else force_refresh

        records: List[Dict[str, Any]] = []
        failures: List[str] = []

        for symbol in symbols:
            analyzer = FundamentalAnalyzer(symbol, raw=self.raw_data)
            try:
                self._load_financials(analyzer, force_refresh=refresh)
                record = analyzer.compute_all_indicators()
                records.append(record)
                logger.info("Computed indicators for %s", symbol)
            except Exception as exc:
                logger.warning("Failed to compute indicators for %s: %s", symbol, exc)
                failures.append(symbol)

        if not records:
            raise RuntimeError("Fundamental analyzer pipeline could not compute any tickers")

        df = pd.DataFrame(records)
        if failures:
            df.attrs["failed_tickers"] = failures
        return PipelineResult(tickers_analyzed=symbols, dataframe=df)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_financials(self, analyzer: FundamentalAnalyzer, *, force_refresh: bool) -> None:
        ticker = analyzer.ticker_symbol
        yf_ticker = analyzer.ticker

        bs_record = self.storage.get_balance_sheet(
            ticker,
            fetcher=lambda: self._fetch_balance_sheet(yf_ticker),
            force_refresh=force_refresh,
        )
        income_record = self.storage.get_income_statement(
            ticker,
            fetcher=lambda: self._fetch_income_statement(yf_ticker),
            force_refresh=force_refresh,
        )
        cash_record = self.storage.get_cashflow(
            ticker,
            fetcher=lambda: self._fetch_cashflow(yf_ticker),
            force_refresh=force_refresh,
        )

        info = yf_ticker.get_info()

        analyzer.populate_financials(
            balance_sheet=bs_record.dataframe,
            income_statement=income_record.dataframe,
            cashflow=cash_record.dataframe,
            info=info,
        )

    # ------------------------------------------------------------------
    # Yahoo fetch fallbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _first_non_empty(fetchers, label: str, ticker: str) -> pd.DataFrame:
        last_exc: Optional[Exception] = None
        for fetch in fetchers:
            try:
                df = fetch()
            except Exception as exc:
                last_exc = exc
                continue
            if df is not None and not df.empty:
                return df
        if last_exc:
            raise last_exc
        raise ValueError(f"No {label} data returned for {ticker}")

    def _fetch_balance_sheet(self, yf_ticker: yf.Ticker) -> pd.DataFrame:
        return self._first_non_empty(
            [
                lambda: yf_ticker.get_balance_sheet(freq="yearly"),
                lambda: yf_ticker.balance_sheet,
                lambda: yf_ticker.get_balance_sheet(freq="quarterly"),
            ],
            "balance_sheet",
            yf_ticker.ticker,
        )

    def _fetch_income_statement(self, yf_ticker: yf.Ticker) -> pd.DataFrame:
        return self._first_non_empty(
            [
                lambda: yf_ticker.income_stmt,
                lambda: yf_ticker.get_income_stmt(freq="yearly"),
                lambda: yf_ticker.get_income_stmt(freq="quarterly"),
            ],
            "income_statement",
            yf_ticker.ticker,
        )

    def _fetch_cashflow(self, yf_ticker: yf.Ticker) -> pd.DataFrame:
        return self._first_non_empty(
            [
                lambda: yf_ticker.get_cashflow(freq="yearly"),
                lambda: yf_ticker.cashflow,
                lambda: yf_ticker.get_cashflow(freq="quarterly"),
            ],
            "cashflow",
            yf_ticker.ticker,
        )


__all__ = [
    "FundamentalAnalyzer",
    "FundamentalAnalyzerPipeline",
    "PipelineResult",
]
