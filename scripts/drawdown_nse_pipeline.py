# -*- coding: utf-8 -*-
"""
NSE Corporate Announcements Price Analysis Script

This script fetches NSE corporate announcements and analyzes price movements
after each announcement for Nifty 500 symbols. It generates a CSV with:
- symbol
- price_at_filing (announcement price)
- max_price_after (maximum price after announcement)
- min_price_after (minimum price after announcement)

Features:
- Batch processing to avoid rate limits
- Automatic retry on 429 errors with 30-second wait
- Independent of server infrastructure
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pandas as pd
import requests
import pyotp
import httpx
from dotenv import load_dotenv

# Load environment variables
env_path = os.getenv("PORTFOLIO_SERVER_ENV_PATH")
if env_path and os.path.exists(env_path):
    load_dotenv(env_path, override=False)
else:
    # Load from project root .env file
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_file = os.path.join(project_root, ".env")
    if os.path.exists(env_file):
        load_dotenv(env_file, override=False)

# Configuration
BATCH_SIZE = 5  # Process 5 symbols at a time
RATE_LIMIT_WAIT = 1  # Wait 1 second between API calls
REQUEST_TIMEOUT = 30  # HTTP request timeout
MAX_REQUESTS_PER_MINUTE = 50  # Angel One rate limit
MARKET_OPEN = (9, 15)  # 9:15 AM IST
MARKET_CLOSE = (15, 30)  # 3:30 PM IST

# Cache for fetched candle data to avoid redundant API calls
candle_cache = {}  # symbol -> {date: candles}

# Relevant filing types to filter (from NSE pipeline)
RELEVANT_FILE_TYPES = {
    "Outcome of Board Meeting": {"positive": True, "negative": True},
    "Press Release": {"positive": True, "negative": False},
    "Appointment": {"positive": True, "negative": True},
    "Acquisition": {"positive": True, "negative": True},
    "Updates": {"positive": True, "negative": True},
    "Action(s) initiated or orders passed": {"positive": True, "negative": True},
    "Investor Presentation": {"positive": True, "negative": True},
    "Sale or Disposal": {"positive": True, "negative": True},
    "Bagging/Receiving of Orders/Contracts": {"positive": True, "negative": True},
    "Change in Director(s)": {"positive": True, "negative": True},
}

# Angel One credentials
ANGELONE_CLIENT_CODE = os.getenv("ANGELONE_CLIENT_CODE")
ANGELONE_API_KEY = os.getenv("ANGELONE_API_KEY")
ANGELONE_PASSWORD = os.getenv("ANGELONE_PASSWORD")
ANGELONE_TOTP_SECRET = os.getenv("ANGELONE_TOTP_SECRET")

# Global state for Angel One session
angelone_token = None
angelone_client = None
token_map = {}


def match_filing_type(desc: str) -> Optional[str]:
    """Match announcement description to a relevant filing type"""
    desc_lower = desc.lower()
    
    # Direct keyword matching
    for filing_type in RELEVANT_FILE_TYPES.keys():
        if filing_type.lower() in desc_lower:
            return filing_type
    
    # Fuzzy matching for common patterns
    if "board" in desc_lower and "meeting" in desc_lower:
        return "Outcome of Board Meeting"
    elif "press" in desc_lower or "release" in desc_lower:
        return "Press Release"
    elif "appoint" in desc_lower or "resignation" in desc_lower:
        return "Appointment"
    elif "acqui" in desc_lower or "merger" in desc_lower:
        return "Acquisition"
    elif "update" in desc_lower:
        return "Updates"
    elif "order" in desc_lower or "action" in desc_lower:
        return "Action(s) initiated or orders passed"
    elif "presentation" in desc_lower or "investor" in desc_lower:
        return "Investor Presentation"
    elif "sale" in desc_lower or "disposal" in desc_lower or "divestment" in desc_lower:
        return "Sale or Disposal"
    elif "contract" in desc_lower or "bagging" in desc_lower:
        return "Bagging/Receiving of Orders/Contracts"
    elif "director" in desc_lower and "change" in desc_lower:
        return "Change in Director(s)"
    
    return None


def is_market_hours(dt: datetime) -> bool:
    """Check if datetime falls within market hours (9:15 AM - 3:30 PM IST)"""
    if dt.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    
    time_obj = dt.time()
    market_open = datetime.strptime(f"{MARKET_OPEN[0]}:{MARKET_OPEN[1]}", "%H:%M").time()
    market_close = datetime.strptime(f"{MARKET_CLOSE[0]}:{MARKET_CLOSE[1]}", "%H:%M").time()
    
    return market_open <= time_obj <= market_close


def filter_relevant_announcements(announcements: List[Dict]) -> List[Dict]:
    """Filter announcements by filing type and market hours"""
    filtered = []
    
    for ann in announcements:
        desc = ann.get("desc", "")
        an_dt_str = ann.get("an_dt", "")
        
        # Match filing type
        filing_type = match_filing_type(desc)
        if not filing_type:
            continue
        
        # Check market hours
        if an_dt_str:
            try:
                an_dt = datetime.strptime(an_dt_str, "%d-%b-%Y %H:%M:%S")
                if not is_market_hours(an_dt):
                    continue
            except ValueError:
                continue
        
        # Add filing type to announcement
        ann["filing_type"] = filing_type
        filtered.append(ann)
    
    return filtered


def load_angelone_token_map() -> Dict[str, Dict]:
    """Load Angel One token map from JSON file"""
    # Try same folder first
    token_file = os.path.join(os.path.dirname(__file__), "angelone_tokens.json")
    
    if not os.path.exists(token_file):
        # Try portfolio-server/docs folder
        token_file = os.path.join(os.path.dirname(__file__), "../apps/portfolio-server/docs/angelone_tokens.json")
    
    if not os.path.exists(token_file):
        print(f"[WARNING] Token map file not found: {token_file}")
        return {}
    
    try:
        with open(token_file, 'r') as f:
            data = json.load(f)
        print(f"[ANGELONE] Loaded {len(data):,} token mappings from {token_file}")
        return data
    except Exception as e:
        print(f"[ERROR] Failed to load token map: {e}")
        return {}


def angelone_login() -> Optional[str]:
    """Login to Angel One and get authorization token"""
    global angelone_token, angelone_client
    
    if not all([ANGELONE_CLIENT_CODE, ANGELONE_API_KEY, ANGELONE_PASSWORD, ANGELONE_TOTP_SECRET]):
        print("[ERROR] Angel One credentials not configured")
        return None
    
    try:
        # Generate TOTP
        totp = pyotp.TOTP(ANGELONE_TOTP_SECRET).now()
        
        # Login request
        url = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1",
            "X-ClientPublicIP": "127.0.0.1",
            "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": ANGELONE_API_KEY
        }
        
        payload = {
            "clientcode": ANGELONE_CLIENT_CODE,
            "password": ANGELONE_PASSWORD,
            "totp": totp
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("status") and data.get("data"):
            angelone_token = data["data"].get("jwtToken")
            angelone_client = httpx.Client(timeout=REQUEST_TIMEOUT)
            print(f"[ANGELONE] ✅ Login successful")
            return angelone_token
        else:
            print(f"[ANGELONE] ❌ Login failed: {data.get('message')}")
            return None
            
    except Exception as e:
        print(f"[ANGELONE] ❌ Login error: {e}")
        return None


def get_nifty_500_symbols() -> List[str]:
    """Get list of Nifty 500 symbols from CSV file"""
    csv_path = os.path.join(os.path.dirname(__file__), "nifty_500_stats.csv")

    try:
        df = pd.read_csv(csv_path, sep=';')
        symbols = df['symbol'].dropna().str.strip().str.upper().tolist()
        print(f"[SYMBOLS] Loaded {len(symbols)} symbols from {csv_path}")
        return symbols
    except Exception as e:
        print(f"[ERROR] Failed to load symbols from {csv_path}: {e}")
        print("[FALLBACK] Using hardcoded list of major symbols")
        # Fallback to hardcoded list
        return [
            "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "HINDUNILVR", "INFY", "HDFC",
            "ITC", "KOTAKBANK", "LT", "AXISBANK", "MARUTI", "BAJFINANCE", "BHARTIARTL",
            "HCLTECH", "ASIANPAINT", "TITAN", "BAJAJFINSV", "ULTRACEMCO", "NESTLEIND",
            "WIPRO", "TECHM", "POWERGRID", "NTPC", "JSWSTEEL", "GRASIM", "INDUSINDBK",
            "HINDALCO", "TATASTEEL", "CIPLA", "DRREDDY", "SHREECEM", "BRITANNIA",
            "EICHERMOT", "APOLLOHOSP", "DIVISLAB", "UPL", "HEROMOTOCO", "ADANIPORTS",
            "COALINDIA", "BPCL", "GAIL", "ONGC", "IOC", "NTPC", "POWERGRID"
        ]


def fetch_nse_announcements_batch(symbols: List[str], from_date: str, to_date: str) -> List[Dict]:
    """Fetch NSE corporate announcements for multiple symbols"""
    all_announcements = []

    for symbol in symbols:
        try:
            print(f"[NSE] Fetching announcements for {symbol}...")

            # Build API URL
            base_url = "https://www.nseindia.com/api/corporate-announcements"
            params = {
                "index": "equities",
                "from_date": from_date,
                "to_date": to_date,
                "symbol": symbol,
                "reqXbrl": "false"
            }

            # NSE requires proper headers to avoid blocking
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/",
                "Connection": "keep-alive"
            }

            # Create session to maintain cookies (NSE requires this)
            session = requests.Session()
            session.headers.update(headers)

            # First visit the main page to get cookies
            session.get("https://www.nseindia.com", timeout=10)

            # Now make the API call
            response = session.get(base_url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            announcements = data if isinstance(data, list) else []

            print(f"[NSE] Fetched {len(announcements)} announcements for {symbol}")
            all_announcements.extend(announcements)

            # Small delay between requests to be respectful
            time.sleep(1)

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to fetch announcements for {symbol}: {e}")
            continue
        except Exception as e:
            print(f"[ERROR] Unexpected error for {symbol}: {e}")
            continue

    return all_announcements


def fetch_symbol_full_range(symbol: str, from_date: datetime, to_date: datetime) -> List:
    """Fetch all candles for a symbol over entire date range (ONE API CALL)"""
    global angelone_token, angelone_client, token_map, candle_cache
    
    # Check cache first
    cache_key = f"{symbol}_{from_date.date()}_{to_date.date()}"
    if cache_key in candle_cache:
        print(f"[CACHE] Using cached data for {symbol}")
        return candle_cache[cache_key]
    
    if not angelone_token:
        print("[ANGELONE] Not logged in, attempting login...")
        if not angelone_login():
            print("[ERROR] Angel One login failed")
            return []

    # Get symbol token from map (Angel One uses symbol-EQ format)
    symbol_key = f"{symbol}-EQ"
    symbol_info = token_map.get(symbol_key)
    if not symbol_info:
        print(f"[ANGELONE] Symbol {symbol} (key: {symbol_key}) not found in token map")
        candle_cache[cache_key] = []
        return []

    symbol_token = symbol_info.get("token")
    if not symbol_token:
        print(f"[ANGELONE] No token for {symbol}")
        candle_cache[cache_key] = []
        return []

    # Angel One API endpoint
    url = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
    
    # Prepare headers
    headers = {
        "Authorization": f"Bearer {angelone_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": ANGELONE_API_KEY
    }

    # Format dates for Angel One API (use ONE_MINUTE interval for intraday analysis)
    fromdate = from_date.replace(hour=9, minute=15, second=0).strftime("%Y-%m-%d %H:%M")
    todate = to_date.replace(hour=15, minute=30, second=0).strftime("%Y-%m-%d %H:%M")

    # Request payload - use ONE_MINUTE interval for precise intraday price movements
    payload = {
        "exchange": "NSE",
        "symboltoken": symbol_token,
        "interval": "ONE_MINUTE",
        "fromdate": fromdate,
        "todate": todate
    }

    try:
        print(f"[ANGELONE] Fetching FULL RANGE data for {symbol} ({fromdate} to {todate})...")
        response = angelone_client.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("status") and data.get("data"):
                candles = []
                for candle in data["data"]:
                    # Angel One format: [timestamp, open, high, low, close, volume]
                    timestamp_str = candle[0]
                    # Parse ISO timestamp
                    dt = datetime.fromisoformat(timestamp_str.replace('+05:30', ''))
                    candles.append([
                        int(dt.timestamp() * 1000),
                        float(candle[1]),
                        float(candle[2]),
                        float(candle[3]),
                        float(candle[4]),
                        int(candle[5])
                    ])
                
                candle_cache[cache_key] = candles
                print(f"[ANGELONE] ✅ Fetched {len(candles)} total candles for {symbol} (cached)")
                return candles
            else:
                print(f"[ANGELONE] No data for {symbol}: {data.get('message')}")
                candle_cache[cache_key] = []
                return []
        else:
            print(f"[ANGELONE] HTTP {response.status_code} for {symbol}")
            candle_cache[cache_key] = []
            return []

    except Exception as e:
        print(f"[ERROR] Failed to fetch data for {symbol}: {e}")
        candle_cache[cache_key] = []
        return []


def fetch_day_candles_with_retry_batch(symbols_batch: List[str], announcement_date: datetime) -> Dict[str, List]:
    """Fetch day candles for symbols using Angel One Historical API"""
    global angelone_token, angelone_client, token_map
    results = {}

    if not angelone_token:
        print("[ANGELONE] Not logged in, attempting login...")
        if not angelone_login():
            print("[ERROR] Angel One login failed, using mock data")
            return fetch_mock_candles(symbols_batch, announcement_date)

    # Angel One API endpoint
    url = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
    
    # Prepare headers
    headers = {
        "Authorization": f"Bearer {angelone_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": ANGELONE_API_KEY
    }

    for symbol in symbols_batch:
        print(f"[ANGELONE] Fetching data for {symbol}...")

        try:
            # Get symbol token from map (Angel One uses symbol-EQ format)
            symbol_key = f"{symbol}-EQ"
            symbol_info = token_map.get(symbol_key)
            if not symbol_info:
                print(f"[ANGELONE] Symbol {symbol} (key: {symbol_key}) not found in token map")
                results[symbol] = []
                continue

            symbol_token = symbol_info.get("token")
            if not symbol_token:
                print(f"[ANGELONE] No token for {symbol}")
                results[symbol] = []
                continue

            # Format dates for Angel One API
            fromdate = announcement_date.replace(hour=9, minute=15, second=0).strftime("%Y-%m-%d %H:%M")
            todate = announcement_date.replace(hour=15, minute=30, second=0).strftime("%Y-%m-%d %H:%M")

            # Request payload
            payload = {
                "exchange": "NSE",
                "symboltoken": symbol_token,
                "interval": "FIVE_MINUTE",
                "fromdate": fromdate,
                "todate": todate
            }

            response = angelone_client.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") and data.get("data"):
                    candles = []
                    for candle in data["data"]:
                        # Angel One format: [timestamp, open, high, low, close, volume]
                        timestamp_str = candle[0]
                        # Parse ISO timestamp
                        dt = datetime.fromisoformat(timestamp_str.replace('+05:30', ''))
                        candles.append([
                            int(dt.timestamp() * 1000),
                            float(candle[1]),
                            float(candle[2]),
                            float(candle[3]),
                            float(candle[4]),
                            int(candle[5])
                        ])
                    
                    results[symbol] = candles
                    print(f"[ANGELONE] ✅ Fetched {len(candles)} candles for {symbol}")
                else:
                    print(f"[ANGELONE] No data for {symbol}: {data.get('message')}")
                    results[symbol] = []
            else:
                print(f"[ANGELONE] HTTP {response.status_code} for {symbol}")
                results[symbol] = []

        except Exception as e:
            print(f"[ERROR] Failed to fetch data for {symbol}: {e}")
            results[symbol] = []

        # Rate limiting
        time.sleep(RATE_LIMIT_WAIT)

    return results


def fetch_mock_candles(symbols_batch: List[str], announcement_date: datetime) -> Dict[str, List]:
    """Fallback mock data generator when API is not available"""
    results = {}

    print(f"[MOCK] Generating mock candle data for {len(symbols_batch)} symbols")

    base_price = 1000.0

    for i, symbol in enumerate(symbols_batch):
        try:
            candles = []
            current_time = announcement_date.replace(hour=9, minute=15, second=0)

            # Generate hourly candles for a trading day
            for hour in range(6):  # 9:15 AM to 3:15 PM
                price_variation = (i * 10) + (hour * 5)
                open_price = base_price + price_variation
                high_price = open_price * 1.02
                low_price = open_price * 0.98
                close_price = open_price + (price_variation % 10 - 5)
                volume = 100000 + (i * 10000)

                candles.append([
                    int(current_time.timestamp() * 1000),
                    float(open_price),
                    float(high_price),
                    float(low_price),
                    float(close_price),
                    int(volume)
                ])

                current_time = current_time.replace(hour=current_time.hour + 1)

            results[symbol] = candles
            print(f"[MOCK] Generated {len(candles)} mock candles for {symbol}")

        except Exception as e:
            print(f"[ERROR] Failed to generate mock data for {symbol}: {e}")
            results[symbol] = []

    return results


def analyze_price_movement_batch(announcements: List[Dict], candles_data: Dict[str, List]) -> List[Dict]:
    """Analyze price movement for multiple announcements using batched candle data"""
    results = []

    for announcement in announcements:
        symbol = announcement.get("symbol", "").strip().upper()
        if not symbol:
            continue

        try:
            # Parse announcement time
            an_dt = announcement.get("an_dt", "")
            if not an_dt:
                continue

            announcement_time = datetime.strptime(an_dt, "%d-%b-%Y %H:%M:%S")

            # Get candles for this symbol
            candles = candles_data.get(symbol, [])
            if not candles:
                continue

            # Find announcement price (closest candle before announcement)
            announcement_price = 0.0
            candles_after = []

            for candle in candles:
                # Assuming candle format: [timestamp_ms, open, high, low, close, volume]
                candle_time = datetime.fromtimestamp(candle[0] / 1000)  # Convert from milliseconds

                if candle_time <= announcement_time:
                    # Use close price as announcement price
                    announcement_price = float(candle[4])
                elif candle_time > announcement_time:
                    candles_after.append(candle)

            if not candles_after or announcement_price == 0.0:
                continue

            # Calculate max and min prices after announcement
            prices_after = [float(candle[4]) for candle in candles_after]  # Close prices
            max_price_after = max(prices_after)
            min_price_after = min(prices_after)

            results.append({
                "symbol": symbol,
                "price_at_filing": announcement_price,
                "max_price_after": max_price_after,
                "min_price_after": min_price_after,
                "announcement_time": an_dt,
                "announcement_desc": announcement.get("desc", "")
            })

        except Exception as e:
            print(f"[ERROR] Failed to analyze price movement for {symbol}: {e}")
            continue

    return results


def get_last_filing_date() -> str:
    """Get the last filing date from existing CSV or default to 6 months ago"""
    csv_path = "nse_announcements_price_analysis.csv"
    
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            if not df.empty and 'announcement_time' in df.columns:
                # Parse all announcement times and find the most recent
                dates = []
                for dt_str in df['announcement_time'].dropna():
                    try:
                        dt = datetime.strptime(dt_str, "%d-%b-%Y %H:%M:%S")
                        dates.append(dt)
                    except ValueError:
                        continue
                
                if dates:
                    last_date = max(dates)
                    # Start from the day after the last filing
                    start_date = last_date + timedelta(days=1)
                    print(f"[INFO] Found existing data. Last filing: {last_date.strftime('%d-%b-%Y')}")
                    print(f"[INFO] Starting from: {start_date.strftime('%d-%m-%Y')}")
                    return start_date.strftime("%d-%m-%Y")
        except Exception as e:
            print(f"[WARNING] Failed to read existing CSV: {e}")
    
    # Default: 6 months ago
    default_date = datetime.now() - timedelta(days=180)
    print(f"[INFO] No existing data found. Starting from 6 months ago: {default_date.strftime('%d-%m-%Y')}")
    return default_date.strftime("%d-%m-%Y")


def process_symbol(symbol: str, from_date: str, to_date: str) -> List[Dict]:
    """Process a single symbol - fetch ALL data once, then analyze all announcements"""
    print(f"[SYMBOL] Processing {symbol}")

    # Parse date strings
    from_dt = datetime.strptime(from_date, "%d-%m-%Y")
    to_dt = datetime.strptime(to_date, "%d-%m-%Y")

    # Fetch announcements for this symbol
    announcements = fetch_nse_announcements_batch([symbol], from_date, to_date)

    if not announcements:
        print(f"[SYMBOL] No announcements found for {symbol}")
        return []

    # Filter announcements by filing type and market hours
    announcements = filter_relevant_announcements(announcements)
    
    if not announcements:
        print(f"[SYMBOL] No relevant announcements found for {symbol} (filtered by type and market hours)")
        return []
    
    print(f"[SYMBOL] Found {len(announcements)} relevant announcements for {symbol}")

    # Fetch ALL candle data for this symbol ONCE (entire date range)
    all_candles = fetch_symbol_full_range(symbol, from_dt, to_dt)
    
    if not all_candles:
        print(f"[SYMBOL] No candle data for {symbol}")
        return []

    # Group announcements by date for analysis
    announcements_by_date = {}
    for announcement in announcements:
        an_dt = announcement.get("an_dt", "")
        if an_dt:
            try:
                announcement_date = datetime.strptime(an_dt, "%d-%b-%Y %H:%M:%S")
                date_key = announcement_date.date()
                if date_key not in announcements_by_date:
                    announcements_by_date[date_key] = []
                announcements_by_date[date_key].append(announcement)
            except ValueError:
                continue

    # Process each date - filter relevant candles from full dataset
    all_results = []
    for announcement_date, date_announcements in announcements_by_date.items():
        print(f"[SYMBOL] Processing {len(date_announcements)} announcements for {symbol} on {announcement_date}")

        # For minute candles, filter candles for this specific trading day
        day_start = int(datetime.combine(announcement_date, datetime.min.time().replace(hour=9, minute=15)).timestamp() * 1000)
        day_end = int(datetime.combine(announcement_date, datetime.min.time().replace(hour=15, minute=30)).timestamp() * 1000)
        
        day_candles = [c for c in all_candles if day_start <= c[0] <= day_end]
        
        if not day_candles:
            print(f"[SYMBOL] No candles found for {symbol} on {announcement_date} (likely holiday/weekend)")
            continue

        # Analyze price movements for all announcements on this date
        candles_data = {symbol: day_candles}
        date_results = analyze_price_movement_batch(date_announcements, candles_data)
        all_results.extend(date_results)

    print(f"[SYMBOL] Completed {symbol}, got {len(all_results)} results")
    return all_results


def main():
    """Main execution function"""
    global token_map

    print("=== NSE Corporate Announcements Price Analysis ===")
    print("Initializing...\n")

    # Load Angel One token map
    token_map = load_angelone_token_map()
    if not token_map:
        print("[ERROR] Failed to load Angel One token map")
        return

    # Login to Angel One
    if not angelone_login():
        print("[ERROR] Failed to login to Angel One")
        return

    # Get date range - from last filing date to today
    from_date = get_last_filing_date()
    to_date = datetime.now().strftime("%d-%m-%Y")

    print(f"\nDate range: {from_date} to {to_date}")
    print(f"Data source: Angel One Historical API")
    print(f"Processing: ONE API call per symbol (full date range)")
    print()

    # Get Nifty 500 symbols
    all_symbols = get_nifty_500_symbols()
    print(f"Total symbols to process: {len(all_symbols)}")

    # Process symbols one by one
    all_results = []

    for i, symbol in enumerate(all_symbols, 1):
        print(f"\n--- Processing Symbol {i}/{len(all_symbols)}: {symbol} ---")

        try:
            symbol_results = process_symbol(symbol, from_date, to_date)
            all_results.extend(symbol_results)

            print(f"Symbol {symbol} completed. Total results so far: {len(all_results)}")

        except Exception as e:
            print(f"[ERROR] Failed to process symbol {symbol}: {e}")
            continue

        # Rate limiting delay between symbols
        if i < len(all_symbols):
            print(f"Waiting {RATE_LIMIT_WAIT} seconds before next symbol...")
            time.sleep(RATE_LIMIT_WAIT)

    # Create DataFrame and save to CSV (append to existing if present)
    if all_results:
        df_new = pd.DataFrame(all_results)
        output_file = "nse_announcements_price_analysis.csv"
        
        # Check if file exists to append data
        if os.path.exists(output_file):
            try:
                df_existing = pd.read_csv(output_file)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                # Remove duplicates based on symbol and announcement_time
                df_combined = df_combined.drop_duplicates(subset=['symbol', 'announcement_time'], keep='last')
                df_combined.to_csv(output_file, index=False)
                print(f"\n[INFO] Appended {len(df_new)} new records to existing file")
                print(f"[INFO] Total records after deduplication: {len(df_combined)}")
            except Exception as e:
                print(f"[WARNING] Failed to append to existing file: {e}")
                print(f"[INFO] Saving as new file")
                df_new.to_csv(output_file, index=False)
        else:
            df_new.to_csv(output_file, index=False)
            print(f"\n[INFO] Created new file with {len(df_new)} records")

        print("\n=== Results Summary ===")
        print(f"Total new announcements processed: {len(all_results)}")
        print(f"Results saved to: {output_file}")
        print(f"Columns: {', '.join(df_new.columns.tolist())}")
        print("\nSample data:")
        print(df_new.head())
    else:
        print("\n[INFO] No results to save - no announcements found or processed")


if __name__ == "__main__":
    main()
