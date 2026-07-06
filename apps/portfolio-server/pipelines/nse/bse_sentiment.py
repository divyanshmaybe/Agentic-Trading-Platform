# -*- coding: utf-8 -*-
from __future__ import annotations
"""
BSE Filings Sentiment Agent - Pathway Real-time Implementation

This script processes BSE corporate filings in real-time, extracts text from PDFs,
fetches stock technical data, and generates trading signals using LLM analysis.
"""

import asyncio
import logging
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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
PORTFOLIO_SERVER_PATH = Path(__file__).resolve().parents[2]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(PORTFOLIO_SERVER_PATH) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_PATH))
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

from kafka_service import (  # type: ignore  # noqa: E402
    KafkaPublisher,
    PublisherAlreadyRegistered,
    default_kafka_bus,
)
from celery_app import celery_app  # type: ignore  # noqa: E402
import httpx

# Initialize Phoenix tracing for BSE filings sentiment
try:
    from phoenix.otel import register
    
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="nse-filings-sentiment",
            endpoint=collector_endpoint,
            auto_instrument=True,
        )
        print(f"✅ Phoenix tracing initialized for BSE filings sentiment: {collector_endpoint}")
except ImportError:
    pass
except Exception:
    pass

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
TARGET = 0.025  # +2.5% CFDT profit target
STOPLOSS = 0.01  # -1% stoploss
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
MARKET_CLOSE_BUFFER_MINUTES = int(os.getenv("NSE_FILINGS_MARKET_CLOSE_BUFFER_MINUTES", "15"))
AUTO_SELL_WINDOW_MINUTES = int(os.getenv("NSE_FILINGS_AUTO_SELL_WINDOW_MINUTES", "30"))
LLM_MODEL = os.getenv("NSE_FILINGS_LLM_MODEL", "gemini-3.1-flash-lite")
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

# Filing categories that trigger company report database updates
# These are categories that provide fundamental/qualitative information about a company
# Different from RELEVANT_FILE_TYPES which are for trading signals
REPORT_UPDATE_FILING_CATEGORIES = [
    "Annual Reports",
    "Business Responsibility and Sustainability Report",
    "Corporate Governance",
    "Related Party Transactions",
    "Scheme of Arrangements",
    "Insider Trading",
    "Qualified Institutional Payments",
    "Credit Rating",
    "Corporate Actions",
    "Board Meetings",
    "Announcements",
    "Voting Results",
    "Foreign Currency Convertible Bonds",
    "Outcome of Board Meeting",
    "Press Release",
    "Acquisition",
    "Sale or Disposal",
    "Change in Director(s)",
    "Appointment",
    "Updates",
    "Action(s) initiated or orders passed",
    "Investor Presentation",
    "Bagging/Receiving of Orders/Contracts",
]


def _is_relevant_for_report_update(filing_subject: str) -> bool:
    """
    Check if a filing subject/category is relevant for company report updates.
    
    Args:
        filing_subject: The subject or category of the filing
        
    Returns:
        True if the filing should trigger a company report update
    """
    if not filing_subject:
        return False
    
    subject_lower = filing_subject.lower().strip()
    
    # Check against relevant categories
    for category in REPORT_UPDATE_FILING_CATEGORIES:
        category_lower = category.lower()
        # Match if category is in subject or subject contains category keywords
        if category_lower in subject_lower or subject_lower in category_lower:
            return True
    
    return False


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
# Kafka publishing for generated trading signals
# ============================================================================

KAFKA_SIGNAL_TOPIC = os.getenv("NSE_FILINGS_SIGNAL_TOPIC", "nse_filings_trading_signal")
KAFKA_PUBLISHER_NAME = "bse_filings_signal_publisher"


class BSESignalEvent(BaseModel):
    symbol: str
    filing_time: str
    signal: int
    explanation: str
    confidence: float
    generated_at: str
    source: str = "bse_filings_pipeline"
    # New fields from XBRL data
    subject_of_announcement: str = ""  # SubjectOfAnnouncement from XBRL
    attachment_url: str = ""  # AttachmentURL from XBRL
    date_time_of_submission: str = ""  # DateAndTimeOfSubmission from XBRL


_signal_publisher: Optional[KafkaPublisher] = None
_publish_loop = asyncio.new_event_loop()


def _publish_loop_runner() -> None:
    asyncio.set_event_loop(_publish_loop)
    _publish_loop.run_forever()


_publish_loop_thread = threading.Thread(target=_publish_loop_runner, name="bse-kafka-publisher-loop", daemon=True)
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
            value_model=BSESignalEvent,
            default_headers={"stream": "bse_filings"},
        )
    except PublisherAlreadyRegistered:
        _signal_publisher = bus.get_publisher(KAFKA_PUBLISHER_NAME)

    return _signal_publisher


def _publish_to_kafka(event: BSESignalEvent) -> None:
    """Internal function to publish event to Kafka"""
    publisher = _get_signal_publisher()
    payload = event.model_dump()
    publisher.publish(payload, key=event.symbol)


print("[KAFKA] Initialising BSE filings signal publisher...")
try:
    _get_signal_publisher()
    print(f"[KAFKA] Connected to Kafka service; topic '{KAFKA_SIGNAL_TOPIC}' ready.")
except Exception as exc:
    print(f"[KAFKA] Failed to initialise Kafka publisher: {exc}")


def publish_signal_to_kafka(
    symbol: str,
    filing_time: str,
    signal: int,
    explanation: str,
    confidence: float,
    stocktechdata: str,
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

    """

    try:
        signal_value = int(signal)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        signal_value = 0

    safe_confidence = float(confidence or 0.0)

    # Extract reference_price from stocktechdata
    # Format: "Current price: 3500.50, timestamp: 2024-01-15 10:30:00"
    reference_price = None
    if stocktechdata and isinstance(stocktechdata, str) and stocktechdata.strip():
        try:
            # Try to extract price from "Current price: XXX" format
            if "Current price:" in stocktechdata:
                # Split on "Current price:" and take what's after it
                after_price = stocktechdata.split("Current price:")[1]
                # Take the number part (before comma or end of string)
                price_part = after_price.split(",")[0].strip()
                # Remove any currency symbols or whitespace
                price_part = price_part.replace("₹", "").replace("$", "").strip()
                if price_part:
                    reference_price = float(price_part)
                    print(f"[PRICE] ✅ Extracted reference_price={reference_price} for {symbol}")
            elif stocktechdata.replace(".", "").replace("-", "").isdigit():
                # stocktechdata might just be a plain number
                reference_price = float(stocktechdata)
                print(f"[PRICE] ✅ Parsed reference_price={reference_price} (plain number) for {symbol}")
            else:
                print(f"[PRICE] ⚠️ stocktechdata format not recognized for {symbol}: '{stocktechdata[:100] if len(stocktechdata) > 100 else stocktechdata}'")
        except (ValueError, IndexError, AttributeError) as exc:
            print(f"[PRICE] ⚠️ Failed to parse reference_price for {symbol}: {exc}")
    else:
        print(f"[PRICE] ⚠️ Empty or invalid stocktechdata for {symbol}: {type(stocktechdata)}")

    event = BSESignalEvent(
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

    try:
        # STEP 1: Queue trade execution ONLY for actionable signals (1=BUY, -1=SELL)
        # Skip signal=0 (HOLD) - no point sending to trading queue
        if signal_value in (1, -1):
            celery_app.send_task(
                "pipeline.trade_execution.process_signal",
                args=[signal_payload],
                queue="trading",  # Route to TRADING queue (NOT pipelines!)
                priority=9,  # HIGH PRIORITY - execute immediately
            )
            price_str = f"₹{reference_price:.2f}" if reference_price is not None else "N/A (will fetch)"
            print(f"[CELERY] Queued trade execution for {symbol} signal={signal_value} (price: {price_str})")
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

        # STEP 3: Queue company report update (non-blocking, background task)
        # This updates the qualitative fundamentals database based on the filing
        # ONLY for relevant filing categories (filters out noise)
        if attachment_url and subject_of_announcement:
            # Check if filing is relevant for report updates BEFORE queueing
            if _is_relevant_for_report_update(subject_of_announcement):
                try:
                    celery_app.send_task(
                        "company_report.update_from_nse_filing_url",
                        args=[symbol, attachment_url, subject_of_announcement, subject_of_announcement, filing_time],
                        queue="general",  # Route to general queue (not blocking trading)
                        priority=3,  # Lower priority than trading
                    )
                    print(f"[REPORT] ✅ Queued company report update for {symbol} (filing: {subject_of_announcement[:50]})")
                except Exception as report_exc:
                    # Report update failure doesn't affect trade execution
                    print(f"[REPORT] ⚠️ Failed to queue company report update: {report_exc}")
            else:
                print(f"[REPORT] ⏭️ Skipped non-relevant filing for {symbol}: {subject_of_announcement[:50]}")

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

BSE_SUBCATEGORY_TO_FILING_TYPE = {
    "outcome of board meeting": "Outcome of Board Meeting",
    "outcome without intimation": "Outcome of Board Meeting",
    "revision of outcome": "Outcome of Board Meeting",
    "financial results": "Outcome of Board Meeting",
    "press release / media release": "Press Release",
    "press release / media release (revised)": "Press Release",
    "acquisition": "Acquisition",
    "investor presentation": "Investor Presentation",
    "diversification / disinvestment": "Sale or Disposal",
    "sale of shares": "Sale or Disposal",
    "restructuring": "Sale or Disposal",
    "award of order / receipt of order": "Bagging/Receiving of Orders/Contracts",
    "change in management": "Change in Director(s)",
    "change in directorate": "Change in Director(s)",
    "resignation of director": "Change in Director(s)",
    "resignation of managing director": "Change in Director(s)",
    "cessation": "Change in Director(s)",
    "appointment of company secretary / compliance officer": "Appointment",
    "resignation of company secretary / compliance officer": "Appointment",
    "resignation of chief executive officer (ceo)": "Appointment",
    "resignation of chief financial officer (cfo)": "Appointment",
    "updates - corporate insolvency resolution process  (cirp)": (
        "Action(s) initiated or orders passed"
    ),
    "liquidation - corporate insolvency resolution process  (cirp)": "Action(s) initiated or orders passed",
    "initiation of corporate insolvency resolution process (cirp) by financial creditors": "Action(s) initiated or orders passed",
    "admission of application by tribunal": "Action(s) initiated or orders passed",
    "appointment of interim resolution professional (irp)": "Action(s) initiated or orders passed",
    "intimation of meeting of committee of creditors": "Action(s) initiated or orders passed",
    "outcome of meeting of committee of creditors": "Action(s) initiated or orders passed",
    "public announcement": "Action(s) initiated or orders passed",
    "scheme of arrangement": "Acquisition",
    "monthly business updates": "Updates",
    "strikes /lockouts / disturbances": "Updates",
}

BSE_ADVERSE_ORDER_KEYWORDS = {
    "income tax",
    "tax authority",
    "tax demand",
    "demand order",
    "penalty",
    "adjudication",
    "regulatory order",
    "court order",
    "nclt",
    "nclat",
    "gst order",
    "show cause",
}


def map_bse_filing_type(
    category_name: str, subcategory_name: str, headline: str
) -> str:
    """Normalize BSE taxonomy to the strategy's established filing types."""
    normalized_subcategory = " ".join(
        (subcategory_name or "").lower().split()
    )
    normalized_map = {
        " ".join(key.split()): value
        for key, value in BSE_SUBCATEGORY_TO_FILING_TYPE.items()
    }
    if (
        normalized_subcategory == "award of order / receipt of order"
        and any(
            keyword in (headline or "").lower()
            for keyword in BSE_ADVERSE_ORDER_KEYWORDS
        )
    ):
        return "Action(s) initiated or orders passed"
    mapped = normalized_map.get(normalized_subcategory)
    if mapped:
        return mapped

    # Only BSE's broad General bucket needs headline classification. Named
    # subcategories are authoritative and should not be reinterpreted using
    # NSE-era fuzzy matching.
    if normalized_subcategory in {"", "general"}:
        return map_filing_type(headline)
    return ""


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
    elif re.search(r"\b(order|action)\b", desc_lower):
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


def should_use_positive_impact(filing_type: str) -> bool:
    """Check if positive impact should be fetched for this filing type"""
    if not filing_type or filing_type not in RELEVANT_FILE_TYPES:
        return False
    return RELEVANT_FILE_TYPES[filing_type].get("positive", False)


def should_use_negative_impact(filing_type: str) -> bool:
    """Check if negative impact should be fetched for this filing type"""
    if not filing_type or filing_type not in RELEVANT_FILE_TYPES:
        return False
    return RELEVANT_FILE_TYPES[filing_type].get("negative", False)


def extract_filename_from_url(url: str) -> str:
    """Extract filename from URL path."""
    if not url:
        return ""
    return url.split("/")[-1]


# ============================================================================
# PDF DOWNLOAD AND PARSING
# ============================================================================

def download_and_parse_pdf(url: str, filename: str) -> str:
    """Download PDF to docs folder and return the filename only.
    
    The PDF will be attached to the LLM in generate_trading_signal and deleted after processing.
    """
    try:
        import requests
        import os
        import uuid

        if not url or not url.strip():
            print(f"[WARN] Empty PDF URL for {filename}, skipping download")
            return ""

        print(f"[PIPELINE] Downloading PDF: {filename} from {url[:100]}...")

        # Use the pipeline docs folder for temporary PDFs.
        docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
        os.makedirs(docs_dir, exist_ok=True)
        
        # Use unique filename to avoid race conditions
        unique_suffix = str(uuid.uuid4())[:8]
        temp_filename = f"{filename}.{unique_suffix}.pdf"
        path = os.path.join(docs_dir, temp_filename)

        # Always download fresh (scraper handles deduplication)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/124.0.0.0 Safari/537.36"
        }

        # Ensure URL is complete (some PDFs might be relative URLs)
        if not url.startswith('http'):
            url = f"https://www.bseindia.com{url}"

        try:
            response = requests.get(url, headers=headers, stream=True, timeout=15)
            response.raise_for_status()

            print(f"[PIPELINE] PDF download started: {filename} ({response.headers.get('Content-Length', 'unknown')} bytes)")

            with open(path, "wb") as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)

            file_size = os.path.getsize(path)
            print(f"[PIPELINE] PDF downloaded: {temp_filename} ({file_size} bytes) to {docs_dir}")
            # Return only the temp filename (with unique suffix)
            return temp_filename
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to download PDF {filename} from {url}: {e}")
            return ""
        except Exception as e:
            print(f"[ERROR] Unexpected error downloading PDF {filename}: {e}")
            return ""

    except Exception as e:
        print(f"Error processing PDF {filename}: {e}")
        # Try to clean up on error too
        try:
            if 'path' in locals() and os.path.exists(path):
                os.remove(path)
        except:
            pass
        return ""


# ============================================================================
# STOCK DATA FETCHING
# ============================================================================

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
        context_end = filing_dt
        context_start = context_end - timedelta(hours=1)
        params = {
            "symbols": symbol,
            "candle": "1h",
            "start": context_start.isoformat(),
            "end": context_end.isoformat(),
        }
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
                        candles = (
                            data.get("metadata", {})
                            .get("candles", {})
                            .get(symbol.upper(), [])
                        )
                        technical_context = ""
                        if candles:
                            closes = [
                                float(candle["close"])
                                for candle in candles
                                if candle.get("close") is not None
                            ]
                            highs = [
                                float(candle["high"])
                                for candle in candles
                                if candle.get("high") is not None
                            ]
                            lows = [
                                float(candle["low"])
                                for candle in candles
                                if candle.get("low") is not None
                            ]
                            volumes = [
                                float(candle.get("volume") or 0)
                                for candle in candles
                            ]
                            if closes:
                                one_hour_return = (
                                    ((closes[-1] / closes[0]) - 1) * 100
                                    if closes[0] > 0
                                    else 0
                                )
                                technical_context = (
                                    f", past_1h_candles: {len(closes)}, "
                                    f"past_1h_return_pct: {one_hour_return:.3f}, "
                                    f"past_1h_high: {max(highs) if highs else closes[-1]:.4f}, "
                                    f"past_1h_low: {min(lows) if lows else closes[-1]:.4f}, "
                                    f"past_1h_volume: {sum(volumes):.0f}"
                                )
                        return (
                            f"Current price: {price}, timestamp: {filing_time}"
                            f"{technical_context}"
                        )

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


def fetch_cold_path_inputs(
    symbol: str, filing_time: str, attachment_url: str, filename: str
) -> str:
    """Fetch PDF and stock context concurrently without making PDF mandatory."""
    import json
    import time

    cold_started = time.perf_counter()

    def timed_pdf():
        started = time.perf_counter()
        result = download_and_parse_pdf(attachment_url, filename)
        return result, int((time.perf_counter() - started) * 1000)

    def timed_stock():
        started = time.perf_counter()
        result = fetch_stock_data(symbol, filing_time)
        return result, int((time.perf_counter() - started) * 1000)

    pdf_filename = ""
    stocktechdata = ""
    pdf_ms = stock_ms = 0
    with ThreadPoolExecutor(max_workers=2) as executor:
        pdf_future = executor.submit(timed_pdf)
        stock_future = executor.submit(timed_stock)
        try:
            pdf_filename, pdf_ms = pdf_future.result(timeout=30)
        except Exception as exc:
            print(f"[COLD-PATH] {symbol} | PDF unavailable: {exc}")
        try:
            stocktechdata, stock_ms = stock_future.result(timeout=15)
        except Exception as exc:
            print(f"[COLD-PATH] {symbol} | stock data unavailable: {exc}")

    return json.dumps(
        {
            "pdf_filename": pdf_filename,
            "stocktechdata": stocktechdata,
            "pdf_ms": pdf_ms,
            "stock_ms": stock_ms,
            "pre_llm_ms": int((time.perf_counter() - cold_started) * 1000),
        }
    )


def parse_cold_input(response: str, field: str) -> str:
    import json
    try:
        return str(json.loads(response).get(field, ""))
    except (TypeError, ValueError):
        return ""


# ============================================================================
# STATIC DATA LOOKUP
# ============================================================================

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
        normalized_types = (
            staticdf["file type"].astype(str).str.strip().str.rstrip(":").str.lower()
        )
        match = staticdf[
            normalized_types == file_type.strip().rstrip(":").lower()
        ]

        if not match.empty:
            return str(match["positive impct "].values[0])
        else:
            return "not much specific"
    except Exception as e:
        print(f"Error reading static data: {e}")
        return "not much specific"


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
        normalized_types = (
            staticdf["file type"].astype(str).str.strip().str.rstrip(":").str.lower()
        )
        match = staticdf[
            normalized_types == file_type.strip().rstrip(":").lower()
        ]

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

def generate_trading_signal(
    pos_impact: str,
    neg_impact: str,
    stocktechdata: str,
    api_key: str,
    pdf_filename: str = "",
    symbol: str = "",
    cold_inputs: str = "",
) -> str:
    """
    Generate a trading signal with one Gemini call.

    The model returns JSON directly wrapped in ```json...``` block.
    This function extracts the JSON and returns it with timing metadata.

    After signal processing, the PDF file is deleted from the docs folder.

    Latency is logged separately so the response stays on the public
    three-field contract.
    """
    import time
    import yaml
    import json

    # Track LLM processing start time
    llm_start_ts = time.time()

    # Load API key from environment if not provided or empty
    if not api_key or api_key.strip() == "":
        api_key = os.getenv("GEMINI_API_KEY", "")

    # GEMINI_API_KEY supports a comma-separated key pool. Never pass the
    # complete comma-separated string to Google as though it were one key.
    gemini_api_keys = [key.strip() for key in api_key.split(",") if key.strip()]
    model1_api_key = gemini_api_keys[0] if gemini_api_keys else ""

    print(f"[PIPELINE] Generating single-model signal (PDF filename: {pdf_filename or 'none'})...")
    # Load prompt templates from YAML files
    templates_dir = Path(__file__).resolve().parents[2] / "templates"

    try:
        # Load signal generation prompt (Model 1)
        gen_prompt_path = templates_dir / "nse_signal_generation_prompt.yaml"
        with open(gen_prompt_path, 'r') as f:
            gen_config = yaml.safe_load(f)

        print(f"[PIPELINE] Loaded prompt templates from {templates_dir}")
    except Exception as e:
        error_msg = f"Failed to load YAML templates from {templates_dir}: {e}"
        print(f"[ERROR] {error_msg}")
        return json.dumps({"error": error_msg, "final_signal": 0, "Confidence": 0})

    def extract_content_from_response(response) -> str:
        """Extract content string from LLM response object."""
        if hasattr(response, 'content'):
            content = response.content
        else:
            content = str(response)

        # Handle content that is a list of content blocks (Gemini format)
        if isinstance(content, list) and len(content) > 0:
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if 'text' in block:
                        text_parts.append(block['text'])
                    elif 'content' in block:
                        text_parts.append(block['content'])
                else:
                    text_parts.append(str(block))
            content = '\n'.join(text_parts)

        return content

    def extract_json_from_response(response_text: str) -> dict:
        """Extract JSON from model response (handles ```json...``` blocks and loose JSON)."""
        # Try to extract JSON from markdown code block
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_match:
            json_text = json_match.group(1).strip()
            try:
                return json.loads(json_text)
            except json.JSONDecodeError as e:
                print(f"[WARN] Failed to parse JSON from code block: {e}")

        # Try to extract the first JSON object from surrounding text
        loose_json_match = re.search(r"\{[\s\S]*\}", response_text)
        if loose_json_match:
            json_text = loose_json_match.group(0).strip()
            try:
                return json.loads(json_text)
            except json.JSONDecodeError as e:
                print(f"[WARN] Failed to parse loose JSON from response: {e}")
        
        # Try to parse the entire response as JSON
        try:
            return json.loads(response_text.strip())
        except json.JSONDecodeError:
            pass
        
        # Fallback: preserve the raw text so we do not lose the model's
        # reasoning when it returns prose instead of strict JSON.
        print(f"[WARN] Could not extract JSON from response: {response_text[:200]}...")
        fallback_text = response_text.strip()
        return {
            "final_signal": 0,
            "Confidence": 0,
            "explanation": fallback_text or "No explanation provided",
            "_raw_response": response_text,
        }

    def _pick_explanation(result: dict) -> str:
        """Pick the best available explanation-like field from a parsed result."""
        for key in ("explanation", "reasoning", "analysis", "justification", "rationale", "details"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raw_text = str(result.get("_raw_response", "") or "").strip()
        if raw_text and raw_text != "{}":
            return raw_text
        return "No explanation provided"

    # ============ MODEL 1: Generate signal + explanation ============
    user_prompt = gen_config['prompt_template'].format(
        stocktechdata=stocktechdata,
        pos_impact=pos_impact,
        neg_impact=neg_impact,
    )
    model1_name = gen_config.get('model', 'gemini-3.1-flash-lite')
    model1_temp = gen_config.get('temperature', 0.1)

    # Determine PDF path from filename (stored in nse/docs folder)
    pdf_path = None
    if pdf_filename and pdf_filename.strip():
        docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
        pdf_path = os.path.join(docs_dir, pdf_filename)
        if not os.path.exists(pdf_path):
            print(f"[WARN] PDF file not found at {pdf_path}, proceeding without attachment")
            pdf_path = None

    try:
        # Validate API key
        if not model1_api_key:
            error_msg = "GEMINI_API_KEY is empty or not set. Please check your .env file."
            print(f"[ERROR] {error_msg}")
            return json.dumps({"error": error_msg, "final_signal": 0, "Confidence": 0})

        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import HumanMessage
        from PyPDF2 import PdfReader
        import base64

        def invoke_with_key_rotation(
            *,
            model_name: str,
            temperature: float,
            message: HumanMessage,
            start_index: int = 0,
            bind_google_search: bool = False,
        ):
            """Invoke Gemini and fail over across the configured API key pool."""
            if not gemini_api_keys:
                raise ValueError("No Gemini API keys are configured")

            last_error = None
            ordered_keys = (
                gemini_api_keys[start_index:] + gemini_api_keys[:start_index]
            )
            for attempt, candidate_key in enumerate(ordered_keys, start=1):
                try:
                    candidate_model = ChatGoogleGenerativeAI(
                        model=model_name,
                        temperature=temperature,
                        api_key=candidate_key,
                        max_retries=0,
                    )
                    if bind_google_search:
                        candidate_model = candidate_model.bind_tools([
                            {"google_search": {}}
                        ])
                    return candidate_model.invoke([message])
                except Exception as exc:
                    last_error = exc
                    error_text = str(exc).lower()
                    retryable = any(
                        marker in error_text
                        for marker in (
                            "429",
                            "quota",
                            "resource_exhausted",
                            "api_key_invalid",
                            "api key not valid",
                            "permissiondenied",
                            "permission denied",
                            "denied access",
                            "403",
                        )
                    )
                    if not retryable or attempt == len(ordered_keys):
                        raise
                    print(
                        f"[WARN] Gemini key {attempt}/{len(ordered_keys)} "
                        f"unavailable for {model_name}; trying next configured key."
                    )

            raise last_error or RuntimeError("Gemini invocation failed")

        # Set GOOGLE_API_KEY env var for langchain
        original_google_key = os.environ.get("GOOGLE_API_KEY", None)
        os.environ["GOOGLE_API_KEY"] = model1_api_key

        try:
            # Build message parts for Model 1
            message_parts = [{"type": "text", "text": user_prompt}]

            # Attach PDF if available and valid
            attach_pdf = False
            if pdf_path:
                try:
                    # Validate PDF with PyPDF2 (non-strict mode)
                    reader = PdfReader(pdf_path, strict=False)
                    page_count = len(reader.pages)
                    if page_count >= 1:
                        attach_pdf = True
                    else:
                        print(f"[WARN] PDF has zero pages, skipping attachment: {pdf_path}")
                except Exception as e:
                    print(f"[WARN] PDF unreadable/corrupted, skipping attachment: {pdf_path} | Error: {e}")

            if attach_pdf:
                try:
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
                    message_parts.append({
                        "type": "file",
                        "mime_type": "application/pdf",
                        "base64": pdf_b64
                    })
                    print(f"[INFO] PDF attached successfully: {pdf_path}")
                except Exception as e:
                    print(f"[WARN] Failed to attach PDF {pdf_path}: {e}")
            else:
                print("[INFO] Proceeding WITHOUT PDF attachment.")

            # Create HumanMessage with multipart content
            human_msg = HumanMessage(content=message_parts)

            print(f"[PIPELINE] Model 1 ({model1_name}): Generating signal + explanation...")
            decision_raw = invoke_with_key_rotation(
                model_name=model1_name,
                temperature=model1_temp,
                message=human_msg,
            )
            decision_text = extract_content_from_response(decision_raw)

            print(f"[PIPELINE] Model 1 Response: {decision_text[:300]}...")

            # Extract JSON from Model 1 response
            model1_result = extract_json_from_response(decision_text)
            signal = model1_result.get("final_signal", model1_result.get("trading_signal", 0))
            confidence = model1_result.get("Confidence", model1_result.get("confidence", 0))

            print(f"[PIPELINE] Model 1 Result: signal={signal}, confidence={confidence}")

            final_signal = signal
            final_confidence = confidence

            # Clamp confidence to [0, 1]
            if isinstance(final_confidence, (int, float)):
                final_confidence = max(0.0, min(1.0, float(final_confidence)))
            else:
                final_confidence = 0.5

            llm_delay_ms = int((time.time() - llm_start_ts) * 1000)
            model1_explanation = _pick_explanation(model1_result)
            pdf_ms = stock_ms = pre_llm_ms = 0
            try:
                cold_metrics = json.loads(cold_inputs or "{}")
                pdf_ms = int(cold_metrics.get("pdf_ms", 0))
                stock_ms = int(cold_metrics.get("stock_ms", 0))
                pre_llm_ms = int(cold_metrics.get("pre_llm_ms", 0))
            except (TypeError, ValueError):
                pass
            print(
                f"[COLD-PATH] {symbol} | pdf_ms={pdf_ms} | "
                f"stock_ms={stock_ms} | llm_ms={llm_delay_ms} | "
                f"total_ms={pre_llm_ms + llm_delay_ms}"
            )
            final_result = {
                "final_signal": final_signal,
                "Confidence": final_confidence,
                "explanation": model1_explanation,
            }

            # Delete PDF file after signal is processed
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                    print(f"[CLEANUP] ✅ Deleted PDF file: {pdf_path}")
                except Exception as e:
                    print(f"[CLEANUP] ⚠️ Failed to delete PDF file {pdf_path}: {e}")

            return json.dumps(final_result)

        finally:
            # Restore original environment variable if it existed
            if original_google_key is not None:
                os.environ["GOOGLE_API_KEY"] = original_google_key
            elif "GOOGLE_API_KEY" in os.environ:
                del os.environ["GOOGLE_API_KEY"]
            
            # Cleanup PDF file on any exit (error or success)
            # This is a fallback in case the cleanup above didn't run
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                    print(f"[CLEANUP] ✅ Deleted PDF file (finally block): {pdf_path}")
                except Exception as e:
                    print(f"[CLEANUP] ⚠️ Failed to delete PDF file {pdf_path}: {e}")

    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] LLM generation failed: {error_msg}")

        # Cleanup PDF file on error
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                print(f"[CLEANUP] ✅ Deleted PDF file (error handler): {pdf_path}")
            except Exception as cleanup_e:
                print(f"[CLEANUP] ⚠️ Failed to delete PDF file {pdf_path}: {cleanup_e}")

        # Provide helpful error message
        error_result = {"final_signal": 0, "Confidence": 0, "error": error_msg}
        if "credentials" in error_msg.lower() or "api key" in error_msg.lower():
            error_result["error"] = f"API key issue - {error_msg}. Please check GEMINI_API_KEY in .env file."
        elif "429" in error_msg or "quota" in error_msg.lower():
            error_result["error"] = "Rate limit exceeded. Please reduce scraping frequency or upgrade Gemini API tier."
        return json.dumps(error_result)


def parse_trading_signal_value(response: str) -> int:
    """Parse trading signal value (1, 0, or -1) from JSON response."""
    import json
    try:
        if not response:
            return 0

        # Parse JSON response
        try:
            data = json.loads(response)
            signal = data.get("final_signal", data.get("trading_signal", 0))
            # Validate signal is in valid range
            if signal not in [-1, 0, 1]:
                print(f"[WARN] Invalid signal value {signal}, defaulting to HOLD (0)")
                return 0
            print(f"[PIPELINE] Parsed signal from JSON: {signal}")
            return signal
        except json.JSONDecodeError as e:
            print(f"[WARN] Failed to parse JSON response: {e}")
            return 0

    except Exception as e:
        print(f"[ERROR] Error parsing signal: {e}")
        return 0


def parse_trading_signal_explanation(response: str) -> str:
    """Parse trading signal explanation from JSON response."""
    import json
    try:
        if not response:
            return "No explanation provided"

        # Parse JSON response
        try:
            data = json.loads(response)
            for key in ("explanation", "reasoning", "analysis", "justification", "rationale", "details"):
                explanation = data.get(key)
                if isinstance(explanation, str) and explanation.strip():
                    print(f"[PIPELINE] Parsed explanation from JSON: {explanation[:100]}...")
                    return explanation.strip()

            return "No explanation provided"
        except json.JSONDecodeError as e:
            print(f"[WARN] Failed to parse JSON response: {e}")
            return "No explanation provided"

    except Exception as e:
        print(f"[ERROR] Error parsing explanation: {e}")
        return "No explanation provided"


def parse_trading_signal_confidence(response: str) -> float:
    """Parse confidence score (0-1) from JSON response."""
    import json
    try:
        if not response:
            return 0.0

        # Parse JSON response
        try:
            data = json.loads(response)
            # Check for error in response
            if data.get("error"):
                return 0.0
            confidence = data.get("Confidence", data.get("confidence", data.get("confidence_score", 0.5)))
            # Ensure confidence is a float and clamp to [0, 1]
            confidence = float(confidence) if confidence is not None else 0.5
            confidence = max(0.0, min(1.0, confidence))
            print(f"[PIPELINE] Parsed confidence from JSON: {confidence}")
            return confidence
        except json.JSONDecodeError as e:
            print(f"[WARN] Failed to parse JSON response: {e}")
            return 0.0

    except Exception as exc:
        print(f"[ERROR] Error parsing confidence score: {exc}")
        return 0.0


# ============================================================================
# DIRECT CELERY COLD PATH
# ============================================================================

def process_bse_filing(
    filing: dict,
    static_data_path: str = "staticdata.csv",
) -> dict:
    """Process one non-bagging BSE filing without a streaming framework."""
    symbol = str(filing.get("symbol") or filing.get("scrip_cd") or "").strip()
    headline = str(filing.get("headline") or "").strip()
    category_name = str(filing.get("category_name") or "").strip()
    subcategory_name = str(
        filing.get("subcategory_name") or ""
    ).strip()
    attachment_name = str(filing.get("attachment_name") or "").strip()
    submission_dt = str(filing.get("submission_dt") or "").strip()

    if not symbol:
        raise ValueError("BSE filing is missing symbol and scrip code")
    if filing.get("is_bagging"):
        raise ValueError("Bagging filings must use the hot path")

    filing_type = map_bse_filing_type(
        category_name,
        subcategory_name,
        headline,
    )
    if not filing_type:
        return {
            "status": "skipped",
            "symbol": symbol,
            "reason": "irrelevant_filing_type",
        }

    filename = extract_filename_from_url(attachment_name)
    cold_inputs = fetch_cold_path_inputs(
        symbol,
        submission_dt,
        attachment_name,
        filename,
    )
    pdf_filename = parse_cold_input(cold_inputs, "pdf_filename")
    stocktechdata = parse_cold_input(cold_inputs, "stocktechdata")
    pos_impact = get_pos_impact(
        filing_type,
        should_use_positive_impact(filing_type),
        static_data_path,
    )
    neg_impact = get_neg_impact(
        filing_type,
        should_use_negative_impact(filing_type),
        static_data_path,
    )
    llm_response = generate_trading_signal(
        pos_impact,
        neg_impact,
        stocktechdata,
        GEMINI_API_KEY,
        pdf_filename,
        symbol,
        cold_inputs,
    )
    signal = parse_trading_signal_value(llm_response)
    explanation = parse_trading_signal_explanation(llm_response)
    confidence = parse_trading_signal_confidence(llm_response)
    publish_status = publish_signal_to_kafka(
        symbol,
        submission_dt,
        signal,
        explanation,
        confidence,
        stocktechdata,
        filing_type,
        attachment_name,
        submission_dt,
    )
    return {
        "status": publish_status,
        "symbol": symbol,
        "filing_time": submission_dt,
        "signal": signal,
        "explanation": explanation,
        "confidence": confidence,
    }


# ============================================================================
# LEGACY PATHWAY GRAPH (unused; retained temporarily for API compatibility)
# ============================================================================

def create_bse_filings_pipeline(
    filings_source: pw.Table,
    static_data_path: str = "staticdata.csv",
    output_path: str = "trading_signals.jsonl"
):
    """
    Deprecated compatibility entrypoint.

    Args:
        filings_source: Pathway table with BSE filing data
        static_data_path: Path to CSV with filing type impact scenarios
        output_path: Path to write trading signals
    """
    raise RuntimeError(
        "Pathway has been removed from the BSE pipeline; use "
        "process_bse_filing via Celery task 'pipeline.bse.process_filing'."
    )

    required_static_columns = {
        "file type",
        "positive impct ",
        "negtive impct",
    }
    if not os.path.isfile(static_data_path):
        raise FileNotFoundError(
            f"CFDT static knowledge base not found: {static_data_path}"
        )
    import pandas as pd

    static_columns = set(pd.read_csv(static_data_path, nrows=1).columns)
    missing_columns = required_static_columns - static_columns
    if missing_columns:
        raise ValueError(
            "CFDT static knowledge base is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

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

        # Keep the streaming graph alive when started before market open.
        # Per-filing market-hours checks run when each filing is processed.

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

    print("[SENTIMENT] Step 1: Processing filings from scraper...")

    def log_filing(symbol, headline, attachment_name):
        print(f"[DEBUG] Incoming BSE filing: {symbol} - {headline[:80]}... PDF: {bool(attachment_name)}")
        return symbol

    filings_source = filings_source.select(
        *pw.this,
        _debug=pw.apply(
            log_filing,
            pw.this.symbol,
            pw.this.headline,
            pw.this.attachment_name,
        )
    )

    filings_with_types = filings_source.select(
        *pw.this,
        filing_type=pw.if_else(
            pw.this.category_name != "",
            pw.this.category_name,
            map_filing_type(pw.this.headline),
        ),
        filename=extract_filename_from_url(pw.this.attachment_name),
    )

    relevant_filings = filings_with_types.filter(
        (pw.this.filing_type != "") & (~pw.this.is_bagging)
    )

    print("[SENTIMENT] Step 1a: Filtered filings by relevant types...")
    print(f"[SENTIMENT] Relevant filing types: {list(RELEVANT_FILE_TYPES.keys())}")

    print("[SENTIMENT] Step 2: Fetching PDF and stock data concurrently...")
    filings_with_inputs = relevant_filings.select(
        symbol=pw.this.symbol,
        headline=pw.this.headline,
        filing_type=pw.this.filing_type,
        submission_dt=pw.this.submission_dt,
        attachment_name=pw.this.attachment_name,
        category_name=pw.this.category_name,
        cold_inputs=fetch_cold_path_inputs(
            pw.this.symbol,
            pw.this.submission_dt,
            pw.this.attachment_name,
            pw.this.filename,
        ),
    )

    print("[SENTIMENT] Step 3: Fetching impact scenarios and stock data...")

    filings_with_impact_flags = filings_with_inputs.select(
        *pw.this,
        filename=parse_cold_input(pw.this.cold_inputs, "pdf_filename"),
        stocktechdata=parse_cold_input(pw.this.cold_inputs, "stocktechdata"),
        use_positive=should_use_positive_impact(pw.this.filing_type),
        use_negative=should_use_negative_impact(pw.this.filing_type),
    )

    filings_enriched = filings_with_impact_flags.select(
        *pw.this,
        pos_impact=get_pos_impact(pw.this.filing_type, pw.this.use_positive, static_data_path),
        neg_impact=get_neg_impact(pw.this.filing_type, pw.this.use_negative, static_data_path),
    )

    print("[SENTIMENT] Step 4: Generating trading signals with LLM...")
    if not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
        print("[WARN] GEMINI_API_KEY not set - trading signals will fail!")

    filings_with_responses = filings_enriched.select(
        *pw.this,
        llm_response=generate_trading_signal(
            pw.this.pos_impact,
            pw.this.neg_impact,
            pw.this.stocktechdata,
            GEMINI_API_KEY,
            pw.this.filename,
            pw.this.symbol,
            pw.this.cold_inputs,
        )
    )

    print("[SENTIMENT] Step 5: Parsing trading signals...")
    trading_signals = filings_with_responses.select(
        symbol=pw.this.symbol,
        filing_time=pw.this.submission_dt,
        signal=parse_trading_signal_value(pw.this.llm_response),
        explanation=parse_trading_signal_explanation(pw.this.llm_response),
        confidence=parse_trading_signal_confidence(pw.this.llm_response),
        stocktechdata=pw.this.stocktechdata,
        subject_of_announcement=pw.this.category_name,
        attachment_url=pw.this.attachment_name,
        date_time_of_submission=pw.this.submission_dt,
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
            pw.this.subject_of_announcement,
            pw.this.attachment_url,
            pw.this.date_time_of_submission,
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
        schema=BSEFilingSchema,
        mode="streaming",
        autocommit_duration_ms=50,  # Minimal latency for trading signals
    )


def create_filings_input_from_kafka(kafka_settings: dict, topic: str) -> pw.Table:
    """Create Pathway table from Kafka topic"""
    return pw.io.kafka.read(
        kafka_settings,
        topic=topic,
        schema=BSEFilingSchema,
        format="json",
        autocommit_duration_ms=50,  # Minimal latency for trading signals
    )


def create_filings_input_from_http(port: int = 8001) -> tuple[pw.Table, pw.io.http.PathwayWebserver]:
    """Create Pathway table from HTTP REST API"""
    class FilingInputSchema(pw.Schema):
        slno: str = pw.column_definition(primary_key=True)
        symbol: str
        scrip_cd: str
        headline: str
        category_name: str
        attachment_name: str
        submission_dt: str
        is_bagging: bool

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
    """Explain the worker entrypoint when this module is run directly."""
    print(
        "BSE cold-path processing runs as Celery task "
        "'pipeline.bse.process_filing'. Start bse_scraper.py for ingestion."
    )


if __name__ == "__main__":
    main()

