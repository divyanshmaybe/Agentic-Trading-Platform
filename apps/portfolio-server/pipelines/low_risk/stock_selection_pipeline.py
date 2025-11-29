"""
Stock Selection Pipeline

Performs company-level research and stock selection within selected industries.
Uses LLM agents with Google Search for company report generation and strategic
stock selection based on fundamental analysis.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Any

import pandas as pd
from jinja2 import Environment, StrictUndefined
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent

from utils.low_risk_utils import (
    trade_converter,
    load_prompt_from_template,
    render_prompt_template,
    parse_json_response,
    clean_and_parse_agent_json_response,
)
from .industry_pipeline import IndustrySelectionPipeline

logger = logging.getLogger(__name__)


# Cache for company reports to avoid regenerating
company_report_db: Dict[str, Dict[str, Any]] = {}


def generate_company_report(ticker: str, gemini_api_key: str) -> Dict[str, Any]:
    """
    Generate a comprehensive company report using LLM with Google Search.

    Args:
        ticker: NIFTY ticker symbol of the company
        gemini_api_key: Gemini API key

    Returns:
        Dictionary containing company report with fundamental analysis

    Raises:
        ValueError: If report generation fails
    """
    try:
        # Load company report generation prompt
        company_report_prompt = load_prompt_from_template("company_report_generation_prompt")

        # Create LLM with Google Search tool
        model = ChatGoogleGenerativeAI(
            model="gemini-2.5-pro",
                google_api_key=gemini_api_key,
        )
        model_with_search = model.bind_tools([{"google_search": {}}])

        # Generate report
        messages = [
            SystemMessage(content=company_report_prompt),
            HumanMessage(content=f"Generate a report on the company {ticker}")
        ]

        logger.info(f"🔍 Generating company report for {ticker}...")
        response = model_with_search.invoke(messages)
        report_text = response.content

        # Parse JSON using common utility
        report = parse_json_response(
            report_text,
            expected_type=dict,
            clean_markdown=True,
            extract_json=True
        )
        logger.info(f"✓ Company report generated for {ticker}")
        return report

    except Exception as e:
        logger.error(f"Error generating company report for {ticker}: {e}", exc_info=True)
        # Check if it's a rate limit error
        if "rate limit" in str(e).lower() or "quota" in str(e).lower():
            logger.warning(f"Rate limit error for {ticker}, will retry later")
            raise ValueError(f"Rate limit error: {e}")
        raise ValueError(f"Failed to generate company report: {e}")


def create_company_report_tool(gemini_api_key: str) -> Any:
    """
    Create the company_report_tool function that can be used by the LLM agent.

    Args:
        gemini_api_key: Gemini API key

    Returns:
        Tool function decorated with @tool
    """

    @tool
    def company_report_tool(ticker: str) -> Dict[str, Any]:
        """
        Generate a company report for the given ticker.

        Input:
        - ticker: NIFTY ticker symbol of the company.

        Output:
        - A dictionary containing the company report with the following fields:
          market_cap, company_description, business_model, segment_exposure,
          geographic_exposure, major_clients, major_partnerships,
          leadership_governance, recent_strategic_actions, rnd_intensity,
          brand_value_drivers, negatives_risks
        """
        # Check cache first
        if ticker in company_report_db:
            logger.info(f"📋 Using cached report for {ticker}")
            return company_report_db[ticker]

        # Generate new report
        try:
            report = generate_company_report(ticker, gemini_api_key)
            company_report_db[ticker] = report
            return report
        except Exception as e:
            logger.error(f"company_report_tool failed for {ticker}: {e}")
            # Return error indicator
            return {
                "error": str(e),
                "ticker": ticker,
                "company_name": ticker,
                "market_cap": "N/A",
                "company_description": f"Error: {str(e)}",
                "business_model": "N/A",
                "segment_exposure": "N/A",
                "geographic_exposure": "N/A",
                "major_clients": "N/A",
                "major_partnerships": "N/A",
                "leadership_governance": "N/A",
                "recent_strategic_actions": "N/A",
                "rnd_intensity": "N/A",
                "brand_value_drivers": "N/A",
                "negatives_risks": "N/A"
            }

    return company_report_tool


def get_company_prompt(industry: str, company_df: pd.DataFrame) -> str:
    """
    Generate a prompt containing company descriptions for an industry.

    Args:
        industry: Industry name
        company_df: DataFrame with columns: Company Name, Industry, company_brief

    Returns:
        String containing company names and descriptions
    """
    company_prompt = ""
    
    # Filter companies by industry
    industry_companies = company_df[company_df["Industry"] == industry]
    
    if industry_companies.empty:
        logger.warning(f"No companies found for industry: {industry}")
        return f"No companies available for {industry}"
    
    # Build company prompt
    for _, row in industry_companies.iterrows():
        company_name = row.get("Company Name", "")
        company_brief = row.get("company_brief", "")
        if company_name:
            company_prompt += f"{company_name}"
            if company_brief:
                company_prompt += f" - {company_brief}"
            company_prompt += "\n"
    
    return company_prompt.strip()


def stock_selection_indwise(
    industry: str,
    industry_allocation: float,
    company_df: pd.DataFrame,
    gemini_api_key: str,
) -> List[Dict[str, Any]]:
    """
    Select stocks within a single industry using LLM agent.

    Args:
        industry: Industry name
        industry_allocation: Percentage allocation for this industry
        company_df: DataFrame with company information
        gemini_api_key: Gemini API key

    Returns:
        List of dictionaries with stock selections:
        [{"ticker": str, "percentage": float, "reasoning": str}, ...]
    """
    try:
        logger.info(f"🎯 Selecting stocks for {industry} ({industry_allocation}% allocation)...")

        # Load prompts
        stock_selection_prompt = load_prompt_from_template("stock_selection_system_prompt")
        strategy_prompt = load_prompt_from_template("strategy_handbook")

        # Get company prompt for this industry
        company_prompt = get_company_prompt(industry, company_df)

        # Render system prompt with company and strategy info
        rendered_prompt = render_prompt_template(
            stock_selection_prompt,
            company_prompt=company_prompt,
            strategy_prompt=strategy_prompt
        )

        # Create LLM
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-pro",
            google_api_key=gemini_api_key,
        )

        # Create company report tool
        company_tool = create_company_report_tool(gemini_api_key)

        # Create agent with tool
        stock_selection_agent = create_agent(
            model=llm,
            tools=[company_tool],
            state_modifier=SystemMessage(content=rendered_prompt)
        )

        # Invoke agent
        logger.info(f"🤖 Invoking stock selection agent for {industry}...")
        result = stock_selection_agent.invoke({
            "messages": [
                HumanMessage(
                    content="Suggest appropriate number of stocks. "
                    "Think about both over-diversification and under-diversification. "
                    "Select 3-7 stocks that best fit the investment strategy."
                )
            ]
        })

        # Parse response using common utility
        ind_portfolio = clean_and_parse_agent_json_response(result, expected_type=list)

        # Adjust percentages based on industry allocation
        # Portfolio percentages are relative to the industry, convert to absolute
        total_stock_percentage = sum(item.get("percentage", 0) for item in ind_portfolio)
        
        for item in ind_portfolio:
            if not isinstance(item, dict):
                raise ValueError(f"Expected dict in list, got {type(item)}")
            
            required_keys = ["ticker", "percentage", "reasoning"]
            for key in required_keys:
                if key not in item:
                    raise ValueError(f"Missing required key '{key}' in stock selection")

            # Convert relative percentage to absolute percentage
            # e.g., if industry gets 30% and stock gets 40% of industry, absolute is 12%
            relative_percentage = float(item["percentage"])
            absolute_percentage = (relative_percentage / 100.0) * industry_allocation
            item["percentage"] = absolute_percentage

        logger.info(
            f"✅ Stock selection complete for {industry}: "
            f"{len(ind_portfolio)} stocks selected"
        )

        return ind_portfolio

    except Exception as e:
        logger.error(f"Error in stock selection for {industry}: {e}", exc_info=True)
        raise ValueError(f"Stock selection failed for {industry}: {e}")


def generate_stock_portfolio(
    industry_list: List[Dict[str, Any]],
    company_df: pd.DataFrame,
    gemini_api_key: str,
) -> List[Dict[str, Any]]:
    """
    Generate complete stock portfolio across all selected industries.

    Args:
        industry_list: List of industry allocations from industry selector
        company_df: DataFrame with company information
        gemini_api_key: Gemini API key

    Returns:
        List of dictionaries with final portfolio:
        [{"ticker": str, "percentage": float, "reasoning": str}, ...]
    """
    logger.info(f"📊 Generating stock portfolio across {len(industry_list)} industries...")

    final_portfolio = []

    for industry_dict in industry_list:
        industry_name = industry_dict.get("name", "")
        industry_allocation = industry_dict.get("percentage", 0)

        if not industry_name or industry_allocation <= 0:
            logger.warning(f"Skipping invalid industry: {industry_dict}")
            continue

        try:
            # Select stocks for this industry
            ind_portfolio = stock_selection_indwise(
                industry_name,
                industry_allocation,
                company_df,
                gemini_api_key  
            )

            # Add to final portfolio
            final_portfolio.extend(ind_portfolio)

        except Exception as e:
            logger.error(f"Failed to select stocks for {industry_name}: {e}")
            # Continue with other industries
            continue

    # Validate final portfolio
    if not final_portfolio:
        raise ValueError("No stocks selected in final portfolio")

    total_allocation = sum(item["percentage"] for item in final_portfolio)
    logger.info(
        f"✅ Stock portfolio complete: {len(final_portfolio)} stocks, "
        f"total allocation: {total_allocation:.1f}%"
    )

    # Normalize if total is not close to 100%
    if abs(total_allocation - 100.0) > 1.0:
        logger.warning(f"Normalizing portfolio allocation from {total_allocation}% to 100%")
        for item in final_portfolio:
            item["percentage"] = (item["percentage"] / total_allocation) * 100.0

    return final_portfolio


class StockSelectionPipeline:
    """
    Main pipeline for stock selection and trade generation.

    Combines industry allocation with company-level fundamental analysis
    to generate a complete portfolio with trade recommendations.
    """

    def __init__(
        self,
        company_df: pd.DataFrame,
        industry_selection_pipeline: IndustrySelectionPipeline,
        gemini_api_key: Optional[str] = None,
    ):
        """
        Initialize the stock selection pipeline.

        Args:
            company_df: DataFrame with company information (Company Name, Industry, company_brief, etc.)
            industry_selection_pipeline: IndustrySelectionPipeline instance for generating industry allocations
            gemini_api_key: Gemini API key (if None, will try to get from env)

        Raises:
            ValueError: If required columns missing or API key not found
        """
        # Validate company DataFrame
        required_cols = ["Company Name", "Industry"]
        missing_cols = [col for col in required_cols if col not in company_df.columns]
        if missing_cols:
            raise ValueError(
                f"company_df missing required columns: {missing_cols}. "
                f"Available: {company_df.columns.tolist()}"
            )

        self.company_df = company_df
        self.industry_selection_pipeline = industry_selection_pipeline

        # Get Gemini API key
        if gemini_api_key is None:
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY not provided and not found in environment variables"
                )
        self.gemini_api_key = gemini_api_key

        logger.info(f"✓ Stock selection pipeline initialized with {len(company_df)} companies")

    def run(
        self,
        fund_allocated: float,
    ) -> Dict[str, Any]:
        """
        Run the complete stock selection and trade generation pipeline.

        Args:
            fund_allocated: Total fund amount to allocate (in currency units)

        Returns:
            Dictionary containing:
            - industry_list: Industry allocations from industry selector
            - final_portfolio: List of stock selections with percentages
            - trade_list: List of trade records with share quantities

        Raises:
            ValueError: If portfolio generation or trade conversion fails
        """
        logger.info("🚀 Starting stock selection pipeline...")

        # Validate inputs
        if fund_allocated <= 0:
            raise ValueError(f"fund_allocated must be positive, got {fund_allocated}")

        # Generate industry list using IndustrySelectionPipeline
        try:
            logger.info("📊 Running industry selection pipeline...")
            industry_list = self.industry_selection_pipeline.run()
            logger.info(f"✓ Generated industry allocations: {len(industry_list)} industries")
        except Exception as e:
            logger.error(f"Failed to generate industry list: {e}", exc_info=True)
            raise

        # Generate stock portfolio
        try:
            final_portfolio = generate_stock_portfolio(
                industry_list,
                self.company_df,
                self.gemini_api_key
            )
        except Exception as e:
            logger.error(f"Failed to generate stock portfolio: {e}", exc_info=True)
            raise

        # Convert portfolio to trade list
        try:
            logger.info(f"💰 Converting portfolio to trades (fund: ₹{fund_allocated:,.2f})...")
            trade_list = trade_converter(final_portfolio, fund_allocated)
            logger.info(f"✅ Trade list generated: {len(trade_list)} trades")
        except Exception as e:
            logger.error(f"Failed to convert portfolio to trades: {e}", exc_info=True)
            raise

        # Calculate summary statistics
        total_invested = sum(trade["amount_invested"] for trade in trade_list)
        total_shares = sum(trade["no_of_shares_bought"] for trade in trade_list)

        logger.info(
            f"📈 Portfolio summary: {len(trade_list)} trades, "
            f"₹{total_invested:,.2f} invested, {total_shares:,.0f} shares"
        )

        return {
            "industry_list": industry_list,
            "final_portfolio": final_portfolio,
            "trade_list": trade_list,
            "summary": {
                "total_stocks": len(final_portfolio),
                "total_trades": len(trade_list),
                "total_invested": total_invested,
                "total_shares": total_shares,
                "fund_allocated": fund_allocated,
                "utilization_rate": (total_invested / fund_allocated) * 100.0
            }
        }


def run_complete_low_risk_pipeline(
    company_df: pd.DataFrame,
    industry_selection_pipeline: IndustrySelectionPipeline,
    fund_allocated: float,
    gemini_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience function to run the complete stock selection pipeline.

    Args:
        company_df: DataFrame with company information
        industry_selection_pipeline: IndustrySelectionPipeline instance
        fund_allocated: Total fund amount to allocate
        gemini_api_key: Gemini API key (optional)

    Returns:
        Dictionary containing industry_list, final_portfolio, and trade_list
    """
    pipeline = StockSelectionPipeline(
        company_df, 
        industry_selection_pipeline, 
        gemini_api_key
    )
    return pipeline.run(fund_allocated)
