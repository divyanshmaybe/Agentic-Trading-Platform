# -*- coding: utf-8 -*-
"""
News Sentiment Based Trading - Pathway Pipeline

This pipeline:
- Fetches news articles from NewsAPI for 23 sectors
- Analyzes sentiment using FinBERT
- Provides functions for trading agent and stock recommender (called from demo)
"""

import os
import json
from typing import List
from dotenv import load_dotenv
import pathway as pw
from langchain_core.messages import SystemMessage, HumanMessage
import re

# Load env vars
load_dotenv()

# All 23 news streams
NEWS_STREAMS = {
    "Financial Services": 'finance OR banking OR insurance OR investments OR "financial regulation" OR "bank earnings" OR fintech',
    "Diversified": 'conglomerate OR diversified OR "business group" OR "multiple industries"',
    "Capital Goods": 'capital goods OR manufacturing OR machinery OR equipment OR "industrial production"',
    "Construction Materials": 'construction materials OR cement OR steel OR building materials OR infrastructure',
    "Power": 'power OR electricity OR utilities OR energy OR "renewable energy"',
    "Fast Moving Consumer Goods": 'FMCG OR consumer goods OR food OR beverages OR personal care OR hygiene',
    "Chemicals": 'chemicals OR petrochemicals OR fertilizers OR polymers OR industrial chemicals',
    "Healthcare": 'healthcare OR pharmaceuticals OR biotechnology OR "drug approval" OR "clinical trials" OR "medical devices"',
    "Metals & Mining": 'metals OR mining OR steel OR aluminium OR minerals OR extraction',
    "Services": 'services OR outsourcing OR consulting OR BPO OR IT services OR support services',
    "Oil Gas & Consumable Fuels": 'oil OR gas OR petroleum OR "consumable fuels" OR exploration OR refining',
    "Consumer Services": 'retail OR consumer services OR hospitality OR tourism OR entertainment',
    "Forest Materials": 'forest products OR timber OR paper OR pulp OR wood products',
    "Construction": 'construction OR real estate OR infrastructure OR civil engineering',
    "Information Technology": 'information technology OR IT OR software OR "artificial intelligence" OR AI OR "machine learning"',
    "Consumer Durables": 'consumer durables OR electronics OR appliances OR automobiles OR automobiles components',
    "Textiles": 'textiles OR garments OR fabrics OR apparel OR clothing industry',
    "Automobile and Auto Components": 'automobile OR cars OR auto components OR vehicles OR manufacturing',
    "Realty": 'realty OR real estate OR property OR housing OR commercial real estate',
    "Telecommunication": 'telecommunication OR telecom OR broadband OR wireless OR mobile networks',
    "Media Entertainment & Publication": 'media OR entertainment OR broadcasting OR publishing OR streaming OR film OR music industry',
    "Politics": 'politics OR election OR government OR regulation OR diplomacy OR trade policy OR foreign affairs OR war',
    "Social Media": 'social media OR influencer OR viral OR digital campaign OR TikTok OR Instagram OR Twitter OR Facebook'
}

# ===========================
# Schemas
# ===========================

class StreamSchema(pw.Schema):
    stream: str
    query: str
    top_k: int


class StockSchema(pw.Schema):
    symbol: str
    industry: str


# ===========================
# UDFs: NewsAPI Retrieval & FinBERT Sentiment
# ===========================

@pw.udf
def fetch_articles(stream: str, query: str, top_k: int, api_key: str) -> List[tuple]:
    """Fetch top-k articles from NewsAPI for a query. Returns list of (title, content)."""
    try:
        import requests
        base = "https://newsapi.org/v2/everything"
        params = {
            "q": f"({query}) AND India",
            "language": "en",
            "pageSize": top_k,
            "apiKey": api_key,
            "sortBy": "publishedAt",
        }
        r = requests.get(base, params=params, timeout=15)
        data = r.json()
        if data.get("status") != "ok":
            return []
        articles = []
        for a in data.get("articles", []):
            title = a.get("title") or ""
            content = a.get("content") or a.get("description") or title
            url = a.get("url") or ""
            if "[" in content and content.strip().endswith("]"):
                content = content.rsplit("[", 1)[0].strip()
            articles.append((title, content, url))
        return articles
    except Exception as e:
        print(f"[WARN] fetch_articles({stream}) failed: {e}")
        return []


@pw.udf
def finbert_sentiment(title: str, content: str) -> str:
    """Run FinBERT Tone classification and return label: positive|neutral|negative."""
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch
        import torch.nn.functional as F

        # Lazy init with simple cache on globals
        global _finbert_tok, _finbert_model, _finbert_device
        if '_finbert_tok' not in globals():
            _finbert_tok = AutoTokenizer.from_pretrained("yiyanghkust/finbert-tone")
        if '_finbert_model' not in globals():
            model = AutoModelForSequenceClassification.from_pretrained("yiyanghkust/finbert-tone")
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            model.to(device)
            model.eval()
            _finbert_model = model
            _finbert_device = device

        text = f"{title} {content}".strip()
        inputs = _finbert_tok(text, return_tensors='pt', truncation=True, padding=True, max_length=256).to(_finbert_device)
        with torch.no_grad():
            outputs = _finbert_model(**inputs)
            probs = F.softmax(outputs.logits, dim=-1)
            pred = torch.argmax(probs, dim=1).item()
        label_map = {0: "neutral", 1: "positive", 2: "negative"}
        return label_map.get(pred, "neutral")
    except Exception as e:
        print(f"[WARN] finbert_sentiment failed: {e}")
        return "neutral"


# ===========================
# Pipeline
# ===========================

def build_news_sentiment_pipeline(streams: pw.Table, news_api_key: str, top_k_default: int = 3) -> pw.Table:
    """Build news sentiment pipeline: streams -> articles -> sentiment."""
    api_key_val = news_api_key or os.getenv("NEWS_ORG_API_KEY", "")

    streams_prep = streams.select(
        stream=pw.this.stream,
        query=pw.this.query,
        top_k=pw.coalesce(pw.this.top_k, top_k_default)
    )

    # Fetch articles per stream
    fetched = streams_prep.select(
        stream=pw.this.stream,
        articles=fetch_articles(pw.this.stream, pw.this.query, pw.this.top_k, api_key_val)
    )

    # Flatten to individual articles
    flat = fetched.flatten(pw.this.articles).select(
        stream=pw.this.stream,
        title=pw.this.articles[0],
        content=pw.this.articles[1],
        url=pw.this.articles[2]
    )

    # Sentiment per article
    scored = flat.select(
        stream=pw.this.stream,
        title=pw.this.title,
        content=pw.this.content,
        url=pw.this.url,
        sentiment=finbert_sentiment(pw.this.title, pw.this.content)
    )

    return scored


# ===========================
# Trading Agent (Gemini LLM) - Regular function, not UDF
# ===========================

def trading_agent_llm(sentiment_json: str, api_key: str) -> str:
    """Call Gemini LLM to generate sector-level trading signals from sentiment data."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        sentiment_data = json.loads(sentiment_json)
        
        prompt = """
You are a sophisticated trading agent tasked with generating actionable short-term trade signals based on a combination of news content and sentiment from multiple financial news streams.

Each stream provides the top three most recent and relevant news articles, along with their sentiment scores derived from a robust sentiment analysis model.

Your ultimate goal is to analyze these inputs efficiently and produce clear buy, sell, or hold signals for relevant assets.

For each stream, you receive:
 - The top three news articles, including headlines and concise summaries.
 - A sentiment score for each article, rated from -1 (strongly negative) to +1 (strongly positive).
 - The stream topic/category (e.g., Macroeconomic news, Technology sector, Market indices).

Analyze the semantic content of the three articles within each news stream, focusing on key market-moving factors like macroeconomic indicators, sector-specific developments, geopolitical events, and investor sentiment.

Integrate the sentiment scores alongside content to gauge the overall qualitative mood (positive, neutral, negative) of the stream in the current context.

Aggregate the three articles' sentiment scores and content to form a composite sentiment indicator per stream.

Evaluate the potential impact on asset prices, considering both the strength of sentiment and the specificity of news content (e.g., earnings beats, policy changes, market volatility signals).

Incorporate understanding of market context such as current trends, volatility levels, and historical reaction patterns linked to similar news.

For each stream, generate a short-term trade signal categorized as:
 - Buy: If the overall sentiment is strongly positive and news indicates potential upward price momentum.
 - Sell: If sentiment is strongly negative, suggesting downside risk or adverse market impact.
 - Hold/Neutral: If sentiment is mixed, weak, or no clear directional cues emerge.

Avoid overreacting to single articles; prioritize the sentiment consensus among the three articles to reduce noise.

Consider temporal relevance; prioritize more recent articles and check for repeated themes across updates.

Incorporate risk management cues, flagging signals where sentiment or news content signals potential for high volatility or reversals.

When sentiment and content conflict (e.g., positive sentiment but news is mixed or uncertain), default to hold and flag for review.

Provide a concise summary explanation with each signal to justify your recommendation based on content and sentiment.

Be very cautious while analysing the news, since the market movement can be both long term and short term- therefore it is your job as a financial expert to decide a specific time window for necessary market positions- for example if the signal is BUY- the time window indicates the right time to buy the shares, whether the next 10 years or whether it is the next minute.I want only the immediate trading recommendations- so much so that I can buy or sell the stock on the current trading day itself-YOUR TASK IS TO ONLY GENERATE SHORT TERM TRADING SIGNALS.

We are catering specifically to the Indian Market. Thus, all the global news for all sectors must strictly be co-verified with India's existing status in all these sectors, since the trading signals are to be generated specifically with reference to Indian markets and investment firms. Also, be very cautious while generating a buy or a sell signal, since a buy or a sell signal wrongly classified as a hold signal is hazardous, but a hold signal wrongly classified as a buy or a sell signal is extremely risky and dangerous. Only generate a buy or a sell signal with an apt time window for investment as long as you are extremely confident about the same. Also be careful while analysing sectors and individual companies.

For example, pertaining to certain war situations or a medical news like COVID outbreak, the market sentiment may be down or bearish, however a renound company like Reliance or TATA, their shares may go down but due to the trust on their credibility it would rather be better to buy them, because right now their shares might be at a lower price but in the future, the price will increase, and over long term it would be profitable. Since you are tasked with only generating short term signals, you must be careful in analysing such situations and not generating an immediate sell signal for such companies under such circumstances or news articles.
The response you generate will be directly passed to a final sector and stock based trade recommendation agent
therefore, for every news article, you must clearly mention its source url, since that will be displayed
to the user for making the final recommendations.
"""
        
        for stream, articles in sentiment_data.items():
            prompt += f"\nSector: {stream}\n"
            for a in articles:
                prompt += f"- News title: {a['title']} | News Description: {a['content']} | Sentiment: {a['sentiment']} | News URL: {a.get('url', 'N/A')}\n"
            prompt += "\n"
        
        model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.7,
            api_key=api_key
        )
        decision = model.invoke(prompt)
        return decision.content if hasattr(decision, 'content') else str(decision)
    except Exception as e:
        import traceback
        error_msg = f"Error generating trading signals: {str(e)}\n{traceback.format_exc()}"
        print(f"[ERROR] trading_agent_llm: {error_msg}")
        return f"Error generating trading signals: {str(e)}"


# ===========================
# UDFs: Technical Indicators
# ===========================

@pw.udf
def get_technical_indicators(symbol: str) -> str:
    """Fetch technical indicators for a stock symbol. Returns JSON string."""
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
        
        # Manual technical indicator calculations (since pandas_ta requires Python 3.12+)
        def calculate_sma(data, period):
            return data.rolling(window=period).mean()
        
        def calculate_ema(data, period):
            return data.ewm(span=period, adjust=False).mean()
        
        def calculate_rsi(data, period=14):
            delta = data.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi
        
        def calculate_bollinger_bands(data, period=20, std_dev=2):
            sma = calculate_sma(data, period)
            std = data.rolling(window=period).std()
            upper = sma + (std * std_dev)
            lower = sma - (std * std_dev)
            return upper, lower
        
        def calculate_stochastic(high, low, close, k_period=14):
            lowest_low = low.rolling(window=k_period).min()
            highest_high = high.rolling(window=k_period).max()
            k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
            return k_percent
        
        ticker = f"{symbol}.NS"
        t = yf.Ticker(ticker)
        
        daily = t.history(period="3mo", interval="1d", auto_adjust=True)
        hourly = t.history(period="2d", interval="1h", auto_adjust=True)
        
        if not hourly.empty:
            hourly['Date'] = hourly.index.date
            today = pd.Timestamp.today().date()
            hourly_today = hourly[hourly['Date'] == today].drop(columns=['Date'])
            data = pd.concat([daily, hourly_today])
        else:
            data = daily
        
        if data is None or data.empty or len(data) < 20:
            return json.dumps(None)
        
        out = {}
        out['Symbol'] = symbol
        out['SMA20'] = float(calculate_sma(data['Close'], 20).iloc[-1])
        out['EMA20'] = float(calculate_ema(data['Close'], 20).iloc[-1])
        out['RSI14'] = float(calculate_rsi(data['Close'], 14).iloc[-1])
        out['ADX14'] = None  # ADX is complex, skipping for now
        
        bb_upper, bb_lower = calculate_bollinger_bands(data['Close'], 20, 2)
        out['BB_UPPER'] = float(bb_upper.iloc[-1])
        out['BB_LOWER'] = float(bb_lower.iloc[-1])
        
        out['STOCHK'] = float(calculate_stochastic(data['High'], data['Low'], data['Close'], 14).iloc[-1])
        
        return json.dumps(out)
    except Exception as e:
        print(f"[ERROR] get_technical_indicators({symbol}): {e}")
        return json.dumps(None)


# ===========================
# Stock Recommender (Gemini LLM) - Regular function, not UDF
# ===========================

def stock_recommender_llm(sector_analysis: str, tech_json: str, api_key: str) -> str:
    """Call Gemini LLM to recommend specific stocks based on sector analysis and technical indicators."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        prompts = [SystemMessage("""
You are a stock recommendation AI agent responsible for providing top stock investment recommendations by integrating sector-wise insights from a news sentiment agent and detailed technical indicators for each stock.

You should take as input sector-wise sentiment scores, time windows for investing, and explanations from the news sentiment agent detailing why and when to invest in each sector.

You should also receive a comprehensive table of technical indicators per stock, such as moving averages, RSI, MACD, Bollinger Bands, and volume metrics.

Your task is to combine the sector sentiment analysis with technical strengths or weaknesses of individual stocks, scoring and ranking stocks that belong to sectors with positive sentiment and favorable time windows.

Recommend the top stocks by providing for each the stock ticker, sector, investment time window, and a clear explanation that ties the sector sentiment with the technical indicators that support the investment decision.

For stocks or sectors with negative sentiment or weak technicals, exclude or flag them with explicit reasons.

Structure the output in a clear, user-friendly format summarizing sector sentiments followed by top stock recommendations with actionable time windows and transparent reasoning.

This approach will enable users to make timely, well-informed investment decisions grounded in both macro-level sector sentiment and micro-level technical stock analysis.

Be very cautious while analysing the news, since the market movement can be both long term and short term- therefore it is your job as a financial expert to decide a specific time window for necessary market positions- for example if the signal is BUY- the time window indicates the right time to buy the shares, whether the next 10 years or whether it is the next minute.I want only the immediate trading recommendations- so much so that I can buy or sell the stock on the current trading day itself-YOUR TASK IS TO ONLY GENERATE SHORT TERM TRADING SIGNALS. and also analyse the impact of the news article and also detect fake news headlines which may not create any difference or are simply false alarms.

Also, be very cautious while generating a buy or a sell signal, since a buy or a sell signal wrongly classified as a hold signal is hazardous, but a hold signal wrongly classified as a buy or a sell signal is extremely risky and dangerous. Only generate a buy or a sell signal with an apt time window for investment as long as you are extremely confident about the same.

The technical indicators you have been provided is for nifty 500 stocks, thus we are catering strongly to the Inidan market.
The table is in the json format and the sector based analysis is in markdown format so analyse accordingly

Also, you are supposed to do a detailed analysis of the technical indicators provided in the json and strike a balance between sentiment and technicality
You must return a structured json output in the following format:
    {
        sector:<sector_name>,
        stock_name:<stock_name>,
        trade_signal:<trade_signal>,
        detailed_analysis:<detailed_analysis>,
        time_window_investment:<time_window_for_investment>,
        news_source:<news_url>
    }
 Output must be a single JSON array containing one object per sector.
 Use valid JSON syntax (double quotes, commas, brackets).
 You must strictly adhere to this output format and must return a valid array of json objects.
 Do not return anything apart from this, such as here's the summary or here's the answer.
 Return only an array of json strings and nothing else
""")]

        prompts.append(HumanMessage(f"""Here is the sector based analysis: {sector_analysis}.
                                    Here is the json for the technical indicators for nifty 500
                                    stocks: {tech_json}"""))
        
        model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.7,
            api_key=api_key
        )
        decision = model.invoke(prompts)
        text = getattr(decision, "content", str(decision)).strip()

        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            text = text.strip()
        first_bracket, last_bracket = text.find("["), text.rfind("]")
        if first_bracket == -1 or last_bracket == -1:
            return {"error": "No JSON array found in LLM output", "raw_text": text[:1000]}

        json_text = text[first_bracket:last_bracket + 1]
        json_text = re.sub(
            r'("news_source"\s*:\s*)(https?://[^\s,}\]]+)',
            lambda m: f'{m.group(1)}"{m.group(2)}"',
            json_text
        )
        json_text = re.sub(r",\s*([\]}])", r"\1", json_text)
        try:
            parsed = json.loads(json_text)
            if not isinstance(parsed, list):
                return {"error": "Parsed JSON is not an array", "parsed_type": type(parsed).__name__, "parsed_value": parsed}
            return parsed
        except Exception as e:
            return {
                "error": f"JSON parse failed: {e}",
                "cleaned_json_snippet": json_text[:1000],
                "raw_text_snippet": text[:1000]
            }

    except Exception as e:
        import traceback
        error_msg = f"Error generating stock recommendations: {str(e)}\n{traceback.format_exc()}"
        print(f"[ERROR] stock_recommender_llm: {error_msg}")
        return {"error": str(e)}


def main():
    print("This module defines pipeline functions. See news_sentiment_demo.py for usage.")


if __name__ == "__main__":
    main()
