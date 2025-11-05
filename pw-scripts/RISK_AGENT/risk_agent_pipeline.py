# -*- coding: utf-8 -*-
"""
Risk Agent - Pathway Pipeline

This pipeline monitors a portfolio of assets in real-time:
- Checks stock prices and calculates percentage changes
- Detects when stocks fall below thresholds
- Fetches relevant news for declining stocks
- Uses LLM (Groq) to assess risk and generate alerts
- Outputs structured alerts with severity levels

Run a demo with: python RISK_AGENT/risk_agent_demo.py
"""

import os
import json
from datetime import date, timedelta
from typing import Optional
from dotenv import load_dotenv
import pathway as pw

# Load env vars
load_dotenv()


# ===========================
# Schemas
# ===========================

class PortfolioAssetSchema(pw.Schema):
    ticker: str
    name: str
    quantity: int
    bought_at: float
    down_percent: int  # Threshold percentage for alert


class StockPriceSchema(pw.Schema):
    ticker: str
    name: str
    quantity: int
    bought_at: float
    down_percent: int
    current_price: float
    current_change: float  # Percentage change from bought_at
    day_change: float  # Percentage change for today


class NewsSchema(pw.Schema):
    ticker: str
    source: str
    title: str
    description: str
    url: str


class RiskAlertSchema(pw.Schema):
    ticker: str
    name: str
    alert: str
    severity: str  # "bad", "worse", or "worst"
    urls: str  # JSON array of news URLs
    fall_percent: float
    current_price: float
    current_change: float


# ===========================
# UDFs: Stock Price Fetching
# ===========================

@pw.udf
def get_stock_price(ticker: str) -> Optional[float]:
    """Get current stock price using yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        price = t.fast_info.get("lastPrice")
        return float(price) if price else None
    except Exception as e:
        print(f"[ERROR] get_stock_price({ticker}): {e}")
        return None


@pw.udf
def get_stock_open(ticker: str) -> Optional[float]:
    """Get today's open price."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        open_price = t.fast_info.get("open")
        return float(open_price) if open_price else None
    except Exception as e:
        print(f"[ERROR] get_stock_open({ticker}): {e}")
        return None


@pw.udf
def calculate_current_change(current_price: float, bought_at: float) -> float:
    """Calculate percentage change from bought_at price."""
    if bought_at == 0:
        return 0.0
    return round(((current_price - bought_at) / bought_at) * 100, 2)


@pw.udf
def calculate_day_change(current_price: float, open_price: float) -> float:
    """Calculate percentage change for today."""
    if open_price == 0:
        return 0.0
    return round(((current_price - open_price) / open_price) * 100, 2)


# ===========================
# UDFs: News Fetching
# ===========================

@pw.udf
def fetch_stock_news(ticker: str, name: str, api_key: str) -> str:
    """Fetch recent news for a stock. Returns JSON string."""
    try:
        import requests
        from datetime import date, timedelta
        
        query = f"{name} OR {ticker}"
        url = f"https://newsapi.org/v2/everything?q={query}&searchIn=title,description&sortBy=relevancy&from={str(date.today() - timedelta(days=7))}&apiKey={api_key}"
        
        res = requests.get(url, timeout=15)
        data = res.json()
        
        if data.get("status") != "ok":
            return json.dumps([])
        
        articles = data.get("articles", [])[:2]  # Top 2 articles
        news = [
            {
                "source": article.get("source", {}).get("name", ""),
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "url": article.get("url", "")
            }
            for article in articles
        ]
        
        return json.dumps(news)
    except Exception as e:
        print(f"[ERROR] fetch_stock_news({ticker}): {e}")
        return json.dumps([])


# ===========================
# UDFs: Risk Assessment (Groq LLM)
# ===========================

ASSET_RISK_PROMPT = """
You are a portfolio risk management specialist. You are the expert in your field.

You have been invoked because a stock has gone down below a certain threshold.

You have the following data:
- details of the stock (ticker, name, quantity)
- Original price at which the stock was bought
- Current price of the stock
- Today's down percentage
- News regarding that stock

Your main job:
- Understand the passed news, and check if the news is relevant. If it is relevant, finally generate a short alert to be sent that is grounded on the news received. Alert should be like "<xyz> stock dropped <p>%, <reasons for alert, grounded on news>".
- Understand the severity of the situation, and give the severity as "bad", "worse", "worst"

Output format:
return structured output using the attached schema "asset_risk_schema"

{
    "alert": "string, the alert to be sent",
    "severity": "string, either 'bad', 'worse', or 'worst'"
}
"""

ASSET_RISK_SCHEMA = {
    "title": "asset_risk_schema",
    "description": "schema to validate the output",
    "type": "object",
    "properties": {
        "alert": {"type": "string"},
        "severity": {"type": "string", "enum": ["bad", "worse", "worst"]}
    },
    "required": ["alert", "severity"]
}


@pw.udf
def format_risk_prompt(
    ticker: str,
    name: str,
    bought_at: float,
    current_price: float,
    day_change: float,
    news_json: str,
    fallen_more: bool = False
) -> str:
    """Format prompt for risk assessment."""
    try:
        news = json.loads(news_json) if news_json else []
        
        message = f"""
The stock {ticker} ({name}) bought at {bought_at} has fallen to {current_price} with today's down percentage {day_change}

The recent news related to the stock is : {news}
"""
        
        if fallen_more:
            message += "\nThe user was alerted before and since then the stock has fallen more. Include this in the alert"
        
        full_prompt = f"{ASSET_RISK_PROMPT}\n\n{message}\n\nPlease respond in JSON format with 'alert' and 'severity' fields. Severity must be one of: bad, worse, worst."
        
        return full_prompt
    except Exception as e:
        print(f"[ERROR] format_risk_prompt({ticker}): {e}")
        return f"{ASSET_RISK_PROMPT}\n\nError formatting prompt: {str(e)}"


# ===========================
# Pipeline
# ===========================

def build_risk_agent_pipeline(
    portfolio: pw.Table,
    news_api_key: str,
    groq_api_key: str,
    check_interval_ms: int = 1800000  # 30 minutes default
) -> pw.Table:
    """
    Build risk agent pipeline that monitors portfolio and generates alerts.
    
    Args:
        portfolio: Table with portfolio assets (PortfolioAssetSchema)
        news_api_key: NewsAPI key for fetching news
        groq_api_key: Groq API key for LLM
        check_interval_ms: How often to check prices (in milliseconds)
    
    Returns:
        Table with risk alerts (RiskAlertSchema)
    """
    news_key = news_api_key or os.getenv("NEWS_API_KEY", "")
    groq_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
    
    # Step 1: Fetch current prices
    with_prices = portfolio.select(
        *pw.this,
        current_price=get_stock_price(pw.this.ticker),
        open_price=get_stock_open(pw.this.ticker)
    ).filter(pw.this.current_price.is_not_none())
    
    # Step 2: Calculate percentage changes
    with_changes = with_prices.select(
        *pw.this,
        current_change=calculate_current_change(pw.this.current_price, pw.this.bought_at),
        day_change=calculate_day_change(pw.this.current_price, pw.this.open_price)
    )
    
    # Step 3: Filter stocks that need alerts
    # Alert if: current_change < -down_percent OR day_change < -5
    needs_alert = with_changes.filter(
        (pw.this.current_change < -pw.this.down_percent) | (pw.this.day_change < -5.0)
    )
    
    # Step 4: Fetch news for stocks that need alerts
    with_news = needs_alert.select(
        *pw.this,
        news_json=fetch_stock_news(pw.this.ticker, pw.this.name, news_key)
    )
    
    # Step 5: Format prompts for LLM
    with_prompts = with_news.select(
        ticker=pw.this.ticker,
        name=pw.this.name,
        prompt=format_risk_prompt(
            pw.this.ticker,
            pw.this.name,
            pw.this.bought_at,
            pw.this.current_price,
            pw.this.day_change,
            pw.this.news_json,
            False  # fallen_more - would need to track previous alerts
        ),
        news_json=pw.this.news_json,
        fall_percent=pw.this.day_change,
        current_price=pw.this.current_price,
        current_change=pw.this.current_change
    )
    
    # Step 6: Assess risk with LLM using LiteLLM (direct API call in UDF)
    @pw.udf
    def assess_risk_with_llm(prompt: str, api_key: str) -> str:
        """Assess risk using LiteLLM with Groq. Returns JSON string with alert and severity."""
        try:
            import litellm
            
            if not api_key:
                return json.dumps({"alert": "API key not provided", "severity": "bad"})
            
            # Set API key for Groq
            os.environ["GROQ_API_KEY"] = api_key
            
            # Use LiteLLM to call Groq
            response = litellm.completion(
                model="groq/openai/gpt-oss-120b",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            
            # Parse JSON response
            try:
                parsed = json.loads(content)
                # Validate severity
                if parsed.get("severity") not in ["bad", "worse", "worst"]:
                    parsed["severity"] = "bad"
                return json.dumps(parsed)
            except json.JSONDecodeError:
                # If JSON parsing fails, try to extract from text
                import re
                json_match = re.search(r'\{[^{}]*"alert"[^{}]*"severity"[^{}]*\}', content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    if parsed.get("severity") not in ["bad", "worse", "worst"]:
                        parsed["severity"] = "bad"
                    return json.dumps(parsed)
                return json.dumps({
                    "alert": content[:200] if content else "Error parsing response",
                    "severity": "bad"
                })
        except Exception as e:
            print(f"[ERROR] assess_risk_with_llm: {e}")
            import traceback
            traceback.print_exc()
            return json.dumps({"alert": f"Error assessing risk: {str(e)}", "severity": "bad"})
    
    # Call LLM using LiteLLM
    with_parsed_risk = with_prompts.select(
        ticker=pw.this.ticker,
        name=pw.this.name,
        risk_json=assess_risk_with_llm(pw.this.prompt, groq_key),
        news_json=pw.this.news_json,
        fall_percent=pw.this.fall_percent,
        current_price=pw.this.current_price,
        current_change=pw.this.current_change
    )
    
    # Step 7: Parse and format alerts
    @pw.udf
    def parse_risk_alert(risk_json: str, news_json: str) -> str:
        """Parse risk assessment and format alert."""
        try:
            risk = json.loads(risk_json) if risk_json else {}
            news = json.loads(news_json) if news_json else []
            
            alert_data = {
                "alert": risk.get("alert", "No alert generated"),
                "severity": risk.get("severity", "bad"),
                "urls": [n.get("url", "") for n in news if n.get("url")]
            }
            return json.dumps(alert_data)
        except Exception as e:
            print(f"[ERROR] parse_risk_alert: {e}")
            return json.dumps({"alert": "Error parsing alert", "severity": "bad", "urls": []})
    
    @pw.udf
    def extract_alert(parsed_json: str) -> str:
        """Extract alert text."""
        try:
            data = json.loads(parsed_json)
            return data.get("alert", "")
        except:
            return ""
    
    @pw.udf
    def extract_severity(parsed_json: str) -> str:
        """Extract severity."""
        try:
            data = json.loads(parsed_json)
            return data.get("severity", "bad")
        except:
            return "bad"
    
    @pw.udf
    def extract_urls(parsed_json: str) -> str:
        """Extract URLs as JSON string."""
        try:
            data = json.loads(parsed_json)
            return json.dumps(data.get("urls", []))
        except:
            return json.dumps([])
    
    alerts = with_parsed_risk.select(
        ticker=pw.this.ticker,
        name=pw.this.name,
        parsed_risk=parse_risk_alert(pw.this.risk_json, pw.this.news_json),
        fall_percent=pw.this.fall_percent,
        current_price=pw.this.current_price,
        current_change=pw.this.current_change
    ).select(
        ticker=pw.this.ticker,
        name=pw.this.name,
        alert=extract_alert(pw.this.parsed_risk),
        severity=extract_severity(pw.this.parsed_risk),
        urls=extract_urls(pw.this.parsed_risk),
        fall_percent=pw.this.fall_percent,
        current_price=pw.this.current_price,
        current_change=pw.this.current_change
    )
    
    return alerts


def main():
    print("This module defines pipeline functions. See risk_agent_demo.py for usage.")


if __name__ == "__main__":
    main()

