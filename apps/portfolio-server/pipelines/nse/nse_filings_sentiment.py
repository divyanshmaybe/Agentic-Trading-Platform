# -*- coding: utf-8 -*-
"""
NSE Filings Sentiment Agent - Pathway Real-time Implementation

This script processes NSE corporate filings in real-time, extracts text from PDFs,
fetches stock technical data, and generates trading signals using LLM analysis.
"""

import asyncio
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
from market_data import get_market_data_service  # type: ignore  # noqa: E402
from utils.backtesting import resolve_intraday_window  # type: ignore  # noqa: E402

# LLM imports
from pathway.xpacks.llm import llms

# Load environment variables ONLY from portfolio-server .env file
# The pipeline service loads it before importing, but we ensure it's loaded here too
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
HOLDING_HOURS = 1  # maximum hold time (1 hour)
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


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
) -> str:
    """Publish the generated trading signal to Kafka and return a status string."""

    try:
        signal_value = int(signal)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        signal_value = 0

    safe_confidence = float(confidence or 0.0)
    event = NSESignalEvent(
        symbol=symbol,
        filing_time=filing_time,
        signal=signal_value,
        explanation=explanation or "",
        confidence=safe_confidence,
        generated_at=datetime.utcnow().isoformat() + "Z",
    )

    try:
        _publish_to_kafka(event)
        return "published"
    except TimeoutError:
        print("[KAFKA] Publish timed out for symbol", symbol)
        return "timeout"
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"[KAFKA] Failed to publish signal for {symbol}: {exc}")
        return f"error:{exc}"


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
        
        print(f"[PIPELINE] Downloading PDF: {filename}")
        
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
        
        response = requests.get(url, headers=headers, stream=True, timeout=15)
        response.raise_for_status()
        
        with open(path, "wb") as f:
            for chunk in response.iter_content(8192):
                f.write(chunk)
        
        print(f"[PIPELINE] PDF downloaded: {filename}, extracting text...")
        
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
    """Fetch stock technical data for the past hour"""
    try:
        import pandas as pd
    except Exception:
        pd = None  # type: ignore

    try:
        filing_dt = datetime.strptime(filing_time, "%Y-%m-%d %H:%M:%S")
    except Exception:
        filing_dt = datetime.utcnow()

    # Attempt to leverage centralised market service first
    try:
        service = get_market_data_service()
        adapter = getattr(service, "adapter", None)
        if adapter and hasattr(adapter, "get_historical_candles"):
            start_dt, end_dt = resolve_intraday_window(
                filing_dt,
                holding_hours=HOLDING_HOURS,
                market_open=MARKET_OPEN,
                market_close=MARKET_CLOSE,
                lookback_minutes=60,
            )
            candles = adapter.get_historical_candles(
                symbol=symbol,
                interval="FIFTEEN_MINUTE",
                fromdate=start_dt.strftime("%Y-%m-%d %H:%M"),
                todate=end_dt.strftime("%Y-%m-%d %H:%M"),
                exchange="NSE",
            )
            if candles and pd is not None:
                df = pd.DataFrame(candles)
                if not df.empty:
                    df["timestamp"] = pd.to_datetime(df["timestamp"]).astype(str)
                    return df.to_json(orient="records")
            elif candles:
                return str(candles)
    except Exception as exc:
        print(f"[WARN] Central market service candle fetch failed for {symbol}: {exc}")

    # Fallback to yfinance if central service unavailable
    try:
        import yfinance as yf
        if pd is None:
            import pandas as pd  # type: ignore

        end_time = filing_dt
        start_time = end_time - timedelta(hours=1)
        ticker = f"{symbol}.NS"
        stock_data = yf.download(
            ticker,
            start=start_time,
            end=end_time,
            interval="15m",
            progress=False,
            raise_errors=False,
        )
        if stock_data is None or stock_data.empty:
            return "No data available"
        return stock_data.to_json(orient="records")
    except Exception as fallback_error:
        error_str = str(fallback_error)
        if "delisted" in error_str.lower() or "no price data" in error_str.lower():
            return "Stock delisted or no data available"
        return f"Error fetching data: {error_str}"


# ============================================================================
# STATIC DATA LOOKUP
# ============================================================================

@pw.udf
def get_pos_impact(file_type: str, static_data_path: str = "staticdata.csv") -> str:
    """Get positive impact scenario for filing type"""
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
def get_neg_impact(file_type: str, static_data_path: str = "staticdata.csv") -> str:
    """Get negative impact scenario for filing type"""
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
    Returns structured response with signal and explanation
    """
    print("[PIPELINE] Generating trading signal with LLM...")
    
    # Load API key from environment if not provided or empty
    if not api_key or api_key.strip() == "":
        api_key = os.getenv("GEMINI_API_KEY", "")
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
        
        # langchain_google_genai uses GOOGLE_API_KEY env var, so set it
        original_google_key = os.environ.get("GOOGLE_API_KEY", None)
        os.environ["GOOGLE_API_KEY"] = api_key
        
        try:
            # Create model - it will use GOOGLE_API_KEY from environment
            trading_model = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
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
                
                # Debug: Print response to see what LLM is returning
                print(f"[PIPELINE] LLM Response: {response_text[:200]}...")
                
                return response_text
                
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
    
    # Step 1: Download PDFs and extract filenames
    print("[SENTIMENT] Step 1: Processing filings from scraper...")
    filings_with_paths = filings_source.select(
        *pw.this,
        filename=pw.apply(lambda url: url.split("/")[-1] if url else "", pw.this.attchmntFile),
    )
    
    # Step 2: Download and parse PDFs
    print("[SENTIMENT] Step 2: Downloading and parsing PDFs...")
    filings_with_text = filings_with_paths.select(
        symbol=pw.this.symbol,
        desc=pw.this.desc,
        sort_date=pw.this.sort_date,
        attchmntFile=pw.this.attchmntFile,
        text=download_and_parse_pdf(pw.this.attchmntFile, pw.this.filename),
    ).filter(pw.this.text != "")
    
    print("[SENTIMENT] Step 2 complete: PDFs parsed, proceeding to sentiment analysis...")
    
    # Step 3: Get impact scenarios and stock data
    print("[SENTIMENT] Step 3: Fetching impact scenarios and stock data...")
    filings_enriched = filings_with_text.select(
        *pw.this,
        pos_impact=get_pos_impact(pw.this.desc, static_data_path),
        neg_impact=get_neg_impact(pw.this.desc, static_data_path),
        stocktechdata=fetch_stock_data(pw.this.symbol, pw.this.sort_date)
    )
    
    # Step 4: Generate trading signals using LLM
    print("[SENTIMENT] Step 4: Generating trading signals with LLM...")
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
    
    # Step 5: Parse trading signals
    print("[SENTIMENT] Step 5: Parsing trading signals...")
    trading_signals = filings_with_responses.select(
        symbol=pw.this.symbol,
        filing_time=pw.this.sort_date,
        signal=parse_trading_signal_value(pw.this.llm_response),
        explanation=parse_trading_signal_explanation(pw.this.llm_response),
        confidence=parse_trading_signal_confidence(pw.this.llm_response),
    )
 
    # Step 6: Publish to Kafka and output results
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
        ),
    )

    pw.io.jsonlines.write(
        signals_with_kafka.select(
            symbol=pw.this.symbol,
            filing_time=pw.this.filing_time,
            signal=pw.this.signal,
            explanation=pw.this.explanation,
            confidence=pw.this.confidence,
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
        autocommit_duration_ms=1000,
    )


def create_filings_input_from_kafka(kafka_settings: dict, topic: str) -> pw.Table:
    """Create Pathway table from Kafka topic"""
    return pw.io.kafka.read(
        kafka_settings,
        topic=topic,
        schema=NSEFilingSchema,
        format="json",
        autocommit_duration_ms=1000,
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
        autocommit_duration_ms=1000,
        delete_completed_queries=False,
    )
    
    return filings, writer


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""
    
    # Example: Create input from CSV
    # Uncomment the appropriate input method:
    
    # Option 1: CSV input
    # filings_input = create_filings_input_from_csv("nse_filings.csv")
    
    # Option 2: Kafka input
    # kafka_settings = {
    #     "bootstrap.servers": "localhost:9092",
    #     "group.id": "nse_filings_consumer",
    # }
    # filings_input = create_filings_input_from_kafka(kafka_settings, "nse_filings")
    
    # Option 3: HTTP input (for testing)
    filings_input, writer = create_filings_input_from_http(port=8001)
    
    # Create pipeline
    trading_signals = create_nse_filings_pipeline(
        filings_source=filings_input,
        static_data_path="staticdata.csv",
        output_path="trading_signals.jsonl"
    )
    
    # Optional: Write signals back via HTTP
    # writer(trading_signals.select(
    #     result=pw.apply(
    #         lambda s, e: f"Signal: {s}, Explanation: {e}",
    #         pw.this.signal,
    #         pw.this.explanation
    #     )
    # ))
    
    # Run the pipeline
    pw.run()


if __name__ == "__main__":
    main()

