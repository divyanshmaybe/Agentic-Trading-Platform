# -*- coding: utf-8 -*-
"""
NSE Filings Sentiment Agent - Pathway Real-time Implementation

This script processes NSE corporate filings in real-time, extracts text from PDFs,
fetches stock technical data, and generates trading signals using LLM analysis.
"""

import asyncio
import logging
import os
import re
import sys
import threading
from concurrent.futures import TimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pathway as pw
import requests
from dotenv import load_dotenv
from pydantic import BaseModel

# Suppress verbose Pathway sink logging - MUST be set before Pathway imports
os.environ["PATHWAY_LOG_LEVEL"] = "ERROR"
os.environ["PATHWAY_MONITORING_LEVEL"] = "NONE"
os.environ["PATHWAY_PERSISTENT_STORAGE"] = ""

# Suppress ALL Pathway-related loggers
import logging
for logger_name in [
    "pathway",
    "pathway.io",
    "pathway.io.kafka",
    "pathway.io.jsonlines",
    "pathway.xpacks",
    "pathway.stdlib",
]:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)
    logging.getLogger(logger_name).propagate = False

# Ensure shared utilities (Kafka service, etc.) are importable when the pipeline
# runs in isolation (e.g. Celery worker context or manual execution).
PROJECT_ROOT = Path(__file__).resolve().parents[4]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

from kafka_service import (  # type: ignore  # noqa: E402
    KafkaPublisher,
    PublisherAlreadyRegistered,
    default_kafka_bus,
)
from celery_app import celery_app  # type: ignore  # noqa: E402
import httpx

# LLM imports
from pathway.xpacks.llm import llms

# Load environment variables ONLY from portfolio-server .env file
# The pipeline service loads it before importing, but we ensure it's loaded here too
# Skip .env loading if SKIP_DOTENV is set (e.g., in Docker where env vars are set via compose)
skip_dotenv = os.getenv("SKIP_DOTENV", "false").lower() in ("true", "1", "yes")
if not skip_dotenv:
    env_path = os.getenv("PORTFOLIO_SERVER_ENV_PATH")
    if env_path and os.path.exists(env_path):
        load_dotenv(env_path, override=False)  # override=False to respect already loaded vars
    else:
        # Calculate portfolio-server directory path and load .env from there
        current_dir = os.path.dirname(os.path.abspath(__file__))
        server_dir = os.path.dirname(os.path.dirname(current_dir))
        env_file = os.path.join(server_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=False)
        else:
            raise FileNotFoundError(f".env file not found in portfolio-server directory: {env_file}")

# Configuration
MAX_TOKENS = 1024
TARGET = 0.03  # +3% profit target
STOPLOSS = 0.01  # -1% stoploss
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
MARKET_CLOSE_BUFFER_MINUTES = int(os.getenv("NSE_FILINGS_MARKET_CLOSE_BUFFER_MINUTES", "15"))
AUTO_SELL_WINDOW_MINUTES = int(os.getenv("NSE_FILINGS_AUTO_SELL_WINDOW_MINUTES", "15"))
LLM_MODEL = os.getenv("NSE_FILINGS_LLM_MODEL", "gemini-2.5-flash")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in {"1", "true", "yes"}  # Default: true for 24/7 signal generation
print(f"[DEBUG] DEMO_MODE environment variable: '{os.getenv('DEMO_MODE', 'NOT_SET')}'")
print(f"[DEBUG] DEMO_MODE parsed value: {DEMO_MODE}")

# Relevant filing types to filter and process
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


# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Validate API key
if not GEMINI_API_KEY:
    print("[WARN] GEMINI_API_KEY not found in environment variables!")
    print("[WARN] Please set it in .env file or export GEMINI_API_KEY=your_key")
else:
    print(f"[INFO] GEMINI_API_KEY loaded (length: {len(GEMINI_API_KEY)})")


# ============================================================================
# SCHEMAS
# ============================================================================

class NSEFilingSchema(pw.Schema):
    """Schema for NSE filing data"""
    symbol: str
    desc: str
    dt: str
    attchmntFile: str
    sm_name: str
    sm_isin: str
    an_dt: str
    sort_date: str
    seq_id: str
    attchmntText: str
    fileSize: str
    # New fields from XBRL data
    subject_of_announcement: str  # SubjectOfAnnouncement from XBRL
    attachment_url: str  # AttachmentURL from XBRL (may differ from attchmntFile)
    date_time_of_submission: str  # DateAndTimeOfSubmission from XBRL


class FilingWithTextSchema(pw.Schema):
    """Schema for filings with extracted text"""
    symbol: str
    desc: str
    sort_date: str
    attchmntFile: str
    text: str
    filepath: str


class TechnicalDataSchema(pw.Schema):
    """Schema for stock technical data"""
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class TradingSignalSchema(pw.Schema):
    """Schema for trading signals"""
    symbol: str
    filing_time: str
    signal: int  # 1=BUY, -1=SELL, 0=HOLD
    explanation: str
    confidence: float


# ============================================================================
# Kafka publishing for generated trading signals
# ============================================================================

KAFKA_SIGNAL_TOPIC = os.getenv("NSE_FILINGS_SIGNAL_TOPIC", "nse_filings_trading_signal")
KAFKA_PUBLISHER_NAME = "nse_filings_signal_publisher"


class NSESignalEvent(BaseModel):
    symbol: str
    filing_time: str
    signal: int
    explanation: str
    confidence: float
    generated_at: str
    source: str = "nse_filings_pipeline"
    # New fields from XBRL data
    subject_of_announcement: str = ""  # SubjectOfAnnouncement from XBRL
    attachment_url: str = ""  # AttachmentURL from XBRL
    date_time_of_submission: str = ""  # DateAndTimeOfSubmission from XBRL


_signal_publisher: Optional[KafkaPublisher] = None
_publish_loop = asyncio.new_event_loop()


def _publish_loop_runner() -> None:
    asyncio.set_event_loop(_publish_loop)
    _publish_loop.run_forever()


_publish_loop_thread = threading.Thread(target=_publish_loop_runner, name="nse-kafka-publisher-loop", daemon=True)
_publish_loop_thread.start()


def _get_signal_publisher() -> KafkaPublisher:
    global _signal_publisher

    if _signal_publisher is not None:
        return _signal_publisher

    bus = default_kafka_bus
    try:
        _signal_publisher = bus.register_publisher(
            KAFKA_PUBLISHER_NAME,
            topic=KAFKA_SIGNAL_TOPIC,
            value_model=NSESignalEvent,
            default_headers={"stream": "nse_filings"},
        )
    except PublisherAlreadyRegistered:
        _signal_publisher = bus.get_publisher(KAFKA_PUBLISHER_NAME)

    return _signal_publisher


def _publish_to_kafka(event: NSESignalEvent) -> None:
    """Internal function to publish event to Kafka"""
    publisher = _get_signal_publisher()
    payload = event.model_dump()
    publisher.publish(payload, key=event.symbol)


print("[KAFKA] Initialising NSE filings signal publisher...")
try:
    _get_signal_publisher()
    print(f"[KAFKA] Connected to Kafka service; topic '{KAFKA_SIGNAL_TOPIC}' ready.")
except Exception as exc:
    print(f"[KAFKA] Failed to initialise Kafka publisher: {exc}")


@pw.udf
def publish_signal_to_kafka(
    symbol: str,
    filing_time: str,
    signal: int,
    explanation: str,
    confidence: float,
    stocktechdata: str,
    llm_timing: str = "",
    subject_of_announcement: str = "",
    attachment_url: str = "",
    date_time_of_submission: str = "",
) -> str:
    """
    Queue trade execution via Celery, then publish signal to Kafka for analytics.
    
    Flow:
    1. Celery task → Execute trade immediately (fast path)
    2. Kafka publish → Analytics/audit trail (async, non-blocking)
    
    This ensures lowest latency: trade executes while Kafka publish happens in background.
    
    Args:
        llm_timing: JSON string with LLM timing metadata (llm_start_time, llm_end_time, llm_delay_ms)
    """

    try:
        signal_value = int(signal)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        signal_value = 0

    safe_confidence = float(confidence or 0.0)
    
    # Parse LLM timing metadata
    llm_timing_data = {}
    if llm_timing:
        try:
            import json
            llm_timing_data = json.loads(llm_timing)
            llm_delay_ms = llm_timing_data.get("llm_delay_ms", 0)
            print(f"[TIMING] ⏱️ LLM delay for {symbol}: {llm_delay_ms}ms")
        except (json.JSONDecodeError, TypeError):
            pass
    
    # Extract reference_price from stocktechdata
    reference_price = None  # Use None instead of 0.0 to indicate missing price
    try:
        # stocktechdata format: "Current price: 3500.50, timestamp: 2024-01-15 10:30:00"
        if stocktechdata and "Current price:" in stocktechdata:
            price_str = stocktechdata.split("Current price:")[1].split(",")[0].strip()
            reference_price = float(price_str)
            print(f"[PRICE] ✅ Extracted reference_price={reference_price} for {symbol}")
        else:
            print(f"[PRICE] ⚠️ Could not extract price from stocktechdata (will be fetched later): {stocktechdata[:100] if stocktechdata else 'None'}")
    except (ValueError, IndexError, AttributeError) as exc:
        print(f"[PRICE] ⚠️ Failed to parse reference_price for {symbol}: {exc} (will be fetched later)")
    
    event = NSESignalEvent(
        symbol=symbol,
        filing_time=filing_time,
        signal=signal_value,
        explanation=explanation or "",
        confidence=safe_confidence,
        generated_at=datetime.utcnow().isoformat() + "Z",
        # Include new XBRL fields
        subject_of_announcement=subject_of_announcement or "",
        attachment_url=attachment_url or "",
        date_time_of_submission=date_time_of_submission or "",
    )
    
    # Prepare payload with reference_price for trade execution
    signal_payload = event.model_dump()
    signal_payload["reference_price"] = reference_price  # Add price to payload
    
    # Add LLM timing metadata to payload for trade execution tracking
    if llm_timing_data:
        signal_payload["llm_delay_ms"] = llm_timing_data.get("llm_delay_ms", 0)
        signal_payload["llm_start_time"] = llm_timing_data.get("llm_start_time", "")
        signal_payload["llm_end_time"] = llm_timing_data.get("llm_end_time", "")

    try:
        # STEP 1: Queue trade execution ONLY for actionable signals (1=BUY, -1=SELL)
        # Skip signal=0 (HOLD) - no point sending to trading queue
        if signal_value in (1, -1):
            celery_app.send_task(
                "pipeline.trade_execution.process_signal",
                args=[signal_payload],  # Send enriched payload with reference_price + llm_timing
                queue="trading",  # Route to TRADING queue (NOT pipelines!)
                priority=9,  # HIGH PRIORITY - execute immediately
            )
            price_str = f"₹{reference_price:.2f}" if reference_price is not None else "N/A (will fetch)"
            llm_delay_str = f"{llm_timing_data.get('llm_delay_ms', 0)}ms" if llm_timing_data else "N/A"
            print(f"[CELERY] ✅ Queued HIGH-PRIORITY trade execution for {symbol} signal={signal_value} (price: {price_str}, llm_delay: {llm_delay_str})")
        else:
            print(f"[CELERY] ⏭️ Skipping signal=0 (HOLD) for {symbol} - no trade needed")
        
        # STEP 2: Publish to Kafka (non-critical, analytics only)
        # This happens async and doesn't block trade execution
        try:
            _publish_to_kafka(event)
            print(f"[KAFKA] ✅ Published signal to Kafka for {symbol}")
        except Exception as kafka_exc:
            # Kafka failure doesn't affect trade execution
            print(f"[KAFKA] ⚠️ Failed to publish to Kafka (trade still executing): {kafka_exc}")
        
        return "published"
        
    except Exception as celery_exc:  # pragma: no cover - defensive logging
        print(f"[CELERY] ❌ Failed to queue trade execution for {symbol}: {celery_exc}")
        # Try Kafka at least for audit trail
        try:
            _publish_to_kafka(event)
        except:
            pass
        return f"error:{celery_exc}"


# ============================================================================
# FILING TYPE MAPPING AND FILTERING
# ============================================================================

@pw.udf
def map_filing_type(desc: str) -> str:
    """Map announcement description to a relevant filing type
    
    Returns the matched filing type from RELEVANT_FILE_TYPES, or empty string if no match.
    """
    if not desc:
        print(f"[DEBUG] map_filing_type: Empty description")
        return ""
    
    desc_lower = desc.lower()
    print(f"[DEBUG] map_filing_type: Processing '{desc[:100]}...'")
    
    # Direct keyword matching - check if filing type appears in description
    for filing_type in RELEVANT_FILE_TYPES.keys():
        if filing_type.lower() in desc_lower:
            print(f"[DEBUG] map_filing_type: Matched filing_type='{filing_type}'")
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
    
    # No match found
    print(f"[DEBUG] map_filing_type: NO MATCH for '{desc[:100]}...'")
    return ""


@pw.udf
def should_use_positive_impact(filing_type: str) -> bool:
    """Check if positive impact should be fetched for this filing type"""
    if not filing_type or filing_type not in RELEVANT_FILE_TYPES:
        return False
    return RELEVANT_FILE_TYPES[filing_type].get("positive", False)


@pw.udf
def should_use_negative_impact(filing_type: str) -> bool:
    """Check if negative impact should be fetched for this filing type"""
    if not filing_type or filing_type not in RELEVANT_FILE_TYPES:
        return False
    return RELEVANT_FILE_TYPES[filing_type].get("negative", False)


# ============================================================================
# PDF DOWNLOAD AND PARSING
# ============================================================================

@pw.udf
def download_and_parse_pdf(url: str, filename: str) -> str:
    """Download PDF and extract text, then clean up the file"""
    try:
        import pdfplumber
        import requests
        import os
        import warnings
        import tempfile
        import uuid
        
        # Suppress pdfplumber warnings about invalid color values
        warnings.filterwarnings("ignore", message=".*Cannot set gray.*")
        
        if not url or not url.strip():
            print(f"[WARN] Empty PDF URL for {filename}, skipping download")
            return ""
        
        print(f"[PIPELINE] Downloading PDF: {filename} from {url[:100]}...")
        
        # Use unique temporary file per worker to avoid race conditions
        os.makedirs("docs", exist_ok=True)
        unique_suffix = str(uuid.uuid4())[:8]
        temp_filename = f"{filename}.{unique_suffix}.tmp"
        path = os.path.join("docs", temp_filename)
        
        # Always download fresh (scraper handles deduplication)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0.0.0 Safari/537.36"
        }
        
        # Ensure URL is complete (some PDFs might be relative URLs)
        if not url.startswith('http'):
            url = f"https://www.nseindia.com{url}"
        
        try:
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            print(f"[PIPELINE] PDF download started: {filename} ({response.headers.get('Content-Length', 'unknown')} bytes)")
            
            with open(path, "wb") as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)
            
            file_size = os.path.getsize(path)
            print(f"[PIPELINE] PDF downloaded: {filename} ({file_size} bytes), extracting text...")
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to download PDF {filename} from {url}: {e}")
            return ""
        except Exception as e:
            print(f"[ERROR] Unexpected error downloading PDF {filename}: {e}")
            return ""
        
        # Extract text using pdfplumber (suppress warnings)
        text = ""
        try:
            # Suppress pdfplumber warnings by redirecting stderr temporarily
            import sys
            import warnings
            from io import StringIO
            
            # Suppress all warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                # Also redirect stderr to suppress pdfplumber's direct prints
                original_stderr = sys.stderr
                try:
                    sys.stderr = StringIO()
                    with pdfplumber.open(path) as pdf:
                        for page in pdf.pages:
                            page_text = page.extract_text()
                            if page_text:
                                text += page_text + "\n"
                finally:
                    # Restore stderr
                    sys.stderr = original_stderr
        finally:
            # Clean up temporary PDF file after extraction
            try:
                if os.path.exists(path):
                    os.remove(path)
                    print(f"[PIPELINE] Temporary PDF cleaned up: {temp_filename}")
            except Exception as cleanup_error:
                print(f"Warning: Could not delete temporary PDF {temp_filename}: {cleanup_error}")
        
        print(f"[PIPELINE] PDF processed: {filename} ({len(text)} chars extracted)")
        return text
    except Exception as e:
        print(f"Error processing PDF {filename}: {e}")
        # Try to clean up on error too (use temp_filename if it was created)
        try:
            # Check if temp_filename variable exists (was created before error)
            if 'temp_filename' in locals():
                path = os.path.join("docs", temp_filename)
                if os.path.exists(path):
                    os.remove(path)
        except:
            pass
        return ""


# ============================================================================
# STOCK DATA FETCHING
# ============================================================================

@pw.udf
def fetch_stock_data(symbol: str, filing_time: str) -> str:
    """Fetch current stock price using market_data service"""
    from zoneinfo import ZoneInfo
    
    try:
        filing_dt = datetime.strptime(filing_time, "%Y-%m-%d %H:%M:%S")
    except Exception:
        filing_dt = datetime.utcnow()

    # Check if we're within market hours using centralized utility
    # Import here to avoid circular dependencies
    try:
        # Add portfolio-server path to sys.path if not already present
        portfolio_server_path = Path(__file__).resolve().parents[2]
        if str(portfolio_server_path) not in sys.path:
            sys.path.insert(0, str(portfolio_server_path))
        
        from utils.market_hours import is_market_hours as check_market_hours, get_market_status
        
        market_open = check_market_hours()
        market_status, market_status_msg = get_market_status()
        
        # Show market status for logging/monitoring
        if not market_open:
            if DEMO_MODE:
                msg = f"🔴 {market_status_msg} for {symbol} 🔵 BUT DEMO_MODE ENABLED - Processing anyway"
                print(f"[MARKET] {msg}")
                logging.info(msg)
            else:
                # Market is closed and not in demo mode - skip processing
                msg = f"🔴 MARKET CLOSED for {symbol} - {market_status_msg}. Filing time: {filing_time}"
                print(f"[MARKET] {msg}")
                logging.warning(msg)
                return f"Market closed - {market_status_msg}"
    except ImportError as e:
        # Fallback to original logic if utils not available
        logging.warning(f"Could not import market_hours utility, using fallback: {e}")
        ist = ZoneInfo("Asia/Kolkata")
        current_time = datetime.now(ist).time()
        market_open_time = datetime.strptime(f"{MARKET_OPEN[0]}:{MARKET_OPEN[1]:02d}", "%H:%M").time()
        market_close_time = datetime.strptime(f"{MARKET_CLOSE[0]}:{MARKET_CLOSE[1]:02d}", "%H:%M").time()
        market_open = market_open_time <= current_time <= market_close_time
        
        if not market_open and not DEMO_MODE:
            msg = f"Market closed (NSE hours: {MARKET_OPEN[0]}:{MARKET_OPEN[1]:02d} - {MARKET_CLOSE[0]}:{MARKET_CLOSE[1]:02d} IST)"
            logging.warning(msg)
            return msg

    try:
        # Get current live price via HTTP API (market_data service)
        portfolio_server_url = os.getenv("PORTFOLIO_SERVER_URL", "http://localhost:8000")
        internal_secret = os.getenv("INTERNAL_SERVICE_SECRET", "agentinvest-secret")
        
        url = f"{portfolio_server_url}/api/market/quotes"
        params = {"symbols": symbol}
        headers = {
            "X-Internal-Service": "true",
            "X-Service-Secret": internal_secret,
        }
        
        # Increased timeout from 5s to 15s to prevent timeouts during signal generation
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data.get("data") and len(data["data"]) > 0:
                    price = data["data"][0].get("price")
                    if price:
                        print(f"[PRICE] ✅ Fetched live price for {symbol}: ₹{price}")
                        return f"Current price: {price}, timestamp: {filing_time}"
            
            # If API call failed, log but DON'T return error - will trigger fallback
            error_msg = f"HTTP {response.status_code}: {response.text[:100]}"
            print(f"[WARN] Market service API call failed for {symbol}: {error_msg}")
            logging.warning(f"Market service API call failed for {symbol}: {error_msg}")
            # Return empty string to trigger fallback in signal processing
            return ""
    except Exception as exc:
        error_msg = str(exc)
        print(f"[WARN] Market service price fetch failed for {symbol}: {exc}")
        logging.warning(f"Market service price fetch failed for {symbol}: {exc}")
        # Return empty string to trigger fallback in signal processing
        return ""


# ============================================================================
# STATIC DATA LOOKUP
# ============================================================================

@pw.udf
def get_pos_impact(file_type: str, use_positive: bool, static_data_path: str = "staticdata.csv") -> str:
    """Get positive impact scenario for filing type
    
    Args:
        file_type: The mapped filing type
        use_positive: Whether to fetch positive impact based on RELEVANT_FILE_TYPES config
        static_data_path: Path to CSV with filing type impact scenarios
    
    Returns:
        Positive impact scenario text, or "not applicable" if shouldn't be used
    """
    if not use_positive:
        return "not applicable for this filing type"
    
    try:
        import pandas as pd
        
        if not os.path.exists(static_data_path):
            return "not much specific"
        
        staticdf = pd.read_csv(static_data_path)
        match = staticdf[staticdf["file type"].str.lower() == file_type.lower()]
        
        if not match.empty:
            return str(match["positive impct "].values[0])
        else:
            return "not much specific"
    except Exception as e:
        print(f"Error reading static data: {e}")
        return "not much specific"


@pw.udf
def get_neg_impact(file_type: str, use_negative: bool, static_data_path: str = "staticdata.csv") -> str:
    """Get negative impact scenario for filing type
    
    Args:
        file_type: The mapped filing type
        use_negative: Whether to fetch negative impact based on RELEVANT_FILE_TYPES config
        static_data_path: Path to CSV with filing type impact scenarios
    
    Returns:
        Negative impact scenario text, or "not applicable" if shouldn't be used
    """
    if not use_negative:
        return "not applicable for this filing type"
    
    try:
        import pandas as pd
        
        if not os.path.exists(static_data_path):
            return "not much specific"
        
        staticdf = pd.read_csv(static_data_path)
        match = staticdf[staticdf["file type"].str.lower() == file_type.lower()]
        
        if not match.empty:
            return str(match["negtive impct"].values[0])
        else:
            return "not much specific"
    except Exception as e:
        print(f"Error reading static data: {e}")
        return "not much specific"


# ============================================================================
# LLM TRADING SIGNAL GENERATION
# ============================================================================

@pw.udf
def generate_trading_signal(
    text: str,
    pos_impact: str,
    neg_impact: str,
    stocktechdata: str,
    api_key: str
) -> str:
    """
    Generate trading signal using LLM
    Returns structured response with signal and explanation.
    
    Includes LLM timing metrics in the response for latency tracking:
    - llm_start_time: ISO timestamp when LLM processing started
    - llm_end_time: ISO timestamp when LLM processing completed  
    - llm_delay_ms: Time in milliseconds for LLM to generate signal
    """
    import time
    
    # Track LLM processing start time
    llm_start_time = datetime.utcnow()
    llm_start_ts = time.time()
    
    # Load API key from environment if not provided or empty
    if not api_key or api_key.strip() == "":
        api_key = os.getenv("GEMINI_API_KEY", "")
    
    # Validate inputs
    if not text or not text.strip():
        print("[WARN] Empty text provided to generate_trading_signal")
        return "Error: Empty text content"
    
    print(f"[PIPELINE] Generating trading signal with LLM (text length: {len(text)} chars)...")
    user_prompt = f"""
You are a financial analysis model capable of making real-time trading decisions based on corporate filings, announcements, and financial news.

Below is a company's filing report, related sentiment references, and technical market context. You must analyse all inputs and decide whether the development is a strong BUY (1), strong SELL (-1), or HOLD (0) signal to be acted upon on the current trading day.

You must also provide a confidence_score between 0 and 1 representing your conviction. Higher confidence implies larger permissible allocation for the trade.

Be cautious and account for the following:
- Verify whether the filing arrived during market hours. If it was outside market hours and the opening move already reflects a 5–6% jump, consider contrarian positioning (short if the price gaps up, or long if it gaps down) only when fundamentals justify it.
- Only issue BUY or SELL when the event is materially impactful for valuation or near-term price trajectory and the move is not already priced in beyond 2–3%.
- Filings such as "Outcome of Board Meeting" often carry noise. Treat them as BUY only when the outcome is genuinely transformational (e.g. surprise earnings beat with guidance upgrade, large buyback, merger). Otherwise, default to HOLD or SELL if the tone is negative.
- Markets trade expectations, not absolute numbers. Strong reported figures can result in declines if guidance softens, margins contract, cash flow weakens, inventory builds up, or management sounds cautious. Consider sector sentiment and expectations drift carefully.

Reference data for this filing type:
- Technical data (past hour / relevant window): {stocktechdata}
- Positive impact playbook: {pos_impact}
- Negative impact playbook: {neg_impact}

Filings data and narrative context:
- NSE filings data: {text}

Instructions:
1. Read every piece of information carefully.
2. Combine the qualitative sentiment from the filing, referenced playbooks, sector backdrop, and the provided technical data snapshot to evaluate near-term price action.
3. If the news creates a highly positive, near-term catalyst with limited prior pricing-in, output 1 (BUY). If it materially deteriorates fundamentals/outlook, output -1 (SELL). Otherwise output 0 (HOLD).
4. When assigning 1/-1 ensure the catalyst is powerful, time-sensitive, and not fully reflected in price. Err on the side of HOLD if doubt remains.
5. Provide a concise two-sentence explanation covering the driver and how it ties to the trading action.
6. Output a confidence_score between 0 and 1 reflecting conviction:
   - 0.0–0.3 : very low confidence / noise
   - 0.4–0.6 : moderate clarity
   - 0.7–0.9 : high conviction
   - 1.0     : extremely rare, only when the outcome is unequivocal.

Strictly adhere to this output format:
trading_signal: <1, 0, or -1>
confidence_score: <float between 0 and 1>
concise_explanation: <brief reasoning for the decision>

RETURN EXACTLY THIS STRUCTURED OUTPUT AND NOTHING ELSE.
"""
    
    try:
        # Validate API key
        if not api_key or api_key.strip() == "":
            error_msg = "GEMINI_API_KEY is empty or not set. Please check your .env file."
            print(f"[ERROR] {error_msg}")
            return f"Error: {error_msg}"
        
        from langchain_google_genai import ChatGoogleGenerativeAI
        import time
        
        # Get LLM model from env var (default: gemini-2.5-flash)
        model_name = os.getenv("NSE_FILINGS_LLM_MODEL", LLM_MODEL)
        
        # langchain_google_genai uses GOOGLE_API_KEY env var, so set it
        original_google_key = os.environ.get("GOOGLE_API_KEY", None)
        os.environ["GOOGLE_API_KEY"] = api_key
        
        try:
            # Create model - it will use GOOGLE_API_KEY from environment
            trading_model = ChatGoogleGenerativeAI(
                model=model_name,
                temperature=0.7,
                api_key=api_key  # Explicitly pass as well (original notebook format)
            )
        finally:
            # Restore original environment variable if it existed
            if original_google_key is not None:
                os.environ["GOOGLE_API_KEY"] = original_google_key
            elif "GOOGLE_API_KEY" in os.environ:
                del os.environ["GOOGLE_API_KEY"]
        
        # Retry logic for rate limits
        max_retries = 2
        retry_delay = 5  # Start with 5 seconds
        
        for attempt in range(max_retries + 1):
            try:
                decision = trading_model.invoke(user_prompt)
                
                # Get response content (match original notebook implementation)
                response_text = decision.content if hasattr(decision, 'content') else str(decision)
                
                # Calculate LLM delay
                llm_end_time = datetime.utcnow()
                llm_delay_ms = int((time.time() - llm_start_ts) * 1000)
                
                # Debug: Print response to see what LLM is returning
                print(f"[PIPELINE] LLM Response: {response_text[:200]}...")
                print(f"[PIPELINE] ⏱️ LLM delay: {llm_delay_ms}ms (started: {llm_start_time.isoformat()}Z)")
                
                # Append timing metadata to response for downstream parsing
                timing_suffix = f"\n__LLM_TIMING__:{llm_start_time.isoformat()}Z|{llm_end_time.isoformat()}Z|{llm_delay_ms}"
                return response_text + timing_suffix
                
            except Exception as invoke_error:
                error_str = str(invoke_error)
                
                # Check if it's a rate limit error
                if "429" in error_str or "quota" in error_str.lower() or "rate limit" in error_str.lower():
                    if attempt < max_retries:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        print(f"[WARN] Rate limit hit, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"[ERROR] Rate limit exceeded after {max_retries} retries")
                        return "Error: Rate limit exceeded. Please reduce scraping frequency or upgrade Gemini API tier."
                else:
                    # Not a rate limit error, re-raise
                    raise invoke_error
        
        return "Error: Max retries exceeded"
        
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] LLM generation failed: {error_msg}")
        
        # Provide helpful error message
        if "credentials" in error_msg.lower() or "api key" in error_msg.lower():
            return f"Error: API key issue - {error_msg}. Please check GEMINI_API_KEY in .env file."
        if "429" in error_msg or "quota" in error_msg.lower():
            return "Error: Rate limit exceeded. Please reduce scraping frequency or upgrade Gemini API tier."
        return f"Error generating signal: {error_msg}"


@pw.udf
def parse_trading_signal_value(response: str) -> int:
    """Parse trading signal value (1, 0, or -1) from LLM response"""
    try:
        # Check if response is an error message
        if not response or "error" in response.lower() or "429" in response or "quota" in response.lower():
            print(f"[WARN] Invalid LLM response (error detected): {response[:200]}")
            return 0
        
        # Try multiple patterns to match various response formats
        patterns = [
            r"trading_signal:\s*(-?\d+)",  # Original format
            r"trading_signal\s*:\s*(-?\d+)",  # With optional spaces
            r"signal:\s*(-?\d+)",  # Alternative format
            r"BUY.*?(\d+)|SELL.*?(-?\d+)|HOLD.*?(\d+)",  # Text format
            r"(-?\d+)\s*[,\n]?\s*(?:BUY|SELL|HOLD)",  # Number before text
        ]
        
        for pattern in patterns:
            signal_match = re.search(pattern, response, re.IGNORECASE)
            if signal_match:
                # Get the first non-None group
                signal_str = next((g for g in signal_match.groups() if g is not None), None)
                if signal_str:
                    signal = int(signal_str)
                    # Validate signal is in valid range
                    if signal not in [-1, 0, 1]:
                        print(f"[WARN] Invalid signal value {signal}, defaulting to HOLD (0)")
                        return 0
                    print(f"[PIPELINE] Parsed signal: {signal} from response")
                    return signal
        
        # If no pattern matches, print debug info
        print(f"[WARN] Could not parse signal from response: {response[:300]}")
        return 0
    except Exception as e:
        print(f"[ERROR] Error parsing signal: {e}, Response: {response[:200]}")
        return 0


@pw.udf
def parse_trading_signal_explanation(response: str) -> str:
    """Parse trading signal explanation from LLM response"""
    try:
        # Try multiple patterns
        patterns = [
            r"concise_explanation:\s*(.+?)(?:\n\n|\n[A-Z]|$)",  # Original format with lookahead
            r"concise_explanation\s*:\s*(.+?)(?:\n\n|\n[A-Z]|$)",  # With spaces
            r"explanation:\s*(.+?)(?:\n\n|\n[A-Z]|$)",  # Alternative format
            r"reasoning:\s*(.+?)(?:\n\n|\n[A-Z]|$)",  # Another alternative
        ]
        
        for pattern in patterns:
            explanation_match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
            if explanation_match:
                explanation = explanation_match.group(1).strip()
                if explanation:
                    print(f"[PIPELINE] Parsed explanation: {explanation[:100]}...")
                    return explanation
        
        # If no pattern matches, try to extract anything after the signal
        # Look for text after "concise_explanation" or after the signal line
        fallback_match = re.search(r"(?:concise_explanation|explanation|reasoning)[:\s]*(.+?)(?:\n\n|$)", response, re.DOTALL | re.IGNORECASE)
        if fallback_match:
            explanation = fallback_match.group(1).strip()
            if explanation and len(explanation) > 10:  # Only if meaningful
                return explanation
        
        print(f"[WARN] Could not parse explanation from response: {response[:300]}")
        return "No explanation provided"
    except Exception as e:
        print(f"[ERROR] Error parsing explanation: {e}")
        return f"Error: {str(e)}"


@pw.udf
def parse_trading_signal_confidence(response: str) -> float:
    """Parse confidence score (0-1) from LLM response."""
    try:
        if not response:
            return 0.0
        if "error" in response.lower() or "rate limit" in response.lower():
            return 0.0

        match = re.search(r"confidence_score:\s*([0-9]*\.?[0-9]+)", response, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                return 0.0
            if value < 0.0:
                return 0.0
            if value > 1.0:
                return 1.0
            return value

        # Fallback: look for JSON style "confidence"
        match_json = re.search(r'"confidence(?:_score)?"\s*:\s*([0-9]*\.?[0-9]+)', response, re.IGNORECASE)
        if match_json:
            try:
                value = float(match_json.group(1))
            except ValueError:
                return 0.0
            return max(0.0, min(1.0, value))

    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"[ERROR] Error parsing confidence score: {exc}")
    return 0.0


@pw.udf
def parse_llm_timing(response: str) -> str:
    """
    Parse LLM timing metadata from response.
    
    Returns JSON string with timing info:
    - llm_start_time: ISO timestamp when LLM processing started
    - llm_end_time: ISO timestamp when LLM processing completed
    - llm_delay_ms: Time in milliseconds for LLM to generate signal
    
    Returns empty string if timing not found.
    """
    try:
        if not response:
            return ""
        
        # Look for timing suffix: __LLM_TIMING__:start_time|end_time|delay_ms
        timing_match = re.search(r"__LLM_TIMING__:([^|]+)\|([^|]+)\|(\d+)", response)
        if timing_match:
            llm_start_time = timing_match.group(1)
            llm_end_time = timing_match.group(2)
            llm_delay_ms = int(timing_match.group(3))
            
            import json
            timing_data = {
                "llm_start_time": llm_start_time,
                "llm_end_time": llm_end_time,
                "llm_delay_ms": llm_delay_ms,
            }
            return json.dumps(timing_data)
        
        return ""
    except Exception as exc:
        print(f"[ERROR] Error parsing LLM timing: {exc}")
        return ""


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def create_nse_filings_pipeline(
    filings_source: pw.Table,
    static_data_path: str = "staticdata.csv",
    output_path: str = "trading_signals.jsonl"
):
    """
    Create the main Pathway pipeline for NSE filings sentiment analysis
    
    Args:
        filings_source: Pathway table with NSE filing data
        static_data_path: Path to CSV with filing type impact scenarios
        output_path: Path to write trading signals
    """
    
    from datetime import datetime, time as dt_time, timezone, timedelta
    # Use IST timezone (UTC+5:30) for market hours check
    ist = timezone(timedelta(hours=5, minutes=30))
    current_time_ist = datetime.now(ist).time()
    current_time = current_time_ist
    market_open_time = dt_time(MARKET_OPEN[0], MARKET_OPEN[1])
    market_close_time = dt_time(MARKET_CLOSE[0], MARKET_CLOSE[1])
    close_buffer_time = dt_time(
        MARKET_CLOSE[0],
        max(0, MARKET_CLOSE[1] - MARKET_CLOSE_BUFFER_MINUTES)
    )
    
    # Check market hours using centralized utility
    try:
        # Import centralized market hours utility
        from utils.market_hours import enforce_market_hours, get_market_status
        
        enforce_market_hours()  # Respects DEMO_MODE automatically
        is_market_open = True
        is_near_close = False
    except ValueError:
        # Market closed - get status for logging
        status, msg = get_market_status()
        is_market_open = False
        is_near_close = False
        market_status = f"🔴 MARKET CLOSED - {msg}"
        print(f"[MARKET] {market_status}")
        logging.warning(market_status)
        
        # Skip signal processing if market closed (unless DEMO_MODE)
        if not DEMO_MODE:
            return filings_source.select(
                symbol=pw.this.symbol,
                filing_time=pw.this.sort_date if hasattr(pw.this, 'sort_date') else "",
                signal=pw.apply(lambda s: 0, pw.this.symbol),
                explanation=pw.apply(lambda s: f"Market closed - {msg}", pw.this.symbol),
                confidence=pw.apply(lambda s: 0.0, pw.this.symbol),
            ).filter(pw.this.symbol == "__NEVER_MATCH__")
    
    # Log market status at pipeline start (only if market is open)
    if DEMO_MODE:
        market_status = f"🟢 MARKET OPEN (NSE: {MARKET_OPEN[0]}:{MARKET_OPEN[1]:02d}-{MARKET_CLOSE[0]}:{MARKET_CLOSE[1]:02d} IST, Current: {current_time.strftime('%H:%M:%S')} IST) 🔵 DEMO MODE ENABLED"
        print(f"[MARKET] {market_status}")
        logging.info(market_status)
    elif is_market_open:
        market_status = f"🟢 MARKET OPEN - NSE trading hours: {MARKET_OPEN[0]}:{MARKET_OPEN[1]:02d} - {MARKET_CLOSE[0]}:{MARKET_CLOSE[1]:02d} IST. Current time: {current_time.strftime('%H:%M:%S')} IST"
        print(f"[MARKET] {market_status}")
        logging.info(market_status)
    else:
        market_status = f"🔴 MARKET CLOSED - NSE hours: {MARKET_OPEN[0]}:{MARKET_OPEN[1]:02d} - {MARKET_CLOSE[0]}:{MARKET_CLOSE[1]:02d} IST. Current time: {current_time.strftime('%H:%M:%S')} IST. Skipping signal processing."
        print(f"[MARKET] {market_status}")
        logging.warning(market_status)
    
    # Skip signal processing only if not in DEMO_MODE and market is closed
    if not DEMO_MODE and not is_market_open:
        # Return empty table with correct schema by filtering on a boolean column
        return filings_source.select(
            symbol=pw.this.symbol,
            filing_time=pw.this.sort_date if hasattr(pw.this, 'sort_date') else "",
            signal=pw.apply(lambda s: 0, pw.this.symbol),
            explanation=pw.apply(lambda s: "Market closed - skipping new trades", pw.this.symbol),
            confidence=pw.apply(lambda s: 0.0, pw.this.symbol),
        ).filter(pw.this.symbol == "__NEVER_MATCH__")
    
    print("[SENTIMENT] Step 1: Processing filings from scraper...")
    
    # Log incoming filings
    def log_filing(symbol, desc, attchmntFile):
        print(f"[DEBUG] Incoming filing: {symbol} - {desc[:80]}... PDF: {bool(attchmntFile)}")
        return symbol
    
    filings_source = filings_source.select(
        *pw.this,
        _debug=pw.apply(log_filing, pw.this.symbol, pw.this.desc, pw.this.attchmntFile)
    )
    
    # Map filing descriptions to filing types and filter relevant ones
    filings_with_types = filings_source.select(
        *pw.this,
        filing_type=map_filing_type(pw.this.desc),
        filename=pw.apply(lambda url: url.split("/")[-1] if url else "", pw.this.attchmntFile),
    )
    
    # Filter to only process relevant filing types
    relevant_filings = filings_with_types.filter(pw.this.filing_type != "")
    
    print("[SENTIMENT] Step 1a: Filtered filings by relevant types...")
    print(f"[SENTIMENT] Relevant filing types: {list(RELEVANT_FILE_TYPES.keys())}")
    
    print("[SENTIMENT] Step 2: Downloading and parsing PDFs...")
    
    filings_with_text = relevant_filings.select(
        symbol=pw.this.symbol,
        desc=pw.this.desc,
        filing_type=pw.this.filing_type,
        sort_date=pw.this.sort_date,
        attchmntFile=pw.this.attchmntFile,
        filename=pw.this.filename,
        text=download_and_parse_pdf(pw.this.attchmntFile, pw.this.filename),
        # Carry through XBRL fields
        subject_of_announcement=pw.this.subject_of_announcement,
        attachment_url=pw.this.attachment_url,
        date_time_of_submission=pw.this.date_time_of_submission,
    ).filter(pw.this.text != "")
    
    print("[SENTIMENT] Step 2 complete: PDFs parsed, proceeding to sentiment analysis...")
    print("[SENTIMENT] Step 3: Fetching impact scenarios and stock data...")
    
    # Determine which impacts to fetch based on filing type configuration
    filings_with_impact_flags = filings_with_text.select(
        *pw.this,
        use_positive=should_use_positive_impact(pw.this.filing_type),
        use_negative=should_use_negative_impact(pw.this.filing_type),
    )
    
    filings_enriched = filings_with_impact_flags.select(
        *pw.this,
        pos_impact=get_pos_impact(pw.this.filing_type, pw.this.use_positive, static_data_path),
        neg_impact=get_neg_impact(pw.this.filing_type, pw.this.use_negative, static_data_path),
        stocktechdata=fetch_stock_data(pw.this.symbol, pw.this.sort_date)
    )
    
    print("[SENTIMENT] Step 4: Generating trading signals with LLM...")
    if not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
        print("[WARN] GEMINI_API_KEY not set - trading signals will fail!")
    
    filings_with_responses = filings_enriched.select(
        *pw.this,
        llm_response=generate_trading_signal(
            pw.this.text,
            pw.this.pos_impact,
            pw.this.neg_impact,
            pw.this.stocktechdata,
            GEMINI_API_KEY
        )
    )
    
    print("[SENTIMENT] Step 5: Parsing trading signals...")
    trading_signals = filings_with_responses.select(
        symbol=pw.this.symbol,
        filing_time=pw.this.sort_date,
        signal=parse_trading_signal_value(pw.this.llm_response),
        explanation=parse_trading_signal_explanation(pw.this.llm_response),
        confidence=parse_trading_signal_confidence(pw.this.llm_response),
        llm_timing=parse_llm_timing(pw.this.llm_response),  # Extract LLM timing metadata
        stocktechdata=pw.this.stocktechdata,  # Pass through for price extraction
        # Carry through XBRL fields
        subject_of_announcement=pw.this.subject_of_announcement,
        attachment_url=pw.this.attachment_url,
        date_time_of_submission=pw.this.date_time_of_submission,
    )
 
    print("[SENTIMENT] Step 6: Publishing signals to Kafka and writing to disk...")
    signals_with_kafka = trading_signals.select(
        symbol=pw.this.symbol,
        filing_time=pw.this.filing_time,
        signal=pw.this.signal,
        explanation=pw.this.explanation,
        confidence=pw.this.confidence,
        kafka_status=publish_signal_to_kafka(
            pw.this.symbol,
            pw.this.filing_time,
            pw.this.signal,
            pw.this.explanation,
            pw.this.confidence,
            pw.this.stocktechdata,  # Pass stocktechdata for price extraction
            pw.this.llm_timing,  # Pass LLM timing metadata
            pw.this.subject_of_announcement,  # XBRL field
            pw.this.attachment_url,  # XBRL field
            pw.this.date_time_of_submission,  # XBRL field
        ),
        # Include XBRL fields in output
        subject_of_announcement=pw.this.subject_of_announcement,
        attachment_url=pw.this.attachment_url,
        date_time_of_submission=pw.this.date_time_of_submission,
    )

    pw.io.jsonlines.write(
        signals_with_kafka.select(
            symbol=pw.this.symbol,
            filing_time=pw.this.filing_time,
            signal=pw.this.signal,
            explanation=pw.this.explanation,
            confidence=pw.this.confidence,
            subject_of_announcement=pw.this.subject_of_announcement,
            attachment_url=pw.this.attachment_url,
            date_time_of_submission=pw.this.date_time_of_submission,
        ),
        output_path,
    )
 
    print("[SENTIMENT] Pipeline ready - waiting for data from scraper...")
    return signals_with_kafka


# ============================================================================
# INPUT CONNECTORS
# ============================================================================

def create_filings_input_from_csv(csv_path: str) -> pw.Table:
    """Create Pathway table from CSV file"""
    return pw.io.csv.read(
        csv_path,
        schema=NSEFilingSchema,
        mode="streaming",
        autocommit_duration_ms=50,  # Minimal latency for trading signals
    )


def create_filings_input_from_kafka(kafka_settings: dict, topic: str) -> pw.Table:
    """Create Pathway table from Kafka topic"""
    return pw.io.kafka.read(
        kafka_settings,
        topic=topic,
        schema=NSEFilingSchema,
        format="json",
        autocommit_duration_ms=50,  # Minimal latency for trading signals
    )


def create_filings_input_from_http(port: int = 8001) -> tuple[pw.Table, pw.io.http.PathwayWebserver]:
    """Create Pathway table from HTTP REST API"""
    class FilingInputSchema(pw.Schema):
        symbol: str
        desc: str
        dt: str
        attchmntFile: str
        sm_name: str
        sm_isin: str
        an_dt: str
        sort_date: str
        seq_id: str
        attchmntText: str
        fileSize: str
    
    webserver = pw.io.http.PathwayWebserver(host="0.0.0.0", port=port)
    
    filings, writer = pw.io.http.rest_connector(
        webserver=webserver,
        schema=FilingInputSchema,
        autocommit_duration_ms=50,  # Minimal latency for trading signals
        delete_completed_queries=False,
    )
    
    return filings, writer


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    
    filings_input, writer = create_filings_input_from_http(port=8001)
    
    trading_signals = create_nse_filings_pipeline(
        filings_source=filings_input,
        static_data_path="staticdata.csv",
        output_path="trading_signals.jsonl"
    )
    pw.run()


if __name__ == "__main__":
    main()

