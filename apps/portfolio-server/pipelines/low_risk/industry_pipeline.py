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

import pandas as pd
import yaml
from jinja2 import Environment, StrictUndefined
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

from utils.economic_indicators_storage import EconomicIndicatorsStorage, get_storage
from .industry_indicators_pipeline import IndustryIndicatorsPipeline

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
        logger.info(f"✓ Extracted PMI value: {pmi_val}")
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

    # CPI data should have date and value columns
    # Check common column names
    date_col = None
    value_col = None

    for col in df.columns:
        col_lower = col.lower()
        if "date" in col_lower or "month" in col_lower or "period" in col_lower:
            date_col = col
        if "value" in col_lower or "index" in col_lower or "cpi" in col_lower:
            value_col = col

    if date_col is None or value_col is None:
        # Try to infer from data structure
        # CPI scraper might return columns like "Month", "CPI", etc.
        logger.warning(
            f"Could not find date/value columns. Available columns: {df.columns.tolist()}"
        )
        # Try common patterns
        if "Month" in df.columns:
            date_col = "Month"
        if "CPI" in df.columns:
            value_col = "CPI"
        elif "Index" in df.columns:
            value_col = "Index"
        elif len(df.columns) >= 2:
            # Assume first is date, second is value
            date_col = df.columns[0]
            value_col = df.columns[1]

    if date_col is None or value_col is None:
        raise ValueError(
            f"Cannot identify date and value columns in CPI data. Columns: {df.columns.tolist()}"
        )

    # Sort by date
    try:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.sort_values(date_col).dropna(subset=[date_col, value_col])
    except Exception as e:
        logger.warning(f"Could not parse dates, using original order: {e}")
        df = df.dropna(subset=[value_col])

    # Extract values as floats
    cpi_values = []
    for val in df[value_col]:
        try:
            # Clean value (remove commas, etc.)
            val_str = str(val).strip().replace(",", "")
            cpi_val = float(val_str)
            cpi_values.append(cpi_val)
        except (ValueError, TypeError):
            logger.warning(f"Skipping invalid CPI value: {val}")
            continue

    if not cpi_values:
        raise ValueError("No valid CPI values found in data")

    logger.info(f"✓ Extracted {len(cpi_values)} CPI values (range: {min(cpi_values):.2f} to {max(cpi_values):.2f})")
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


def load_prompt_template() -> str:
    """
    Load the industry selector prompt template from YAML file.

    Returns:
        Prompt template string
    """
    # Get template file path
    template_dir = Path(__file__).resolve().parent.parent.parent / "templates"
    template_file = template_dir / "industry_selector_prompt.yaml"

    if not template_file.exists():
        raise FileNotFoundError(
            f"Prompt template not found at {template_file}"
        )

    with open(template_file, "r") as f:
        template_data = yaml.safe_load(f)

    prompt = template_data.get("prompt", "")
    if not prompt:
        raise ValueError("Prompt template is empty in YAML file")

    return prompt


def create_industry_selection_agent(
    pipeline: IndustryIndicatorsPipeline,
    gemini_api_key: str,
    economic_regime: str,
    cpi_val: float,
    pmi_val: float,
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
    prompt_template = load_prompt_template()
    env = Environment(undefined=StrictUndefined)
    template = env.from_string(prompt_template)

    rendered_prompt = template.render(
        economic_regime=economic_regime.lower(),
        cpi_val=cpi_val,
        pmi_val=pmi_val,
    )

    # Create LLM
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.7,
        google_api_key=gemini_api_key,
    )

    # Bind tools to LLM
    llm_with_tools = llm.bind_tools([industry_metrics_tool])

    # Create system message
    system_message = SystemMessage(content=rendered_prompt)

    # Create agent that handles tool calls
    class SimpleAgent:
        def __init__(self, llm, system_message, tool):
            self.llm = llm
            self.system_message = system_message
            self.tool = tool
            self.max_iterations = 10  # Prevent infinite loops

        def invoke(self, user_message: str) -> Dict[str, Any]:
            """Invoke the agent with a user message, handling tool calls."""
            messages = [self.system_message, HumanMessage(content=user_message)]
            iteration = 0

            while iteration < self.max_iterations:
                iteration += 1
                response = self.llm.invoke(messages)

                # Check if response has tool calls
                if hasattr(response, "tool_calls") and response.tool_calls:
                    # Execute tool calls
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.get("name", "")
                        tool_args = tool_call.get("args", {})

                        if tool_name == "industry_metrics":
                            # Execute the tool
                            tool_result = self.tool.invoke(tool_args)
                            # Add tool result to messages
                            tool_message = ToolMessage(
                                content=json.dumps(tool_result),
                                tool_call_id=tool_call.get("id", ""),
                            )
                            messages.append(response)  # Add LLM response with tool calls
                            messages.append(tool_message)  # Add tool result
                        else:
                            logger.warning(f"Unknown tool: {tool_name}")
                    # Continue loop to get final response
                else:
                    # No tool calls, this is the final response
                    messages.append(response)
                    break

            return {"messages": messages}

    agent = SimpleAgent(llm_with_tools, system_message, industry_metrics_tool)
    return agent


def industry_selector(
    pipeline: IndustryIndicatorsPipeline,
    economic_regime: str,
    cpi_val: float,
    pmi_val: float,
    gemini_api_key: str,
) -> List[Dict[str, Any]]:
    """
    Select industries using LLM agent based on economic regime.

    Args:
        pipeline: IndustryIndicatorsPipeline instance (must have computed data)
        economic_regime: Economic regime classification
        cpi_val: Current CPI value
        pmi_val: Current PMI value
        gemini_api_key: Gemini API key

    Returns:
        List of dictionaries with industry allocations:
        [{"name": str, "percentage": float, "reasoning": str}, ...]
    """
    # Create agent
    agent = create_industry_selection_agent(
        pipeline, gemini_api_key, economic_regime, cpi_val, pmi_val
    )

    # Invoke agent
    logger.info("🤖 Invoking industry selection agent...")
    result = agent.invoke("suggest industries")

    # Extract response from agent output
    messages = result.get("messages", [])
    if not messages:
        raise ValueError("Agent returned no messages")

    # Get the last message (agent response)
    last_message = messages[-1]
    response_text = last_message.content if hasattr(last_message, "content") else str(last_message)

    # Clean response text (remove markdown code blocks if present)
    response_text = re.sub(r"```(?:python|json)?\s*\n?", "", response_text)
    response_text = re.sub(r"```\s*$", "", response_text)
    response_text = response_text.strip()

    # Try to extract JSON from response
    # Look for JSON array pattern
    json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group(0)

    # Parse JSON
    try:
        industry_list = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse agent response as JSON: {e}")
        logger.error(f"Response text: {response_text[:500]}")
        raise ValueError(f"Agent response is not valid JSON: {e}")

    # Validate response format
    if not isinstance(industry_list, list):
        raise ValueError(f"Expected list, got {type(industry_list)}")

    # Validate each item
    total_percentage = 0.0
    for item in industry_list:
        if not isinstance(item, dict):
            raise ValueError(f"Expected dict in list, got {type(item)}")
        required_keys = ["name", "percentage", "reasoning"]
        for key in required_keys:
            if key not in item:
                raise ValueError(f"Missing required key '{key}' in industry allocation")

        # Validate percentage is numeric
        try:
            percentage = float(item["percentage"])
            total_percentage += percentage
            item["percentage"] = percentage  # Ensure it's a float
        except (ValueError, TypeError):
            raise ValueError(f"Invalid percentage value: {item['percentage']}")

    # Check if percentages sum to 100 (allow small rounding errors)
    if abs(total_percentage - 100.0) > 1.0:
        logger.warning(
            f"Industry allocations sum to {total_percentage}%, not 100%. Adjusting..."
        )
        # Normalize percentages to sum to 100
        if total_percentage > 0:
            for item in industry_list:
                item["percentage"] = (item["percentage"] / total_percentage) * 100.0
        else:
            raise ValueError("Total percentage is zero or negative")

    logger.info(
        f"✅ Industry selection complete: {len(industry_list)} industries, "
        f"total allocation: {sum(item['percentage'] for item in industry_list):.1f}%"
    )

    return industry_list


class IndustrySelectionPipeline:
    """
    Main pipeline for industry selection based on macro regime classification.
    """

    def __init__(
        self,
        industry_pipeline: IndustryIndicatorsPipeline,
        gemini_api_key: Optional[str] = None,
        storage: Optional[EconomicIndicatorsStorage] = None,
    ):
        """
        Initialize the industry selection pipeline.

        Args:
            industry_pipeline: IndustryIndicatorsPipeline instance (must have computed data)
            gemini_api_key: Gemini API key (if None, will try to get from env)
            storage: EconomicIndicatorsStorage instance (if None, will use get_storage())
        """
        self.industry_pipeline = industry_pipeline
        self.storage = storage or get_storage()

        # Get Gemini API key
        if gemini_api_key is None:
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY not provided and not found in environment variables"
                )
        self.gemini_api_key = gemini_api_key

        # Verify industry pipeline has computed data
        if not industry_pipeline._is_computed:
            raise RuntimeError(
                "IndustryIndicatorsPipeline must have computed data. Call compute() first."
            )

    def run(self) -> List[Dict[str, Any]]:
        """
        Run the complete industry selection pipeline.

        Returns:
            List of industry allocation dictionaries:
            [{"name": str, "percentage": float, "reasoning": str}, ...]
        """
        logger.info("🚀 Starting industry selection pipeline...")

        # Get PMI
        try:
            pmi_val = get_pmi(self.storage)
            logger.info(f"✓ PMI value: {pmi_val}")
        except Exception as e:
            logger.error(f"Failed to get PMI: {e}", exc_info=True)
            raise

        # Get CPI list
        try:
            cpi_list = get_cpi_list(self.storage)
            logger.info(f"✓ CPI data: {len(cpi_list)} values")
        except Exception as e:
            logger.error(f"Failed to get CPI data: {e}", exc_info=True)
            raise

        # Classify regime
        try:
            economic_regime = classify_macro_regime(pmi_val, cpi_list)
            logger.info(f"✓ Economic regime: {economic_regime}")
        except Exception as e:
            logger.error(f"Failed to classify regime: {e}", exc_info=True)
            raise

        # Get latest CPI value
        cpi_val = cpi_list[-1]
        logger.info(f"✓ Latest CPI value: {cpi_val}")

        # Select industries using LLM agent
        try:
            industry_list = industry_selector(
                self.industry_pipeline,
                economic_regime,
                cpi_val,
                pmi_val,
                self.gemini_api_key,
            )
            logger.info(f"✅ Industry selection complete: {len(industry_list)} industries")
            return industry_list
        except Exception as e:
            logger.error(f"Failed to select industries: {e}", exc_info=True)
            raise

