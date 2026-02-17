"""
Low Risk Observability Agent Tasks

This module implements an observability agent that monitors the low risk portfolio
allocation pipeline and analyzes drawdowns to provide actionable feedback.

The agent:
1. Receives drawdown alerts with portfolio context
2. Analyzes stock and industry selection reasoning
3. Compares against quantitative metrics
4. Generates structured feedback for pipeline improvement
5. Publishes analysis to Kafka for monitoring/alerting

Trigger conditions (to be configured by caller):
- Maximum drawdown threshold exceeded
- Significant price drops in portfolio holdings
- Rebalancing round completion with negative performance
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml
from celery.utils.log import get_task_logger
from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, Field

# Initialize Phoenix tracing for low risk observability
try:
    from phoenix.otel import register
    
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="low-risk-observability",
            endpoint=collector_endpoint,
            auto_instrument=True,
        )
        print(f"✅ Phoenix tracing initialized for low risk observability: {collector_endpoint}")
except ImportError:
    pass
except Exception:
    pass

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
LOW_RISK_OBSERVABILITY_KAFKA_TOPIC = os.getenv(
    "LOW_RISK_OBSERVABILITY_TOPIC", "low_risk_agent_observability_logs"
)
LOW_RISK_OBSERVABILITY_PUBLISHER_NAME = "low_risk_observability_publisher"

# ============================================================================
# Data Models
# ============================================================================


@dataclass
class LowRiskDrawdownContext:
    """Context for observability analysis of low risk portfolio drawdown."""

    # Drawdown information
    max_drawdown: float  # Percentage drawdown that triggered alert
    drawdown_threshold: float = 0.05  # Default 5% threshold

    # Portfolio composition
    portfolio_composition: Dict[str, float] = field(default_factory=dict)  # {symbol: weight}
    industry_allocation: Dict[str, float] = field(default_factory=dict)  # {industry: weight}

    # Stock drops - list of tuples (symbol, % drop)
    stock_drops: List[Tuple[str, float]] = field(default_factory=list)

    # Quantitative metrics
    stock_metrics: Dict[str, Any] = field(default_factory=dict)
    industry_metrics: Dict[str, Any] = field(default_factory=dict)

    # Agent reasoning
    stock_selector_reasoning: str = ""
    industry_selector_reasoning: str = ""
    previous_rebalancing_reasoning: Optional[str] = None

    # Metadata
    portfolio_id: Optional[str] = None
    user_id: Optional[str] = None
    task_id: Optional[str] = None
    triggered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class LowRiskObservabilityResult(BaseModel):
    """Structured result from the low risk observability agent analysis."""

    # Identifiers
    portfolio_id: Optional[str] = None
    user_id: Optional[str] = None

    # Input echo
    max_drawdown_value: float = Field(description="Maximum drawdown that triggered alert")
    portfolio_composition: Dict[str, Any] = Field(
        default_factory=dict, description="Portfolio allocation at time of drawdown"
    )

    # Reasoning analysis
    stock_allocator_reasoning: str = Field(
        default="", description="Original reasoning from stock allocator"
    )
    industry_allocator_reasoning: str = Field(
        default="", description="Original reasoning from industry allocator"
    )
    previous_rebalancing_reasoning: Optional[str] = Field(
        default=None, description="Reasoning from previous rebalancing if available"
    )

    # Feedback
    stock_selector_feedback: str = Field(
        default="", description="Detailed feedback on stock selector reasoning"
    )
    industry_selector_feedback: str = Field(
        default="", description="Detailed feedback on industry selector reasoning"
    )

    # Recommendations
    prompt_improvement_suggestions: List[Dict[str, Any]] = Field(
        default_factory=list, description="Suggestions to improve agent prompts"
    )
    guardrail_recommendations: List[Dict[str, Any]] = Field(
        default_factory=list, description="Recommended guardrails to add"
    )
    priority_actions: List[Dict[str, Any]] = Field(
        default_factory=list, description="Priority-ordered action items"
    )

    # Root cause
    root_cause_analysis: str = Field(
        default="", description="Deep analysis of what caused the drawdown"
    )

    # Metadata
    analyzed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: str = "low_risk_observability_agent"


# ============================================================================
# Kafka Publisher
# ============================================================================

_low_risk_observability_publisher: Optional[KafkaPublisher] = None


def _get_observability_publisher() -> KafkaPublisher:
    """Get or create Kafka publisher for low risk observability logs."""
    global _low_risk_observability_publisher

    if _low_risk_observability_publisher is not None:
        return _low_risk_observability_publisher

    bus = default_kafka_bus
    try:
        _low_risk_observability_publisher = bus.register_publisher(
            LOW_RISK_OBSERVABILITY_PUBLISHER_NAME,
            topic=LOW_RISK_OBSERVABILITY_KAFKA_TOPIC,
            value_model=LowRiskObservabilityResult,
            default_headers={"stream": "low_risk_observability"},
        )
        task_logger.info(
            f"✅ Registered Kafka publisher for {LOW_RISK_OBSERVABILITY_KAFKA_TOPIC}"
        )
    except PublisherAlreadyRegistered:
        _low_risk_observability_publisher = bus.get_publisher(
            LOW_RISK_OBSERVABILITY_PUBLISHER_NAME
        )
        task_logger.debug(
            f"Using existing Kafka publisher for {LOW_RISK_OBSERVABILITY_KAFKA_TOPIC}"
        )

    return _low_risk_observability_publisher


def publish_observability_result(result: LowRiskObservabilityResult) -> bool:
    """Publish low risk observability analysis result to Kafka."""
    try:
        publisher = _get_observability_publisher()
        payload = result.model_dump()
        key = result.portfolio_id or result.user_id or "unknown"
        publisher.publish(payload, key=key)
        task_logger.info(
            f"📤 Published low risk observability analysis to Kafka (drawdown: {result.max_drawdown_value:.2%})"
        )
        return True
    except Exception as exc:
        task_logger.error(f"❌ Failed to publish low risk observability result: {exc}")
        return False


# ============================================================================
# Prompt Configuration (loaded from YAML)
# ============================================================================

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Cache for prompt config
_cached_config: Optional[Dict[str, Any]] = None


def _load_prompt_config() -> Dict[str, Any]:
    """Load the low risk observability agent prompt configuration from YAML."""
    prompt_file = PROMPTS_DIR / "low_risk_observability_agent.yaml"

    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt config not found: {prompt_file}")

    with open(prompt_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    task_logger.info(f"✅ Loaded prompt config from {prompt_file.name}")
    return config


def get_prompt_config() -> Dict[str, Any]:
    """Get cached prompt configuration."""
    global _cached_config
    if _cached_config is None:
        _cached_config = _load_prompt_config()
    return _cached_config


def _render_template(template: str, **kwargs) -> str:
    """Render a Jinja2 template with provided variables."""
    env = Environment(undefined=StrictUndefined)
    jinja_template = env.from_string(template)
    return jinja_template.render(**kwargs)


# ============================================================================
# LLM Analysis
# ============================================================================


async def analyze_drawdown_with_llm(
    context: LowRiskDrawdownContext,
) -> Optional[LowRiskObservabilityResult]:
    """
    Analyze a low risk portfolio drawdown using the Gemini LLM with Google Search.

    Args:
        context: LowRiskDrawdownContext with all portfolio and reasoning information

    Returns:
        LowRiskObservabilityResult or None if analysis fails
    """
    if not GEMINI_API_KEY:
        task_logger.error(
            "❌ GEMINI_API_KEY not configured - cannot run low risk observability analysis"
        )
        return None

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_core.messages import SystemMessage, HumanMessage

        # Get config from YAML
        config = get_prompt_config()
        model_config = config.get("model", {})

        # Initialize the Gemini model with Google Search tool
        model = ChatGoogleGenerativeAI(
            model=model_config.get("name", "gemini-2.5-flash"),
            google_api_key=GEMINI_API_KEY,
            temperature=model_config.get("temperature", 0.7),
            timeout=model_config.get("timeout_seconds", 120),
            max_retries=model_config.get("max_retries", 3),
        )

        # Bind Google Search tool if specified
        if "google_search" in model_config.get("tools", []):
            model = model.bind_tools([{"google_search": {}}])

        # Get prompts from config
        system_prompt = config.get("system_prompt", "")
        human_template = config.get("human_message_template", "")

        # Render human message with context
        human_message = _render_template(
            human_template,
            drawdown_max=f"{context.max_drawdown:.2%}",
            portfolio_comp=json.dumps(context.portfolio_composition, indent=2),
            quant_stocks=json.dumps(context.stock_metrics, indent=2),
            quant_industries=json.dumps(context.industry_metrics, indent=2),
            reason_stock=context.stock_selector_reasoning,
            reason_industry=context.industry_selector_reasoning,
            stock_drop=str(context.stock_drops),
            previous_rebalancing_reasoning=context.previous_rebalancing_reasoning,
        )

        # Build messages
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]

        task_logger.info(
            f"🔍 Analyzing low risk drawdown ({context.max_drawdown:.2%}) with Gemini..."
        )

        # Invoke the model
        response = model.invoke(messages)
        response_text = (
            response.content if hasattr(response, "content") else str(response)
        )

        # Parse the JSON response
        result = _parse_llm_response(response_text, context)

        if result:
            task_logger.info("✅ Successfully analyzed low risk drawdown")
        else:
            task_logger.warning("⚠️ Failed to parse LLM response")

        return result

    except Exception as exc:
        task_logger.error(f"❌ Error analyzing drawdown with LLM: {exc}", exc_info=True)
        return None


def _parse_llm_response(
    response_text: str, context: LowRiskDrawdownContext
) -> Optional[LowRiskObservabilityResult]:
    """Parse the LLM response into a structured result."""
    try:
        # Clean response - remove markdown code blocks if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)

        # Parse JSON
        data = json.loads(cleaned)

        # Build result
        result = LowRiskObservabilityResult(
            portfolio_id=context.portfolio_id,
            user_id=context.user_id,
            max_drawdown_value=context.max_drawdown,
            portfolio_composition={
                "stocks": context.portfolio_composition,
                "industries": context.industry_allocation,
            },
            stock_allocator_reasoning=data.get(
                "stock_allocator_reasoning", context.stock_selector_reasoning
            ),
            industry_allocator_reasoning=data.get(
                "industry_allocator_reasoning", context.industry_selector_reasoning
            ),
            previous_rebalancing_reasoning=data.get("previous_rebalancing_reasoning"),
            stock_selector_feedback=data.get("stock_selector_feedback", ""),
            industry_selector_feedback=data.get("industry_selector_feedback", ""),
            prompt_improvement_suggestions=data.get("prompt_improvement_suggestions", []),
            guardrail_recommendations=data.get("guardrail_recommendations", []),
            priority_actions=data.get("priority_actions", []),
            root_cause_analysis=data.get("root_cause_analysis", ""),
        )

        return result

    except json.JSONDecodeError as exc:
        task_logger.error(f"❌ Failed to parse LLM response as JSON: {exc}")
        task_logger.debug(f"Raw response: {response_text[:500]}...")
        return None
    except Exception as exc:
        task_logger.error(f"❌ Error parsing LLM response: {exc}")
        return None


# ============================================================================
# Celery Tasks
# ============================================================================


@celery_app.task(
    name="observability.analyze_low_risk_drawdown",
    bind=True,
    queue=QUEUE_NAMES["general"],
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=300,  # 5 minutes
    time_limit=360,  # 6 minutes hard limit
)
def analyze_low_risk_drawdown_task(
    self,
    max_drawdown: float,
    portfolio_composition: Dict[str, float],
    industry_allocation: Dict[str, float],
    stock_drops: List[Tuple[str, float]],
    stock_metrics: Dict[str, Any],
    industry_metrics: Dict[str, Any],
    stock_selector_reasoning: str,
    industry_selector_reasoning: str,
    previous_rebalancing_reasoning: Optional[str] = None,
    portfolio_id: Optional[str] = None,
    user_id: Optional[str] = None,
    task_id: Optional[str] = None,
    publish_to_kafka: bool = True,
) -> Dict[str, Any]:
    """
    Celery task to analyze low risk portfolio drawdown.

    Args:
        max_drawdown: Maximum drawdown percentage that triggered alert
        portfolio_composition: Dict of {symbol: weight}
        industry_allocation: Dict of {industry: weight}
        stock_drops: List of (symbol, % drop) tuples
        stock_metrics: Quantitative metrics for stocks
        industry_metrics: Quantitative metrics for industries
        stock_selector_reasoning: Original reasoning from stock selector
        industry_selector_reasoning: Original reasoning from industry selector
        previous_rebalancing_reasoning: Reasoning from previous rebalancing (optional)
        portfolio_id: Portfolio identifier
        user_id: User identifier
        task_id: Celery task ID
        publish_to_kafka: Whether to publish results to Kafka

    Returns:
        Dict with analysis results
    """
    task_logger.info(
        f"📊 Starting low risk drawdown analysis (drawdown: {max_drawdown:.2%})"
    )

    # Build context
    context = LowRiskDrawdownContext(
        max_drawdown=max_drawdown,
        portfolio_composition=portfolio_composition,
        industry_allocation=industry_allocation,
        stock_drops=stock_drops,
        stock_metrics=stock_metrics,
        industry_metrics=industry_metrics,
        stock_selector_reasoning=stock_selector_reasoning,
        industry_selector_reasoning=industry_selector_reasoning,
        previous_rebalancing_reasoning=previous_rebalancing_reasoning,
        portfolio_id=portfolio_id,
        user_id=user_id,
        task_id=task_id or self.request.id,
    )

    try:
        # Run async analysis in event loop
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(analyze_drawdown_with_llm(context))

        if result is None:
            task_logger.warning("⚠️ Low risk drawdown analysis returned no result")
            return {
                "success": False,
                "error": "Analysis returned no result",
                "max_drawdown": max_drawdown,
            }

        # Publish to Kafka if enabled
        if publish_to_kafka:
            publish_observability_result(result)

        task_logger.info(
            f"✅ Completed low risk drawdown analysis (drawdown: {max_drawdown:.2%})"
        )

        return {
            "success": True,
            "analysis": result.model_dump(),
            "max_drawdown": max_drawdown,
            "published_to_kafka": publish_to_kafka,
        }

    except Exception as exc:
        task_logger.error(
            f"❌ Low risk drawdown analysis failed: {exc}", exc_info=True
        )

        # Retry on transient failures
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        return {
            "success": False,
            "error": str(exc),
            "max_drawdown": max_drawdown,
        }


# ============================================================================
# Helper Functions for Triggering
# ============================================================================


def trigger_low_risk_drawdown_analysis(
    max_drawdown: float,
    portfolio_composition: Dict[str, float],
    industry_allocation: Dict[str, float],
    stock_drops: List[Tuple[str, float]],
    stock_metrics: Dict[str, Any],
    industry_metrics: Dict[str, Any],
    stock_selector_reasoning: str,
    industry_selector_reasoning: str,
    previous_rebalancing_reasoning: Optional[str] = None,
    portfolio_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """
    Trigger low risk drawdown analysis asynchronously via Celery.

    Returns:
        Celery task ID
    """
    task = analyze_low_risk_drawdown_task.delay(
        max_drawdown=max_drawdown,
        portfolio_composition=portfolio_composition,
        industry_allocation=industry_allocation,
        stock_drops=stock_drops,
        stock_metrics=stock_metrics,
        industry_metrics=industry_metrics,
        stock_selector_reasoning=stock_selector_reasoning,
        industry_selector_reasoning=industry_selector_reasoning,
        previous_rebalancing_reasoning=previous_rebalancing_reasoning,
        portfolio_id=portfolio_id,
        user_id=user_id,
        publish_to_kafka=True,
    )
    task_logger.info(f"🚀 Triggered low risk drawdown analysis task: {task.id}")
    return task.id
