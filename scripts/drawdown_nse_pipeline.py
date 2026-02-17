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
import warnings
import uuid
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

# LLM Configuration
LLM_MODEL = os.getenv("NSE_FILINGS_LLM_MODEL", "gemini-2.0-flash")
GEMINI_API_KEYS = os.getenv("GEMINI_API_KEY", "")  # Comma-separated API keys

# Historical data configuration - fetch ALL available filings
DEFAULT_LOOKBACK_YEARS = int(os.getenv("NSE_LOOKBACK_YEARS", "2"))  # Default: 10 years of historical data

# Cache for fetched candle data to avoid redundant API calls
candle_cache = {}  # symbol -> {date: candles}
pdf_text_cache = {}  # url -> text

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


# ============================================================================
# API KEY ROTATION
# ============================================================================

class APIKeyRotator:
    """Manage multiple API keys and rotate on rate limits"""
    def __init__(self, api_keys_str: str):
        # Parse comma-separated API keys
        self.api_keys = [key.strip() for key in api_keys_str.split(',') if key.strip()]
        self.current_index = 0
        self.failed_keys = set()
        print(f"[API] Initialized with {len(self.api_keys)} API key(s)")

    def get_current_key(self) -> str:
        """Get the current active API key"""
        if not self.api_keys:
            return ""
        return self.api_keys[self.current_index]

    def rotate(self) -> bool:
        """Rotate to next API key. Returns True if rotation successful, False if all keys exhausted"""
        self.failed_keys.add(self.current_index)

        # Try next available key
        for _ in range(len(self.api_keys)):
            self.current_index = (self.current_index + 1) % len(self.api_keys)
            if self.current_index not in self.failed_keys:
                print(f"[API] Rotated to key #{self.current_index + 1}")
                return True

        print("[API] All API keys exhausted")
        return False

    def reset(self):
        """Reset failed keys tracking"""
        self.failed_keys.clear()
        self.current_index = 0


# Global API key rotator
api_key_rotator = None

def get_api_key_rotator() -> APIKeyRotator:
    """Get or create the global API key rotator"""
    global api_key_rotator
    if api_key_rotator is None:
        api_key_rotator = APIKeyRotator(GEMINI_API_KEYS)
    return api_key_rotator


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


# ============================================================================
# PDF EXTRACTION
# ============================================================================

def download_and_parse_pdf(url: str, filename: str) -> str:
    """Download PDF and extract text"""
    global pdf_text_cache

    # Check cache first
    if url in pdf_text_cache:
        print(f"[CACHE] Using cached PDF text for {filename}")
        return pdf_text_cache[url]

    try:
        # Suppress pdfplumber warnings
        warnings.filterwarnings("ignore", message=".*Cannot set gray.*")

        if not url or not url.strip():
            print(f"[WARN] Empty PDF URL for {filename}")
            return ""

        print(f"[PDF] Downloading: {filename} from {url[:80]}...")

        # Create temporary directory
        os.makedirs("temp_pdfs", exist_ok=True)
        unique_suffix = str(uuid.uuid4())[:8]
        temp_filename = f"{filename}.{unique_suffix}.tmp"
        path = os.path.join("temp_pdfs", temp_filename)

        # Ensure URL is complete
        if not url.startswith('http'):
            url = f"https://www.nseindia.com{url}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        try:
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()

            with open(path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size = os.path.getsize(path)
            print(f"[PDF] Downloaded: {filename} ({file_size} bytes)")
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to download PDF {filename}: {e}")
            return ""

        # Extract text using pdfplumber
        text = ""
        try:
            import pdfplumber

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
        except Exception as e:
            print(f"[ERROR] Failed to extract text from {filename}: {e}")
            text = ""
        finally:
            # Clean up temp file
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

        # Cache the result
        pdf_text_cache[url] = text
        print(f"[PDF] Extracted {len(text)} characters from {filename}")
        return text

    except Exception as e:
        print(f"[ERROR] PDF processing failed for {filename}: {e}")
        return ""


# ============================================================================
# LLM FEATURE EXTRACTION
# ============================================================================

def extract_filing_features(
    text: str,
    pos_impact: str,
    neg_impact: str,
    stocktechdata: str,
) -> Dict:
    """Extract structured features from NSE filing using LLM with API key rotation"""

    if not text or not text.strip():
        print("[WARN] Empty text provided to extract_filing_features")
        return {"error": "Empty text content"}

    print(f"[LLM] Extracting features (text length: {len(text)} chars)...")

    prompt = f"""You are an expert financial NLP engine specialized in analyzing Indian corporate disclosures, particularly NSE filings.
Your role is to transform complex regulatory text into STRICT, MACHINE-READABLE STRUCTURED FEATURES used by a trading ML model.

Your output MUST be precise, consistent, and fully deterministic.

You are given:
- Technical indicators for the past hour: {stocktechdata}
- Common positive market reactions for this filing type: {pos_impact}
- Common negative reactions for this filing type: {neg_impact}
- The raw NSE filing content: {text[:5000]}


ANALYSIS INSTRUCTIONS:

Your task is to extract ONLY SIX FIELDS in the EXACT ORDER below.
Each field must be rigorous, data-driven, and based on the combined interpretation of:
- Filing tone and financial meaning
- Company fundamentals implied in text
- Market expectations vs actual results
- Magnitude and direction of event impact
- Common NSE market behaviour for similar filings
- Whether the information is routine or materially price-moving

Interpretation Rules:
1. "file_type":
   - Must be a **normalized category** describing the filing.
   - Examples: "earnings", "order_win", "credit_rating", "pledge_update",
     "shareholding", "board_meeting", "results", "corporate_action", etc.

2. "headline_sentiment":
   - A float ∈ [-1, 1] capturing *true financial impact*, NOT emotional tone.
   - Consider revenue/profit direction, margin trend, guidance, capex plans,
     order wins/losses, debt impact, cashflow commentary, promoter behaviour,
     operational risks, and sector conditions.
   - -1 = highly negative fundamental surprise
     0  = neutral / routine
     +1 = highly positive & material

3. "direction":
   - One of: "BUY", "HOLD", "SELL"
   - BUY  → strong positive, clear upward short-term pressure
   - SELL → strong negative, clear downward pressure
   - HOLD → neutral, noisy, routine, unclear, or already priced-in event

4. "impact_level":
   - Integer {{0, 1, 2}}
   - 0: Routine or low-materiality filings (default for most board meetings)
   - 1: Noticeable but not major short-term impact
   - 2: High-impact, market-moving event (major earnings surprise, big order win,
        buyback, merger, sharp rating change, major guidance update)

5. "positive_keyword_count":
   - Count words strongly associated with bullish short-term reactions.
   - Examples: "order", "approval", "upgrade", "growth", "expansion", "revenue up",
     "profit rises", "guidance raised", "buyback", "merger benefit", etc.

6. "negative_keyword_count":
   - Count words strongly associated with bearish reactions.
   - Examples: "downgrade", "delay", "default", "loss", "fall", "decline",
     "pledge", "fraud", "investigation", "guidance cut", etc.

Critical Notes:
- If the filing is long but routine → direction="HOLD", impact_level=0.
- "Outcome of Board Meeting" is often low-impact unless MAJOR decisions are present.
- Strong numbers can still produce SELL signals if the filing shows weak outlook,
  deteriorating margins, inventory buildup, cashflow issues, or sector headwinds.
- Be extremely careful to avoid overestimating impact.


OUTPUT:

Return ONLY the following EXACT JSON structure and NOTHING ELSE:

{{
  "file_type": "<string>",
  "headline_sentiment": <float>,
  "direction": "<BUY|HOLD|SELL>",
  "impact_level": <0|1|2>,
  "positive_keyword_count": <int>,
  "negative_keyword_count": <int>
}}
"""

    rotator = get_api_key_rotator()
    max_retries = len(rotator.api_keys) if rotator.api_keys else 1

    for attempt in range(max_retries):
        api_key = rotator.get_current_key()

        if not api_key:
            print("[ERROR] No API key available")
            return {"error": "No API key available"}

        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            # Set API key for this attempt
            original_google_key = os.environ.get("GOOGLE_API_KEY", None)
            os.environ["GOOGLE_API_KEY"] = api_key

            try:
                llm = ChatGoogleGenerativeAI(
                    model=LLM_MODEL,
                    temperature=0.0,
                    timeout=30,
                )
                response = llm.invoke(prompt)
                result = response.content.strip()

                # Clean the response - remove markdown code blocks if present
                if result.startswith("```json"):
                    result = result.replace("```json", "").replace("```", "").strip()
                elif result.startswith("```"):
                    result = result.replace("```", "").strip()

                # Try to extract JSON from the response
                # Sometimes LLM adds explanatory text before/after JSON
                import re
                json_match = re.search(r'\{[^{}]*"file_type"[^{}]*\}', result, re.DOTALL)
                if json_match:
                    result = json_match.group(0)

                # Validate JSON response
                try:
                    parsed = json.loads(result)
                    # Ensure all required fields are present
                    required_fields = ["file_type", "headline_sentiment", "direction",
                                     "impact_level", "positive_keyword_count", "negative_keyword_count"]

                    if all(field in parsed for field in required_fields):
                        # Validate data types and ranges
                        try:
                            # Ensure headline_sentiment is float in [-1, 1]
                            parsed["headline_sentiment"] = float(parsed["headline_sentiment"])
                            parsed["headline_sentiment"] = max(-1.0, min(1.0, parsed["headline_sentiment"]))

                            # Ensure impact_level is int in [0, 1, 2]
                            parsed["impact_level"] = int(parsed["impact_level"])
                            parsed["impact_level"] = max(0, min(2, parsed["impact_level"]))

                            # Ensure direction is valid
                            if parsed["direction"] not in ["BUY", "HOLD", "SELL"]:
                                parsed["direction"] = "HOLD"

                            # Ensure keyword counts are non-negative integers
                            parsed["positive_keyword_count"] = max(0, int(parsed["positive_keyword_count"]))
                            parsed["negative_keyword_count"] = max(0, int(parsed["negative_keyword_count"]))

                            print(f"[LLM] ✅ Features extracted successfully (attempt {attempt + 1})")
                            return parsed
                        except (ValueError, TypeError) as e:
                            print(f"[WARN] Invalid data types in LLM response: {e}")
                            return {"error": f"Invalid data types: {str(e)}", "raw": result[:500]}
                    else:
                        missing = [f for f in required_fields if f not in parsed]
                        print(f"[WARN] LLM response missing fields: {missing}")
                        return {"error": f"Missing fields: {missing}", "raw": result[:500]}

                except json.JSONDecodeError as e:
                    print(f"[WARN] LLM response not valid JSON: {str(e)}")
                    print(f"[DEBUG] Response content: {result[:300]}")

                    # Try manual parsing as fallback
                    try:
                        manual_parsed = {}

                        # Try to extract values using regex
                        file_type_match = re.search(r'"file_type":\s*"([^"]+)"', result)
                        if file_type_match:
                            manual_parsed["file_type"] = file_type_match.group(1)

                        sentiment_match = re.search(r'"headline_sentiment":\s*([-+]?\d*\.?\d+)', result)
                        if sentiment_match:
                            manual_parsed["headline_sentiment"] = float(sentiment_match.group(1))

                        direction_match = re.search(r'"direction":\s*"(BUY|HOLD|SELL)"', result)
                        if direction_match:
                            manual_parsed["direction"] = direction_match.group(1)

                        impact_match = re.search(r'"impact_level":\s*(\d+)', result)
                        if impact_match:
                            manual_parsed["impact_level"] = int(impact_match.group(1))

                        pos_kw_match = re.search(r'"positive_keyword_count":\s*(\d+)', result)
                        if pos_kw_match:
                            manual_parsed["positive_keyword_count"] = int(pos_kw_match.group(1))

                        neg_kw_match = re.search(r'"negative_keyword_count":\s*(\d+)', result)
                        if neg_kw_match:
                            manual_parsed["negative_keyword_count"] = int(neg_kw_match.group(1))

                        # Check if we got all required fields
                        required_fields = ["file_type", "headline_sentiment", "direction",
                                         "impact_level", "positive_keyword_count", "negative_keyword_count"]
                        if all(field in manual_parsed for field in required_fields):
                            print(f"[LLM] ✅ Fallback parsing successful")
                            return manual_parsed
                        else:
                            print(f"[WARN] Fallback parsing incomplete")
                            return {"error": f"Invalid JSON: {str(e)}", "raw": result[:500]}
                    except Exception as parse_error:
                        print(f"[ERROR] Fallback parsing failed: {parse_error}")
                        return {"error": f"Invalid JSON: {str(e)}", "raw": result[:500]}

            finally:
                # Restore original API key
                if original_google_key is not None:
                    os.environ["GOOGLE_API_KEY"] = original_google_key
                else:
                    os.environ.pop("GOOGLE_API_KEY", None)

        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] Feature extraction failed (attempt {attempt + 1}): {error_msg[:200]}")

            # Check for rate limit errors
            if "429" in error_msg or "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                print(f"[API] Rate limit hit on key #{rotator.current_index + 1}")
                if attempt < max_retries - 1:
                    if rotator.rotate():
                        print(f"[API] Retrying with next key...")
                        time.sleep(2)  # Brief delay before retry
                        continue
                    else:
                        return {"error": "All API keys rate limited"}
                else:
                    return {"error": "Rate limit exceeded on all keys"}
            else:
                # Non-rate-limit error
                return {"error": f"LLM error: {error_msg[:200]}"}

    return {"error": "Max retries exceeded"}


def get_static_impact_text(filing_type: str) -> Tuple[str, str]:
    """Get positive and negative impact text for filing type from staticdata.csv"""
    try:
        # Try to load staticdata.csv from docs folder
        csv_path = os.path.join(os.path.dirname(__file__), "../apps/portfolio-server/docs/staticdata.csv")

        if not os.path.exists(csv_path):
            print(f"[WARN] staticdata.csv not found at {csv_path}")
            return ("not much specific", "not much specific")

        df = pd.read_csv(csv_path)
        match = df[df["file type"].str.lower() == filing_type.lower()]

        if not match.empty:
            pos_impact = str(match.iloc[0]["positive impct "]) if "positive impct " in match.columns else "not much specific"
            neg_impact = str(match.iloc[0]["negtive impct"]) if "negtive impct" in match.columns else "not much specific"
            return (pos_impact, neg_impact)
        else:
            return ("not much specific", "not much specific")
    except Exception as e:
        print(f"[ERROR] Failed to read staticdata.csv: {e}")
        return ("not much specific", "not much specific")


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

    print(f"[ANALYZE] Processing {len(announcements)} announcement(s) for signal generation...")
    processed_count = 0
    skipped_count = 0
    llm_success_count = 0
    llm_failure_count = 0

    for idx, announcement in enumerate(announcements, 1):
        symbol = announcement.get("symbol", "").strip().upper()
        if not symbol:
            continue

        try:
            # Parse announcement time
            an_dt = announcement.get("an_dt", "")
            if not an_dt:
                print(f"[SKIP] {symbol}: No announcement time")
                skipped_count += 1
                continue

            announcement_time = datetime.strptime(an_dt, "%d-%b-%Y %H:%M:%S")
            print(f"[INFO] {symbol}: Announcement at {an_dt}")

            # Extract PDF text if attachment exists
            pdf_text = ""
            pdf_url = announcement.get("attchmntFile", "")
            if pdf_url and pdf_url.strip():
                pdf_filename = pdf_url.split("/")[-1] if "/" in pdf_url else f"{symbol}_filing.pdf"
                print(f"[PDF] {symbol}: Extracting from {pdf_filename}...")
                pdf_text = download_and_parse_pdf(pdf_url, pdf_filename)
                if pdf_text:
                    print(f"[PDF] {symbol}: ✅ Extracted {len(pdf_text)} characters")
                else:
                    print(f"[PDF] {symbol}: ⚠️ No text extracted")
            else:
                print(f"[PDF] {symbol}: ⚠️ No PDF attachment found")

            # Get candles for this symbol
            candles = candles_data.get(symbol, [])
            if not candles:
                print(f"[SKIP] {symbol}: No candle data available")
                skipped_count += 1
                continue

            print(f"[CANDLES] {symbol}: Found {len(candles)} candles")

            # Find announcement price (closest candle before announcement)
            announcement_price = 0.0
            candles_after = []

            for candle in candles:
                # Assuming candle format: [timestamp_ms, open, high, low, close, volume]
                candle_time = datetime.fromtimestamp(candle[0] / 1000)  # Convert from milliseconds

                if candle_time <= announcement_time:
                    # Use close price as announcement price (most recent before announcement)
                    announcement_price = float(candle[4])
                else:
                    # All candles after announcement time
                    candles_after.append(candle)

            if not candles_after:
                print(f"[SKIP] {symbol}: No candles after announcement at {announcement_time}")
                skipped_count += 1
                continue

            print(f"[CANDLES] {symbol}: {len(candles_after)} candles after announcement")

            if announcement_price == 0.0:
                # If no candle before announcement, use first candle's open price
                announcement_price = float(candles[0][1]) if candles else 0.0
                if announcement_price == 0.0:
                    print(f"[SKIP] {symbol}: No valid announcement price at {announcement_time}")
                    skipped_count += 1
                    continue

            # Calculate max and min prices after announcement (using high/low for accuracy)
            max_price_after = max([float(candle[2]) for candle in candles_after])  # High prices
            min_price_after = min([float(candle[3]) for candle in candles_after])  # Low prices

            # Initialize result dictionary with basic info
            result = {
                "symbol": symbol,
                "filing_type": announcement.get("filing_type", "Unknown"),
                "price_at_filing": announcement_price,
                "max_price_after": max_price_after,
                "min_price_after": min_price_after,
                "max_gain_pct": ((max_price_after - announcement_price) / announcement_price * 100),
                "max_loss_pct": ((min_price_after - announcement_price) / announcement_price * 100),
                "announcement_time": an_dt,
                "announcement_desc": announcement.get("desc", ""),
                "pdf_extracted": len(pdf_text) > 0,
                "pdf_text_length": len(pdf_text)
            }

            # Extract LLM features if PDF text is available
            if pdf_text and len(pdf_text) > 100:  # Only process if meaningful text
                print(f"[LLM] {symbol}: Starting feature extraction...")
                filing_type = announcement.get("filing_type", "Unknown")
                pos_impact, neg_impact = get_static_impact_text(filing_type)

                # Build stocktechdata string from candles
                stocktechdata = f"Price at filing: ₹{announcement_price:.2f}, Max after: ₹{max_price_after:.2f}, Min after: ₹{min_price_after:.2f}"

                # Extract features using LLM
                features = extract_filing_features(pdf_text, pos_impact, neg_impact, stocktechdata)

                if "error" not in features:
                    # Add LLM-extracted features to result
                    result.update({
                        "llm_file_type": features.get("file_type", ""),
                        "headline_sentiment": features.get("headline_sentiment", 0.0),
                        "direction": features.get("direction", "HOLD"),
                        "impact_level": features.get("impact_level", 0),
                        "positive_keyword_count": features.get("positive_keyword_count", 0),
                        "negative_keyword_count": features.get("negative_keyword_count", 0)
                    })
                    llm_success_count += 1
                    print(f"[LLM] {symbol}: ✅ SUCCESS - sentiment={features.get('headline_sentiment', 0):.2f}, direction={features.get('direction', 'HOLD')}, impact={features.get('impact_level', 0)}")
                else:
                    # LLM extraction failed, add default values
                    result.update({
                        "llm_file_type": "",
                        "headline_sentiment": 0.0,
                        "direction": "HOLD",
                        "impact_level": 0,
                        "positive_keyword_count": 0,
                        "negative_keyword_count": 0,
                        "llm_error": features.get("error", "Unknown error")
                    })
                    llm_failure_count += 1
                    print(f"[LLM] {symbol}: ❌ FAILED - {features.get('error', 'Unknown')}")
            else:
                # No PDF text, add default values
                print(f"[LLM] {symbol}: ⚠️ SKIPPED - No meaningful PDF text (length: {len(pdf_text)})")
                result.update({
                    "llm_file_type": "",
                    "headline_sentiment": 0.0,
                    "direction": "HOLD",
                    "impact_level": 0,
                    "positive_keyword_count": 0,
                    "negative_keyword_count": 0
                })
                llm_failure_count += 1

            results.append(result)
            processed_count += 1
            print(f"[RESULT] {symbol}: ✅ COMPLETE - Filing @ ₹{announcement_price:.2f}, Max ₹{max_price_after:.2f} (+{result['max_gain_pct']:.2f}%), Min ₹{min_price_after:.2f} ({result['max_loss_pct']:.2f}%)")

        except Exception as e:
            print(f"[ERROR] {symbol}: Failed to analyze - {e}")
            skipped_count += 1
            continue

    # Print comprehensive summary
    print(f"\n{'='*60}")
    print(f"SIGNAL GENERATION SUMMARY")
    print(f"{'='*60}")
    print(f"Total announcements: {len(announcements)}")
    print(f"Successfully processed: {processed_count} ({processed_count/len(announcements)*100:.1f}%)")
    print(f"Skipped: {skipped_count} ({skipped_count/len(announcements)*100:.1f}%)")
    print(f"")
    print(f"LLM Feature Extraction:")
    print(f"  ✅ Success: {llm_success_count}")
    print(f"  ❌ Failed/Skipped: {llm_failure_count}")
    if llm_success_count + llm_failure_count > 0:
        print(f"  Success rate: {llm_success_count/(llm_success_count+llm_failure_count)*100:.1f}%")
    print(f"{'='*60}\n")

    return results


def get_last_filing_date() -> str:
    """Get the last filing date from existing CSV or default to configurable period"""
    csv_path = "nse_announcements_price_analysis.csv"

    # Check if user wants to override and start from scratch
    force_refresh = os.getenv("NSE_FORCE_REFRESH", "false").lower() in {"1", "true", "yes"}
    lookback_days = int(os.getenv("NSE_LOOKBACK_DAYS", str(DEFAULT_LOOKBACK_YEARS * 365)))  # Default: 10 years

    if force_refresh:
        default_date = datetime.now() - timedelta(days=lookback_days)
        years = lookback_days / 365
        print(f"[INFO] FORCE_REFRESH enabled. Fetching ALL available filings from last {years:.1f} years ({lookback_days} days)")
        print(f"[INFO] Start date: {default_date.strftime('%d-%m-%Y')}")
        return default_date.strftime("%d-%m-%Y")

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
                    print(f"[INFO] Tip: Set NSE_FORCE_REFRESH=true to fetch all data for last {lookback_days} days")
                    return start_date.strftime("%d-%m-%Y")
        except Exception as e:
            print(f"[WARNING] Failed to read existing CSV: {e}")

    # Default: fetch for the entire lookback period (10 years by default)
    default_date = datetime.now() - timedelta(days=lookback_days)
    years = lookback_days / 365
    print(f"[INFO] No existing data found. Fetching ALL available filings from last {years:.1f} years ({lookback_days} days)")
    print(f"[INFO] Date range: {default_date.strftime('%d-%m-%Y')} to {datetime.now().strftime('%d-%m-%Y')}")
    print(f"[INFO] Tip: Adjust NSE_LOOKBACK_YEARS env variable to change historical depth")
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
    print("Fetching and analyzing NSE filings with enhanced LLM features")
    print("")

    # Load Angel One token map
    token_map = load_angelone_token_map()
    if not token_map:
        print("[ERROR] Failed to load Angel One token map")
        return

    # Login to Angel One
    if not angelone_login():
        print("[ERROR] Failed to login to Angel One")
        return

    # Get date range - from last filing date to today (default: 1 year)
    from_date = get_last_filing_date()
    to_date = datetime.now().strftime("%d-%m-%Y")

    # Calculate number of days
    from_dt = datetime.strptime(from_date, "%d-%m-%Y")
    to_dt = datetime.strptime(to_date, "%d-%m-%Y")
    days_span = (to_dt - from_dt).days

    print(f"\n{'='*60}")
    print(f"Date range: {from_date} to {to_date}")
    print(f"Period: {days_span} days (~{days_span/30:.1f} months)")
    print(f"Data source: Angel One Historical API + NSE Filings")
    print(f"Processing: ONE API call per symbol (full date range)")
    print(f"LLM Features: Sentiment, Direction, Impact Level, Keywords")
    print(f"{'='*60}\n")

    # Get Nifty 500 symbols
    all_symbols = get_nifty_500_symbols()

    # Check for START_FROM_SYMBOL mode - start from a specific symbol
    START_FROM_SYMBOL = os.getenv("NSE_START_FROM", "").upper()
    if START_FROM_SYMBOL:
        try:
            start_idx = all_symbols.index(START_FROM_SYMBOL)
            all_symbols = all_symbols[start_idx:]
            print(f"[START FROM] Starting from symbol: {START_FROM_SYMBOL} (index {start_idx})")
            print(f"[START FROM] Will process {len(all_symbols)} symbols from this point")
        except ValueError:
            print(f"[WARNING] Symbol {START_FROM_SYMBOL} not found in Nifty 500, processing all symbols")

    # Check for RESUME mode - skip already processed symbols
    RESUME_MODE = os.getenv("NSE_RESUME", "false").lower() in {"1", "true", "yes"}
    processed_symbols = set()

    if RESUME_MODE and os.path.exists("nse_announcements_price_analysis.csv"):
        try:
            df_existing = pd.read_csv("nse_announcements_price_analysis.csv")
            processed_symbols = set(df_existing['symbol'].unique())
            original_count = len(all_symbols)
            all_symbols = [s for s in all_symbols if s not in processed_symbols]
            print(f"[RESUME MODE] Already processed: {len(processed_symbols)} symbols")
            print(f"[RESUME MODE] Remaining to process: {len(all_symbols)} symbols")
            if all_symbols:
                print(f"[RESUME MODE] Will start from: {all_symbols[0]}")
        except Exception as e:
            print(f"[WARNING] Could not load existing data for resume: {e}")
            print(f"[INFO] Starting fresh processing")

    # TEST MODE: Set NSE_TEST_MODE=true to process only first 10 symbols
    TEST_MODE = os.getenv("NSE_TEST_MODE", "false").lower() in {"1", "true", "yes"}
    if TEST_MODE:
        all_symbols = all_symbols[:10]
        print(f"[TEST MODE] Processing only first {len(all_symbols)} symbols")

    print(f"Total symbols to process: {len(all_symbols)}")

    if TEST_MODE:
        print(f"[NOTE] To process all 500 symbols, set NSE_TEST_MODE=false or remove the environment variable")

    if RESUME_MODE and processed_symbols:
        print(f"[NOTE] To start fresh (ignore existing data), set NSE_RESUME=false")

    print(f"[INFO] Expected processing time: ~{len(all_symbols) * 2} minutes (approximate)")
    print(f"{'='*60}\n")

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
