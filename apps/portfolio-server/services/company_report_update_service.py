"""
Company Report Update Service

Handles company report updates triggered by:
1. NSE Filings - Real-time updates when relevant filings are scraped
2. News Articles - Scheduled at market close (3:30 PM IST)

Original Research: Qualitative Database Updation - NSE & News (Colab)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# Add shared/py to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from company_report_service import CompanyReportService

# Local imports
from utils.low_risk_utils import (
    load_prompt_from_template,
    parse_json_response,
    clean_markdown_from_response,
    extract_json_from_text,
)

logger = logging.getLogger(__name__)

# Load environment
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

# Relevant NSE filing categories that trigger report updates
RELEVANT_NSE_FILING_CATEGORIES = [
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


class CompanyReportUpdateService:
    """
    Service for updating company reports based on NSE filings and news.

    Implements two update flows:
    1. NSE Filing Update - Triggered by NSE scraper when filing matches relevant categories
    2. News Update - Scheduled at market close (3:30 PM IST)
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        report_service: Optional[CompanyReportService] = None,
    ):
        """
        Initialize the company report update service.

        Args:
            gemini_api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            report_service: CompanyReportService instance (defaults to singleton)
        """
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        self.report_service = report_service or CompanyReportService.get_instance()
        self._initialized = False

        # Load prompts
        self._nse_prompt_data = self._load_yaml_template("company_report_nse_update_prompt")
        self._news_prompt_data = self._load_yaml_template("company_report_news_update_prompt")

        logger.info("✅ CompanyReportUpdateService initialized")

    def _load_yaml_template(self, template_name: str) -> Dict[str, Any]:
        """Load a YAML template and return its full data."""
        import yaml

        template_dir = Path(__file__).parent.parent / "templates"
        template_file = template_dir / f"{template_name}.yaml"

        if not template_file.exists():
            raise FileNotFoundError(f"Template not found: {template_file}")

        with open(template_file, "r") as f:
            return yaml.safe_load(f)

    async def initialize(self) -> None:
        """Initialize async resources (MongoDB/Redis connections)."""
        if not self._initialized:
            await self.report_service.initialize()
            self._initialized = True
            logger.debug("✅ CompanyReportUpdateService async resources initialized")

    async def ticker_exists_in_db(self, ticker: str) -> bool:
        """
        Check if a ticker exists in the company reports database.

        Args:
            ticker: Stock ticker symbol (e.g., "RELIANCE")

        Returns:
            True if ticker exists in database, False otherwise
        """
        if not self._initialized:
            await self.initialize()

        try:
            report = await self.report_service.get_report_by_ticker(ticker)
            exists = report is not None
            logger.debug(f"Ticker {ticker} exists in DB: {exists}")
            return exists
        except Exception as e:
            logger.error(f"Error checking ticker existence for {ticker}: {e}")
            return False

    def _create_llm(self, with_search_tool: bool = False) -> ChatGoogleGenerativeAI:
        """Create LLM instance with optional Google Search tool."""
        model_name = self._nse_prompt_data.get("model", "gemini-2.5-flash")

        model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=self.gemini_api_key,
            temperature=0.5,
        )

        if with_search_tool:
            model = model.bind_tools([{"google_search": {}}])

        return model

    def _parse_update_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse the LLM response for update flag and report.

        Returns:
            Dict with 'flag' ('UPDATED' or 'NO_UPDATE') and 'report' (dict or None)
        """
        try:
            # Clean and extract JSON
            cleaned = clean_markdown_from_response(response_text)
            json_str = extract_json_from_text(cleaned)

            result = json.loads(json_str)

            # Validate structure
            if "flag" not in result:
                logger.warning("Response missing 'flag' field, defaulting to NO_UPDATE")
                return {"flag": "NO_UPDATE", "report": None}

            flag = result.get("flag", "NO_UPDATE").upper()
            report = result.get("report")

            if flag not in ("UPDATED", "NO_UPDATE"):
                logger.warning(f"Invalid flag value '{flag}', defaulting to NO_UPDATE")
                flag = "NO_UPDATE"

            return {"flag": flag, "report": report}

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            return {"flag": "NO_UPDATE", "report": None}
        except Exception as e:
            logger.error(f"Unexpected error parsing response: {e}")
            return {"flag": "NO_UPDATE", "report": None}

    # =========================================================================
    # NSE Filing Update
    # =========================================================================

    def is_relevant_nse_filing(self, filing_category: str) -> bool:
        """Check if an NSE filing category is relevant for report updates."""
        if not filing_category:
            return False

        # Normalize and check
        category_lower = filing_category.lower().strip()
        for relevant in RELEVANT_NSE_FILING_CATEGORIES:
            if relevant.lower() in category_lower or category_lower in relevant.lower():
                return True
        return False

    async def update_from_nse_filing(
        self,
        ticker: str,
        pdf_base64: str,
        filing_category: str,
        filing_subject: str = "",
        filing_date: str = "",
    ) -> Dict[str, Any]:
        """
        Update company report based on NSE filing.

        This method is called by the NSE scraper when a relevant filing is detected.

        Args:
            ticker: Stock ticker symbol (e.g., "RELIANCE")
            pdf_base64: Base64 encoded PDF content of the filing
            filing_category: Category of the filing (e.g., "Outcome of Board Meeting")
            filing_subject: Subject/title of the announcement
            filing_date: Date of the filing

        Returns:
            Dict with update status and any changes made
        """
        await self.initialize()

        ticker_upper = ticker.upper()
        logger.info(f"📄 Processing NSE filing update for {ticker_upper}: {filing_category}")

        try:
            # 1. Fetch current report from DB
            current_report = await self.report_service.get_report_by_ticker(ticker_upper)

            if not current_report:
                logger.warning(f"No existing report found for {ticker_upper}, skipping update")
                return {
                    "status": "skipped",
                    "reason": "no_existing_report",
                    "ticker": ticker_upper,
                }

            # 2. Build prompt
            system_prompt = self._nse_prompt_data.get("system_context", "")
            prompt_template = self._nse_prompt_data.get("prompt_template", "")
            output_instructions = self._nse_prompt_data.get("output_instructions", "")

            # Render prompt with variables
            user_prompt = prompt_template.format(
                ticker=ticker_upper,
                current_report=json.dumps(current_report, indent=2, default=str),
                filing_category=filing_category,
                filing_subject=filing_subject,
                filing_date=filing_date,
            )

            full_system_prompt = f"{system_prompt}\n\n{output_instructions}"

            # 3. Create LLM and invoke with PDF
            model = self._create_llm(with_search_tool=False)

            messages = [
                SystemMessage(content=full_system_prompt),
                HumanMessage(
                    content=[
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "file",
                            "mime_type": "application/pdf",
                            "data": pdf_base64,
                        },
                    ]
                ),
            ]

            response = model.invoke(messages)
            response_text = response.content if hasattr(response, "content") else str(response)

            # 4. Parse response
            result = self._parse_update_response(response_text)

            # 5. Handle based on flag
            if result["flag"] == "NO_UPDATE":
                logger.info(f"✅ No update needed for {ticker_upper} (NSE filing: {filing_category})")
                return {
                    "status": "no_update",
                    "ticker": ticker_upper,
                    "filing_category": filing_category,
                }

            # 6. Update report in DB (this also clears cache)
            updated_report = result["report"]
            if updated_report:
                # Ensure ticker is preserved
                updated_report["ticker"] = ticker_upper

                # Preserve _id if present in original
                if "_id" in current_report and "_id" not in updated_report:
                    updated_report["_id"] = current_report["_id"]

                # Preserve created_at
                if "created_at" in current_report:
                    updated_report["created_at"] = current_report["created_at"]

                # Set updated_at
                updated_report["updated_at"] = datetime.now(timezone.utc).isoformat()

                await self.report_service.upsert_report(updated_report)
                logger.info(f"✅ Updated report for {ticker_upper} from NSE filing: {filing_category}")

                return {
                    "status": "updated",
                    "ticker": ticker_upper,
                    "filing_category": filing_category,
                    "updated_at": updated_report["updated_at"],
                }

            return {
                "status": "error",
                "reason": "empty_report_in_response",
                "ticker": ticker_upper,
            }

        except Exception as e:
            logger.error(f"❌ Failed to update {ticker_upper} from NSE filing: {e}", exc_info=True)
            return {
                "status": "error",
                "ticker": ticker_upper,
                "error": str(e),
            }

    # =========================================================================
    # News-Based Update
    # =========================================================================

    async def update_from_news(
        self,
        ticker: str,
        news_articles: List[Dict[str, Any]],
        overall_sentiment: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Update company report based on news articles.

        This method is called at market close (3:30 PM IST) for stocks with news.

        Args:
            ticker: Stock ticker symbol (e.g., "RELIANCE")
            news_articles: List of news articles with title, description, sentiment
            overall_sentiment: Aggregated sentiment score (0.0 to 1.0)

        Returns:
            Dict with update status and any changes made
        """
        await self.initialize()

        ticker_upper = ticker.upper()
        logger.info(f"📰 Processing news update for {ticker_upper} ({len(news_articles)} articles)")

        if not news_articles:
            logger.debug(f"No news articles for {ticker_upper}, skipping")
            return {
                "status": "skipped",
                "reason": "no_news_articles",
                "ticker": ticker_upper,
            }

        try:
            # 1. Fetch current report from DB
            current_report = await self.report_service.get_report_by_ticker(ticker_upper)

            if not current_report:
                logger.warning(f"No existing report found for {ticker_upper}, skipping news update")
                return {
                    "status": "skipped",
                    "reason": "no_existing_report",
                    "ticker": ticker_upper,
                }

            # 2. Calculate sentiment stats
            positive_count = sum(1 for a in news_articles if a.get("sentiment", "").lower() == "positive")
            negative_count = sum(1 for a in news_articles if a.get("sentiment", "").lower() == "negative")
            neutral_count = len(news_articles) - positive_count - negative_count

            # Format news articles for prompt
            news_text = "\n\n".join([
                f"Title: {a.get('title', 'N/A')}\n"
                f"Description: {a.get('description', a.get('content', 'N/A'))}\n"
                f"Sentiment: {a.get('sentiment', 'neutral')}\n"
                f"Source: {a.get('url', a.get('source', 'N/A'))}"
                for a in news_articles
            ])

            # 3. Build prompt
            system_prompt = self._news_prompt_data.get("system_context", "")
            prompt_template = self._news_prompt_data.get("prompt_template", "")
            output_instructions = self._news_prompt_data.get("output_instructions", "")

            user_prompt = prompt_template.format(
                ticker=ticker_upper,
                company_name=current_report.get("company_name", ticker_upper),
                current_report=json.dumps(current_report, indent=2, default=str),
                news_articles=news_text,
                overall_sentiment=f"{overall_sentiment:.2f}",
                positive_count=positive_count,
                negative_count=negative_count,
                neutral_count=neutral_count,
            )

            full_system_prompt = f"{system_prompt}\n\n{output_instructions}"

            # 4. Create LLM with Google Search tool and invoke
            model = self._create_llm(with_search_tool=True)

            messages = [
                SystemMessage(content=full_system_prompt),
                HumanMessage(content=user_prompt),
            ]

            response = model.invoke(messages)
            response_text = response.content if hasattr(response, "content") else str(response)

            # 5. Parse response
            result = self._parse_update_response(response_text)

            # 6. Handle based on flag
            if result["flag"] == "NO_UPDATE":
                logger.info(f"✅ No update needed for {ticker_upper} (news analysis)")
                # Cache is preserved - no DB write
                return {
                    "status": "no_update",
                    "ticker": ticker_upper,
                    "articles_analyzed": len(news_articles),
                }

            # 7. Update report in DB (this also clears cache)
            updated_report = result["report"]
            if updated_report:
                # Ensure ticker is preserved
                updated_report["ticker"] = ticker_upper

                # Preserve _id if present in original
                if "_id" in current_report and "_id" not in updated_report:
                    updated_report["_id"] = current_report["_id"]

                # Preserve created_at
                if "created_at" in current_report:
                    updated_report["created_at"] = current_report["created_at"]

                # Set updated_at
                updated_report["updated_at"] = datetime.now(timezone.utc).isoformat()

                await self.report_service.upsert_report(updated_report)
                logger.info(f"✅ Updated report for {ticker_upper} from news analysis")

                return {
                    "status": "updated",
                    "ticker": ticker_upper,
                    "articles_analyzed": len(news_articles),
                    "updated_at": updated_report["updated_at"],
                }

            return {
                "status": "error",
                "reason": "empty_report_in_response",
                "ticker": ticker_upper,
            }

        except Exception as e:
            logger.error(f"❌ Failed to update {ticker_upper} from news: {e}", exc_info=True)
            return {
                "status": "error",
                "ticker": ticker_upper,
                "error": str(e),
            }

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def batch_update_from_news(
        self,
        news_by_ticker: Dict[str, List[Dict[str, Any]]],
        sentiments_by_ticker: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Batch update multiple company reports from news.

        Called at market close to process all news for the day.

        Args:
            news_by_ticker: Dict mapping ticker to list of news articles
            sentiments_by_ticker: Optional dict mapping ticker to overall sentiment

        Returns:
            Summary of updates performed
        """
        await self.initialize()

        sentiments = sentiments_by_ticker or {}
        results = {
            "total": len(news_by_ticker),
            "updated": 0,
            "no_update": 0,
            "skipped": 0,
            "errors": 0,
            "details": [],
        }

        logger.info(f"📰 Starting batch news update for {len(news_by_ticker)} tickers")

        for ticker, articles in news_by_ticker.items():
            try:
                sentiment = sentiments.get(ticker, 0.5)
                result = await self.update_from_news(ticker, articles, sentiment)

                status = result.get("status", "error")
                if status == "updated":
                    results["updated"] += 1
                elif status == "no_update":
                    results["no_update"] += 1
                elif status == "skipped":
                    results["skipped"] += 1
                else:
                    results["errors"] += 1

                results["details"].append(result)

            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
                results["errors"] += 1
                results["details"].append({
                    "status": "error",
                    "ticker": ticker,
                    "error": str(e),
                })

        logger.info(
            f"✅ Batch news update complete: "
            f"{results['updated']} updated, "
            f"{results['no_update']} no change, "
            f"{results['skipped']} skipped, "
            f"{results['errors']} errors"
        )

        return results


# Singleton instance
_service_instance: Optional[CompanyReportUpdateService] = None


def get_company_report_update_service(
    gemini_api_key: Optional[str] = None,
) -> CompanyReportUpdateService:
    """Get or create singleton instance of CompanyReportUpdateService."""
    global _service_instance

    if _service_instance is None:
        _service_instance = CompanyReportUpdateService(gemini_api_key=gemini_api_key)

    return _service_instance


__all__ = [
    "CompanyReportUpdateService",
    "get_company_report_update_service",
    "RELEVANT_NSE_FILING_CATEGORIES",
]
