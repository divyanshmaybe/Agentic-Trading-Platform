# NSE Filings Sentiment Agent - Complete Pipeline

A real-time Pathway-based system for scraping NSE corporate filings, analyzing sentiment, generating trading signals, and backtesting strategies.

## Overview

The complete pipeline:
1. **Live Scraping**: Continuously scrapes NSE announcements via API (every 60 seconds)
2. **XBRL Filtering**: Filters relevant announcements by file type using XBRL parsing
3. **PDF Processing**: Downloads and extracts text from PDF filings
4. **Sentiment Analysis**: Uses LLM (Google Gemini) to analyze sentiment and generate trading signals
5. **Backtesting**: Simulates trades with target (+3%) and stoploss (-1%)
6. **Output**: Writes results to JSONL files

## Architecture

```
NSE API → Scraper → Sentiment Pipeline → Backtest → Output Files
           ↓              ↓                  ↓
      XBRL Filter    PDF Download      Trade Simulation
      Deduplication  LLM Analysis     Metrics Calculation
```

## Files

### Core Pipeline
- `nse_pipeline.py` - **Main entry point** - Complete end-to-end pipeline
- `nse_live_scraper.py` - Live NSE API scraper with XBRL filtering
- `nse_filings_sentiment.py` - Sentiment analysis and trading signal generation
- `nse_backtest.py` - Backtesting module with trade simulation

### Supporting Files
- `nse_live_demo.py` - Alternative demo script
- `requirements.txt` - Python dependencies
- `staticdata.csv` - Filing type impact scenarios (required)

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment Variables
Create a `.env` file:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Static Data File (Optional)
The `staticdata.csv` file is **optional**. If not provided, the system will use default impact scenarios.

To customize filing type impacts, create `staticdata.csv` with columns:
- `file type` - Type of filing (e.g., "Press Release", "Outcome of Board Meeting")
- `positive impct ` - Positive impact scenarios
- `negtive impct` - Negative impact scenarios

### 4. Required File Types
The system filters for these relevant file types:
- Outcome of Board Meeting
- Press Release
- Appointment
- Acquisition
- Updates
- Action(s) initiated or orders passed
- Investor Presentation
- Sale or Disposal
- Bagging/Receiving of Orders/Contracts
- Change in Director(s)

## Usage

### Main Pipeline (Recommended)
```bash
python nse_pipeline.py
```

This will:
- Start live scraping from NSE API
- Process announcements through sentiment pipeline
- Run backtest on signals
- Write results to JSONL files

### Output Files
- `trading_signals.jsonl` - Trading signals (BUY/SELL/HOLD)
- `backtest_results.jsonl` - Individual trade results
- `backtest_metrics.jsonl` - Aggregated performance metrics
- `processed_announcements.json` - Tracked processed announcements (auto-generated)

## Features

### Live Scraping
- **API-based**: Uses NSE API endpoint for reliable data
- **Deduplication**: Tracks processed announcements and PDFs
- **XBRL Filtering**: Only processes relevant file types
- **Auto-cleanup**: Removes downloaded PDFs after processing
- **Continuous Polling**: Runs every 60 seconds (configurable)

### Sentiment Analysis
- **LLM-powered**: Uses Google Gemini for analysis
- **Context-aware**: Considers filing type impact scenarios
- **Stock Data**: Fetches technical indicators for past hour
- **Structured Output**: Generates BUY (1), SELL (-1), or HOLD (0) signals

### Backtesting
- **Trade Simulation**: Simulates trades with target (+3%) and stoploss (-1%)
- **Market Hours**: Adjusts entry times to market hours
- **Metrics**: Calculates win rate, profit factor, total PnL
- **Real-time**: Processes signals as they arrive

## Configuration

### Scraper Settings (`nse_live_scraper.py`)
```python
refresh_interval = 60  # Seconds between API polls
```

### Backtest Settings (`nse_backtest.py`)
```python
TARGET = 0.03  # +3% profit target
STOPLOSS = 0.01  # -1% stoploss
HOLDING_HOURS = 1  # Maximum hold time
MARKET_OPEN = (9, 15)  # Market opening time
MARKET_CLOSE = (15, 30)  # Market closing time
```

### LLM Settings (`nse_filings_sentiment.py`)
- Model: Google Gemini (configurable via `GEMINI_API_KEY`)
- Max tokens: 1000
- Temperature: 0.7

## Output Format

### Trading Signals (`trading_signals.jsonl`)
```json
{
  "symbol": "RELIANCE",
  "filing_time": "2025-11-05 19:55:49",
  "signal": 1,
  "explanation": "Strong positive impact from board meeting outcome..."
}
```

### Backtest Results (`backtest_results.jsonl`)
```json
{
  "symbol": "RELIANCE",
  "entry_time": "2025-11-05 09:15:00",
  "signal": 1,
  "pnl": 0.025,
  "exit_time": "2025-11-05 10:30:00",
  "session": "during_market",
  "exit_reason": "target_hit"
}
```

### Backtest Metrics (`backtest_metrics.jsonl`)
```json
{
  "total_trades": 10,
  "wins": 7,
  "losses": 3,
  "total_pnl": 0.15,
  "avg_pnl": 0.015,
  "win_rate": 70.0,
  "profit_factor": 2.33
}
```

## Troubleshooting

### Common Issues

1. **API Key Errors**
   - Verify `GEMINI_API_KEY` in `.env` file
   - Check API quota limits

2. **PDF Download Fails**
   - Check network connectivity
   - Verify NSE URL validity
   - PDFs are auto-cleaned after processing

3. **No Announcements Found**
   - Check if announcements match relevant file types
   - Verify API endpoint is accessible
   - Check `processed_announcements.json` for duplicates

4. **Stock Data Missing**
   - Ensure market hours or use appropriate time ranges
   - Check if stock symbol is valid
   - Some stocks may be delisted

5. **Primary Key Errors**
   - Ensure `seq_id` is unique for each announcement
   - Check for duplicate announcements

## File Structure

```
NSE_FILLINGS/
├── nse_pipeline.py          # Main pipeline
├── nse_live_scraper.py      # Live scraper
├── nse_filings_sentiment.py # Sentiment analysis
├── nse_backtest.py          # Backtesting
├── nse_live_demo.py         # Demo script
├── requirements.txt         # Dependencies
├── staticdata.csv           # Impact scenarios (optional)
├── .gitignore              # Git ignore rules
├── README.md               # This file
└── docs/                   # PDF storage (auto-cleaned)
```

## Notes

- **PDF Cleanup**: PDFs are automatically deleted after text extraction
- **Deduplication**: System tracks processed announcements and files to avoid duplicates
- **Continuous Operation**: Pipeline runs indefinitely until stopped (Ctrl+C)
- **Error Handling**: Individual errors don't crash the pipeline
- **Data Persistence**: Processed announcements are saved to `processed_announcements.json`

## License

See main project license.
