# Risk Agent - Pathway

This module converts the Colab notebook into a Pathway pipeline for real-time portfolio risk monitoring.

## Features

- **Real-time portfolio monitoring**: Continuously monitors stock prices from your portfolio
- **Threshold-based alerts**: Detects when stocks fall below configured thresholds
- **News integration**: Fetches relevant news articles for declining stocks
- **AI-powered risk assessment**: Uses Groq LLM to assess risk severity and generate contextual alerts
- **Structured alerts**: Outputs alerts with severity levels ("bad", "worse", "worst")

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

Or install individually:
```bash
pip install "pathway[xpack-llm]" yfinance requests python-dotenv
```

**Note:** We use direct Groq API calls instead of `langchain-groq` for better compatibility with Pathway UDFs.

2. Set environment variables:
```bash
export NEWS_API_KEY=your_newsapi_key
export GROQ_API_KEY=your_groq_api_key
```

Or create a `.env` file:
```
NEWS_API_KEY=your_newsapi_key
GROQ_API_KEY=your_groq_api_key
```

## Usage

### Basic Demo

```bash
python RISK_AGENT/risk_agent_demo.py
```

This will:
- Create a sample portfolio
- Monitor stock prices in real-time
- Generate alerts when stocks fall below thresholds
- Write alerts to `risk_alerts.jsonl`

### Pipeline Components

1. **Portfolio Input**: Table with assets (ticker, name, quantity, bought_at, down_percent)
2. **Price Monitoring**: Fetches current prices and calculates percentage changes
3. **Alert Detection**: Filters stocks that need alerts (current_change < -down_percent OR day_change < -5%)
4. **News Fetching**: Retrieves recent news articles for declining stocks
5. **Risk Assessment**: Uses Groq LLM to assess risk and generate alerts
6. **Alert Output**: Structured alerts with severity and news URLs

## Alert Conditions

An alert is generated when:
- Current change from bought_at price < -down_percent threshold, OR
- Today's change < -5%

## Alert Format

Each alert contains:
- `ticker`: Stock ticker symbol
- `name`: Stock name
- `alert`: Human-readable alert message
- `severity`: Risk level ("bad", "worse", "worst")
- `urls`: List of relevant news article URLs
- `fall_percent`: Today's percentage change
- `current_price`: Current stock price
- `current_change`: Change from bought_at price

## Customization

To customize the portfolio, modify `create_sample_portfolio()` in `risk_agent_demo.py`:

```python
portfolio_data = [
    ("TICKER.NS", "Stock Name", quantity, bought_at_price, down_percent_threshold),
    # Add more stocks...
]
```

## Notes

- The pipeline runs continuously and checks prices based on `check_interval_ms` (default: 30 minutes)
- For real-time monitoring, use Pathway's streaming mode
- News is fetched from the last 7 days
- The LLM uses Groq's `openai/gpt-oss-120b` model for risk assessment

