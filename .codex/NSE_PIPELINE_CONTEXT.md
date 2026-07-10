# NSE / BSE Filings Pipeline Context

This note is project context for future Codex sessions. It summarizes the current filings-driven high-risk trading flow in this repo and points to the files that matter.

## Mental Model

The product idea is: detect important exchange filings quickly, convert them into a trading signal, and auto-execute trades for portfolios that have an active `high_risk` trading agent.

Despite older docs saying "NSE pipeline", the current live ingestion path is mostly BSE corporate announcements. It still feeds the same high-risk/NSE-style trade execution system.

High-level flow:

```text
BSE corporate announcement
  -> hot path or cold path
  -> signal payload: symbol, signal, confidence, explanation, reference_price
  -> Celery task: pipeline.trade_execution.process_signal
  -> PipelineService.process_nse_trade_signals()
  -> active high_risk TradingAgent lookup
  -> trade sizing
  -> Trade + TradeExecutionLog persisted
  -> Celery task: trading.execute_trade_job
  -> simulated/live execution
  -> positions, allocation cash, P&L, snapshots updated
```

## Key Files

- `apps/portfolio-server/workers/pipeline_tasks.py`
  - Celery tasks for starting pipelines and processing signals.
  - Important tasks:
    - `pipeline.start`
    - `pipeline.bse.process_filing`
    - `pipeline.trade_execution.process_signal`
    - `pipeline.sell_high_risk_before_close`

- `apps/portfolio-server/pipelines/nse/bse_scraper.py`
  - Low-latency BSE announcement poller.
  - Polls BSE API every `BSE_REFRESH_INTERVAL` seconds.
  - Detects "bagging/order win" announcements.
  - Hot path sends an immediate BUY signal to `pipeline.trade_execution.process_signal`.
  - Non-hot but relevant filings are sent to `pipeline.bse.process_filing`.

- `apps/portfolio-server/pipelines/nse/bse_sentiment.py`
  - Cold path processor for non-bagging filings.
  - Downloads/extracts PDF text, fetches stock technical data, calls the LLM, parses `signal`, `confidence`, and `explanation`.
  - Sends actionable signals to `pipeline.trade_execution.process_signal`.
  - Also publishes signal events to Kafka topic `nse_filings_trading_signal` for analytics/UI.
  - Queues company report updates for relevant filings.

- `apps/portfolio-server/services/pipeline_service.py`
  - Main orchestration service.
  - `run_nse_pipeline_forever()` currently launches the BSE pipeline.
  - `process_nse_trade_signals()` is the core signal-to-trade path.
  - Finds active `high_risk` trading agents, builds portfolio snapshots, prepares trade payloads, sizes trades, persists them, and dispatches execution tasks.

- `apps/portfolio-server/services/trade_sizing_service.py`
  - Direct Python trade sizing logic.
  - Replaces the older Pathway sizing path for lower latency.
  - Maps:
    - signal `1` -> `BUY`
    - signal `-1` -> `SHORT_SELL`
    - signal `0` -> `HOLD`
  - Confidence allocation:
    - confidence `> 0.8` -> `MAX_POSITION_FRACTION`
    - confidence `> 0.49` -> `25%`
    - otherwise no trade

- `apps/portfolio-server/pipelines/nse/trade_execution_pipeline.py`
  - Legacy Pathway implementation of trade sizing.
  - Still contains schemas/event types and Kafka publishing helpers.
  - Current service path uses `trade_sizing_service.calculate_trade_execution_jobs()` instead of `run_trade_execution_requests()`.

- `apps/portfolio-server/services/trade_execution_service.py`
  - Persists `Trade` and `TradeExecutionLog`.
  - Enforces market hours unless demo mode allows bypass.
  - Calculates TP/SL prices for opening trades.
  - Validates cash, reserves allocation cash, updates positions, P&L, snapshots, and trade status.
  - Simulated execution is default when `ANGELONE_TRADING_ENABLED` is false.

- `apps/portfolio-server/workers/trade_execution_tasks.py`
  - Celery task `trading.execute_trade_job`.
  - Calls `TradeExecutionService.execute_trade()`.
  - Tracks execution latency.

- `apps/portfolio-server/celery_app.py`
  - Queue routing and scheduled jobs.
  - `pipeline.trade_execution.process_signal` and `trading.execute_trade_job` route to the `trading` queue.
  - Market close task sells high-risk positions before close.

## Signal Payload

Typical signal payload:

```json
{
  "symbol": "RELIANCE",
  "filing_time": "2026-07-10 10:15:00",
  "signal": 1,
  "explanation": "Bagging order detected - instant execution",
  "confidence": 0.75,
  "generated_at": "2026-07-10T04:45:00Z",
  "source": "bse_filings_pipeline",
  "subject_of_announcement": "Award of Order / Receipt of Order",
  "attachment_url": "https://...",
  "reference_price": 2500.0
}
```

`pipeline.trade_execution.process_signal` ensures `reference_price` exists. If missing, it fetches current market price through the portfolio market API before sizing.

## Eligibility Model

Older docs mention `User.subscriptions = ["high_risk"]`. The current execution path mostly uses `TradingAgent` rows:

- `agent_type = "high_risk"`
- `status = "active"`
- linked `allocation`
- linked active `portfolio`

So, for real auto-trading, check active high-risk `TradingAgent` setup, not only the user subscription array.

## Trade Sizing And Position Rules

The signal is processed for each eligible active high-risk agent.

Sizing uses:

- available capital from the agent/portfolio snapshot
- confidence threshold
- reference price
- max concurrent trades from `services.cfdt_strategy.MAX_CONCURRENT_TRADES`

The system avoids pyramiding repeated signals:

- If a matching long exists and the new signal is BUY, skip.
- If a matching short exists and the new signal is SHORT_SELL, skip.
- If a BUY signal arrives while a short exists, convert to `COVER`.
- If a SHORT_SELL signal arrives while a long exists, convert to `SELL`.

## Execution

After sizing:

1. `TradeExecutionService.persist_and_publish()` creates `Trade` and `TradeExecutionLog`.
2. `PipelineService` dispatches `trading.execute_trade_job`.
3. `TradeExecutionService.execute_trade()` executes the linked `Trade`.
4. In paper mode, it marks execution without broker contact.
5. In live mode, it uses broker integration when enabled and allowed.

Default safety:

- `ANGELONE_TRADING_ENABLED=false` means simulated/paper execution.
- `CFDT_PAPER_TRADING_ONLY=true` blocks live CFDT execution.
- Market-hours enforcement is applied in trade creation unless demo mode bypasses it.

## Kafka Topics

- `nse_filings_trading_signal`
  - signal analytics/UI topic from filings sentiment.

- `TRADE_EXECUTION_TOPIC`
  - current code default in `trade_execution_pipeline.py` is `nse_pipeline_trade_logs`.
  - older docs mention `trade_execution_requests`; verify env before assuming.

Kafka failures should not block trade execution; the code treats Kafka as analytics/audit after persistence in several places.

## Market Close

High-risk positions are closed before market close:

- Celery task: `pipeline.sell_high_risk_before_close`
- Service method: `PipelineService.sell_all_high_risk_positions()`
- It finds active high-risk agents, closes long positions via `SELL`, and short positions via `COVER`.

Alpha positions have a separate close task later to avoid overloading execution.

## What To Check When Debugging

1. Is the BSE/NSE pipeline task running?
   - `pipeline.start`
   - Redis lock keys can prevent duplicate pipeline runs.

2. Did the filing become a signal?
   - Hot path: `bse_scraper.py`
   - Cold path: `bse_sentiment.py`
   - Kafka topic: `nse_filings_trading_signal`

3. Did `pipeline.trade_execution.process_signal` run?
   - Check trading Celery worker logs.
   - Duplicate signals can be blocked by Redis fingerprinting.

4. Are there active high-risk agents?
   - `TradingAgent.agent_type == "high_risk"`
   - `TradingAgent.status == "active"`
   - Must have allocation and active portfolio.

5. Did sizing produce jobs?
   - `trade_sizing_service.calculate_trade_execution_jobs()`
   - Watch for low confidence, zero price, zero allocation, max position count.

6. Did persistence succeed?
   - Check `trades`
   - Check `trade_execution_logs`

7. Did execution run?
   - Celery task `trading.execute_trade_job`
   - `TradeExecutionService.execute_trade()`

## Useful Study Order For Divya

1. Read `bse_scraper.py` to understand ingestion.
2. Read `bse_sentiment.py` around `process_bse_filing()` and `publish_signal_to_kafka()`.
3. Read `pipeline_tasks.py` around `process_trade_signal()`.
4. Read `pipeline_service.py` around `_process_nse_trade_signals_async()`.
5. Read `trade_sizing_service.py` fully.
6. Read `trade_execution_service.py` in chunks:
   - `create_trade_log()`
   - `persist_and_publish()`
   - `execute_trade()`
   - position update helpers
7. Read `celery_app.py` routing so worker queues make sense.

## Current Caveats

- Naming is inconsistent: docs say NSE, current ingestion code uses BSE, execution remains high-risk/NSE-style.
- There is both a legacy Pathway trade execution pipeline and a newer direct Python sizing service. Prefer the direct Python path when explaining current behavior.
- Some docs mention automatic TP/SL orders; current `execute_trade()` comments say TP/SL orders are not automatically created unless explicitly specified by strategy. The `Trade` record does store TP/SL prices for opening trades.
- User subscriptions still exist in Prisma, but active `TradingAgent` status is the main runtime opt-in for this flow.
