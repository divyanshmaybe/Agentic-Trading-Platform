"""
Industry Selection Pipeline

Combines macro regime classification with LLM-based industry selection.
Uses PMI and CPI data to classify economic regime, then uses an LLM agent
with industry metrics tool to suggest optimal industry allocations.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent

from utils.economic_indicators_storage import EconomicIndicatorsStorage, get_storage
from utils.low_risk_utils import (
    load_prompt_from_template,
    render_prompt_template,
    clean_and_parse_agent_json_response,
    validate_percentage_list,
    publish_to_kafka,
)
from .industry_indicators_pipeline import IndustryIndicatorsPipeline

# Initialize Phoenix tracing for industry pipeline
try:
    from phoenix.otel import register
    
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="industry-pipeline",
            endpoint=collector_endpoint,
            auto_instrument=True
        )
        print(f"✅ Phoenix tracing initialized for industry pipeline: {collector_endpoint}")
    else:
        print("⚠️ COLLECTOR_ENDPOINT not set, Phoenix tracing disabled for industry pipeline")
except ImportError:
    print("⚠️ Phoenix not installed, tracing disabled for industry pipeline")
except Exception as e:
    print(f"⚠️ Failed to initialize Phoenix tracing for industry pipeline: {e}")

# LangSmith tracing (optional - can run alongside Phoenix)
langsmith_api_key = os.getenv("LANGSMITH_API_KEY", "")
if langsmith_api_key:
    os.environ["LANGSMITH_API_KEY"] = langsmith_api_key
    os.environ["LANGSMITH_TRACING_V2"] = "true"
    os.environ["LANGSMITH_PROJECT"] = "portfolio_prod"
    print("🔍 LangSmith tracing also enabled")

logger = logging.getLogger(__name__)


def classify_macro_regime(pmi_val: float, cpi_list: List[float]) -> str:
    """
    Classifies the economic regime based on PMI (Growth) and CPI (Inflation).

    Logic based on the Investment Clock:
    1. RECOVERY:    Growth > 50 (Expansion) | Inflation Falling
    2. OVERHEATING: Growth > 50 (Expansion) | Inflation Rising
    3. STAGFLATION: Growth < 50 (Contraction) | Inflation Rising
    4. RECESSION:   Growth < 50 (Contraction) | Inflation Falling

    Args:
        pmi_val: Current Manufacturing PMI value
        cpi_list: List of CPI values (at least 13 months needed)

    Returns:
        Regime classification: "RECOVERY", "OVERHEATING", "STAGFLATION", or "RECESSION"
    """
    if len(cpi_list) < 13:
        logger.warning(
            f"CPI list has only {len(cpi_list)} values, need at least 13 for YoY calculation"
        )
        # Use available data if possible
        if len(cpi_list) < 2:
            logger.error("Insufficient CPI data for regime classification")
            return "RECESSION"  # Default to conservative

    # Calculate CPI year-over-year growth rate
    # Compare last value with value 12 months ago (index -13)
    current_cpi = cpi_list[-1]
    year_ago_cpi = cpi_list[-13] if len(cpi_list) >= 13 else cpi_list[0]

    if year_ago_cpi == 0:
        logger.warning("Year-ago CPI is zero, cannot calculate growth rate")
        inflation_rising = False
    else:
        cpi_year_growth_rate = (current_cpi - year_ago_cpi) / year_ago_cpi
        inflation_rising = cpi_year_growth_rate > 0

    growth_expanding = pmi_val > 50

    if growth_expanding and not inflation_rising:
        return "RECOVERY"
    elif growth_expanding and inflation_rising:
        return "OVERHEATING"
    elif not growth_expanding and inflation_rising:
        return "STAGFLATION"
    else:
        return "RECESSION"


def get_pmi(storage: EconomicIndicatorsStorage) -> float:
    """
    Extract Manufacturing PMI value from trading economics data.

    Args:
        storage: EconomicIndicatorsStorage instance

    Returns:
        PMI value as float

    Raises:
        ValueError: If PMI data not found
    """
    df = storage.read_indicators_df("trading_economics")
    if df is None or df.empty:
        raise ValueError("Trading economics data not found or empty")

    # Filter for Manufacturing PMI
    # The indicator column might have variations like "Manufacturing PMI", "PMI Manufacturing", etc.
    pmi_mask = df["indicator"].str.contains("PMI", case=False, na=False) & df[
        "indicator"
    ].str.contains("Manufacturing", case=False, na=False)

    pmi_rows = df[pmi_mask]
    if pmi_rows.empty:
        # Try just "PMI" if Manufacturing not found
        pmi_mask = df["indicator"].str.contains("PMI", case=False, na=False)
        pmi_rows = df[pmi_mask]

    if pmi_rows.empty:
        raise ValueError(
            f"Manufacturing PMI not found in trading economics data. Available indicators: {df['indicator'].unique()[:10].tolist()}"
        )

    # Get the latest PMI value from "last" column
    latest_pmi_row = pmi_rows.iloc[0]  # Take first match
    pmi_str = str(latest_pmi_row.get("last", "")).strip()

    # Clean the value (remove commas, %, etc.)
    pmi_str = re.sub(r"[,\s%]", "", pmi_str)

    try:
        pmi_val = float(pmi_str)
        msg = f"✓ Extracted PMI value: {pmi_val}"
        logger.info(msg)
        return pmi_val
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Failed to parse PMI value '{pmi_str}' as float: {e}"
        )


def get_cpi_list(storage: EconomicIndicatorsStorage) -> List[float]:
    """
    Extract CPI values from CPI data, sorted by date.

    Args:
        storage: EconomicIndicatorsStorage instance

    Returns:
        List of CPI values as floats, sorted chronologically (oldest to newest)

    Raises:
        ValueError: If CPI data not found or cannot be parsed
    """
    df = storage.read_indicators_df("cpi")
    if df is None or df.empty:
        raise ValueError("CPI data not found or empty")

    # Filter for All India data if State column exists
    if "State" in df.columns:
        df = df[df["State"].str.upper().str.contains("ALL INDIA", na=False)]
        if df.empty:
            raise ValueError("No All India CPI data found")
        logger.info(f"✓ Filtered to {len(df)} All India CPI records")

    # Check if we have Year, Month, Combined columns (actual CPI data structure)
    if "Year" in df.columns and "Month" in df.columns and "Combined" in df.columns:
        # Create datetime from Year and Month
        month_map = {
            "January": 1, "February": 2, "March": 3, "April": 4,
            "May": 5, "June": 6, "July": 7, "August": 8,
            "September": 9, "October": 10, "November": 11, "December": 12
        }

        df["date"] = pd.to_datetime(
            df["Year"].astype(str) + "-" + df["Month"].map(month_map).astype(str) + "-01",
            format="%Y-%m-%d"
        )
        df = df.sort_values("date")

        # Extract Combined CPI values
        cpi_values = df["Combined"].astype(float).tolist()

        msg = f"✓ Extracted {len(cpi_values)} CPI values (range: {min(cpi_values):.2f} to {max(cpi_values):.2f})"
        logger.info(msg)
        return cpi_values

    # Fallback: Try to identify date and value columns
    date_col = None
    value_col = None

    for col in df.columns:
        col_lower = col.lower()
        if "date" in col_lower or "period" in col_lower:
            date_col = col
        if "value" in col_lower or "index" in col_lower or "cpi" in col_lower:
            value_col = col

    if date_col is None or value_col is None:
        logger.warning(
            f"Could not find date/value columns. Available columns: {df.columns.tolist()}"
        )
        if "CPI" in df.columns:
            value_col = "CPI"
        elif "Index" in df.columns:
            value_col = "Index"
        elif len(df.columns) >= 2:
            date_col = df.columns[0]
            value_col = df.columns[1]

    if value_col is None:
        raise ValueError(
            f"Cannot identify value column in CPI data. Columns: {df.columns.tolist()}"
        )

    # Sort by date if available
    if date_col:
        try:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.sort_values(date_col).dropna(subset=[value_col])
        except Exception as e:
            logger.warning(f"Could not parse dates, using original order: {e}")
            df = df.dropna(subset=[value_col])
    else:
        df = df.dropna(subset=[value_col])

    # Extract values as floats
    cpi_values = []
    for val in df[value_col]:
        try:
            val_str = str(val).strip().replace(",", "")
            cpi_val = float(val_str)
            cpi_values.append(cpi_val)
        except (ValueError, TypeError):
            logger.warning(f"Skipping invalid CPI value: {val}")
            continue

    if not cpi_values:
        raise ValueError("No valid CPI values found in data")

    msg = f"✓ Extracted {len(cpi_values)} CPI values (range: {min(cpi_values):.2f} to {max(cpi_values):.2f})"
    logger.info(msg)
    return cpi_values


def create_industry_metrics_tool(
    pipeline: IndustryIndicatorsPipeline,
) -> Any:
    """
    Create the industry_metrics tool function that can be used by the LLM agent.

    Args:
        pipeline: IndustryIndicatorsPipeline instance (must have computed data)

    Returns:
        Tool function decorated with @tool
    """

    @tool
    def industry_metrics(industries: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Get industry-specific metrics for the given industries.

        Input:
        - industries: list of industries to get metrics for

        Output:
        dictionary containing metrics for each industry.

        The dictionary has each industry as key and a dictionary of metrics as value.
        The dictionary of metrics has the following keys:
        "pct_above_ema50",
        "pct_above_ema200",
        "median_rsi",
        "pct_rsi_overbought",
        "pct_rsi_oversold",
        "industry_ret_6m",
        "benchmark_ret_6m"
        """
        try:
            # Get industry indicators from pipeline
            df = pipeline.get_industry_indicators(industries)

            if df.is_empty():
                logger.warning(f"No data found for industries: {industries}")
                return {}

            # Convert Polars DataFrame to dict format
            # Get benchmark return from the first row (should be same for all)
            benchmark_ret_6m = None
            if "benchmark_ret_6m" in df.columns and not df["benchmark_ret_6m"].is_null().all():
                benchmark_ret_6m = df["benchmark_ret_6m"][0]

            # Build result dictionary
            result = {}
            for row in df.iter_rows(named=True):
                industry = row.get("industry", "Unknown")
                result[industry] = {
                    "pct_above_ema50": row.get("pct_above_ema50"),
                    "pct_above_ema200": row.get("pct_above_ema200"),
                    "median_rsi": row.get("median_rsi"),
                    "pct_rsi_overbought": row.get("pct_rsi_overbought"),
                    "pct_rsi_oversold": row.get("pct_rsi_oversold"),
                    "industry_ret_6m": row.get("industry_ret_6m"),
                    "benchmark_ret_6m": benchmark_ret_6m,
                }

            return result
        except Exception as e:
            logger.error(f"Error in industry_metrics tool: {e}", exc_info=True)
            return {}

    return industry_metrics

def industry_metrics_callable(industries: List[str], pipeline) -> Dict[str, Dict[str, Any]]:
    """
    Get industry-specific metrics for the given industries.

    Input:
    - industries: list of industries to get metrics for

    Output:
    dictionary containing metrics for each industry.

    The dictionary has each industry as key and a dictionary of metrics as value.
    The dictionary of metrics has the following keys:
    "pct_above_ema50",
    "pct_above_ema200",
    "median_rsi",
    "pct_rsi_overbought",
    "pct_rsi_oversold",
    "industry_ret_6m",
    "benchmark_ret_6m"
    """
    try:
        # Get industry indicators from pipeline
        df = pipeline.get_industry_indicators(industries)

        if df.is_empty():
            logger.warning(f"No data found for industries: {industries}")
            return {}

        # Convert Polars DataFrame to dict format
        # Get benchmark return from the first row (should be same for all)
        benchmark_ret_6m = None
        if "benchmark_ret_6m" in df.columns and not df["benchmark_ret_6m"].is_null().all():
            benchmark_ret_6m = df["benchmark_ret_6m"][0]

        # Build result dictionary
        result = {}
        for row in df.iter_rows(named=True):
            industry = row.get("industry", "Unknown")
            result[industry] = {
                "pct_above_ema50": row.get("pct_above_ema50"),
                "pct_above_ema200": row.get("pct_above_ema200"),
                "median_rsi": row.get("median_rsi"),
                "pct_rsi_overbought": row.get("pct_rsi_overbought"),
                "pct_rsi_oversold": row.get("pct_rsi_oversold"),
                "industry_ret_6m": row.get("industry_ret_6m"),
                "benchmark_ret_6m": benchmark_ret_6m,
            }

        return result
    except Exception as e:
        logger.error(f"Error in industry_metrics tool: {e}", exc_info=True)
        return {}


def create_industry_selection_agent(
    pipeline: IndustryIndicatorsPipeline,
    gemini_api_key: str,
    economic_regime: str,
    cpi_val: float,
    pmi_val: float,
    rebalance: bool = False,
    prev_ind_list: list[Dict[str, Any]] = []
) -> Any:
    """
    Create an LLM agent for industry selection with tools.

    Args:
        pipeline: IndustryIndicatorsPipeline instance
        gemini_api_key: Gemini API key
        economic_regime: Economic regime string (lowercase)
        cpi_val: Current CPI value
        pmi_val: Current PMI value

    Returns:
        Agent executor or callable agent
    """
    # Create tool
    industry_metrics_tool = create_industry_metrics_tool(pipeline)

    # Load and render prompt template
    prompt_template = load_prompt_from_template("industry_selector_prompt.yaml")
    rendered_prompt = render_prompt_template(
        prompt_template,
        rebalance=rebalance,
        prev_ind_list=json.dumps(prev_ind_list, indent=4),
        economic_regime=economic_regime.lower(),
        cpi_val=cpi_val,
        pmi_val=pmi_val,
    )

    # Create LLM
    gemini2 = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=gemini_api_key,
        temperature=0.5,
    )
    agent = create_agent(
        model=gemini2,
        tools=[industry_metrics_tool],
        system_prompt=SystemMessage(rendered_prompt)
    )
    return agent


def industry_selector(
    pipeline: IndustryIndicatorsPipeline,
    economic_regime: str,
    cpi_val: float,
    pmi_val: float,
    gemini_api_key: str,
    user_id: str,
    task_id: Optional[str] = None,
    rebalance: bool = False,
    prev_ind_list: list[Dict[str, Any]] = [],
) -> List[Dict[str, Any]]:
    """
    Select industries using LLM agent based on economic regime.

    Args:
        pipeline: IndustryIndicatorsPipeline instance (must have computed data)
        economic_regime: Economic regime classification
        cpi_val: Current CPI value
        pmi_val: Current PMI value
        gemini_api_key: Gemini API key
        user_id: User identifier for Kafka messages
        task_id: Celery task ID for Kafka message routing

    Returns:
        List of dictionaries with industry allocations:
        [{"name": str, "percentage": float, "reasoning": str}, ...]
    """
    # Create agent
    agent = create_industry_selection_agent(
        pipeline, gemini_api_key, economic_regime, cpi_val, pmi_val, rebalance, prev_ind_list
    )

    # Invoke agent
    msg = "Invoking industry selection agent..."
    logger.info(msg)
    publish_to_kafka({"content": msg}, user_id=user_id, message_type="start", task_id=task_id)
    messages = []
    for chunk in agent.stream(
            {"messages": [HumanMessage("suggest industries")]},
            stream_mode="updates",
        ):
        new_message = list(chunk.values())[0]["messages"]
        messages.extend(new_message)
        fnc_call = new_message[0].additional_kwargs.get("function_call", None)
        if fnc_call is not None:
            ind_list = json.loads(fnc_call["arguments"])["industries"]
            to_send = {
                "status": "fetching",
                "content": {
                    "industries": ind_list,
                }
            }
            # Publish to_send to Kafka
            publish_to_kafka(to_send, user_id=user_id, message_type="industry", task_id=task_id)
        elif isinstance(new_message[0], ToolMessage):
            metrics = json.loads(new_message[0].content)
            to_send = {
                "status": "fetched",
                "content": {
                    "industries": list(metrics.keys()),
                    "metrics": metrics,
                }
            }
            # Publish to_send to Kafka
            publish_to_kafka(to_send, user_id=user_id, message_type="industry", task_id=task_id)

    # Parse and validate response using common utility
    result = {"messages": messages}
    industry_list = clean_and_parse_agent_json_response(result, expected_type=list)

    # Validate and normalize percentages
    industry_list = validate_percentage_list(
        industry_list,
        required_keys=["name", "percentage", "reasoning"],
        normalize=True,
        tolerance=1.0
    )

    msg = f"Industry selection complete: {len(industry_list)} industries"
    to_send = {
        "status": "done",
        "content": {
            "industries": industry_list,
            "message": msg,
        }
    }
    logger.info(msg + f", total allocation: {sum(item['percentage'] for item in industry_list):.1f}%")
    publish_to_kafka(to_send, user_id=user_id, message_type="industry", task_id=task_id)

    industry_metrics = industry_metrics_callable([i["name"] for i in industry_list], pipeline)

    for i in industry_list:
        i["metrics"] = industry_metrics[i["name"]]

    return industry_list


class IndustrySelectionPipeline:
    """
    Main pipeline for industry selection based on macro regime classification.
    """

    def __init__(
        self,
        industry_pipeline: IndustryIndicatorsPipeline,
        user_id: str,
        gemini_api_key: Optional[str] = None,
        storage: Optional[EconomicIndicatorsStorage] = None,
        task_id: Optional[str] = None,
    ):
        """
        Initialize the industry selection pipeline.

        Args:
            industry_pipeline: IndustryIndicatorsPipeline instance (must have computed data)
            user_id: User identifier for logging and partitioning
            gemini_api_key: Gemini API key (if None, will try to get from env)
            storage: EconomicIndicatorsStorage instance (if None, will use get_storage())
            task_id: Celery task ID for Kafka message routing
        """
        self.industry_pipeline = industry_pipeline
        self.user_id = user_id
        self.storage = storage or get_storage()

        # Get Gemini API key
        if gemini_api_key is None:
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY not provided and not found in environment variables"
                )
        self.gemini_api_key = gemini_api_key

        # Store user context for Kafka publishing (uses singleton via publish_to_kafka helper)
        self.user_id = user_id  # Store user_id for publish calls
        self.task_id = task_id  # Store task_id for Kafka message routing

        # Verify industry pipeline has computed data
        if not industry_pipeline._is_computed:
            raise RuntimeError(
                "IndustryIndicatorsPipeline must have computed data. Call compute() first."
            )

    def run(self, rebalance=False, summary={}) -> List[Dict[str, Any]]:
        """
        Run the complete industry selection pipeline.

        Returns:
            List of industry allocation dictionaries:
            [{"name": str, "percentage": float, "reasoning": str}, ...]
        """
        msg = "Starting industry selection pipeline..."
        logger.info(msg)
        prev_ind_list = summary.get("industry_list", [])
        # Get PMI
        try:
            pmi_val = get_pmi(self.storage)
            msg = f"✓ PMI value: {pmi_val}"
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
        except Exception as e:
            logger.error(f"Failed to get PMI: {e}", exc_info=True)
            raise

        # Get CPI list
        try:
            cpi_list = get_cpi_list(self.storage)
            msg = f"✓ CPI data: {len(cpi_list)} values"
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
        except Exception as e:
            logger.error(f"Failed to get CPI data: {e}", exc_info=True)
            raise

        # Classify regime
        try:
            economic_regime = classify_macro_regime(pmi_val, cpi_list)
            msg = f"✓ Economic regime: {economic_regime}"
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
        except Exception as e:
            logger.error(f"Failed to classify regime: {e}", exc_info=True)
            raise

        # Get latest CPI value
        cpi_val = cpi_list[-1]
        msg = f"✓ Latest CPI value: {cpi_val}"
        logger.info(msg)
        publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)

        msg = f"✓ Latest PMI value: {pmi_val}"
        logger.info(msg)
        publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
        # Select industries using LLM agent
        try:
            industry_list = industry_selector(
                self.industry_pipeline,
                economic_regime,
                cpi_val,
                pmi_val,
                self.gemini_api_key,
                self.user_id,
                task_id=self.task_id,
                rebalance=rebalance,
                prev_ind_list=prev_ind_list
            )
            msg = f"Industry selection complete: {len(industry_list)} industries"
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
            return industry_list
        except Exception as e:
            logger.error(f"Failed to select industries: {e}", exc_info=True)
            raise

