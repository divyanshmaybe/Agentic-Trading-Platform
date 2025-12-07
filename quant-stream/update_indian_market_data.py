#!/usr/bin/env python3
"""
Script to update Indian market data CSV for Nifty 500 stocks using Groww API.

This script:
1. Reads the nifty500.txt file to get all symbols and their date ranges
2. Pre-populates the new CSV from the old CSV if needed
3. For each symbol, checks the last date in the CSV
4. Fetches new data from the last date until the last market close day (parallel)
5. Updates the CSV file by appending new data (sorted by date)
6. Updates nifty500.txt with new end dates

Rate Limits: 10 requests/second, 300 requests/minute
"""

from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import pyotp
from growwapi import GrowwAPI
import os
from dotenv import load_dotenv

# File paths
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / ".data"
CSV_FILE = DATA_DIR / "indian_stock_market_nifty500.csv"  # New file for Nifty 500 only
OLD_CSV_FILE = DATA_DIR / "indian_market_data.csv"  # Original CSV to pre-populate from
NIFTY500_FILE = DATA_DIR / "nifty500.txt"
# Load environment variables from alphacopilot/.env
load_dotenv(SCRIPT_DIR / "alphacopilot" / ".env")
TOTP_TOKEN = os.getenv("TOTP_TOKEN")
TOTP_SECRET = os.getenv("TOTP_SECRET")

if not TOTP_TOKEN or not TOTP_SECRET:
    raise ValueError("TOTP_TOKEN and TOTP_SECRET must be set in environment variables")

# Rate limiting: 5 requests/second, 150 requests/minute (conservative for new API)
MAX_REQUESTS_PER_SECOND = 5
MAX_REQUESTS_PER_MINUTE = 150
MIN_INTERVAL_BETWEEN_REQUESTS = 1.0 / MAX_REQUESTS_PER_SECOND  # 0.2 seconds

# Groww API constants
INTERVAL_DAILY = 1440  # Daily candles (24 hours * 60 minutes)

# Thread-safe rate limiter
class RateLimiter:
    """Thread-safe rate limiter for API requests."""
    
    def __init__(self, max_per_second: float, max_per_minute: int):
        self.max_per_second = max_per_second
        self.max_per_minute = max_per_minute
        self.min_interval = 1.0 / max_per_second
        self.lock = threading.Lock()
        self.last_request_time = 0.0
        self.request_times: List[float] = []
    
    def wait(self):
        """Wait if necessary to respect rate limits."""
        with self.lock:
            now = time.time()
            
            # Remove requests older than 1 minute
            self.request_times = [t for t in self.request_times if now - t < 60]
            
            # Check per-minute limit
            if len(self.request_times) >= self.max_per_minute:
                # Wait until oldest request is 60 seconds old
                oldest = min(self.request_times)
                wait_time = 60 - (now - oldest) + 0.01  # Add small buffer
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
                    # Clean up again
                    self.request_times = [t for t in self.request_times if now - t < 60]
            
            # Check per-second limit
            elapsed = now - self.last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
                now = time.time()
            
            # Record this request
            self.last_request_time = now
            self.request_times.append(now)


# Global rate limiter instance
rate_limiter = RateLimiter(MAX_REQUESTS_PER_SECOND, MAX_REQUESTS_PER_MINUTE)


def get_last_market_close_date() -> datetime:
    """
    Get the last market close date (today if it's a weekday, otherwise last Friday).
    Note: This doesn't check for holidays, but the API will only return data for trading days.
    """
    today = datetime.now().date()
    
    # If today is Saturday (5) or Sunday (6), go back to last Friday
    weekday = today.weekday()
    if weekday == 5:  # Saturday
        days_back = 1
    elif weekday == 6:  # Sunday
        days_back = 2
    else:
        days_back = 0
    
    last_market_close = today - timedelta(days=days_back)
    
    # For market hours, if before 4 PM IST, use yesterday
    now = datetime.now()
    if now.hour < 16:  # Before 4 PM IST
        last_market_close = last_market_close - timedelta(days=1)
        # Adjust if yesterday was weekend
        while last_market_close.weekday() >= 5:
            last_market_close = last_market_close - timedelta(days=1)
    
    return datetime.combine(last_market_close, datetime.min.time())


def read_nifty500_file() -> Dict[str, Tuple[str, str]]:
    """Read nifty500.txt and return a dict of symbol -> (start_date, end_date)."""
    symbols = {}
    
    if not NIFTY500_FILE.exists():
        print(f"ERROR: {NIFTY500_FILE} does not exist.")
        return symbols
    
    with open(NIFTY500_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split('\t')
            if len(parts) >= 3:
                symbol = parts[0]
                start_date = parts[1]
                end_date = parts[2]
                symbols[symbol] = (start_date, end_date)
    
    return symbols


def get_last_date_in_csv(symbol: str) -> Optional[datetime]:
    """Get the last date for a symbol in the CSV file."""
    if not CSV_FILE.exists():
        return None
    
    try:
        # Read only the symbol and date columns to be memory efficient
        df = pd.read_csv(CSV_FILE, usecols=['symbol', 'date'], dtype={'symbol': str, 'date': str})
        symbol_data = df[df['symbol'] == symbol]
        
        if symbol_data.empty:
            return None
        
        dates = pd.to_datetime(symbol_data['date'])
        return dates.max().to_pydatetime()
    except (pd.errors.EmptyDataError, KeyError, ValueError) as e:
        print(f"Warning: Error reading CSV for {symbol}: {e}")
        return None


def fetch_historical_data_chunk(
    groww: GrowwAPI,
    symbol: str,
    start_date: datetime,
    end_date: datetime
) -> Optional[list]:
    """Fetch historical candle data for a single chunk from Groww API with rate limiting.
    
    Uses the newer get_historical_candles method which returns more up-to-date data.
    Response format: [date_str, open(None), high, low, close, volume, adj_close(None)]
    """
    rate_limiter.wait()  # Apply rate limiting
    
    try:
        start_time_str = start_date.strftime("%Y-%m-%d 09:15:00")  # Market open time
        end_time_str = end_date.strftime("%Y-%m-%d 15:30:00")  # Market close time
        groww_symbol = f"NSE-{symbol}"  # New API requires NSE-SYMBOL format
        
        response = groww.get_historical_candles(
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            groww_symbol=groww_symbol,
            start_time=start_time_str,
            end_time=end_time_str,
            candle_interval=groww.CANDLE_INTERVAL_DAY
        )
        
        if response and 'candles' in response:
            return response['candles']
        return None
    except Exception as e:
        print(f"Error fetching data for {symbol} ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}): {e}")
        return None


def fetch_historical_data(
    groww: GrowwAPI,
    symbol: str,
    start_date: datetime,
    end_date: datetime
) -> Optional[list]:
    """
    Fetch historical candle data from Groww API, splitting large date ranges into chunks.
    Uses 180 days (~6 months of trading days) per chunk to avoid API limits.
    """
    # Calculate the date range in days
    days_diff = (end_date.date() - start_date.date()).days
    
    # Maximum days per chunk (180 days ≈ 6 months of trading days, safe for API limits)
    max_days_per_chunk = 180
    
    if days_diff <= max_days_per_chunk:
        # Small range, fetch in one go
        return fetch_historical_data_chunk(groww, symbol, start_date, end_date)
    
    # Large range, split into chunks
    all_candles = []
    current_start = start_date
    chunk_num = 0
    total_chunks = (days_diff // max_days_per_chunk) + (1 if days_diff % max_days_per_chunk else 0)
    
    while current_start <= end_date:
        # Calculate chunk end date
        chunk_end = min(
            current_start + timedelta(days=max_days_per_chunk),
            end_date
        )
        
        chunk_num += 1
        if total_chunks > 1:
            print(f"  Fetching chunk {chunk_num}/{total_chunks} for {symbol} ({current_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')})")
        
        # Fetch chunk
        chunk_candles = fetch_historical_data_chunk(groww, symbol, current_start, chunk_end)
        
        if chunk_candles:
            all_candles.extend(chunk_candles)
        # If a chunk fails, continue with next chunk (already logged in fetch_historical_data_chunk)
        
        # Move to next chunk (start from day after chunk_end)
        current_start = chunk_end + timedelta(days=1)
        
        # Break if we've reached the end
        if current_start > end_date:
            break
        
        # Small delay between chunks to be respectful
        time.sleep(0.1)
    
    return all_candles if all_candles else None


def candles_to_dataframe(symbol: str, candles: list) -> pd.DataFrame:
    """Convert candle data from API response to DataFrame matching CSV format.
    
    New API format: [date_str, open(None), high, low, close, volume, adj_close(None)]
    Example: ['2025-12-05T00:00:00', None, 1545.6, 1520.6, 1540.6, 10183266, None]
    """
    if not candles:
        return pd.DataFrame()
    
    data = []
    for candle in candles:
        if len(candle) >= 6:
            date_str_raw = candle[0]  # ISO format like '2025-12-05T00:00:00'
            # open_price = candle[1]  # Often None in new API
            high_price = candle[2]
            low_price = candle[3]
            close_price = candle[4]
            volume = candle[5]
            
            # Parse ISO date string to get date and timestamp
            if isinstance(date_str_raw, str):
                # Parse ISO format date
                date_obj = datetime.fromisoformat(date_str_raw.replace('Z', '+00:00').split('+')[0])
                date_str = date_obj.strftime("%Y-%m-%d")
                # Generate timestamp (epoch seconds at market close 15:30 IST = 10:00 UTC)
                timestamp = int(date_obj.replace(hour=18, minute=30).timestamp())  # 18:30 UTC = 00:00 IST next day - 5:30
            else:
                # Fallback for epoch timestamp (old API format)
                date_obj = datetime.fromtimestamp(date_str_raw)
                date_str = date_obj.strftime("%Y-%m-%d")
                timestamp = date_str_raw
            
            # Use close as open if open is None (common in new API)
            open_price = candle[1] if candle[1] is not None else close_price
            
            data.append({
                'symbol': symbol,
                'date': date_str,
                'timestamp': timestamp,
                'open': open_price,
                'high': high_price,
                'low': low_price,
                'close': close_price,
                'volume': volume
            })
    
    return pd.DataFrame(data)


def initialize_groww_api() -> GrowwAPI:
    """Initialize Groww API using TOTP authentication."""
    print("Generating TOTP code...")
    
    # Generate TOTP code from secret
    totp_gen = pyotp.TOTP(TOTP_SECRET)
    totp = totp_gen.now()
    
    print("Getting access token from Groww API...")
    # Get access token using TOTP
    access_token = GrowwAPI.get_access_token(api_key=TOTP_TOKEN, totp=totp)
    
    # Initialize GrowwAPI with access token
    groww = GrowwAPI(access_token)
    print("✓ Successfully authenticated with Groww API")
    
    return groww


def process_symbol(
    groww: GrowwAPI,
    symbol: str,
    start_date_str: str,
    end_date_str: str,
    last_market_close: datetime
) -> Tuple[str, Optional[pd.DataFrame], str]:
    """
    Process a single symbol: fetch data and return result.
    Returns: (symbol, dataframe, status_message)
    """
    # Get last date in CSV
    last_date = get_last_date_in_csv(symbol)
    
    if last_date:
        # Start from next day after last date
        fetch_start = last_date + timedelta(days=1)
    else:
        # No data exists, start from the symbol's start date
        try:
            fetch_start = datetime.strptime(start_date_str, "%Y-%m-%d")
        except ValueError:
            return (symbol, None, f"ERROR: Invalid start date format: {start_date_str}")
    
    # Don't fetch if we're already up to date
    if fetch_start > last_market_close:
        last_date_str = last_date.strftime('%Y-%m-%d') if last_date else 'N/A'
        return (symbol, None, f"Already up to date (last date: {last_date_str})")
    
    # Fetch data
    candles = fetch_historical_data(groww, symbol, fetch_start, last_market_close)
    
    if candles is None or len(candles) == 0:
        return (symbol, None, "No new data")
    
    # Convert to DataFrame
    new_df = candles_to_dataframe(symbol, candles)
    
    if new_df.empty:
        return (symbol, None, "No new data")
    
    last_date_in_new = pd.to_datetime(new_df['date']).max()
    new_rows = len(new_df)
    status = f"✓ Added {new_rows} rows (up to {last_date_in_new.strftime('%Y-%m-%d')})"
    
    return (symbol, new_df, status)


def append_to_csv(new_data: pd.DataFrame):
    """Append new data to CSV file, avoiding duplicates. Sorted by date."""
    if new_data.empty:
        return
    
    # Read existing data to check for duplicates
    existing_df = pd.DataFrame()
    if CSV_FILE.exists():
        try:
            existing_df = pd.read_csv(CSV_FILE, dtype={'symbol': str, 'date': str})
        except Exception as e:
            print(f"Warning: Error reading existing CSV: {e}")
    
    if not existing_df.empty:
        # Remove duplicates based on symbol and date
        combined = pd.concat([existing_df, new_data], ignore_index=True)
        combined = combined.drop_duplicates(subset=['symbol', 'date'], keep='last')
        combined = combined.sort_values(['date', 'symbol'])
        combined.to_csv(CSV_FILE, index=False)
    else:
        # First time writing
        new_data = new_data.sort_values(['date', 'symbol'])
        new_data.to_csv(CSV_FILE, index=False)


def pre_populate_from_old_csv(nifty500_symbols: set) -> bool:
    """
    Pre-populate the new CSV file from the old CSV file, filtering for Nifty 500 symbols.
    Returns True if pre-population was done, False otherwise.
    """
    # Check if old CSV exists
    if not OLD_CSV_FILE.exists():
        print(f"Note: Old CSV file ({OLD_CSV_FILE.name}) not found. Starting fresh.")
        return False
    
    # Check if new CSV already exists and has data
    if CSV_FILE.exists():
        try:
            existing_df = pd.read_csv(CSV_FILE, usecols=['symbol'])
            if not existing_df.empty and len(existing_df['symbol'].unique()) > 0:
                print("Note: New CSV file already exists with data. Skipping pre-population.")
                return False
        except Exception:
            # File exists but might be corrupted, proceed with pre-population
            pass
    
    print("Pre-populating new CSV from old CSV file...")
    print(f"Reading from: {OLD_CSV_FILE.name}")
    
    try:
        # Read the old CSV in chunks to handle large file
        chunk_size = 100000
        filtered_chunks = []
        total_rows_read = 0
        total_rows_filtered = 0
        
        # Read in chunks to handle large files efficiently
        for chunk in pd.read_csv(
            OLD_CSV_FILE,
            chunksize=chunk_size,
            dtype={'symbol': str, 'date': str}
        ):
            total_rows_read += len(chunk)
            # Filter for Nifty 500 symbols only
            filtered_chunk = chunk[chunk['symbol'].isin(nifty500_symbols)]
            if not filtered_chunk.empty:
                filtered_chunks.append(filtered_chunk)
                total_rows_filtered += len(filtered_chunk)
        
        if filtered_chunks:
            # Combine all filtered chunks
            combined_df = pd.concat(filtered_chunks, ignore_index=True)
            
            # Sort by date and symbol
            combined_df = combined_df.sort_values(['date', 'symbol'])
            
            # Remove duplicates (if any)
            combined_df = combined_df.drop_duplicates(subset=['symbol', 'date'], keep='last')
            
            # Write to new CSV
            combined_df.to_csv(CSV_FILE, index=False)
            
            print(f"✓ Pre-populated {len(combined_df):,} rows for {combined_df['symbol'].nunique()} symbols")
            print(f"  (Filtered from {total_rows_read:,} total rows in old CSV)")
            return True
        else:
            print("No matching data found in old CSV for Nifty 500 symbols.")
            return False
            
    except Exception as e:
        print(f"Warning: Error pre-populating from old CSV: {e}")
        print("Proceeding without pre-population.")
        return False


def get_all_last_dates_from_csv() -> Dict[str, datetime]:
    """Get the last date for all symbols in the CSV file in a single read.
    
    This is MUCH faster than calling get_last_date_in_csv() for each symbol,
    which would read the 70MB CSV file 500 times.
    """
    if not CSV_FILE.exists():
        return {}
    
    try:
        print("  Reading CSV to get last dates for all symbols (single pass)...")
        # Read only the symbol and date columns to be memory efficient
        df = pd.read_csv(CSV_FILE, usecols=['symbol', 'date'], dtype={'symbol': str, 'date': str})
        df['date'] = pd.to_datetime(df['date'])
        
        # Group by symbol and get max date for each
        last_dates = df.groupby('symbol')['date'].max().to_dict()
        
        # Convert to datetime objects
        result = {symbol: date.to_pydatetime() for symbol, date in last_dates.items()}
        print(f"  Found last dates for {len(result)} symbols")
        return result
    except (pd.errors.EmptyDataError, KeyError, ValueError) as e:
        print(f"Warning: Error reading CSV for last dates: {e}")
        return {}


def update_nifty500_file(symbols_data: Dict[str, Tuple[str, str]]):
    """Update nifty500.txt file with new end dates."""
    lines = []
    
    # Get all last dates in a single CSV read (instead of 500 separate reads!)
    all_last_dates = get_all_last_dates_from_csv()
    
    for symbol, (start_date, _) in sorted(symbols_data.items()):
        last_date = all_last_dates.get(symbol)
        if last_date:
            end_date = last_date.strftime("%Y-%m-%d")
        else:
            end_date = start_date  # Use start date if no data found
        
        lines.append(f"{symbol}\t{start_date}\t{end_date}\n")
    
    with open(NIFTY500_FILE, 'w') as f:
        f.writelines(lines)
    print(f"✓ Updated {len(lines)} entries in nifty500.txt")


def main():
    """Main function to update market data."""
    print("=" * 80)
    print("Indian Market Data Update Script (Nifty 500)")
    print("=" * 80)
    print()
    
    # Ensure data directory exists
    DATA_DIR.mkdir(exist_ok=True)
    
    # Read nifty500.txt first (needed for pre-population)
    print("Reading nifty500.txt...")
    symbols_data = read_nifty500_file()
    print(f"Found {len(symbols_data)} symbols")
    print()
    
    if not symbols_data:
        print("No symbols found in nifty500.txt. Exiting.")
        return
    
    # Pre-populate new CSV from old CSV if needed (before API initialization)
    nifty500_symbols = set(symbols_data.keys())
    pre_populate_from_old_csv(nifty500_symbols)
    print()
    
    # Initialize Groww API with TOTP authentication
    print("Initializing Groww API with TOTP...")
    groww = initialize_groww_api()
    print()
    
    # Get last market close date
    last_market_close = get_last_market_close_date()
    print(f"Last market close date: {last_market_close.strftime('%Y-%m-%d')}")
    print()
    
    # Check if data is already up to date (single CSV read for all symbols)
    print("Checking if data is up to date...")
    all_last_dates = get_all_last_dates_from_csv()
    symbols_needing_update = []
    for symbol, (start_date_str, end_date_str) in sorted(symbols_data.items()):
        last_date = all_last_dates.get(symbol)
        if last_date is None:
            # No data exists, needs full fetch
            symbols_needing_update.append((symbol, start_date_str, end_date_str))
        elif last_date.date() < last_market_close.date():
            # Data is stale, needs update
            symbols_needing_update.append((symbol, start_date_str, end_date_str))
        # else: symbol is already up to date, skip
    
    if not symbols_needing_update:
        print(f"✓ All {len(symbols_data)} symbols are already up to date (last date: {last_market_close.strftime('%Y-%m-%d')})")
        print()
        print("=" * 80)
        print("No update needed!")
        print("=" * 80)
        return
    
    print(f"Found {len(symbols_needing_update)} symbols needing update (out of {len(symbols_data)} total)")
    print()
    
    # Process only symbols that need updating
    symbols_to_process = symbols_needing_update
    
    # Process symbols in parallel
    print("Processing symbols in parallel (with rate limiting)...")
    print(f"Rate limits: {MAX_REQUESTS_PER_SECOND} req/sec, {MAX_REQUESTS_PER_MINUTE} req/min")
    print("-" * 80)
    
    updated_count = 0
    failed_count = 0
    skipped_count = 0
    total_new_rows = 0
    
    # Collect all new dataframes before writing (thread-safe)
    all_new_dataframes: List[pd.DataFrame] = []
    results_lock = threading.Lock()
    
    # Use ThreadPoolExecutor for parallel processing
    # Limit concurrent threads to respect rate limits
    max_workers = min(10, MAX_REQUESTS_PER_SECOND)  # Don't exceed rate limit
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_symbol = {
            executor.submit(
                process_symbol,
                groww,
                symbol,
                start_date_str,
                end_date_str,
                last_market_close
            ): symbol
            for symbol, start_date_str, end_date_str in symbols_to_process
        }
        
        # Process completed tasks as they finish
        for i, future in enumerate(as_completed(future_to_symbol), 1):
            symbol = future_to_symbol[future]
            try:
                result_symbol, new_df, status = future.result()
                print(f"[{i}/{len(symbols_to_process)}] {result_symbol}: {status}")
                
                if new_df is not None and not new_df.empty:
                    # Collect dataframes to write later (thread-safe)
                    with results_lock:
                        all_new_dataframes.append(new_df)
                    new_rows = len(new_df)
                    total_new_rows += new_rows
                    updated_count += 1
                else:
                    if "ERROR" in status:
                        failed_count += 1
                    else:
                        skipped_count += 1
                        
            except Exception as e:
                print(f"[{i}/{len(symbols_to_process)}] {symbol}: ERROR - {e}")
                failed_count += 1
    
    # Write all collected dataframes to CSV at once (thread-safe)
    if all_new_dataframes:
        print()
        print(f"Writing {len(all_new_dataframes)} symbol updates to CSV...")
        combined_df = pd.concat(all_new_dataframes, ignore_index=True)
        append_to_csv(combined_df)
        print("✓ CSV file updated")
    
    print("-" * 80)
    print()
    print("=" * 80)
    print("Update Summary")
    print("=" * 80)
    print(f"Total symbols processed: {len(symbols_to_process)}")
    print(f"Symbols updated: {updated_count}")
    print(f"Symbols skipped (already up to date): {skipped_count}")
    print(f"Symbols failed: {failed_count}")
    print(f"Total new rows added: {total_new_rows:,}")
    print()
    
    # Update nifty500.txt file
    print("Updating nifty500.txt...")
    update_nifty500_file(symbols_data)
    print()
    
    print("=" * 80)
    print(f"Update complete! Data saved to: {CSV_FILE}")
    print("=" * 80)


if __name__ == "__main__":
    main()

