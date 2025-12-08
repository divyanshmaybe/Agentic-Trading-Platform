"""Vendored news sentiment research utilities.

This module mirrors the experimental implementation that lives under
``pw-scripts/NEWS_SENTIMENT`` so the portfolio server can operate without that
directory being present.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pathway as pw
from langchain_core.messages import HumanMessage, SystemMessage
import pandas as pd

# Initialize Phoenix tracing for news research pipeline
try:
    from phoenix.otel import register
    
    collector_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    if collector_endpoint:
        tracer_provider = register(
            project_name="news-research-pipeline",
            endpoint=collector_endpoint,
            auto_instrument=True,
        )
        print(f"✅ Phoenix tracing initialized for news research: {collector_endpoint}")
except ImportError:
    pass
except Exception:
    pass

try:
    from market_data import get_market_data_service  # type: ignore
except ImportError:  # pragma: no cover - defensive
    get_market_data_service = None  # type: ignore


# ---------------------------------------------------------------------------
# Streams and schemas
# ---------------------------------------------------------------------------

NEWS_STREAMS: Dict[str, str] = {
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
    "Social Media": 'social media OR influencer OR viral OR digital campaign OR TikTok OR Instagram OR Twitter OR Facebook',
}


class StreamSchema(pw.Schema):
    stream: str
    query: str
    top_k: int


class StockSchema(pw.Schema):
    symbol: str
    industry: str


# ---------------------------------------------------------------------------
# News retrieval and sentiment
# ---------------------------------------------------------------------------


def _fetch_news_api(stream: str, query: str, top_k: int, api_key: str) -> List[tuple]:
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
        response = requests.get(base, params=params, timeout=15)
        data = response.json()
        if data.get("status") != "ok":
            message = data.get("message")
            print(f"[WARN] API error for {stream}: {message}")
            return []

        articles: List[tuple] = []
        for article in data.get("articles", []):
            title = article.get("title") or ""
            content = article.get("content") or article.get("description") or title
            url = article.get("url") or ""
            if "[" in content and content.strip().endswith("]"):
                content = content.rsplit("[", 1)[0].strip()
            articles.append((title, content, url))
        print(f"[INFO] {stream}: fetched {len(articles)} articles, totalResults={data.get('totalResults')}")
        return articles
    except Exception as exc:  # pragma: no cover - network failures
        print(f"[WARN] Failed to fetch {stream}: {exc}")
        return []


@pw.udf
def fetch_articles(stream: str, query: str, top_k: int, api_key: str) -> List[tuple]:
    return _fetch_news_api(stream, query, top_k, api_key)


_finbert_lock = threading.Lock()
_finbert_loaded = False
_finbert_tok = None
_finbert_model = None
_finbert_device = None


def _ensure_finbert_loaded() -> None:
    global _finbert_loaded, _finbert_tok, _finbert_model, _finbert_device
    if _finbert_loaded:
        return

    with _finbert_lock:
        if _finbert_loaded:
            return

        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        import torch
        import os

        tokenizer = AutoTokenizer.from_pretrained("yiyanghkust/finbert-tone")
        model = AutoModelForSequenceClassification.from_pretrained("yiyanghkust/finbert-tone")

        # Force CPU usage to avoid CUDA memory issues with multiple workers
        # Check env var to allow GPU if explicitly set
        use_gpu = os.getenv("FINBERT_USE_GPU", "false").lower() in ("true", "1", "yes")
        
        if use_gpu and torch.cuda.is_available():
            print("[INFO] FinBERT using GPU (FINBERT_USE_GPU=true)")
            device = torch.device("cuda")
        else:
            print("[INFO] FinBERT using CPU (safer for multi-worker deployments)")
            device = torch.device("cpu")

        model.to(device)
        model.eval()

        _finbert_tok = tokenizer
        _finbert_model = model
        _finbert_device = device
        _finbert_loaded = True


@pw.udf
def finbert_sentiment(title: str, content: str) -> str:
    import torch
    import torch.nn.functional as F

    try:
        _ensure_finbert_loaded()
        assert _finbert_tok is not None and _finbert_model is not None and _finbert_device is not None

        text = f"{title} {content}".strip()
        inputs = _finbert_tok(
            text,
            return_tensors="pt",
            truncation=True,
            padding=True,
            max_length=256,
        ).to(_finbert_device)

        with torch.no_grad():
            outputs = _finbert_model(**inputs)
            logits = outputs.logits if hasattr(outputs, "logits") else outputs
            probs = F.softmax(logits, dim=-1)
            pred = torch.argmax(probs, dim=1).item()

        label_map = {0: "neutral", 1: "positive", 2: "negative"}
        return label_map.get(pred, "neutral")
    except Exception as exc:  # pragma: no cover - inference failures
        print(f"[WARN] finbert_sentiment failed: {exc}")
        return "neutral"


def build_news_sentiment_pipeline(streams: pw.Table, news_api_key: str, top_k_default: int = 3) -> pw.Table:
    api_key_val = news_api_key or os.getenv("NEWS_ORG_API_KEY", "")

    streams_prep = streams.select(
        stream=pw.this.stream,
        query=pw.this.query,
        top_k=pw.coalesce(pw.this.top_k, top_k_default),
    )

    fetched = streams_prep.select(
        stream=pw.this.stream,
        articles=fetch_articles(pw.this.stream, pw.this.query, pw.this.top_k, api_key_val),
    )

    flat = fetched.flatten(pw.this.articles).select(
        stream=pw.this.stream,
        title=pw.this.articles[0],
        content=pw.this.articles[1],
        url=pw.this.articles[2],
    )

    scored = flat.select(
        stream=pw.this.stream,
        title=pw.this.title,
        content=pw.this.content,
        url=pw.this.url,
        sentiment=finbert_sentiment(pw.this.title, pw.this.content),
    )

    return scored


# ---------------------------------------------------------------------------
# LLM utilities
# ---------------------------------------------------------------------------


def trading_agent_llm(sentiment_json: str, api_key: str) -> str:
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
and that will be displayed to the user for making the final recommendations.

YOU MUST OUTPUT IN A STRUCTURED FORMAT AS FOLLOWS:
<sector name>:<specific news stream>
<trade signal generated>:<generated trade signal- buy sell or hold>
<analysis>: <concise explanation of your reasoning for the specific stream>

DO NOT INCLUDE ANY SOURCE URLS IN THE ANALYSIS FIELD WHICH START WITH https://example.com/ . In case you get 
such a URL, then DONT INCLUDE IT. Only mention valid URLS, otherwise skip them. You should avoid such sources, be very very careful about this.
EVERY FIELD WITHIN THE JSON MUST BE A VALID PYTHON STRING ONLY. NO MARKDOWN, NO MARKDOWN AT ALL.

YOU MUST STRICTLY OUTPUT A JSON OBJECT IN THE ABOVE FORMAT. COMPLETELY AVOID MARKDOWN. THERE SHOULD BE NO MARKDOWN, NO BACKTICKS AT ALL! NO MARKDOWN AT ALL! NO BACKTICKS AT ALL! A VALID JSON OBJECT ONLY
REMEMBER YOUR OUTPUT WILL DIRECTLY BE USED AS A PYTHON DICTIONARY IN CODE. ANY MISTAKE WILL BREAK THE CODE FLOW AND GENERATE BUGS. BE VERY VERY VERY CAREFUL ABOUT THIS.
"""

        for stream, articles in sentiment_data.items():
            prompt += f"\nSector: {stream}\n"
            for article in articles:
                prompt += (
                    f"- News title: {article['title']} | News Description: {article['content']} | "
                    f"Sentiment: {article['sentiment']} | News URL: {article.get('url', 'N/A')}\n"
                )
            prompt += "\n"

        model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.2,
            api_key=api_key,
        )
        decision = model.invoke(prompt)
        text = getattr(decision, "content", str(decision)).strip()

        # --- JSON VALIDATION & CLEANING START ---
        
        # 1. Log raw response for debugging
        print(f"[TRADING_AGENT] Raw LLM response (first 500 chars): {text[:500]}...")

        # 2. Strip Markdown code blocks
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            text = text.strip()

        # 3. Locate JSON boundaries (Curly braces for Dict, Square brackets for List)
        # The prompt asks for a "JSON OBJECT", so we prioritize {
        first_char = text.find("{")
        last_char = text.rfind("}")
        
        # Fallback if it output a list of objects
        if first_char == -1 or last_char == -1:
            first_char = text.find("[")
            last_char = text.rfind("]")

        if first_char == -1 or last_char == -1:
            error_msg = "No JSON object or array found in response"
            print(f"[TRADING_AGENT] ERROR: {error_msg}")
            return json.dumps({"error": error_msg, "raw_text": text})

        json_text = text[first_char : last_char + 1]

        # 4. Attempt to parse to ensure validity
        try:
            parsed = json.loads(json_text)
            # If successful, return the CLEANED string so downstream agents get valid JSON text
            return json.dumps(parsed)
        except json.JSONDecodeError as exc:
            print(f"[TRADING_AGENT] ERROR: JSON parse failed: {exc}")
            print(f"[TRADING_AGENT] Invalid snippet: {json_text[:200]}...")
            return json.dumps({"error": f"JSON parse failed: {exc}", "raw_text": text})
            
        # --- JSON VALIDATION & CLEANING END ---

    except Exception as exc:  # pragma: no cover - external errors
        import traceback

        error_msg = f"Error generating trading signals: {exc}\n{traceback.format_exc()}"
        print(f"[ERROR] trading_agent_llm: {error_msg}")
        return json.dumps({"error": f"Error generating trading signals: {exc}"})


def compute_technical_indicators(symbol: str) -> Optional[Dict[str, Optional[float]]]:
    if get_market_data_service is None:
        raise RuntimeError("Market data service is unavailable")

    service = get_market_data_service()
    adapter = getattr(service, "adapter", None)
    if not adapter or not hasattr(adapter, "get_historical_candles"):
        raise RuntimeError("Active market data adapter does not support historical candles")

    # Use service's normalize method if available, otherwise use symbol as-is
    if hasattr(service, "_normalize_symbol"):
        normalized_symbol = service._normalize_symbol(symbol)
    elif hasattr(service, "normalize_symbol"):
        normalized_symbol = service.normalize_symbol(symbol)
    else:
        # Fallback: basic normalization (remove suffix like -EQ)
        normalized_symbol = symbol.replace("-EQ", "").upper()
    now = datetime.utcnow()
    start_daily = (now - timedelta(days=120)).replace(hour=9, minute=15)
    start_hourly = (now - timedelta(days=2)).replace(hour=9, minute=15)

    def _fetch_range(start_dt: datetime, end_dt: datetime, interval: str) -> pd.DataFrame:
        candles = adapter.get_historical_candles(
            symbol=normalized_symbol,
            interval=interval,
            fromdate=start_dt.strftime("%Y-%m-%d %H:%M"),
            todate=end_dt.strftime("%Y-%m-%d %H:%M"),
            exchange="NSE",
        )
        if not candles:
            return pd.DataFrame()
        frame = pd.DataFrame(candles)
        if frame.empty:
            return frame
        frame.rename(
            columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            },
            inplace=True,
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame.dropna(subset=["timestamp"], inplace=True)
        frame.set_index("timestamp", inplace=True)
        frame.sort_index(inplace=True)
        return frame

    daily = _fetch_range(start_daily, now, "ONE_DAY")
    hourly = _fetch_range(start_hourly, now, "ONE_HOUR")
    if not hourly.empty:
        today = now.date()
        hourly_local = hourly.index.tz_convert("Asia/Kolkata")
        mask = hourly_local.date == today
        hourly = hourly.loc[mask]

    data = pd.concat([daily, hourly])
    data = data[~data.index.duplicated(keep="last")]

    if data.empty or len(data) < 20:
        return None

    def calculate_sma(series: pd.Series, period: int) -> Optional[float]:
        if series is None or len(series) < period:
            return None
        return float(series.rolling(window=period).mean().iloc[-1])

    def calculate_ema(series: pd.Series, period: int) -> Optional[float]:
        if series is None or len(series) < period:
            return None
        return float(series.ewm(span=period, adjust=False).mean().iloc[-1])

    def calculate_rsi(series: pd.Series, period: int = 14) -> Optional[float]:
        if series is None or len(series) < period + 1:
            return None
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period).mean()
        if loss.iloc[-1] == 0:
            return 100.0
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        value = rsi.iloc[-1]
        return float(value) if pd.notna(value) else None

    def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: int = 2) -> tuple[Optional[float], Optional[float]]:
        if series is None or len(series) < period:
            return (None, None)
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return (
            float(upper.iloc[-1]) if pd.notna(upper.iloc[-1]) else None,
            float(lower.iloc[-1]) if pd.notna(lower.iloc[-1]) else None,
        )

    def calculate_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14) -> Optional[float]:
        if any(series is None or len(series) < k_period for series in (high, low, close)):
            return None
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        denominator = highest_high - lowest_low
        if denominator.iloc[-1] == 0:
            return None
        stoch_k = 100 * ((close - lowest_low) / denominator)
        value = stoch_k.iloc[-1]
        return float(value) if pd.notna(value) else None

    indicators: Dict[str, Optional[float]] = {"Symbol": symbol}
    indicators["SMA20"] = calculate_sma(data["Close"], 20)
    indicators["EMA20"] = calculate_ema(data["Close"], 20)
    indicators["RSI14"] = calculate_rsi(data["Close"], 14)
    indicators["ADX14"] = None

    bb_upper, bb_lower = calculate_bollinger_bands(data["Close"], 20, 2)
    indicators["BB_UPPER"] = bb_upper
    indicators["BB_LOWER"] = bb_lower

    indicators["STOCHK"] = calculate_stochastic(data["High"], data["Low"], data["Close"], 14)

    return indicators


def compute_technical_indicators_for_stocks(
    nifty500_df: pd.DataFrame,
    logger: Optional[Any] = None,
    max_stocks: int = 100
) -> List[Dict[str, Any]]:
    """
    Compute technical indicators for Nifty 500 stocks using AngelOne candle data.
    
    Args:
        nifty500_df: DataFrame with columns [Symbol, Industry, Company Name]
        logger: Optional logger for progress tracking
        max_stocks: Maximum number of stocks to process (to avoid rate limits)
        
    Returns:
        List of dicts with Symbol, Industry, and technical indicators
    """
    import time
    
    log = logger or logging.getLogger(__name__)
    results = []
    
    # Limit stocks to avoid timeouts
    stocks_to_process = nifty500_df.head(max_stocks) if max_stocks else nifty500_df
    total = len(stocks_to_process)
    
    log.info(f"Processing {total} stocks for technical indicators...")
    
    for idx, row in stocks_to_process.iterrows():
        symbol = row.get("Symbol", "")
        industry = row.get("Industry", "Unknown")
        company_name = row.get("Company Name", "")
        
        if not symbol:
            continue
            
        try:
            indicators = compute_technical_indicators(symbol)
            
            if indicators:
                result = {
                    "Symbol": symbol,
                    "CompanyName": company_name,
                    "Industry": industry,
                    **indicators
                }
                results.append(result)
                
                if (idx + 1) % 10 == 0:
                    log.info(f"Progress: {idx + 1}/{total} stocks processed")
            else:
                log.debug(f"No indicators for {symbol} (insufficient data)")
                
            # Small delay to avoid rate limiting
            time.sleep(0.1)
            
        except Exception as exc:
            log.warning(f"Failed to compute indicators for {symbol}: {exc}")
            continue
    
    log.info(f"✅ Successfully computed technical indicators for {len(results)}/{total} stocks")
    return results

    daily = _fetch_range(start_daily, now, "ONE_DAY")
    hourly = _fetch_range(start_hourly, now, "ONE_HOUR")
    if not hourly.empty:
        today = now.date()
        hourly_local = hourly.index.tz_convert("Asia/Kolkata")
        mask = hourly_local.date == today
        hourly = hourly.loc[mask]

    data = pd.concat([daily, hourly])
    data = data[~data.index.duplicated(keep="last")]

    if data.empty or len(data) < 20:
        return None

    def calculate_sma(series: pd.Series, period: int) -> Optional[float]:
        if series is None or len(series) < period:
            return None
        return float(series.rolling(window=period).mean().iloc[-1])

    def calculate_ema(series: pd.Series, period: int) -> Optional[float]:
        if series is None or len(series) < period:
            return None
        return float(series.ewm(span=period, adjust=False).mean().iloc[-1])

    def calculate_rsi(series: pd.Series, period: int = 14) -> Optional[float]:
        if series is None or len(series) < period + 1:
            return None
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(window=period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=period).mean()
        if loss.iloc[-1] == 0:
            return 100.0
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        value = rsi.iloc[-1]
        return float(value) if pd.notna(value) else None

    def calculate_bollinger_bands(series: pd.Series, period: int = 20, std_dev: int = 2) -> tuple[Optional[float], Optional[float]]:
        if series is None or len(series) < period:
            return (None, None)
        sma = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return (
            float(upper.iloc[-1]) if pd.notna(upper.iloc[-1]) else None,
            float(lower.iloc[-1]) if pd.notna(lower.iloc[-1]) else None,
        )

    def calculate_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14) -> Optional[float]:
        if any(series is None or len(series) < k_period for series in (high, low, close)):
            return None
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        denominator = highest_high - lowest_low
        if denominator.iloc[-1] == 0:
            return None
        stoch_k = 100 * ((close - lowest_low) / denominator)
        value = stoch_k.iloc[-1]
        return float(value) if pd.notna(value) else None

    indicators: Dict[str, Optional[float]] = {"Symbol": symbol}
    indicators["SMA20"] = calculate_sma(data["Close"], 20)
    indicators["EMA20"] = calculate_ema(data["Close"], 20)
    indicators["RSI14"] = calculate_rsi(data["Close"], 14)
    indicators["ADX14"] = None

    bb_upper, bb_lower = calculate_bollinger_bands(data["Close"], 20, 2)
    indicators["BB_UPPER"] = bb_upper
    indicators["BB_LOWER"] = bb_lower

    indicators["STOCHK"] = calculate_stochastic(data["High"], data["Low"], data["Close"], 14)

    return indicators


@pw.udf
def get_technical_indicators(symbol: str) -> str:
    try:
        indicators = compute_technical_indicators(symbol)
        return json.dumps(indicators)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"[ERROR] get_technical_indicators({symbol}): {exc}")
        return json.dumps(None)


def stock_recommender_llm(sector_analysis: str, tech_json: str, api_key: str) -> Any:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        prompt = SystemMessage(
            """
You are a stock recommendation AI agent responsible for providing top stock investment recommendations by integrating sector-wise insights from a news sentiment agent and detailed technical indicators for each stock.

You should take as input sector-wise sentiment scores, time windows for investing, and explanations from the news sentiment agent detailing why and when to invest in each sector.

You should also receive a comprehensive table of technical indicators per stock, such as moving averages, RSI, MACD, Bollinger Bands, and volume metrics.

CRITICAL: The sector analysis contains news articles with their URLs (marked as "News URL: <url>"). You MUST ONLY use URLs that are explicitly provided in the sector analysis above. DO NOT invent, hallucinate, or create URLs. Only extract URLs that actually appear in the "News URL:" fields in the sector analysis. If you cannot find a relevant URL in the sector analysis for a stock, leave the news_source field as an empty string "".

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
 CRITICAL: The news_source field MUST contain ONLY URLs that are explicitly listed in the sector analysis above (marked as "News URL: <url>"). DO NOT invent, make up, or hallucinate URLs. You can ONLY use URLs that actually appear in the sector analysis. If you cannot find a matching URL in the sector analysis for a stock, you MUST use an empty string "" (NOT null, NOT "N/A", NOT a made-up URL).
 Do not return anything apart from this, such as here's the summary or here's the answer.
 Return only an array of json strings and nothing else
 Also for hold signals since investment time window is not valid, instead of simply printing
 'N/A', in the time_investment_window field write a proper message like no time window valid for
 hold signals.
 Every field within the JSON must be a valid Python STRING ONLY. REMEMBER THIS NO MARKDOWN, NO MARKDOWN AT ALL.
                              
 Also if a url is invalid, starting with https://example.com, then dont include that and leave 
 the url field blank (empty string "") for that particular json object.
 YOU MUST STRICTLY OUTPUT A JSON OBJECT IN THE ABOVE FORMAT. COMPLETELY AVOID MARKDOWN. THERE SHOULD BE NO MARKDOWN, NO BACKTICKS AT ALL! NO MARKDOWN AT ALL! NO BACKTICKS AT ALL! A VALID JSON OBJECT ONLY
 REMEMBER YOUR OUTPUT WILL DIRECTLY BE USED AS A PYTHON DICTIONARY IN CODE. ANY MISTAKE WILL BREAK THE CODE FLOW AND GENERATE BUGS. BE VERY VERY VERY CAREFUL ABOUT THIS.
"""
        ).content

        prompt = prompt + "\n" + HumanMessage(
            f"""Here is the sector based analysis: {sector_analysis}.
                                    Here is the json for the technical indicators for nifty 500
                                    stocks: {tech_json}"""
        ).content

        model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.2,
            api_key=api_key,
        )
        decision = model.invoke(prompt)
        text = getattr(decision, "content", str(decision)).strip()
        
        # Log raw response for debugging (first 500 chars)
        print(f"[STOCK_RECOMMENDER] Raw LLM response (first 500 chars): {text[:500]}...")

        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            text = text.strip()
        first_bracket, last_bracket = text.find("["), text.rfind("]")
        if first_bracket == -1 or last_bracket == -1:
            print(f"[STOCK_RECOMMENDER] ERROR: No JSON array found in LLM output. Full response length: {len(text)}")
            print(f"[STOCK_RECOMMENDER] Response preview: {text[:1000]}")
            return {"error": "No JSON array found in LLM output", "raw_text": text[:1000]}

        json_text = text[first_bracket : last_bracket + 1]
        json_text = re.sub(
            r'("news_source"\s*:\s*)(https?://[^\s,}\]]+)',
            lambda m: f'{m.group(1)}"{m.group(2)}"',
            json_text,
        )
        json_text = re.sub(r",\s*([\]}])", r"\1", json_text)
        try:
            parsed = json.loads(json_text)
            if not isinstance(parsed, list):
                print(f"[STOCK_RECOMMENDER] ERROR: Parsed JSON is not an array. Type: {type(parsed).__name__}, Value: {parsed}")
                return {
                    "error": "Parsed JSON is not an array",
                    "parsed_type": type(parsed).__name__,
                    "parsed_value": parsed,
                }
            if len(parsed) == 0:
                print(f"[STOCK_RECOMMENDER] WARNING: LLM returned empty array - no stock recommendations generated")
            else:
                print(f"[STOCK_RECOMMENDER] Successfully parsed {len(parsed)} stock recommendations")
                # Post-process: ensure news_source is never null, use empty string instead
                for rec in parsed:
                    if isinstance(rec, dict):
                        if "news_source" not in rec or rec.get("news_source") is None:
                            rec["news_source"] = ""
                        # Also check for invalid example.com URLs
                        news_source = rec.get("news_source", "")
                        if news_source and "example.com" in str(news_source):
                            rec["news_source"] = ""
            return parsed
        except Exception as exc:
            print(f"[STOCK_RECOMMENDER] ERROR: JSON parse failed: {exc}")
            print(f"[STOCK_RECOMMENDER] Cleaned JSON snippet: {json_text[:1000]}")
            return {
                "error": f"JSON parse failed: {exc}",
                "cleaned_json_snippet": json_text[:1000],
                "raw_text_snippet": text[:1000],
            }

    except Exception as exc:  # pragma: no cover - external errors
        import traceback

        error_msg = f"Error generating stock recommendations: {exc}\n{traceback.format_exc()}"
        print(f"[ERROR] stock_recommender_llm: {error_msg}")
        return {"error": str(exc)}


def stock_recommender(sector_analysis: str, tech_json: str, *, gemini_api_key: Optional[str] = None, sentiment_data: Optional[Dict[str, Any]] = None) -> Any:
    # Extract valid URLs from sentiment data to prevent hallucination
    valid_urls = set()
    if sentiment_data:
        try:
            for stream, articles in sentiment_data.items():
                for article in articles:
                    url = article.get("url") or ""
                    if url and url.strip() and url != "N/A" and "example.com" not in url:
                        valid_urls.add(url.strip())
        except Exception as exc:
            print(f"[STOCK_RECOMMENDER] Warning: Failed to extract URLs from sentiment data: {exc}")
    
    raw = stock_recommender_llm(
        sector_analysis,
        tech_json,
        gemini_api_key or os.getenv("GEMINI_API_KEY", ""),
    )

    parsed = None
    if isinstance(raw, (dict, list)):
        parsed = raw
    else:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw
    
    # Validate URLs against valid_urls if we have sentiment data
    if parsed and isinstance(parsed, list) and valid_urls:
        validated_count = 0
        removed_count = 0
        for rec in parsed:
            if isinstance(rec, dict):
                news_source = rec.get("news_source") or ""
                if news_source:
                    news_source = str(news_source).strip()
                    # Check if URL is in valid URLs or if it's empty/null
                    if news_source and news_source != "N/A":
                        if news_source not in valid_urls:
                            print(f"[STOCK_RECOMMENDER] WARNING: Removing hallucinated URL: {news_source}")
                            rec["news_source"] = ""
                            removed_count += 1
                        else:
                            validated_count += 1
                            rec["news_source"] = news_source  # Ensure it's the exact URL from valid set
                    else:
                        rec["news_source"] = ""
                else:
                    rec["news_source"] = ""
        if validated_count > 0 or removed_count > 0:
            print(f"[STOCK_RECOMMENDER] URL validation: {validated_count} valid, {removed_count} hallucinated URLs removed")
    
    return parsed


# ---------------------------------------------------------------------------
# High-level helpers (parity with research notebook/demo)
# ---------------------------------------------------------------------------


def news_retriever(top_k: int = 3, api_key: Optional[str] = None) -> Dict[str, List[Dict[str, str]]]:
    api_key_val = api_key or os.getenv("NEWS_ORG_API_KEY", "")
    results: Dict[str, List[Dict[str, str]]] = {}

    for stream, query in NEWS_STREAMS.items():
        articles = _fetch_news_api(stream, query, top_k, api_key_val)
        results[stream] = [
            {
                "title": title,
                "content": content,
                "url": url,
            }
            for title, content, url in articles
        ]

    return results


def sentiment_analyzer(news_by_stream: Dict[str, List[Dict[str, str]]]) -> Dict[str, List[Dict[str, str]]]:
    import torch
    import torch.nn.functional as F

    _ensure_finbert_loaded()
    assert _finbert_tok is not None and _finbert_model is not None and _finbert_device is not None

    analysed: Dict[str, List[Dict[str, str]]] = {}
    for stream, articles in news_by_stream.items():
        print(f"\nAnalysing sentiment for stream: {stream} ({len(articles)} articles)")
        enriched = []
        for article in articles:
            text = f"{article.get('title', '')} {article.get('content', '')}"
            inputs = _finbert_tok(
                text,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=256,
            ).to(_finbert_device)

            with torch.no_grad():
                outputs = _finbert_model(**inputs)
                logits = outputs.logits if hasattr(outputs, "logits") else outputs
                probs = F.softmax(logits, dim=-1)
                pred = torch.argmax(probs, dim=1).item()

            label_map = {0: "neutral", 1: "positive", 2: "negative"}
            enriched.append({**article, "sentiment": label_map.get(pred, "neutral")})

        analysed[stream] = enriched

    return analysed


def trading_agent(
    top_k: int = 3,
    *,
    news_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
) -> str:
    news_data = news_retriever(top_k=top_k, api_key=news_api_key)
    sentiment_data = sentiment_analyzer(news_data)
    return trading_agent_llm(
        json.dumps(sentiment_data),
        gemini_api_key or os.getenv("GEMINI_API_KEY", ""),
    )


__all__ = [
    "NEWS_STREAMS",
    "StreamSchema",
    "StockSchema",
    "build_news_sentiment_pipeline",
    "compute_technical_indicators",
    "compute_technical_indicators_for_stocks",
    "get_technical_indicators",
    "news_retriever",
    "sentiment_analyzer",
    "trading_agent",
    "stock_recommender",
    "stock_recommender_llm",
    "trading_agent_llm",
]
