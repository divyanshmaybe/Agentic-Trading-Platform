"""Financial statement cache with MultiIndex storage.

Instead of persisting one CSV per ticker (which would become 1,500+ files for the
Nifty 500 universe × 3 statement types) we keep a *single* file per statement
(`balance_sheet`, `income_statement`, `cashflow`). Each file stores a
``pd.DataFrame`` whose columns form a MultiIndex ``(ticker, period)`` so the
original Yahoo Finance layout is preserved. Fetching a ticker simply slices out
its columns and you get the exact same shape as ``yf.Ticker().get_balance_sheet``.

Typical usage::

    storage = FinancialStatementsStorage()
    ticker = yf.Ticker("RELIANCE.NS")
    bs_record = storage.get_balance_sheet(
        "RELIANCE.NS",
        fetcher=lambda: ticker.get_balance_sheet(freq="yearly"),
    )
    balance_sheet_df = bs_record.dataframe  # identical schema to Yahoo output

The helper also exposes ``load_nifty500_symbols`` which reads
``scripts/nifty_500_stats.csv`` and returns every NSE symbol with the ``.NS``
suffix so you can drive bulk downloads for the entire universe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Literal, Optional

import pandas as pd

StatementType = Literal["balance_sheet", "income_statement", "cashflow", "financials"]


@dataclass
class StatementRecord:
    """Convenience wrapper returned by the storage service."""

    ticker: str
    statement_type: StatementType
    dataframe: pd.DataFrame
    source: Literal["cache", "fetched"]
    last_updated: datetime


class FinancialStatementsStorage:
    """Aggregate Yahoo Finance statements into MultiIndex pickle files."""

    STATEMENT_FILES: Dict[StatementType, str] = {
        "balance_sheet": "balance_sheet.pkl",
        "income_statement": "income_statement.pkl",
        "cashflow": "cashflow.pkl",
        "financials": "financials.pkl",
    }

    INFO_FILE = "ticker_info.json"

    def __init__(
        self,
        data_dir: str | Path = "data/financial_statements",
        max_age_days: int = 30,
        nifty500_csv: Optional[str | Path] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.max_age = timedelta(days=max_age_days)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.nifty500_csv = (
            Path(nifty500_csv)
            if nifty500_csv
            else Path(__file__).resolve().parents[3] / "scripts" / "nifty_500_stats.csv"
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_balance_sheet(
        self,
        ticker: str,
        *,
        fetcher: Optional[Callable[[], pd.DataFrame]] = None,
        force_refresh: bool = False,
    ) -> StatementRecord:
        """Get balance sheet, returning empty record if not cached and no fetcher."""
        if fetcher is None and not force_refresh:
            return self._get_cached_or_empty("balance_sheet", ticker)
        return self._get_statement("balance_sheet", ticker, fetcher, force_refresh)

    def get_income_statement(
        self,
        ticker: str,
        *,
        fetcher: Optional[Callable[[], pd.DataFrame]] = None,
        force_refresh: bool = False,
    ) -> StatementRecord:
        """Get income statement, returning empty record if not cached and no fetcher."""
        if fetcher is None and not force_refresh:
            return self._get_cached_or_empty("income_statement", ticker)
        return self._get_statement("income_statement", ticker, fetcher, force_refresh)

    def get_cashflow(
        self,
        ticker: str,
        *,
        fetcher: Optional[Callable[[], pd.DataFrame]] = None,
        force_refresh: bool = False,
    ) -> StatementRecord:
        """Get cashflow, returning empty record if not cached and no fetcher."""
        if fetcher is None and not force_refresh:
            return self._get_cached_or_empty("cashflow", ticker)
        return self._get_statement("cashflow", ticker, fetcher, force_refresh)

    def get_financials(
        self,
        ticker: str,
        *,
        fetcher: Optional[Callable[[], pd.DataFrame]] = None,
        force_refresh: bool = False,
    ) -> StatementRecord:
        """Get financials statement, returning empty record if not cached and no fetcher."""
        if fetcher is None and not force_refresh:
            return self._get_cached_or_empty("financials", ticker)
        return self._get_statement("financials", ticker, fetcher, force_refresh)

    def _get_cached_or_empty(
        self,
        statement_type: StatementType,
        ticker: str,
    ) -> StatementRecord:
        """Return cached statement or empty record (never raises)."""
        ticker_fmt = self._fmt_ticker(ticker)
        collection = self._load_collection(statement_type)
        metadata = self._load_metadata(statement_type)
        cached_df = self._extract_ticker(collection, ticker_fmt)
        
        last_updated = datetime.utcnow()
        if ticker_fmt in metadata:
            last_updated = datetime.fromisoformat(metadata[ticker_fmt])
        
        return StatementRecord(
            ticker=ticker_fmt,
            statement_type=statement_type,
            dataframe=cached_df,  # May be empty DataFrame
            source="cache",
            last_updated=last_updated,
        )

    def get_info(
        self,
        ticker: str,
    ) -> Dict:
        """Get cached ticker info or return empty dict."""
        ticker_fmt = self._fmt_ticker(ticker)
        info_path = self.data_dir / self.INFO_FILE
        if not info_path.exists():
            return {}
        try:
            all_info = json.loads(info_path.read_text())
            return all_info.get(ticker_fmt, {})
        except Exception:
            return {}

    def cache_info(
        self,
        ticker: str,
        info: Dict,
    ) -> None:
        """Cache ticker info to JSON file."""
        ticker_fmt = self._fmt_ticker(ticker)
        info_path = self.data_dir / self.INFO_FILE
        try:
            all_info = json.loads(info_path.read_text()) if info_path.exists() else {}
        except Exception:
            all_info = {}
        all_info[ticker_fmt] = info
        info_path.write_text(json.dumps(all_info, indent=2, default=str))

    def cache_statement(
        self,
        statement_type: StatementType,
        ticker: str,
        dataframe: pd.DataFrame,
    ) -> StatementRecord:
        """Save a statement DataFrame directly (used after manual fetch)."""
        ticker_fmt = self._fmt_ticker(ticker)
        dataframe = self._validate_dataframe(dataframe, ticker_fmt, statement_type)
        collection = self._load_collection(statement_type)
        collection = self._upsert_ticker(collection, ticker_fmt, dataframe)
        self._save_collection(statement_type, collection)
        self._update_metadata(statement_type, ticker_fmt)
        return StatementRecord(
            ticker=ticker_fmt,
            statement_type=statement_type,
            dataframe=dataframe,
            source="fetched",
            last_updated=datetime.utcnow(),
        )

    def clear_cache(
        self,
        statement_type: Optional[StatementType] = None,
        tickers: Optional[Iterable[str]] = None,
    ) -> int:
        """Remove cached tickers (or whole files). Returns count removed."""
        if statement_type is None:
            removed = 0
            for stype in self.STATEMENT_FILES:
                removed += self.clear_cache(stype, tickers)
            return removed

        collection = self._load_collection(statement_type)
        metadata = self._load_metadata(statement_type)

        if tickers is None:
            file_path = self._collection_file(statement_type)
            if file_path.exists():
                file_path.unlink()
            meta_path = self._metadata_file(statement_type)
            if meta_path.exists():
                meta_path.unlink()
            return len(metadata)

        tickers_norm = [self._fmt_ticker(t) for t in tickers]
        removed = 0
        if not collection.empty and isinstance(collection.columns, pd.MultiIndex):
            level0 = collection.columns.get_level_values(0)
            for ticker in tickers_norm:
                if ticker in level0:
                    collection = collection.drop(columns=ticker, level=0)
                    metadata.pop(ticker, None)
                    removed += 1

        if collection.empty:
            file_path = self._collection_file(statement_type)
            if file_path.exists():
                file_path.unlink()
        else:
            self._save_collection(statement_type, collection)

        self._save_metadata(statement_type, metadata)
        return removed

    def load_nifty500_symbols(self) -> List[str]:
        """Return all NSE symbols from nifty_500_stats.csv with `.NS` suffix."""
        try:
            df = pd.read_csv(self.nifty500_csv)
        except Exception:
            return []

        if "Symbol" not in df.columns:
            return []

        symbols = {
            self._fmt_ticker(str(symbol))
            for symbol in df["Symbol"].dropna().unique().tolist()
            if str(symbol).strip()
        }
        return sorted(symbols)

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def _get_statement(
        self,
        statement_type: StatementType,
        ticker: str,
        fetcher: Optional[Callable[[], pd.DataFrame]],
        force_refresh: bool,
    ) -> StatementRecord:
        ticker_fmt = self._fmt_ticker(ticker)
        collection = self._load_collection(statement_type)
        metadata = self._load_metadata(statement_type)
        cached_df = self._extract_ticker(collection, ticker_fmt)

        if (
            not force_refresh
            and not cached_df.empty
            and ticker_fmt in metadata
            and datetime.utcnow() - datetime.fromisoformat(metadata[ticker_fmt]) <= self.max_age
        ):
            return StatementRecord(
                ticker=ticker_fmt,
                statement_type=statement_type,
                dataframe=cached_df,
                source="cache",
                last_updated=datetime.fromisoformat(metadata[ticker_fmt]),
            )

        if fetcher is None:
            raise ValueError(
                f"Cached {statement_type} for {ticker_fmt} missing/stale, and no fetcher provided."
            )

        fetched = fetcher()
        fetched = self._validate_dataframe(fetched, ticker_fmt, statement_type)
        collection = self._upsert_ticker(collection, ticker_fmt, fetched)
        self._save_collection(statement_type, collection)
        self._update_metadata(statement_type, ticker_fmt)

        return StatementRecord(
            ticker=ticker_fmt,
            statement_type=statement_type,
            dataframe=fetched,
            source="fetched",
            last_updated=datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    def _collection_file(self, statement_type: StatementType) -> Path:
        return self.data_dir / self.STATEMENT_FILES[statement_type]

    def _load_collection(self, statement_type: StatementType) -> pd.DataFrame:
        path = self._collection_file(statement_type)
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_pickle(path)
        except Exception:
            return pd.DataFrame()

    def _save_collection(self, statement_type: StatementType, dataframe: pd.DataFrame) -> None:
        path = self._collection_file(statement_type)
        dataframe.to_pickle(path)

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _metadata_file(self, statement_type: StatementType) -> Path:
        return self.data_dir / f"{statement_type}_metadata.json"

    def _load_metadata(self, statement_type: StatementType) -> Dict[str, str]:
        path = self._metadata_file(statement_type)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    def _save_metadata(self, statement_type: StatementType, metadata: Dict[str, str]) -> None:
        path = self._metadata_file(statement_type)
        path.write_text(json.dumps(metadata, indent=2))

    def _update_metadata(self, statement_type: StatementType, ticker: str) -> None:
        metadata = self._load_metadata(statement_type)
        metadata[ticker] = datetime.utcnow().isoformat()
        self._save_metadata(statement_type, metadata)

    # ------------------------------------------------------------------
    # DataFrame helpers
    # ------------------------------------------------------------------

    def _upsert_ticker(
        self,
        collection: pd.DataFrame,
        ticker: str,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        wrapped = self._wrap_with_ticker(dataframe, ticker)
        if collection.empty:
            return wrapped

        if isinstance(collection.columns, pd.MultiIndex):
            if ticker in collection.columns.get_level_values(0):
                collection = collection.drop(columns=ticker, level=0)
        else:
            collection = pd.DataFrame()

        if collection.empty:
            return wrapped

        # Use join='inner' to only keep rows that exist in both DataFrames
        # This prevents NaN values from appearing when row indices differ
        # between the existing collection and the new ticker data.
        # Each ticker's data will be complete for its own rows.
        return pd.concat([collection, wrapped], axis=1, join='outer')

    @staticmethod
    def _wrap_with_ticker(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        wrapped = df.copy()
        if wrapped.empty:
            raise ValueError(f"Fetched DataFrame for {ticker} is empty")

        level0 = pd.Index([ticker] * wrapped.shape[1], name="ticker")
        level1 = pd.Index(wrapped.columns, name="period")
        wrapped.columns = pd.MultiIndex.from_arrays([level0, level1])
        return wrapped

    @staticmethod
    def _extract_ticker(collection: pd.DataFrame, ticker: str) -> pd.DataFrame:
        if collection.empty or not isinstance(collection.columns, pd.MultiIndex):
            return pd.DataFrame()
        if ticker not in collection.columns.get_level_values(0):
            return pd.DataFrame()
        extracted = collection.xs(ticker, axis=1, level=0)
        # Drop rows where ALL values are NaN (these are rows that didn't exist
        # in the original fetch for this ticker but exist for other tickers)
        return extracted.dropna(how='all')

    @staticmethod
    def _validate_dataframe(
        dataframe: Optional[pd.DataFrame],
        ticker: str,
        statement_type: StatementType,
    ) -> pd.DataFrame:
        if dataframe is None or dataframe.empty:
            raise ValueError(f"Fetcher returned empty DataFrame for {ticker} ({statement_type})")
        if dataframe.index.name is None:
            dataframe = dataframe.copy()
            dataframe.index.name = "line_item"
        return dataframe

    @staticmethod
    def _fmt_ticker(ticker: str) -> str:
        ticker = ticker.strip().upper()
        return ticker if ticker.endswith(".NS") else f"{ticker}.NS"


from typing import Any

__all__ = ["FinancialStatementsStorage", "StatementRecord"]
