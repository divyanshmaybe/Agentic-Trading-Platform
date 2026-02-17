"""Celery tasks for alpha signal generation.

This module provides scheduled and on-demand tasks for generating trading signals
from live alphas using their workflow configurations. The main task runs daily
before market open to:
1. Load all active LiveAlphas (status='running')
2. For each alpha, generate signals using the same logic as the manual workflow
3. Persist signals to database with batch_id for tracking

The signal generation logic is shared with the manual /generate-signals endpoint
to ensure consistency between scheduled and on-demand signal generation.
"""

from __future__ import annotations

import os
import sys
import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

import pandas as pd
from celery.utils.log import get_task_logger

from celery_app import celery_app

# parents[2] = apps/portfolio-server -> apps
# parents[3] = apps -> project root (Agentic-Trading-Platform-Pathway)
PORTFOLIO_SERVER_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHARED_PY_PATH = PROJECT_ROOT / "shared" / "py"
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"

if str(SHARED_PY_PATH) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_PATH))
if str(QUANT_STREAM_PATH) not in sys.path:
    sys.path.insert(0, str(QUANT_STREAM_PATH))

task_logger = get_task_logger(__name__)

# Market data file path
MARKET_DATA_CSV = QUANT_STREAM_PATH / ".data" / "indian_stock_market_nifty500.csv"


def _check_market_data_freshness() -> bool:
    """Check if market data CSV has today's data (or last trading day's data)."""
    if not MARKET_DATA_CSV.exists():
        return False
    
    try:
        # Use tail command to read only the last 100 lines (much faster than reading entire file)
        import subprocess
        result = subprocess.run(
            ['tail', '-100', str(MARKET_DATA_CSV)],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            return False
        
        # Parse just the last lines to find max date
        lines = result.stdout.strip().split('\n')
        max_date = None
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 2 and parts[1] != 'date':  # Skip header if present
                try:
                    date = datetime.strptime(parts[1], '%Y-%m-%d').date()
                    if max_date is None or date > max_date:
                        max_date = date
                except ValueError:
                    continue
        
        if max_date is None:
            return False
        
        today = datetime.now().date()
        
        # Get last trading day (skip weekends)
        last_trading_day = today
        if today.weekday() == 5:  # Saturday
            last_trading_day = today - timedelta(days=1)
        elif today.weekday() == 6:  # Sunday
            last_trading_day = today - timedelta(days=2)
        
        # If before market close (3:30 PM IST = 10:00 AM UTC), use previous trading day
        now = datetime.now()
        if now.hour < 16:  # Before 4 PM IST (using some buffer after market close)
            if last_trading_day.weekday() == 0:  # Monday
                last_trading_day = last_trading_day - timedelta(days=3)  # Go to Friday
            else:
                last_trading_day = last_trading_day - timedelta(days=1)
            # Skip weekends again
            while last_trading_day.weekday() >= 5:
                last_trading_day = last_trading_day - timedelta(days=1)
        
        # Data is fresh if it has last trading day's data
        return max_date >= last_trading_day
    except Exception as e:
        task_logger.warning("Error checking market data freshness: %s", e)
        return False


async def _update_market_data_if_needed(logger) -> bool:
    """Update market data CSV if it's stale. Returns True if update was successful or not needed."""
    if _check_market_data_freshness():
        logger.info("Market data is fresh, skipping update")
        return True
    
    logger.info("Market data is stale, updating...")
    
    try:
        # Import and run the update script
        import subprocess
        update_script = QUANT_STREAM_PATH / "update_indian_market_data.py"
        
        if not update_script.exists():
            logger.error("Market data update script not found: %s", update_script)
            return False
        
        # Run the update script as a subprocess
        result = subprocess.run(
            [sys.executable, str(update_script)],
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            cwd=str(QUANT_STREAM_PATH)
        )
        
        if result.returncode == 0:
            logger.info("Market data updated successfully")
            return True
        else:
            logger.error("Market data update failed: %s", result.stderr[-500:] if result.stderr else "No error output")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Market data update timed out after 10 minutes")
        return False
    except Exception as e:
        logger.error("Failed to update market data: %s", e)
        return False


async def generate_signals_for_alpha_core(
    client,
    alpha,
    logger=None,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Core signal generation logic shared between Celery task and API endpoint.
    
    This function:
    1. Loads market data from quant-stream
    2. Computes factor expressions
    3. Loads trained ML model from MLflow (if available)
    4. Generates predictions and ranks symbols
    5. Persists signals to database with batch_id
    
    Args:
        client: Prisma client
        alpha: LiveAlpha model instance
        logger: Optional logger (defaults to task_logger)
        progress_callback: Optional callback(step, progress, message) for progress updates
        
    Returns:
        Dict with status, signals count, batch_id, etc.
    """
    logger = logger or task_logger
    
    def update_progress(step: str, progress: int, message: str):
        if progress_callback:
            progress_callback(step, progress, message)
        logger.info("[%s] %d%% - %s", step, progress, message)
    
    workflow_config = alpha.workflow_config
    if isinstance(workflow_config, str):
        workflow_config = json.loads(workflow_config)
    
    if not workflow_config:
        return {"status": "skipped", "reason": "No workflow config"}
    
    strategy_config = workflow_config.get("strategy", {})
    strategy_type = alpha.strategy_type or strategy_config.get("type", "TopkDropout")
    params = strategy_config.get("params", {})
    topk = params.get("topk", 30)
    allocated_amount = float(alpha.allocated_amount)
    
    try:
        # Import quant-stream
        try:
            from quant_stream.backtest.runner import load_market_data, calculate_factors
        except ModuleNotFoundError as import_err:
            logger.error("❌ quant_stream module not available: %s", import_err)
            return {
                "status": "error", 
                "error": f"quant_stream module not installed: {str(import_err)}",
                "alpha_id": alpha.id,
                "alpha_name": alpha.name,
            }
        
        features_config = workflow_config.get("features", [])
        
        if not features_config:
            return {"status": "skipped", "reason": "No features configured"}
        
        # Step 0: Update market data if stale
        update_progress("updating_data", 5, "Checking market data freshness...")
        await _update_market_data_if_needed(logger)
        
        # Step 1: Load market data
        update_progress("loading_data", 10, "Loading market data...")
        
        data_path = str(QUANT_STREAM_PATH / ".data" / "indian_stock_market_nifty500.csv")
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        date_ranges = [(start_date, end_date)]
        
        logger.info("Loading market data for alpha %s from %s to %s", alpha.name, start_date, end_date)
        
        table = load_market_data(data_path=data_path, date_ranges=date_ranges)
        
        # Step 2: Compute factors
        update_progress("computing_factors", 30, f"Computing {len(features_config)} factor expressions...")
        
        _, features_df, _ = calculate_factors(table, features_config)
        
        # Get latest values per symbol
        features_df['timestamp'] = pd.to_datetime(features_df['timestamp'])
        latest_df = features_df.sort_values('timestamp').groupby('symbol').last().reset_index()
        
        # Get feature columns and compute predictions
        factor_names = [f["name"] for f in features_config]
        available_factors = [f for f in factor_names if f in latest_df.columns]
        
        if not available_factors:
            return {"status": "skipped", "reason": "No available factors in data"}
        
        X = latest_df[available_factors].fillna(0)
        
        # Step 3: Load model
        update_progress("loading_model", 50, "Loading ML model...")
        
        mlflow_run_id = workflow_config.get("experiment", {}).get("run_id")
        if not mlflow_run_id:
            mlflow_run_id = workflow_config.get("experiment", {}).get("mlflow_run_id")
        
        model = None
        
        if mlflow_run_id:
            try:
                from quant_stream.recorder.utils import load_mlflow_run_artifacts
                tracking_uri = f"sqlite:///{QUANT_STREAM_PATH / 'mlruns.db'}"
                artifacts = load_mlflow_run_artifacts(
                    run_id=mlflow_run_id,
                    artifact_names=["model", "trained_model", "lgb_model", "xgb_model"],
                    tracking_uri=tracking_uri,
                )
                for name in ["model", "trained_model", "lgb_model", "xgb_model"]:
                    if name in artifacts and artifacts[name] is not None:
                        model = artifacts[name]
                        logger.info("Loaded model '%s' from MLflow run %s", name, mlflow_run_id)
                        break
            except Exception as e:
                logger.warning("Failed to load model from MLflow: %s", e)
        
        # Step 4: Generate predictions
        update_progress("running_model", 65, "Generating return predictions...")
        
        if model is not None and hasattr(model, 'predict'):
            # Use frozen model from backtesting
            predicted_returns = model.predict(X)
        else:
            # Fallback: use factor signals directly
            logger.info("No ML model available, using factor signals directly")
            if len(available_factors) == 1:
                predicted_returns = X[available_factors[0]].values
            else:
                normalized = (X - X.mean()) / (X.std() + 1e-8)
                predicted_returns = normalized.mean(axis=1).values
            # Normalize
            pred_std = predicted_returns.std()
            if pred_std > 0:
                predicted_returns = predicted_returns / pred_std * 0.02
        
        # Add predictions to dataframe
        latest_df['predicted_return'] = predicted_returns
        
        # Step 5: Apply strategy
        update_progress("generating_signals", 80, f"Applying {strategy_type} strategy...")
        
        # Sort by predicted return (descending) and select top-k
        ranked_df = latest_df.sort_values('predicted_return', ascending=False)
        buy_candidates = ranked_df.head(topk)
        
        # Fetch live prices for candidate symbols to use current market prices
        # instead of stale historical data for execution
        live_prices = {}
        try:
            import httpx
            candidate_symbols = buy_candidates['symbol'].tolist()
            # Use Docker internal network name for container-to-container communication
            market_service_url = os.getenv("MARKET_SERVICE_URL", "http://portfolio_server:8000")
            internal_secret = os.getenv("INTERNAL_SERVICE_SECRET", "agentinvest-secret")
            
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                params = "&".join([f"symbols={s}" for s in candidate_symbols])
                response = await http_client.get(
                    f"{market_service_url}/api/market/quotes?{params}",
                    headers={
                        "X-Internal-Service": "true",
                        "X-Service-Secret": internal_secret,
                    }
                )
                if response.status_code == 200:
                    quotes_data = response.json()
                    for quote in quotes_data.get("data", []):
                        if quote.get("symbol") and quote.get("price"):
                            live_prices[quote["symbol"]] = float(quote["price"])
                    logger.info("Fetched live prices for %d/%d symbols", len(live_prices), len(candidate_symbols))
                else:
                    logger.warning("Failed to fetch live prices (status %d), using historical data", response.status_code)
        except Exception as price_err:
            logger.warning("Could not fetch live prices: %s. Using historical data.", price_err)
        
        # Calculate allocations (equal weight)
        allocation_per_stock = allocated_amount / topk
        
        signals = []
        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        # Signals expire at end of trading day (3:30 PM IST = 10:00 AM UTC)
        expires_at = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now.hour >= 10:
            expires_at = expires_at + timedelta(days=1)
        
        for rank, (_, row) in enumerate(buy_candidates.iterrows(), 1):
            symbol = row['symbol']
            # Use live price if available; otherwise require a valid close price and skip if missing
            current_price = live_prices.get(symbol)
            if current_price is None:
                try:
                    current_price = float(row.get('close'))
                except (TypeError, ValueError):
                    continue
            if current_price is None or current_price <= 0:
                continue
            
            quantity = int(allocation_per_stock / current_price)
            if quantity <= 0:
                continue
            
            pred_return = float(row['predicted_return'])
            confidence = min(1.0, max(0.0, abs(pred_return) * 10))
            
            signals.append({
                "symbol": symbol,
                "signal_type": "buy",
                "quantity": quantity,
                "predicted_return": pred_return,
                "confidence": confidence,
                "price": current_price,  # Now uses live price when available
                "allocated_amount": quantity * current_price,
                "rank": rank,
            })
        
        # Persist signals to database and auto-execute them
        if signals:
            update_progress("saving_signals", 85, f"Saving {len(signals)} signals to database...")
            
            logger.info("Persisting %d signals for alpha %s with batch_id %s", len(signals), alpha.id, batch_id)
            
            # Get portfolio info for trade execution
            portfolio = await client.portfolio.find_unique(where={"id": alpha.portfolio_id})
            if not portfolio:
                logger.error("Portfolio not found for alpha %s", alpha.id)
                return {"status": "error", "alpha_id": alpha.id, "error": "Portfolio not found"}
            
            # Get or create alpha agent for trade execution
            agent_id = alpha.agent_id
            if not agent_id:
                # Create alpha agent inline
                existing_agent = await client.tradingagent.find_first(
                    where={
                        "portfolio_id": alpha.portfolio_id,
                        "agent_type": "alpha",
                        "status": "active",
                    }
                )
                if existing_agent:
                    agent_id = existing_agent.id
                else:
                    # Create allocation for the alpha agent
                    allocation = await client.portfolioallocation.create(
                        data={
                            "portfolio_id": alpha.portfolio_id,
                            "allocation_type": "alpha",
                            "target_percentage": 0,
                            "allocated_cash": float(alpha.allocated_amount),
                            "available_cash": float(alpha.allocated_amount),
                            "invested_value": 0,
                            "metadata": {"created_for": f"alpha_signals:{alpha.name}"},
                        }
                    )
                    # Create the alpha agent
                    agent = await client.tradingagent.create(
                        data={
                            "portfolio_id": alpha.portfolio_id,
                            "portfolio_allocation_id": allocation.id,
                            "agent_type": "alpha",
                            "agent_name": f"Alpha Signal Executor",
                            "status": "active",
                            "strategy_config": {"source": "alpha_signals"},
                            "metadata": {"created_for": alpha.name},
                        }
                    )
                    agent_id = agent.id
                    logger.info("Created new alpha agent: %s", agent_id)
                
                # Link alpha to agent
                await client.livealpha.update(
                    where={"id": alpha.id},
                    data={"agent_id": agent_id}
                )
            
            # Import trade execution service for auto-execution
            from services.trade_execution_service import TradeExecutionService
            trade_service = TradeExecutionService(logger=logger)
            
            executed_count = 0
            failed_count = 0
            
            for sig in signals:
                # Create signal record
                signal_record = await client.alphasignal.create(
                    data={
                        "live_alpha_id": alpha.id,
                        "batch_id": batch_id,
                        "symbol": sig["symbol"],
                        "signal_type": sig["signal_type"],
                        "quantity": sig["quantity"],
                        "predicted_return": sig["predicted_return"],
                        "confidence": sig["confidence"],
                        "price": sig["price"],
                        "allocated_amount": sig["allocated_amount"],
                        "rank": sig["rank"],
                        "status": "pending",
                        "generated_at": now,
                        "expires_at": expires_at,
                    }
                )
                
                # Auto-execute the signal
                try:
                    job_row = {
                        "request_id": str(uuid.uuid4()),
                        "user_id": portfolio.customer_id,
                        "organization_id": portfolio.organization_id,
                        "portfolio_id": alpha.portfolio_id,
                        "customer_id": portfolio.customer_id,
                        "symbol": sig["symbol"],
                        "side": sig["signal_type"].upper(),
                        "quantity": sig["quantity"],
                        "reference_price": sig["price"],
                        "exchange": "NSE",
                        "segment": "EQUITY",
                        "agent_id": agent_id,
                        "agent_type": "alpha",
                        "allocation_id": None,
                        "triggered_by": f"alpha_signal:{alpha.name}",
                        "confidence": sig["confidence"],
                        "allocated_capital": sig["allocated_amount"],
                        "take_profit_pct": 0.03,
                        "stop_loss_pct": 0.01,
                        "explanation": f"Alpha signal: {alpha.name} - {sig['signal_type']} {sig['symbol']} (rank #{sig['rank']})",
                        "filing_time": "",
                        "generated_at": now.isoformat(),
                    }
                    
                    events = await trade_service.persist_and_publish([job_row], publish_kafka=False)
                    
                    if events and len(events) > 0:
                        trade_id = events[0].trade_id
                        result = await trade_service.execute_trade(trade_id, simulate=True)
                        
                        # Update signal with trade link
                        await client.alphasignal.update(
                            where={"id": signal_record.id},
                            data={
                                "status": "executed",
                                "executed_at": now,
                                "trade_id": trade_id,
                            }
                        )
                        executed_count += 1
                        logger.info("✅ Auto-executed signal %s -> trade %s", signal_record.id[:8], trade_id[:8])
                    else:
                        failed_count += 1
                        logger.warning("Failed to create trade for signal %s", signal_record.id)
                        
                except Exception as exec_error:
                    failed_count += 1
                    logger.error("Failed to execute signal %s: %s", signal_record.id, exec_error)
            
            update_progress("completed", 100, f"Executed {executed_count} trades, {failed_count} failed")
            
            # Update alpha's last_signal_at and total_signals
            await client.livealpha.update(
                where={"id": alpha.id},
                data={
                    "last_signal_at": now,
                    "total_signals": alpha.total_signals + len(signals),
                }
            )
            
            logger.info("✅ Alpha %s: generated %d signals, executed %d trades, %d failed", 
                       alpha.name, len(signals), executed_count, failed_count)
        
        return {
            "status": "success",
            "alpha_id": alpha.id,
            "alpha_name": alpha.name,
            "signals_generated": len(signals),
            "signals_executed": executed_count if signals else 0,
            "signals_failed": failed_count if signals else 0,
            "batch_id": batch_id,
            "strategy_type": strategy_type,
            "topk": topk,
        }
        
    except Exception as e:
        logger.error("Failed to generate signals for alpha %s: %s", alpha.id, e, exc_info=True)
        return {"status": "error", "alpha_id": alpha.id, "error": str(e)}


@celery_app.task(
    bind=True,
    name="alpha.generate_daily_signals",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    # acks_late=False by default - safe for auto-retry (no duplicate executions)
    reject_on_worker_lost=True,
)
def generate_daily_alpha_signals(self) -> Dict[str, Any]:
    """
    Generate daily alpha signals for all active LiveAlphas.
    
    This task runs daily before market open (8:00 AM IST by default).
    
    Process:
    1. Load all active LiveAlpha configurations (status='running')
    2. For each alpha, use the shared generate_signals_for_alpha_core function
    3. Persist signals to database with batch_id for tracking
    
    Uses the same logic as the manual /generate-signals endpoint.
    """
    import asyncio
    from redis import Redis
    from celery_app import BROKER_URL
    
    # Redis-based lock to prevent concurrent execution
    redis_client = Redis.from_url(BROKER_URL)
    lock_key = "pipeline:alpha_signals:lock"
    pid_key = "pipeline:alpha_signals:pid"
    current_pid = os.getpid()
    
    # Try to acquire lock
    lock_acquired = redis_client.set(lock_key, "locked", nx=True, ex=3600)  # 1 hour TTL
    
    if not lock_acquired:
        task_logger.warning("Alpha signals pipeline lock acquisition failed, skipping this execution")
        return {"status": "skipped", "reason": "lock_acquisition_failed"}
    
    redis_client.set(pid_key, str(current_pid), ex=3600)
    task_logger.info("✅ Alpha signals pipeline lock acquired (PID: %s)", current_pid)
    
    try:
        result = asyncio.run(_generate_signals_async())
        task_logger.info("✅ Alpha signals generation completed: %s", result)
        return result
    except Exception as exc:
        task_logger.error("❌ Alpha signals generation failed: %s", exc, exc_info=True)
        raise
    finally:
        redis_client.delete(lock_key)
        redis_client.delete(pid_key)
        task_logger.info("Alpha signals pipeline lock released")


async def _generate_signals_async() -> Dict[str, Any]:
    """Async implementation of signal generation for all running alphas."""
    from dbManager import DBManager  # type: ignore
    
    db_manager = DBManager.get_instance()
    
    async with db_manager.session() as client:
        
        # Get all running live alphas
        live_alphas = await client.livealpha.find_many(
            where={"status": "running"}
        )
        
        if not live_alphas:
            task_logger.info("No active live alphas found")
            return {"status": "success", "alphas_processed": 0, "signals_generated": 0}
        
        task_logger.info("Found %d active live alphas to process", len(live_alphas))
        
        total_signals = 0
        processed = 0
        errors = []
        results = []
        
        for alpha in live_alphas:
            try:
                task_logger.info("Processing alpha: %s (%s)", alpha.name, alpha.id)
                
                # Use the shared core function
                result = await generate_signals_for_alpha_core(client, alpha, task_logger)
                
                if result.get("status") == "success":
                    signal_count = result.get("signals_generated", 0)
                    total_signals += signal_count
                    processed += 1
                    results.append(result)
                    
                    task_logger.info(
                        "Alpha %s generated %d signals (batch_id: %s)",
                        alpha.name, signal_count, result.get("batch_id")
                    )
                elif result.get("status") == "skipped":
                    task_logger.warning(
                        "Alpha %s skipped: %s",
                        alpha.name, result.get("reason")
                    )
                else:
                    errors.append({"alpha_id": alpha.id, "error": result.get("error")})
                    # Update alpha status to error
                    await client.livealpha.update(
                        where={"id": alpha.id},
                        data={"status": "error"}
                    )
                
            except Exception as exc:
                task_logger.error(
                    "Failed to process alpha %s: %s",
                    alpha.id, exc, exc_info=True
                )
                errors.append({"alpha_id": alpha.id, "error": str(exc)})
                
                # Update alpha status to error
                await client.livealpha.update(
                    where={"id": alpha.id},
                    data={"status": "error"}
                )
        
        return {
            "status": "success",
            "alphas_processed": processed,
            "signals_generated": total_signals,
            "results": results,
            "errors": errors if errors else None,
        }


@celery_app.task(
    bind=True,
    name="alpha.generate_signals_for_alpha",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def generate_signals_for_single_alpha(self, alpha_id: str) -> Dict[str, Any]:
    """
    Generate signals for a specific live alpha.
    
    This can be triggered manually or on-demand via API.
    Uses the same logic as the manual /generate-signals endpoint.
    Reports progress via Celery task state updates.
    """
    import asyncio
    
    def progress_callback(step: str, progress: int, message: str):
        """Update Celery task state with progress information."""
        self.update_state(
            state="PROGRESS",
            meta={
                "step": step,
                "progress": progress,
                "message": message,
                "alpha_id": alpha_id,
            }
        )
    
    try:
        result = asyncio.run(_generate_signals_for_alpha_async(alpha_id, progress_callback))
        return result
    except Exception as exc:
        task_logger.error("Failed to generate signals for alpha %s: %s", alpha_id, exc, exc_info=True)
        raise


async def _generate_signals_for_alpha_async(alpha_id: str, progress_callback=None) -> Dict[str, Any]:
    """Async implementation for single alpha signal generation."""
    from dbManager import DBManager  # type: ignore
    
    db_manager = DBManager.get_instance()
    
    async with db_manager.session() as client:
        alpha = await client.livealpha.find_unique(where={"id": alpha_id})
        if not alpha:
            return {"status": "error", "error": "Alpha not found"}
        
        if alpha.status != "running":
            return {"status": "skipped", "reason": f"Alpha status is {alpha.status}"}
        
        # Use the shared core function with progress callback
        result = await generate_signals_for_alpha_core(client, alpha, task_logger, progress_callback)
        return result


@celery_app.task(
    bind=True,
    name="alpha.process_signal_batch",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_alpha_signal_batch(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Process a batch of alpha signals and convert them to trade execution jobs.
    
    Args:
        signals: List of signal dictionaries with:
            - alpha_id: ID of the live alpha
            - symbol: Stock symbol
            - signal_type: 'buy' or 'sell'
            - quantity: Number of shares
            - confidence: Signal confidence (0-1)
    """
    import asyncio
    
    try:
        result = asyncio.run(_process_signal_batch_async(signals))
        return result
    except Exception as exc:
        task_logger.error("Failed to process signal batch: %s", exc, exc_info=True)
        raise


async def _process_signal_batch_async(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Async implementation for signal batch processing.
    
    Converts alpha signals into trade execution jobs using TradeExecutionService.
    Each signal includes:
    - alpha_id: ID of the live alpha
    - portfolio_id: ID of the portfolio
    - symbol: Stock symbol
    - signal_type: 'buy' or 'sell'
    - quantity: Number of shares
    - confidence: Signal confidence (0-1)
    - reference_price: Current stock price
    - allocated_amount: Capital allocated for this signal
    """
    from dbManager import DBManager  # type: ignore
    from services.trade_execution_service import TradeExecutionService
    
    db_manager = DBManager.get_instance()
    
    async with db_manager.session() as client:
        trade_service = TradeExecutionService(logger=task_logger)
        
        processed = 0
        errors = []
        
        for signal in signals:
            try:
                # Get alpha and its portfolio
                alpha_id = signal.get("alpha_id")
                if not alpha_id:
                    errors.append({"signal": signal, "error": "Missing alpha_id"})
                    continue
                
                alpha = await client.livealpha.find_unique(
                    where={"id": alpha_id},
                    include={"portfolio": True}
                )
                if not alpha:
                    errors.append({"signal": signal, "error": "Alpha not found"})
                    continue
                
                # Create trade using TradeExecutionService
                result = await trade_service.create_alpha_trade(
                    alpha=alpha,
                    symbol=signal["symbol"],
                    signal_type=signal["signal_type"],
                    quantity=signal.get("quantity"),
                    confidence=signal.get("confidence", 1.0),
                    reference_price=signal.get("reference_price"),
                )
                
                if result.get("status") in ["executed", "pending"]:
                    processed += 1
                    task_logger.info(
                        "✅ Processed signal: %s %s x %d for alpha %s",
                        signal["signal_type"],
                        signal["symbol"],
                        signal.get("quantity", 0),
                        alpha.name,
                    )
                elif result.get("status") == "skipped":
                    task_logger.warning(
                        "⚠️ Signal skipped: %s %s - %s",
                        signal["signal_type"],
                        signal["symbol"],
                        result.get("reason", "unknown"),
                    )
                else:
                    errors.append({"signal": signal, "error": result.get("error", "Unknown error")})
                
            except Exception as exc:
                task_logger.error(
                    "Failed to process signal: %s - %s",
                    signal, exc
                )
                errors.append({"signal": signal, "error": str(exc)})
        
        return {
            "status": "success",
            "processed": processed,
            "errors": errors if errors else None,
        }



