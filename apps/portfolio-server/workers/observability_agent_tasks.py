"""
Observability Agent Tasks - NSE Pipeline Loss Analysis

This module implements an observability agent that analyzes trades from the NSE pipeline
when they result in losses (negative realized PnL or stop-loss triggers).

The agent:
1. Receives trade closure data with signal context
2. Downloads and analyzes the original NSE filing PDF
3. Compares the LLM's reasoning with actual market outcome
4. Generates structured feedback for pipeline improvement
5. Publishes analysis to Kafka for monitoring/alerting

Trigger conditions:
- Trade closed with negative realized_pnl
- Stop-loss triggered (status changes to executed with stop_loss order_type)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Initialize Phoenix tracing for observability agent
try:
    from phoenix.otel import register
    
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="observability-agent",
            endpoint=collector_endpoint,
            auto_instrument=True,
        )
        print(f"✅ Phoenix tracing initialized for observability agent: {collector_endpoint}")
except ImportError:
    pass
except Exception:
    pass

import httpx
from celery.utils.log import get_task_logger
from pydantic import BaseModel, Field

# Add paths for imports
SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

from celery_app import celery_app, QUEUE_NAMES  # type: ignore  # noqa: E402
from kafka_service import (  # type: ignore  # noqa: E402
    KafkaPublisher,
    PublisherAlreadyRegistered,
    default_kafka_bus,
)

task_logger = get_task_logger(__name__)

# ============================================================================
# Constants and Configuration
# ============================================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OBSERVABILITY_KAFKA_TOPIC = os.getenv("NSE_OBSERVABILITY_TOPIC", "nse_agent_observability_logs")
OBSERVABILITY_PUBLISHER_NAME = "nse_observability_publisher"

# Filing type impact data (same as in nse_filings_sentiment.py)
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


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class TradeObservabilityContext:
    """Context for observability analysis of a trade."""
    
    # Trade information
    trade_id: str
    symbol: str
    side: str  # BUY or SELL
    quantity: int
    entry_price: float
    exit_price: float
    realized_pnl: float
    
    # Signal information
    signal_id: Optional[str] = None
    signal_value: int = 0  # 1=BUY, -1=SELL, 0=HOLD
    signal_confidence: float = 0.0
    signal_explanation: str = ""
    filing_time: str = ""
    generated_at: str = ""
    
    # Filing information
    filing_type: str = ""
    subject_of_announcement: str = ""
    attachment_url: str = ""
    pdf_url: str = ""
    
    # Execution metadata
    triggered_by: str = ""  # "stop_loss", "take_profit", "auto_sell", "manual"
    execution_time: Optional[str] = None
    trade_delay_ms: int = 0
    
    # Additional context
    agent_id: Optional[str] = None
    portfolio_id: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ObservabilityAnalysisResult(BaseModel):
    """Structured result from the observability agent analysis."""
    
    # Identifiers
    trade_id: str
    signal_id: Optional[str] = None
    symbol: str
    
    # Analysis results
    trading_decision: str = Field(description="Trading decision made by NSE agent")
    timestamp_of_trade_execution: str = Field(description="Timestamp of trade execution")
    reasoning_of_nse_agent: str = Field(description="Original reasoning from NSE agent")
    loss_incurred: str = Field(description="Profit or loss incurred")
    feedback_on_agent_performance: str = Field(description="Analysis and feedback on agent decision")
    
    # Metadata
    analyzed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "nse_observability_agent"
    
    # Additional context
    filing_type: Optional[str] = None
    confidence_score: float = 0.0
    triggered_by: str = ""


@dataclass
class LLMAnalysisOutput:
    """Extended output from LLM analysis including metadata for DB storage."""
    result: ObservabilityAnalysisResult
    prompt: str
    raw_response: str
    model_name: str
    model_provider: str
    latency_ms: int
    token_count: Optional[int] = None


# ============================================================================
# Kafka Publisher
# ============================================================================

_observability_publisher: Optional[KafkaPublisher] = None


def _get_observability_publisher() -> KafkaPublisher:
    """Get or create Kafka publisher for observability logs."""
    global _observability_publisher
    
    if _observability_publisher is not None:
        return _observability_publisher
    
    bus = default_kafka_bus
    try:
        _observability_publisher = bus.register_publisher(
            OBSERVABILITY_PUBLISHER_NAME,
            topic=OBSERVABILITY_KAFKA_TOPIC,
            value_model=ObservabilityAnalysisResult,
            default_headers={"stream": "nse_observability"},
        )
        task_logger.info(f"✅ Registered Kafka publisher for {OBSERVABILITY_KAFKA_TOPIC}")
    except PublisherAlreadyRegistered:
        _observability_publisher = bus.get_publisher(OBSERVABILITY_PUBLISHER_NAME)
        task_logger.debug(f"Using existing Kafka publisher for {OBSERVABILITY_KAFKA_TOPIC}")
    
    return _observability_publisher


def publish_observability_result(result: ObservabilityAnalysisResult) -> bool:
    """Publish observability analysis result to Kafka."""
    try:
        publisher = _get_observability_publisher()
        payload = result.model_dump()
        publisher.publish(payload, key=result.trade_id)
        task_logger.info(f"📤 Published observability analysis for trade {result.trade_id[:8]} to Kafka")
        return True
    except Exception as exc:
        task_logger.error(f"❌ Failed to publish observability result: {exc}")
        return False


# ============================================================================
# Database Storage for Observability Logs
# ============================================================================

async def save_observability_to_db(
    result: ObservabilityAnalysisResult,
    context: "TradeObservabilityContext",
    prompt: str = "",
    raw_response: str = "",
    model_name: str = "gemini-2.0-flash",
    model_provider: str = "google",
    token_count: Optional[int] = None,
    latency_ms: Optional[int] = None,
) -> Optional[str]:
    """
    Save observability analysis result to database.
    
    Args:
        result: The analyzed result from LLM
        context: The trade context used for analysis
        prompt: The prompt sent to the LLM
        raw_response: The raw LLM response text
        model_name: Name of the model used
        model_provider: Provider of the model (google, openai, etc.)
        token_count: Number of tokens used
        latency_ms: Time taken for LLM call in milliseconds
        
    Returns:
        The created record ID, or None if save fails
    """
    try:
        from db_context import get_db_connection
        
        async with get_db_connection() as client:
            # Extract key findings and recommendations from feedback
            feedback = result.feedback_on_agent_performance or ""
            
            # Build context data JSON
            context_data = {
                "trade_id": result.trade_id,
                "signal_id": result.signal_id,
                "symbol": result.symbol,
                "side": context.side if context else None,
                "quantity": context.quantity if context else None,
                "entry_price": context.entry_price if context else None,
                "exit_price": context.exit_price if context else None,
                "realized_pnl": context.realized_pnl if context else None,
                "pdf_url": context.pdf_url if context else None,
                "filing_type": result.filing_type,
            }
            
            # Determine sentiment from the feedback
            sentiment = None
            feedback_lower = feedback.lower()
            if any(word in feedback_lower for word in ["good", "correct", "accurate", "profit", "successful"]):
                sentiment = "positive"
            elif any(word in feedback_lower for word in ["bad", "wrong", "incorrect", "loss", "failed", "poor"]):
                sentiment = "negative"
            else:
                sentiment = "neutral"
            
            # Create the record
            record = await client.nseobservabilitylog.create(
                data={
                    "analysisType": "trade_loss_analysis",
                    "symbol": result.symbol,
                    "analysisPeriod": context.generated_at if context else None,
                    "prompt": prompt,
                    "response": raw_response,
                    "modelName": model_name,
                    "modelProvider": model_provider,
                    "tokenCount": token_count,
                    "latencyMs": latency_ms,
                    "contextData": json.dumps(context_data),
                    "summary": result.feedback_on_agent_performance[:500] if result.feedback_on_agent_performance else None,
                    "keyFindings": json.dumps([
                        result.trading_decision,
                        result.reasoning_of_nse_agent,
                        result.loss_incurred,
                    ]),
                    "sentiment": sentiment,
                    "riskFactors": json.dumps([result.loss_incurred]) if result.loss_incurred else None,
                    "recommendations": json.dumps([feedback]) if feedback else None,
                    "confidenceScore": result.confidence_score,
                    "dataFreshness": datetime.now(timezone.utc),
                    "triggeredBy": result.triggered_by,
                    "workerId": f"celery-observability-{os.getpid()}",
                    "status": "completed",
                    "metadata": json.dumps({
                        "trade_id": result.trade_id,
                        "signal_id": result.signal_id,
                        "analyzed_at": result.analyzed_at,
                        "source": result.source,
                    }),
                }
            )
            
            task_logger.info(f"💾 Saved observability analysis to DB for trade {result.trade_id[:8]} (record_id={record.id})")
            return record.id
            
    except Exception as exc:
        task_logger.error(f"❌ Failed to save observability result to DB: {exc}")
        return None


def save_observability_to_db_sync(
    result: ObservabilityAnalysisResult,
    context: "TradeObservabilityContext",
    prompt: str = "",
    raw_response: str = "",
    model_name: str = "gemini-2.0-flash",
    model_provider: str = "google",
    token_count: Optional[int] = None,
    latency_ms: Optional[int] = None,
) -> Optional[str]:
    """Synchronous wrapper for save_observability_to_db."""
    try:
        return asyncio.run(save_observability_to_db(
            result, context, prompt, raw_response, 
            model_name, model_provider, token_count, latency_ms
        ))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(save_observability_to_db(
                result, context, prompt, raw_response,
                model_name, model_provider, token_count, latency_ms
            ))
        finally:
            asyncio.set_event_loop(None)
            loop.close()


# ============================================================================
# PDF Download and Encoding
# ============================================================================

def download_pdf_as_base64(pdf_url: str, timeout: float = 30.0) -> Optional[str]:
    """
    Download PDF from URL and return as base64 encoded string.
    
    Args:
        pdf_url: URL to download PDF from
        timeout: Request timeout in seconds
        
    Returns:
        Base64 encoded PDF string, or None if download fails
    """
    if not pdf_url:
        task_logger.warning("No PDF URL provided for download")
        return None
    
    try:
        task_logger.info(f"📥 Downloading PDF from: {pdf_url[:80]}...")
        
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(pdf_url)
            response.raise_for_status()
            
            pdf_bytes = response.content
            pdf_base64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
            
            task_logger.info(f"✅ Downloaded PDF ({len(pdf_bytes)} bytes)")
            return pdf_base64
            
    except httpx.HTTPStatusError as exc:
        task_logger.error(f"❌ HTTP error downloading PDF: {exc.response.status_code}")
        return None
    except httpx.RequestError as exc:
        task_logger.error(f"❌ Request error downloading PDF: {exc}")
        return None
    except Exception as exc:
        task_logger.error(f"❌ Unexpected error downloading PDF: {exc}")
        return None


# ============================================================================
# Impact Data Loading
# ============================================================================

def get_filing_impact_data(filing_type: str) -> str:
    """
    Get positive/negative impact data for a filing type.
    
    Args:
        filing_type: The type of filing (e.g., "Outcome of Board Meeting")
        
    Returns:
        String describing positive and negative impacts
    """
    try:
        static_data_path = SERVER_ROOT / "pipelines" / "nse" / "staticdata.csv"
        
        if not static_data_path.exists():
            return f"Filing type: {filing_type}\nImpact data not available."
        
        import pandas as pd
        staticdf = pd.read_csv(static_data_path)
        match = staticdf[staticdf["file type"].str.lower() == filing_type.lower()]
        
        if not match.empty:
            pos_impact = str(match["positive impct "].values[0])
            neg_impact = str(match["negative impact"].values[0])
            return (
                f"Filing type: {filing_type}\n"
                f"Positive impact scenarios: {pos_impact}\n"
                f"Negative impact scenarios: {neg_impact}"
            )
        else:
            return f"Filing type: {filing_type}\nNo specific impact data available."
            
    except Exception as exc:
        task_logger.warning(f"Failed to load impact data: {exc}")
        return f"Filing type: {filing_type}\nImpact data loading failed."


# ============================================================================
# Prompt Configuration (loaded from YAML)
# ============================================================================

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Cache for prompt config
_cached_config: Optional[Dict[str, Any]] = None


def get_prompt_config() -> Dict[str, Any]:
    """Load and cache the observability agent prompt configuration from YAML."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    
    prompt_file = PROMPTS_DIR / "observability_agent.yaml"
    
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt config not found: {prompt_file}")
    
    import yaml
    with open(prompt_file, "r", encoding="utf-8") as f:
        _cached_config = yaml.safe_load(f) or {}
    
    task_logger.info(f"✅ Loaded prompt config from {prompt_file.name}")
    return _cached_config


async def analyze_trade_with_llm(
    context: TradeObservabilityContext,
    pdf_base64: Optional[str] = None,
) -> Optional[LLMAnalysisOutput]:
    """
    Analyze a losing trade using the Gemini LLM.
    
    Args:
        context: TradeObservabilityContext with all trade and signal information
        pdf_base64: Base64 encoded PDF of the filing (optional)
        
    Returns:
        LLMAnalysisOutput with result and metadata, or None if analysis fails
    """
    if not GEMINI_API_KEY:
        task_logger.error("❌ GEMINI_API_KEY not configured - cannot run observability analysis")
        return None
    
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage
        
        # Get model config from YAML or use defaults
        config = get_prompt_config()
        model_config = config.get("model", {})
        
        # Initialize the Gemini model
        model = ChatGoogleGenerativeAI(
            model=model_config.get("name", "gemini-2.5-flash"),
            google_api_key=GEMINI_API_KEY,
            temperature=model_config.get("temperature", 0.7),
            timeout=model_config.get("timeout", 120),
            max_retries=model_config.get("max_retries", 3),
        )
        
        # Get filing impact data
        impact_data = get_filing_impact_data(context.filing_type)
        
        # Build the human message content
        trade_signal_info = (
            f"Symbol: {context.symbol}\n"
            f"Signal: {context.signal_value} ({'BUY' if context.signal_value > 0 else 'SELL' if context.signal_value < 0 else 'HOLD'})\n"
            f"Confidence: {context.signal_confidence:.2%}\n"
            f"Side executed: {context.side}\n"
            f"Quantity: {context.quantity}\n"
            f"Entry price: ₹{context.entry_price:.2f}\n"
            f"Exit price: ₹{context.exit_price:.2f}"
        )
        
        loss_info = (
            f"Realized PnL: ₹{context.realized_pnl:.2f}\n"
            f"Triggered by: {context.triggered_by}\n"
            f"Trade delay: {context.trade_delay_ms}ms"
        )
        
        reasoning_info = context.signal_explanation or "No reasoning provided by the agent."
        
        # Get human message template from YAML
        human_template = config.get("human_message_template", "")
        if not human_template:
            raise ValueError("human_message_template not found in YAML config")
        
        human_text = human_template.format(
            impact_data=impact_data,
            trade_signal_info=trade_signal_info,
            loss_info=loss_info,
            reasoning_info=reasoning_info,
        )
        
        # Build message content
        content_parts = [
            {
                "type": "text",
                "text": human_text,
            }
        ]
        
        # Add PDF if available
        if pdf_base64:
            content_parts.append({
                "type": "file",
                "mime_type": "application/pdf",
                "data": pdf_base64,
            })
            task_logger.info("📄 Including PDF in analysis")
        else:
            task_logger.warning("⚠️ No PDF available for analysis")
        
        # Get system prompt from YAML config
        system_prompt = config.get("system_prompt", "")
        if not system_prompt:
            raise ValueError("system_prompt not found in YAML config")
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=content_parts),
        ]
        
        # Build full prompt for storage
        full_prompt = f"SYSTEM:\n{system_prompt}\n\nHUMAN:\n{human_text}"
        
        task_logger.info(f"🤖 Invoking Gemini for observability analysis of {context.symbol}...")
        
        # Track timing for latency
        import time
        start_time = time.time()
        
        # Invoke the model
        response = await asyncio.to_thread(model.invoke, messages)
        
        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)
        
        # Parse response
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # Store raw response before cleaning
        raw_response_text = response_text
        
        # Clean up response (remove any markdown artifacts)
        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        try:
            analysis_dict = json.loads(response_text)
        except json.JSONDecodeError as exc:
            task_logger.error(f"❌ Failed to parse LLM response as JSON: {exc}")
            task_logger.debug(f"Raw response: {response_text[:500]}")
            # Create a fallback result
            analysis_dict = {
                "trading_decision": f"{context.side} {context.quantity} shares of {context.symbol}",
                "timestamp_of_trade_execution": context.execution_time or context.generated_at,
                "reasoning_of_nse_agent": context.signal_explanation,
                "loss_incurred": f"₹{context.realized_pnl:.2f}",
                "feedback_on_agent_performance": f"LLM analysis failed to parse. Raw response: {response_text[:200]}",
            }
        
        # Build result
        result = ObservabilityAnalysisResult(
            trade_id=context.trade_id,
            signal_id=context.signal_id,
            symbol=context.symbol,
            trading_decision=analysis_dict.get("trading_decision", "Unknown"),
            timestamp_of_trade_execution=analysis_dict.get("timestamp_of_trade_execution", context.execution_time or ""),
            reasoning_of_nse_agent=analysis_dict.get("reasoning_of_nse_agent", context.signal_explanation),
            loss_incurred=analysis_dict.get("loss_incurred", f"₹{context.realized_pnl:.2f}"),
            feedback_on_agent_performance=analysis_dict.get("feedback_on_agent_performance", "Analysis not available"),
            filing_type=context.filing_type,
            confidence_score=context.signal_confidence,
            triggered_by=context.triggered_by,
        )
        
        # Get model name from config
        model_name = model_config.get("name", "gemini-2.5-flash")
        
        task_logger.info(f"✅ Observability analysis complete for {context.symbol} (latency={latency_ms}ms)")
        
        # Return extended output with metadata
        return LLMAnalysisOutput(
            result=result,
            prompt=full_prompt,
            raw_response=raw_response_text,
            model_name=model_name,
            model_provider="google",
            latency_ms=latency_ms,
            token_count=None,  # Could extract from response metadata if available
        )
        
    except ImportError as exc:
        task_logger.error(f"❌ Missing dependency for LLM analysis: {exc}")
        return None
    except Exception as exc:
        task_logger.exception(f"❌ Error during LLM analysis: {exc}")
        return None


# ============================================================================
# Trade Context Extraction
# ============================================================================

async def extract_trade_context(
    trade_id: str,
    triggered_by: str = "unknown",
) -> Optional[TradeObservabilityContext]:
    """
    Extract full context for a trade from the database.
    
    Args:
        trade_id: The ID of the trade to analyze
        triggered_by: What triggered this analysis (stop_loss, negative_pnl, etc.)
        
    Returns:
        TradeObservabilityContext or None if extraction fails
    """
    try:
        from db_context import get_db_connection
        
        async with get_db_connection() as client:
            # Fetch trade with execution logs
            trade = await client.trade.find_unique(
                where={"id": trade_id},
                include={
                    "executions": True,
                    "portfolio": True,
                    "agent": True,
                }
            )
            
            if not trade:
                task_logger.warning(f"Trade {trade_id} not found")
                return None
            
            # Parse metadata
            metadata = {}
            if trade.metadata:
                if isinstance(trade.metadata, dict):
                    metadata = trade.metadata
                elif isinstance(trade.metadata, str):
                    try:
                        metadata = json.loads(trade.metadata)
                    except json.JSONDecodeError:
                        pass
            
            # Extract prices
            entry_price = float(trade.price or 0)
            exit_price = float(trade.executed_price or entry_price)
            realized_pnl = float(trade.realized_pnl or 0)
            
            # Extract signal information from metadata
            signal_id = trade.signal_id or metadata.get("signal_id")
            signal_explanation = metadata.get("explanation", "")
            signal_confidence = float(trade.confidence or metadata.get("confidence", 0))
            
            # Extract filing information
            filing_type = metadata.get("filing_type", "")
            subject_of_announcement = metadata.get("subject_of_announcement", "")
            attachment_url = metadata.get("attachment_url", "")
            pdf_url = metadata.get("pdf_url", attachment_url)
            
            # Get trade delay from execution log
            trade_delay_ms = 0
            if trade.executions:
                for exec_log in trade.executions:
                    if exec_log.trade_delay:
                        trade_delay_ms = exec_log.trade_delay
                        break
            
            context = TradeObservabilityContext(
                trade_id=trade_id,
                symbol=trade.symbol,
                side=trade.side,
                quantity=trade.quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                signal_id=signal_id,
                signal_value=1 if trade.side == "BUY" else -1 if trade.side in ["SELL", "SHORT_SELL"] else 0,
                signal_confidence=signal_confidence,
                signal_explanation=signal_explanation,
                filing_time=metadata.get("filing_time", ""),
                generated_at=metadata.get("generated_at", ""),
                filing_type=filing_type,
                subject_of_announcement=subject_of_announcement,
                attachment_url=attachment_url,
                pdf_url=pdf_url,
                triggered_by=triggered_by,
                execution_time=trade.execution_time.isoformat() if trade.execution_time else None,
                trade_delay_ms=trade_delay_ms,
                agent_id=trade.agent_id,
                portfolio_id=trade.portfolio_id,
                metadata=metadata,
            )
            
            return context
            
    except Exception as exc:
        task_logger.exception(f"❌ Failed to extract trade context for {trade_id}: {exc}")
        return None


# ============================================================================
# Celery Tasks
# ============================================================================

@celery_app.task(
    bind=True,
    name="observability.analyze_losing_trade",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 2},
    soft_time_limit=180,  # 3 minutes (LLM can be slow)
    time_limit=240,       # 4 minutes hard limit
    acks_late=True,
)
def analyze_losing_trade_task(
    self,
    trade_id: str,
    triggered_by: str = "unknown",
    signal_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Celery task to analyze a losing trade from the NSE pipeline.
    
    This task is triggered when:
    1. A trade is closed with negative realized_pnl
    2. A stop-loss order is executed
    
    Args:
        trade_id: The ID of the trade to analyze
        triggered_by: What triggered this analysis ("stop_loss", "negative_pnl", "take_profit_miss")
        signal_context: Optional additional context about the original signal
        
    Returns:
        Dict with analysis results and publish status
    """
    task_logger.info(
        f"🔍 Starting observability analysis for trade {trade_id[:8]} "
        f"(triggered_by: {triggered_by})"
    )
    
    async def _analyze():
        # Extract trade context
        context = await extract_trade_context(trade_id, triggered_by)
        
        if not context:
            return {
                "success": False,
                "error": "Failed to extract trade context",
                "trade_id": trade_id,
            }
        
        # Merge any additional signal context
        if signal_context:
            if signal_context.get("explanation"):
                context.signal_explanation = signal_context["explanation"]
            if signal_context.get("pdf_url"):
                context.pdf_url = signal_context["pdf_url"]
            if signal_context.get("filing_type"):
                context.filing_type = signal_context["filing_type"]
        
        # Skip if not actually a loss
        if context.realized_pnl >= 0 and triggered_by != "stop_loss":
            task_logger.info(
                f"⏭️ Skipping analysis for trade {trade_id[:8]} - "
                f"PnL is not negative (₹{context.realized_pnl:.2f})"
            )
            return {
                "success": True,
                "skipped": True,
                "reason": "Trade is not a loss",
                "trade_id": trade_id,
                "realized_pnl": context.realized_pnl,
            }
        
        # Download PDF if available
        pdf_base64 = None
        if context.pdf_url:
            pdf_base64 = download_pdf_as_base64(context.pdf_url)
        
        # Run LLM analysis
        llm_output = await analyze_trade_with_llm(context, pdf_base64)
        
        if not llm_output:
            return {
                "success": False,
                "error": "LLM analysis failed",
                "trade_id": trade_id,
            }
        
        # Save to database instead of Kafka
        record_id = await save_observability_to_db(
            result=llm_output.result,
            context=context,
            prompt=llm_output.prompt,
            raw_response=llm_output.raw_response,
            model_name=llm_output.model_name,
            model_provider=llm_output.model_provider,
            token_count=llm_output.token_count,
            latency_ms=llm_output.latency_ms,
        )
        
        return {
            "success": True,
            "trade_id": trade_id,
            "symbol": context.symbol,
            "realized_pnl": context.realized_pnl,
            "triggered_by": triggered_by,
            "analysis_summary": llm_output.result.feedback_on_agent_performance[:200] + "..." 
                if len(llm_output.result.feedback_on_agent_performance) > 200 
                else llm_output.result.feedback_on_agent_performance,
            "saved_to_db": record_id is not None,
            "record_id": record_id,
        }
    
    # Run async function
    try:
        return asyncio.run(_analyze())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_analyze())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


@celery_app.task(
    bind=True,
    name="observability.batch_analyze_losses",
    soft_time_limit=600,  # 10 minutes
    time_limit=720,       # 12 minutes hard limit
)
def batch_analyze_losses_task(
    self,
    lookback_hours: int = 24,
    max_trades: int = 50,
) -> Dict[str, Any]:
    """
    Batch analyze recent losing trades for observability.
    
    This can be scheduled to run periodically to catch any missed analyses.
    
    Args:
        lookback_hours: How far back to look for losing trades
        max_trades: Maximum number of trades to analyze in one batch
        
    Returns:
        Dict with batch analysis summary
    """
    from datetime import timedelta
    
    task_logger.info(
        f"🔍 Starting batch loss analysis (lookback: {lookback_hours}h, max: {max_trades})"
    )
    
    async def _batch_analyze():
        from db_context import get_db_connection
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        
        async with get_db_connection() as client:
            # Find losing trades from NSE pipeline
            losing_trades = await client.trade.find_many(
                where={
                    "source": {"contains": "nse"},
                    "status": "executed",
                    "realized_pnl": {"lt": 0},
                    "updated_at": {"gte": cutoff_time},
                },
                order={"updated_at": "desc"},
                take=max_trades,
            )
            
            task_logger.info(f"Found {len(losing_trades)} losing trades to analyze")
            
            analyzed = 0
            failed = 0
            
            for trade in losing_trades:
                try:
                    # Queue individual analysis
                    analyze_losing_trade_task.delay(
                        trade_id=trade.id,
                        triggered_by="batch_analysis",
                    )
                    analyzed += 1
                except Exception as exc:
                    task_logger.warning(f"Failed to queue analysis for {trade.id}: {exc}")
                    failed += 1
            
            return {
                "success": True,
                "total_found": len(losing_trades),
                "queued_for_analysis": analyzed,
                "failed_to_queue": failed,
                "lookback_hours": lookback_hours,
            }
    
    try:
        return asyncio.run(_batch_analyze())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_batch_analyze())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


# ============================================================================
# Helper function to trigger analysis from other modules
# ============================================================================

def trigger_loss_analysis(
    trade_id: str,
    triggered_by: str,
    signal_context: Optional[Dict[str, Any]] = None,
    priority: int = 5,
) -> None:
    """
    Trigger observability analysis for a losing trade.
    
    This is called from the streaming order monitor when:
    1. Stop-loss is executed
    2. Trade is closed with negative PnL
    
    Args:
        trade_id: The ID of the trade to analyze
        triggered_by: What triggered this ("stop_loss", "negative_pnl", etc.)
        signal_context: Optional context from the original signal
        priority: Celery task priority (default 5, lower = higher priority)
    """
    try:
        analyze_losing_trade_task.apply_async(
            args=[trade_id, triggered_by],
            kwargs={"signal_context": signal_context},
            queue=QUEUE_NAMES.get("general", "general"),
            priority=priority,
        )
        task_logger.info(
            f"📤 Queued observability analysis for trade {trade_id[:8]} "
            f"(triggered_by: {triggered_by})"
        )
    except Exception as exc:
        task_logger.error(f"❌ Failed to queue observability analysis: {exc}")


# ============================================================================
# Module exports
# ============================================================================

__all__ = [
    "TradeObservabilityContext",
    "ObservabilityAnalysisResult",
    "LLMAnalysisOutput",
    "analyze_losing_trade_task",
    "batch_analyze_losses_task",
    "trigger_loss_analysis",
    "publish_observability_result",
    "save_observability_to_db",
    "save_observability_to_db_sync",
]
