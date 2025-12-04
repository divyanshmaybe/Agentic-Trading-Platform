from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Tuple
import hashlib
import tempfile

import pathway as pw
import pandas as pd

from quant_stream.data.schema import MarketData


DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parents[2] / ".data" / "indian_stock_market_nifty500.csv"
)


def replay_market_data(
    csv_path: Path | str = DEFAULT_CSV_PATH,
    speedup: float = 3600 * 24,  # 1 second of real time = 1 day of market data
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    mode: str = "static",  # "static" for batch processing, "streaming" for real-time replay
    date_ranges: Optional[List[Tuple[Optional[str], Optional[str]]]] = None,
    cache_dir: Optional[str | Path] = None,
) -> pw.Table:
    """Load market data from a CSV file.

    Args:
        csv_path: Path to the CSV file containing market data (default: nifty500 filtered data)
        speedup: Replay speed multiplier (default: 3600 * 24 => 1 second = 1 day)
                 Only used in streaming mode.
        start_date: Optional start date to filter data (e.g., '2020-01-01')
        end_date: Optional end date to filter data (e.g., '2021-12-31')
        date_ranges: Optional list of [start, end] tuples to cover
                     specific segments (takes precedence over start/end)
        mode: Loading mode:
              - "static": Load all data immediately (for backtesting)
              - "streaming": Replay data over time (for real-time demos)

    Returns:
        A ``pw.Table`` with market data.
    
    Note:
        - In static mode, all data is loaded immediately for batch processing
        - In streaming mode, data is replayed based on timestamps
        - Symbol filtering is NOT applied as the data source is already filtered to nifty500
        - Date filtering is applied using native Pathway operations (no temp files)
    """
    csv_path = Path(csv_path).expanduser().resolve()

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file '{csv_path}' does not exist.")

    normalized_ranges = _normalize_date_ranges(date_ranges, start_date, end_date)
    cache_base = _resolve_cache_dir(cache_dir)

    # Load the CSV file
    csv_to_load = str(csv_path)
    
    # Choose loading mode
    if mode == "static":
        print(f"[INFO] Loading CSV in static mode: {csv_to_load}", flush=True)

        parquet_slices: List[Path] = []
        for range_start, range_end in normalized_ranges:
            print(f"[INFO] Processing date range: {range_start} to {range_end}", flush=True)
            parquet_slice = _materialize_parquet_slice(
                csv_path,
                (range_start, range_end),
                cache_base,
            )
            parquet_slices.append(parquet_slice)
            print(f"[INFO] Completed date range: {range_start} to {range_end}", flush=True)

        merged_parquet = _merge_parquet_slices(parquet_slices, cache_base)
        return pw.debug.table_from_parquet(str(merged_parquet))
    elif mode == "streaming":
        # Streaming mode: Replay data based on timestamps
        table = pw.demo.replay_csv_with_time(
            csv_to_load,
            schema=MarketData,
            time_column="timestamp",
            speedup=speedup,
        )
        
        # Apply date filtering for streaming mode
        # Note: Symbol filtering is not needed as data source is already filtered to nifty500
        if start_date or end_date:
            filters_applied = []
            if start_date:
                table = table.filter(pw.this.date >= start_date)
                filters_applied.append(f"date >= {start_date}")
            if end_date:
                table = table.filter(pw.this.date <= end_date)
                filters_applied.append(f"date <= {end_date}")
            print(f"[DEBUG] Applied stream filters: {', '.join(filters_applied)}")
        
        return table
    else:
        raise ValueError(f"Invalid mode: {mode}. Must be 'static' or 'streaming'.")


def _normalize_date_ranges(
    date_ranges: Optional[List[Tuple[Optional[str], Optional[str]]]],
    start_date: Optional[str],
    end_date: Optional[str],
) -> List[Tuple[Optional[str], Optional[str]]]:
    normalized: List[Tuple[Optional[str], Optional[str]]] = []
    if date_ranges:
        for entry in date_ranges:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError(f"date_ranges entries must be [start, end], got: {entry!r}")
            normalized_entry = (entry[0] or None, entry[1] or None)
            if normalized_entry not in normalized:
                normalized.append(normalized_entry)
    else:
        normalized.append((start_date, end_date))
    return normalized


def _resolve_cache_dir(cache_dir: Optional[str | Path]) -> Path:
    base_dir = Path(cache_dir).expanduser() if cache_dir else Path(tempfile.gettempdir()) / "quant_stream_cache"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _build_cache_key(
    data_path: Path,
    date_range: Tuple[Optional[str], Optional[str]],
) -> str:
    start, end = date_range
    cache_input = f"{data_path.resolve()}|{start or 'START'}|{end or 'END'}"
    return hashlib.sha1(cache_input.encode("utf-8")).hexdigest()


def _materialize_parquet_slice(
    csv_path: Path,
    date_range: Tuple[Optional[str], Optional[str]],
    cache_dir: Path,
) -> Path:
    """Create a cached Parquet slice for a date range.
    
    Note: Symbol filtering is not applied as data source is already filtered to nifty500.
    """
    cache_key = _build_cache_key(csv_path, date_range)
    parquet_path = cache_dir / f"{cache_key}.parquet"
    if parquet_path.exists():
        return parquet_path

    start_date, end_date = date_range
    print(
        f"[INFO] Creating cached slice for {csv_path} "
        f"({start_date or 'beginning'} to {end_date or 'end'})",
        flush=True
    )

    df = pd.read_csv(csv_path)

    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]

    if df.empty:
        raise ValueError(
            f"No rows found for date range {date_range} in {csv_path}"
        )

    df.to_parquet(parquet_path, index=False)
    return parquet_path


def _merge_parquet_slices(
    parquet_paths: List[Path],
    cache_dir: Path,
) -> Path:
    if not parquet_paths:
        raise ValueError("No parquet slices found when attempting to load market data.")

    if len(parquet_paths) == 1:
        return parquet_paths[0]

    key_input = "|".join(str(path.resolve()) for path in parquet_paths)
    cache_key = hashlib.sha1(key_input.encode("utf-8")).hexdigest()
    merged_path = cache_dir / f"{cache_key}_merged.parquet"
    if merged_path.exists():
        return merged_path

    data_frames = [pd.read_parquet(path) for path in parquet_paths]
    merged_df = pd.concat(data_frames, ignore_index=True)
    merged_df = merged_df.drop_duplicates(subset=["symbol", "timestamp"]).sort_values(
        ["timestamp", "symbol"]
    )
    merged_df.to_parquet(merged_path, index=False)
    return merged_path
