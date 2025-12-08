"""
Stock Selection Pipeline

Performs company-level research and stock selection within selected industries.
"""

import asyncio
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Coroutine, Annotated
from operator import add

# Add shared/py to sys.path
shared_dir = Path(__file__).resolve().parent.parent.parent.parent.parent / "shared" / "py"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))

import pandas as pd
from company_report_service import CompanyReportService
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain.tools import tool, InjectedToolCallId, ToolRuntime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent, AgentState
from langgraph.types import Command
from dotenv import load_dotenv
from pathlib import Path

import concurrent.futures

from . fundamental_analyzer_pipeline import FundamentalAnalyzerPipeline

# Resolve path to .env file
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Initialize Phoenix tracing for stock selection pipeline
try:
    from phoenix.otel import register
    
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="stock-selection-pipeline",
            endpoint=collector_endpoint,
            auto_instrument=True,
        )
        print(f"✅ Phoenix tracing initialized for stock selection: {collector_endpoint}")
    else:
        print("⚠️ COLLECTOR_ENDPOINT not set, Phoenix tracing disabled for stock selection")
except ImportError:
    print("⚠️ Phoenix not installed, tracing disabled for stock selection")
except Exception as e:
    print(f"⚠️ Failed to initialize Phoenix tracing for stock selection: {e}")

# LangSmith tracing (optional - can run alongside Phoenix)
langsmith_api_key = os.getenv("LANGSMITH_API_KEY", "")
if langsmith_api_key:
    os.environ["LANGSMITH_API_KEY"] = langsmith_api_key
    os.environ["LANGSMITH_TRACING_V2"] = "true"
    os.environ["LANGSMITH_PROJECT"] = "portfolio_prod"
    print("🔍 LangSmith tracing also enabled")
else:
    os.environ["LANGSMITH_TRACING_V2"] = "false"

from utils.low_risk_utils import (
    trade_converter,
    load_prompt_from_template,
    render_prompt_template,
    parse_json_response,
    clean_and_parse_agent_json_response,
    publish_to_kafka,
)
from . industry_pipeline import IndustrySelectionPipeline

logger = logging.getLogger(__name__)

# Cache for company reports
company_report_db: Dict[str, Dict[str, Any]] = {}


class StockSelectionPipeline:
    """Main pipeline for stock selection and trade generation."""

    def __init__(
        self,
        pipeline: FundamentalAnalyzerPipeline,
        company_df: pd.DataFrame,
        industry_list: List[Dict[str, Any]],
        gemini_api_key: Optional[str] = None,
        user_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        """Initialize the stock selection pipeline."""
        # Validate company DataFrame
        required_cols = ["Company Name", "Industry"]
        missing_cols = [col for col in required_cols if col not in company_df.columns]
        if missing_cols:
            raise ValueError(
                f"company_df missing required columns: {missing_cols}"
            )

        self.company_df = company_df
        self.industry_list = industry_list

        # Store user context for Kafka publishing (uses singleton via publish_to_kafka helper)
        self.user_id = user_id
        self.task_id = task_id
        self.pipeline = pipeline

        # Get Gemini API key
        if gemini_api_key is None:
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                raise ValueError("GEMINI_API_KEY not found")
        self.gemini_api_key = gemini_api_key

        # Initialize CompanyReportService
        self.report_service = CompanyReportService.get_instance()

        # Background event loop for async tasks (company reports)
        self._background_loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()
        self._start_background_loop()

        logger.info(f"Stock selection pipeline initialized with {len(company_df)} companies")

    async def generate_company_report(self, ticker: str) -> Dict[str, Any]:
        """
        Generate company report - checks DB/cache first, generates if not found.

        This method is called WITHIN a thread's event loop.
        """
        try:
            # Initialize report service (safe to call multiple times)
            await self.report_service.initialize()

            # Check MongoDB/Redis cache first
            existing_report = await self.report_service.get_report_by_ticker(ticker)
            if existing_report:
                logger.info(f"📋 Found existing report in DB for {ticker}")
                return existing_report

            # Generate new report
            logger.info(f"🔍 Generating fresh company report for {ticker}")

            # Load prompt
            company_report_prompt = load_prompt_from_template("company_report_generation_prompt")

            # Create LLM with Google Search
            model = ChatGoogleGenerativeAI(
                model="gemini-2.5-pro",
                google_api_key=self.gemini_api_key,
                temperature=0.5
            )
            model_with_search = model.bind_tools([{"google_search": {}}])

            # Generate report
            messages = [
                SystemMessage(content=company_report_prompt),
                HumanMessage(content=f"Generate a report on the company {ticker}")
            ]

            msg = f"🔍 Generating company report for {ticker}..."
            logger.info(msg)
            # publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)

            response = model_with_search.invoke(messages)
            report_text = response.content

            # Parse JSON
            report = parse_json_response(
                report_text,
                expected_type=dict,
                clean_markdown=True,
                extract_json=True
            )

            # Add ticker
            if "ticker" not in report:
                report["ticker"] = ticker

            # Store to MongoDB
            logger.info(f"💾 Storing report to MongoDB for {ticker}...")
            await self.report_service.upsert_report(report)
            logger.info(f"✅ Report stored to MongoDB for {ticker}")

            msg = f"Company report generated for {ticker}"
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
            to_send = {
                                "status": "fetched",
                                "content": {"content": ticker}
                        }
            publish_to_kafka(to_send, user_id=self.user_id, message_type="stock", task_id=self.task_id)
            return report

        except Exception as e:
            logger.error(f"Error generating company report for {ticker}: {e}", exc_info=True)
            if "rate limit" in str(e).lower() or "quota" in str(e).lower():
                raise ValueError(f"Rate limit error: {e}")
            raise ValueError(f"Failed to generate company report: {e}")

    def _start_background_loop(self) -> None:
        """Start dedicated event loop in a background thread for async tasks."""

        def loop_runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._background_loop = loop
            self._loop_ready.set()
            loop.run_forever()

        self._loop_thread = threading.Thread(target=loop_runner, daemon=True)
        self._loop_thread.start()
        self._loop_ready.wait()

    def _run_in_background_loop(self, coro: Coroutine[Any, Any, Any], timeout: float = 180.0) -> Any:
        """Schedule coroutine on background loop and wait for result."""
        if not self._background_loop or not self._background_loop.is_running():
            raise RuntimeError("Background event loop not running")
        future = asyncio.run_coroutine_threadsafe(coro, self._background_loop)
        return future.result(timeout=timeout)

    def create_company_metrics_tool(self) -> Any:
        """
        Create the company_metrics_tool function that can be used by the LLM agent.
        """
        @tool
        def company_metrics_tool(tickers: list[str], metrics: list[str]) -> Dict[str, Dict[str, Any]]:
            """
            Generate company metrics for all the given tickers.
            Input:
            - tickers: List of NIFTY tickers symbol of the company.
            - metrics: List of metrics to generate.
            Output:
            - A dictionary of dictionary containing the company metrics.
            """

            try:
                result = {}
                for ticker in tickers:
                    res_json = self.pipeline.get_metrics(ticker)
                    if res_json is None:
                        logger.warning(f"No metrics found for {ticker}")
                        # Set all metrics to None if res_json is None
                        ticker_result = {m: None for m in metrics}
                    else:
                        ticker_result = {}
                        for m in metrics:
                            ticker_result[m] = res_json.get(m, None)
                    result[ticker] = ticker_result

                metrics_list = ", ".join(metrics)
                tickers_list = ", ".join(tickers)
                publish_to_kafka(
                    {"content": f"Fetching metrics {metrics_list} for {tickers_list}"},
                    user_id=self.user_id,
                    message_type="info",
                    task_id=self.task_id,
                )

                return result
            except Exception as e:
                logger.error(f"Error in company_metrics tool: {e}", exc_info=True)

        return company_metrics_tool

    def company_metrics_tool_callable(self, tickers: list[str], metrics: list[str]) -> Dict[str, Dict[str, Any]]:
            """
            Generate company metrics for all the given tickers.
            Input:
            - tickers: List of NIFTY tickers symbol of the company.
            - metrics: List of metrics to generate.
            Output:
            - A dictionary of dictionary containing the company metrics.
            """

            try:
                result = {}
                for ticker in tickers:
                    res_json = self.pipeline.get_metrics(ticker)
                    if res_json is None:
                        logger.warning(f"No metrics found for {ticker}")
                        # Set all metrics to None if res_json is None
                        ticker_result = {m: None for m in metrics}
                    else:
                        ticker_result = {}
                        for m in metrics:
                            ticker_result[m] = res_json.get(m, None)
                    result[ticker] = ticker_result

                metrics_list = ", ".join(metrics)
                tickers_list = ", ".join(tickers)

                return result
            except Exception as e:
                logger.error(f"Error in company_metrics tool: {e}", exc_info=True)


    def create_company_report_tool(self, gemini_api_key: str) -> Any:
        """
        Create the company_report_tool function that can be used by the LLM agent.

        This uses ThreadPoolExecutor to run async code in a dedicated thread.
        """

        @tool
        def company_report_tool(ticker: str) -> Dict[str, Any]:
            """
            Generate a company report for the given ticker.

            Input:
            - ticker: NIFTY ticker symbol of the company.

            Output:
            - A dictionary containing the company report.
            """
            # Check memory cache first
            if ticker in company_report_db:
                to_send = {
                    "status": "cached",
                    "content": {"ticker": ticker}
                }
                logger.info(f"Using cached report for {ticker}")
                publish_to_kafka(to_send, user_id=self.user_id, message_type="report", task_id=self.task_id)
                return company_report_db[ticker]

            # Generate new report
            try:
                to_send = {
                    "status": "generating",
                    "content": {"ticker": ticker}
                }
                publish_to_kafka(to_send, user_id=self.user_id, message_type="report", task_id=self.task_id)

                # Run async workflow on dedicated loop
                report = self._run_in_background_loop(
                    self.generate_company_report(ticker),
                    timeout=900.0,
                )

                # Cache the result
                company_report_db[ticker] = report

                to_send = {
                    "status": "generated",
                    "content": {"ticker": ticker}
                }
                publish_to_kafka(to_send, user_id=self.user_id, message_type="report", task_id=self.task_id)

                return report

            except concurrent.futures.TimeoutError:
                logger.error(f"Timeout generating report for {ticker}")
                return {
                    "error": "Timeout",
                    "ticker": ticker,
                    "company_name": ticker,
                    "market_cap": "N/A",
                    "company_description": "Error: Request timeout",
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
            except Exception as e:
                logger.error(f"company_report_tool failed for {ticker}: {e}")
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

    def create_reasoning_tool(self, gemini_api_key: str, industry: str, company_df: pd.DataFrame) -> Any:
        """
        Create the reasoning_tool function that can be used by the LLM agent.
        """
        strategy_prompt = load_prompt_from_template("strategy_handbook")
        reasoning_prompt = load_prompt_from_template("reasoning_prompt")
        company_metrics_prompt = load_prompt_from_template("company_metrics_prompt")
        # Get company prompt for this industry
        company_prompt = self.get_company_prompt(industry, company_df, push_notif=False)
        @tool
        def reasoning_tool(runtime: ToolRuntime, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
            """
            Generate a reasoning for extracted information
            Input:
            No input required
            Output:
            - A string of reasoning tokens with proper analysis, interpretation, and possible next steps.
            """
            # reasoning_llm = ChatGoogleGenerativeAI(model="gemini-3-pro-preview", thinking_budget=2000, temperature=0.5)
            reasoning_llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.5)
            messages = runtime.state["messages"]
            reasoning_messages = runtime.state["reasoning_messages"]
            if len(reasoning_messages) == 0:
                reasoning_messages.append(render_prompt_template(
                    reasoning_prompt,
                    company_prompt=company_prompt,
                    strategy_prompt=strategy_prompt,
                    company_metrics_prompt=company_metrics_prompt,
                ))

            if len(messages) >= 2 and isinstance(messages[-2], ToolMessage):
                # last tool name
                last_tn = messages[-2].name
                # last tool message
                last_tm = messages[-2].content
                publish_to_kafka({"content": f"Comparing..."}, user_id=self.user_id, message_type="info", task_id=self.task_id)
                new_reasoning_message = reasoning_llm.invoke(reasoning_messages + [HumanMessage(
                    f"New Tool Call for {last_tn} with output {last_tm}"
                )])

                reasoning = new_reasoning_message.content
            else:
                reasoning = ""
                new_reasoning_message = AIMessage("")
            msg = reasoning
            to_send = {
                "status": "thinking",
                "content": {
                    "message": msg
                }
            }
            publish_to_kafka(to_send, user_id=self.user_id, message_type="reasoning", task_id=self.task_id)

            return Command(
                update={
                    "messages": [ToolMessage(content=reasoning, tool_call_id=tool_call_id)],
                    "reasoning_messages": [new_reasoning_message]
                }
            )
        return reasoning_tool

    def check_low_risk_guardrails(self, data):
        report = {
            "passed": True,
            "failed_guardrails": []
        }

        def fail(message):
            report["passed"] = False
            report["failed_guardrails"].append(message)

        try:
            sma50 = data.get("sma50", None)
            sma200 = data.get("sma200", None)
            rsi_14 = data.get("rsi_14", None)
            volatility = data.get("volatility", None)

            # Guardrail 1
            if sma50 and sma200:
                logger.error("sma50 sma 200 exists")
                if sma50*1.02 <= sma200:
                    fail(f"Guardrail_1")
                    logger.error("guardrail 1 failed")

            # Guardrail 2
            if rsi_14:
                logger.error("rsi exists")
                if rsi_14 >= 70:
                    fail(f"Guardrail_2")
                    logger.error("guardrail 2 failed")

            # Guardrail 3
            if volatility:
                logger.error("volatility exists")
                if volatility >= 0.6:
                    fail(f"Guardrail_3")
                    logger.error("guardrail 3 failed")

        except Exception as e:
            logger.error(e)
            return {
                "passed": False,
                "failed_guardrails": [f"error: {str(e)}"]
            }
        if report["passed"] == False:
            logger.info("company failed")

        return report


    def get_company_prompt(self, industry: str, company_df: pd.DataFrame, push_notif: bool=True) -> str:
        """Generate a prompt containing company descriptions for an industry."""
        pipeline = self.pipeline
        company_prompt = ""

        # Filter companies by industry
        industry_companies = company_df[company_df["Industry"] == industry]

        if industry_companies.empty:
            logger.warning(f"No companies found for industry: {industry}")
            return f"No companies available for {industry}"

        # failed companies
        failed_companies = []
        count = 0
        # Build company prompt
        for _, row in industry_companies.iterrows():
            company_name = row.get("Company Name", "")
            company_brief = row.get("company_brief", "")

            # CHECKING GUARDRAILS
            ticker = row.get("Symbol", "")
            res_json = pipeline.get_metrics(ticker)
            logger.info(f"res_json for {company_name}: {res_json}")
            metrics = ["current_price", 'sma200', 'sma50', 'operating_cashflow', 'net_income', 'rsi_14', "volatility"]
            if res_json is None:
                logger.warning(f"No metrics found for {ticker}")
                # Set all metrics to None if res_json is None
                ticker_result = {m: None for m in metrics}
            else:
                ticker_result = {}
                for m in metrics:
                    ticker_result[m] = res_json.get(m, None)

            logger.info(f"ticker_result for {company_name}: {ticker_result}")
            guardrail_report = self.check_low_risk_guardrails(ticker_result)
            print("guardrail_report", guardrail_report)

            if guardrail_report["passed"]:
                if company_name:
                    company_prompt += f"{company_name}"
                    if company_brief:
                        company_prompt += f" - {company_brief}"
                    company_prompt += "\n"
                    count+=1
            else:
                failed_companies.append({
                    "name": company_name,
                    "failed_guardrails": guardrail_report["failed_guardrails"]
                })

        if len(failed_companies) > 0 and push_notif:
            logger.info("Rejecting companies due to failed guardrails")
            failed_names = ', '.join(c['name'] for c in failed_companies)
            publish_to_kafka({"content": f"Rejecting companies due to failed guardrails\n{failed_names}"}, user_id=self.user_id, task_id=self.task_id)

        logger.info(f"{count} passed for {industry}")
        return company_prompt.strip()

    def stock_selection_indwise(
        self,
        industry: str,
        industry_allocation: float,
        company_df: pd.DataFrame,
        gemini_api_key: str,
        rebalance: bool = False,
        prev_stock_list: list[Dict[str, Any]] = [],
    ) -> List[Dict[str, Any]]:
        """Select stocks within a single industry using LLM agent."""
        try:
            msg = f"Selecting stocks for {industry} ({industry_allocation}% allocation)..."
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)

            # Load prompts
            stock_selection_prompt = load_prompt_from_template("stock_selection_system_prompt")
            strategy_prompt = load_prompt_from_template("strategy_handbook")
            company_metrics_prompt = load_prompt_from_template("company_metrics_prompt")

            # Get company prompt for this industry
            company_prompt = self.get_company_prompt(industry, company_df)

            # Render system prompt
            rendered_prompt = render_prompt_template(
                stock_selection_prompt,
                company_prompt=company_prompt,
                strategy_prompt=strategy_prompt,
                company_metrics_prompt=company_metrics_prompt,
                rebalance=rebalance,
                prev_stock_list=prev_stock_list,
            )

            # Create LLM
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-pro",
                google_api_key=gemini_api_key,
                temperature=0.5,
            )

            # Create company report tool
            company_report_tool = self.create_company_report_tool(self.gemini_api_key)
            company_metrics_tool = self.create_company_metrics_tool()
            reasoning_tool = self.create_reasoning_tool(self.gemini_api_key, industry, company_df)

            class StockWithReasonState(AgentState):
                reasoning_messages: Annotated[list[AnyMessage], add]

            # Create agent
            stock_selection_agent = create_agent(
                model=llm,
                tools=[company_report_tool, company_metrics_tool, reasoning_tool],
                system_prompt=rendered_prompt,
                state_schema=StockWithReasonState
            )

            # Invoke agent
            msg = f"Invoking stock selection agent for {industry}..."
            logger.info(msg)
            publish_to_kafka({"content": msg, "stage": f"{industry}", "status": "start"}, user_id=self.user_id, task_id=self.task_id, message_type="stage")

            # Stream agent responses
            messages = []
            for chunk in stock_selection_agent.stream(
                {
                    "messages": [
                        HumanMessage(
                            content="Select 3-5 stocks that best fit the investment strategy."
                        )
                    ]
                },
                stream_mode="updates"
            ):
                new_message = list(chunk.values())[0]["messages"]
                messages.extend(new_message)
                if len(new_message) > 0 and hasattr(new_message[0], 'additional_kwargs'):
                    fnc_call = new_message[0].additional_kwargs.get("function_call", None)
                    if fnc_call is not None:
                        if fnc_call["name"] == "company_report_tool":
                            ticker = json.loads(fnc_call["arguments"])["ticker"]
                            to_send = {
                                "status": "fetching",
                                "content": {"content": ticker}
                            }
                            publish_to_kafka(to_send, user_id=self.user_id, message_type="stock", task_id=self.task_id)

            result = {"messages": messages}

            # Parse response
            ind_portfolio = clean_and_parse_agent_json_response(result, expected_type=list)

            # Adjust percentages based on industry allocation
            for item in ind_portfolio:
                if not isinstance(item, dict):
                    raise ValueError(f"Expected dict in list, got {type(item)}")

                required_keys = ["ticker", "percentage", "reasoning"]
                for key in required_keys:
                    if key not in item:
                        raise ValueError(f"Missing required key '{key}' in stock selection")

                # Convert relative percentage to absolute percentage
                relative_percentage = float(item["percentage"])
                absolute_percentage = (relative_percentage / 100.0) * industry_allocation
                item["percentage"] = absolute_percentage

            msg = f"Stock selection complete for {industry}: {len(ind_portfolio)} stocks selected"
            logger.info(msg)
            publish_to_kafka({"content": msg,"stage": f"{industry}", "status": "done"}, user_id=self.user_id, task_id=self.task_id,message_type="stage")

            return ind_portfolio

        except Exception as e:
            logger.error(f"Error in stock selection for {industry}: {e}", exc_info=True)
            raise ValueError(f"Stock selection failed for {industry}: {e}")

    def generate_stock_portfolio(
        self,
        industry_list: List[Dict[str, Any]],
        company_df: pd.DataFrame,
        gemini_api_key: str,
        rebalance: bool = False,
        prev_stock_list: list[Dict[str, Any]] = []
    ) -> List[Dict[str, Any]]:
        """Generate complete stock portfolio across all selected industries."""
        msg = f"Generating stock portfolio across {len(industry_list)} industries..."
        logger.info(msg)
        publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)

        final_portfolio = []

        for industry_dict in industry_list:
            industry_name = industry_dict.get("name", "")
            industry_allocation = industry_dict.get("percentage", 0)

            if not industry_name or industry_allocation <= 0:
                logger.warning(f"Skipping invalid industry: {industry_dict}")
                continue

            try:
                # Select stocks for this industry
                ind_portfolio = self.stock_selection_indwise(
                    industry_name,
                    industry_allocation,
                    company_df,
                    gemini_api_key,
                    rebalance=rebalance,
                    prev_stock_list=prev_stock_list
                )

                # Add to final portfolio
                final_portfolio.extend(ind_portfolio)

            except Exception as e:
                error_msg = str(e).lower()
                # Re-raise if it's a quota or rate limit error - no point continuing
                if any(x in error_msg for x in ['quota', 'rate limit', 'resource exhausted', '429', 'too many requests']):
                    logger.error(f"Gemini API quota/rate limit error for {industry_name}: {e}")
                    raise ValueError(f"Gemini API quota exceeded: {e}")
                logger.error(f"Failed to select stocks for {industry_name}: {e}")
                continue

        # Validate final portfolio
        if not final_portfolio:
            raise ValueError("No stocks selected in final portfolio. Check Gemini API quota and industry list.")

        total_allocation = sum(item["percentage"] for item in final_portfolio)
        msg = f"Stock portfolio complete: {len(final_portfolio)} stocks, total allocation: {total_allocation:.1f}%"
        logger.info(msg)
        publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)

        # Normalize if needed
        if abs(total_allocation - 100.0) > 1.0:
            logger.warning(f"Normalizing portfolio allocation from {total_allocation}% to 100%")
            for item in final_portfolio:
                item["percentage"] = (item["percentage"] / total_allocation) * 100.0

        return final_portfolio

    def run(self, fund_allocated: float, rebalance: bool = False, prev_summary: Dict[str, Any] = {}) -> Dict[str, Any]:
        """Run the complete stock selection and trade generation pipeline."""
        msg = "Starting stock selection pipeline..."
        prev_stock_list = prev_summary.get("final_portfolio", [])
        logger.info(msg)
        publish_to_kafka({"content": msg}, user_id=self.user_id, message_type="info", task_id=self.task_id)

        # Validate inputs
        if fund_allocated <= 0:
            raise ValueError(f"fund_allocated must be positive, got {fund_allocated}")

        # Use provided industry list
        try:
            msg = "Using provided industry allocations..."
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
            industry_list = self.industry_list
            msg = f"Using {len(industry_list)} industries"
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
        except Exception as e:
            logger.error(f"Failed to use industry list: {e}", exc_info=True)
            raise

        # Generate stock portfolio
        try:
            final_portfolio = self.generate_stock_portfolio(
                industry_list,
                self.company_df,
                self.gemini_api_key,
                rebalance=rebalance,
                prev_stock_list=prev_stock_list
            )
        except Exception as e:
            logger.error(f"Failed to generate stock portfolio: {e}", exc_info=True)
            raise

        # Convert portfolio to trade list
        try:
            msg = f"Converting portfolio to trades (fund: ₹{fund_allocated:,.2f})..."
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)

            trade_list = trade_converter(final_portfolio, fund_allocated)

            msg = f"Trade list generated: {len(trade_list)} trades"
            logger.info(msg)
            publish_to_kafka({"content": msg}, user_id=self.user_id, task_id=self.task_id)
        except Exception as e:
            logger.error(f"Failed to convert portfolio to trades: {e}", exc_info=True)
            raise

        # Calculate summary statistics
        total_invested = sum(trade["amount_invested"] for trade in trade_list)
        total_shares = sum(trade["no_of_shares_bought"] for trade in trade_list)

        logger.info(
            f"Portfolio summary: {len(trade_list)} trades, "
            f"₹{total_invested:,.2f} invested, {total_shares:,.0f} shares"
        )

        res = {
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
        industry_metrics = {i["name"]: i["metrics"] for i in industry_list}

        company_metrics_tool = self.create_company_metrics_tool()
        metrics = ["piotroski_fscore", "sloan_ratio", "debt_to_equity", "ev_to_ebitda", "price_to_book", "shareholder_yield", "pe_ratio", "forward_pe", "roic", "roe", "ccc", "revenue_growth", "earnings_growth", "gross_profit_growth", "price_to_ema200", "price_to_ema50", "rsi14", "fifty_two_week_change", "momentum_6_1"]
        stock_metrics = self.company_metrics_tool_callable([s["ticker"] for s in final_portfolio], metrics)

        publish_to_kafka({"content": res}, user_id=self.user_id, message_type="summary", task_id=self.task_id)
        # publish_to_kafka({"industry_metrics": industry_metrics, "stock_metrics": stock_metrics}, user_id=self.user_id, task_id=self.task_id, message_type="metrics")
        return res

    def __del__(self):
        """Cleanup thread pool on deletion."""
        try:
            if self._background_loop and self._background_loop.is_running():
                self._background_loop.call_soon_threadsafe(self._background_loop.stop)
            if self._loop_thread and self._loop_thread.is_alive():
                self._loop_thread.join(timeout=1.0)
        except Exception:
            pass


def run_complete_low_risk_pipeline(
    company_df: pd.DataFrame,
    industry_selection_pipeline: IndustrySelectionPipeline,
    fund_allocated: float,
    gemini_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Convenience function to run the complete stock selection pipeline."""
    pipeline = StockSelectionPipeline(
        company_df,
        industry_selection_pipeline,
        gemini_api_key
    )
    return pipeline.run(fund_allocated)