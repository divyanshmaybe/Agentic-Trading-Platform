"""
Trade Execution Service

Provides helpers for persisting auto-trade jobs, publishing events, and delegating
execution to broker integrations.

PRODUCTION FEATURES:
- Market hours enforcement (9:15 AM - 3:30 PM IST)
- Short selling support (SHORT_SELL and COVER trades)
- Fail-fast validation (no assumptions, no fallbacks)
- Redis-based distributed locking for race condition prevention
- Atomic cash reservation before trade execution
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional

import os

from db import get_db_manager  # type: ignore  # noqa: E402
from pipelines.nse.trade_execution_pipeline import (  # type: ignore  # noqa: E402
    TradeExecutionEvent,
    publish_trade_execution_events,
)
from services.trade_validation_service import TradeValidationService  # noqa: E402
from utils.market_hours import enforce_market_hours, is_market_hours, get_market_status  # noqa: E402

# Redis for distributed locking
try:
    from redis import Redis
    REDIS_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    _redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
except Exception:
    _redis_client = None


@asynccontextmanager
async def allocation_lock(allocation_id: str, timeout: float = 15.0):
    """
    Distributed lock for allocation cash operations.
    Prevents race conditions when multiple trades try to use the same allocation.
    """
    lock_key = f"allocation_lock:{allocation_id}"
    lock_value = str(uuid.uuid4())
    acquired = False
    
    try:
        if _redis_client:
            # Try to acquire lock with NX (only if not exists) and EX (expiry)
            acquired = _redis_client.set(lock_key, lock_value, nx=True, ex=int(timeout))
            if not acquired:
                # Wait a bit and retry once
                await asyncio.sleep(0.1)
                acquired = _redis_client.set(lock_key, lock_value, nx=True, ex=int(timeout))
        
        if not acquired and _redis_client:
            logging.getLogger(__name__).warning(
                "⚠️ Could not acquire allocation lock %s - proceeding without lock",
                allocation_id
            )
        
        yield acquired
        
    finally:
        # Release lock only if we acquired it and value matches
        if acquired and _redis_client:
            try:
                current_value = _redis_client.get(lock_key)
                if current_value == lock_value:
                    _redis_client.delete(lock_key)
            except Exception:
                pass


def _parse_metadata(metadata):
    """Parse metadata from string or dict."""
    if not metadata:
        return {}
    if isinstance(metadata, str):
        try:
            return json.loads(metadata)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logging.getLogger(__name__).warning(f"Failed to parse metadata: {e}")
            return {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _calculate_auto_sell_at(record, execution_time, logger, trade_id):
    """Calculate auto_sell_at timestamp for high-risk NSE pipeline trades.
    
    Args:
        record: Either a Trade object or a TradeExecutionLog object (with nested .trade)
        execution_time: The time of trade execution
        logger: Logger instance
        trade_id: Trade ID for logging
    """
    # Get metadata - handle both Trade object and TradeExecutionLog object
    metadata = _parse_metadata(getattr(record, "metadata", None))
    triggered_by = metadata.get("triggered_by", "")
    agent_type = getattr(record, "agent_type", None) or metadata.get("agent_type", "")
    
    # If record is a TradeExecutionLog (has .trade), also check the Trade's metadata
    if hasattr(record, "trade") and record.trade:
        trade_metadata = _parse_metadata(getattr(record.trade, "metadata", None))
        if not triggered_by:
            triggered_by = trade_metadata.get("triggered_by", "")
        if not agent_type:
            agent_type = trade_metadata.get("agent_type", "")
    
    logger.info(
        "🔍 AUTO_SELL_AT DEBUG for trade %s: triggered_by='%s', agent_type='%s', metadata_keys=%s",
        trade_id, triggered_by, agent_type, list(metadata.keys()) if metadata else []
    )
    
    is_nse_trade = (
        triggered_by == "nse_filings_pipeline" or
        agent_type == "high_risk" or
        "nse" in triggered_by.lower() or
        "nse_filings" in triggered_by.lower()
    )
    
    if not is_nse_trade:
        logger.warning(
            "⚠️ Trade %s is NOT an NSE trade (triggered_by='%s', agent_type='%s'), skipping auto_sell_at",
            trade_id, triggered_by, agent_type
        )
        return None
    
    auto_sell_window_minutes = int(os.getenv("NSE_FILINGS_AUTO_SELL_WINDOW_MINUTES", "15"))
    auto_sell_at = execution_time + timedelta(minutes=auto_sell_window_minutes)
    
    logger.info(
        "✅ Calculated auto_sell_at for trade %s: %s (%d minutes from execution)",
        trade_id, auto_sell_at, auto_sell_window_minutes
    )
    
    # Compare against market close time in Asia/Kolkata timezone (15:30 IST)
    try:
        ist = ZoneInfo("Asia/Kolkata")
        local_auto_sell = auto_sell_at.astimezone(ist)
    except Exception:
        # If timezone conversion is not possible, fall back to naive comparison
        local_auto_sell = auto_sell_at

    if local_auto_sell.hour > 15 or (local_auto_sell.hour == 15 and local_auto_sell.minute > 30):
        logger.warning(
            "⚠️ Auto-sell time %s (local %s) would be after market close (>15:30 IST), skipping auto-sell for trade %s",
            auto_sell_at, local_auto_sell, trade_id
        )
        return None
    
    return auto_sell_at


@dataclass
class TradeExecutionRecord:
    """Lightweight representation of a persisted trade execution log."""

    id: str
    request_id: str
    status: str
    broker_order_id: Optional[str]


class TradeExecutionService:
    """Coordinates persistence, messaging, and broker handoff for trade jobs."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._manager = get_db_manager()

    async def _ensure_client(self):
        await self._manager.connect()
        return self._manager.get_client()

    @staticmethod
    def _as_decimal(value: Any, precision: str = "0.0001") -> Decimal:
        try:
            return Decimal(str(value)).quantize(Decimal(precision), rounding=ROUND_HALF_UP)
        except Exception:
            return Decimal("0")

    async def validate_total_allocation(
        self,
        portfolio_id: str,
        new_allocation_amount: Decimal = Decimal("0"),
        exclude_allocation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate that total allocated amount across all agents doesn't exceed portfolio value.
        
        CRITICAL: Prevents over-allocation which could lead to accounting violations.
        
        Args:
            portfolio_id: Portfolio to check
            new_allocation_amount: Amount being added (for new allocations)
            exclude_allocation_id: Allocation ID to exclude from total (for updates)
            
        Returns:
            {"valid": bool, "error": str, "total_allocated": Decimal, "portfolio_value": Decimal}
        """
        client = await self._ensure_client()
        
        try:
            portfolio = await client.portfolio.find_unique(
                where={"id": portfolio_id},
                include={"allocations": True}
            )
            
            if not portfolio:
                return {
                    "valid": False,
                    "error": f"Portfolio {portfolio_id} not found",
                    "total_allocated": Decimal("0"),
                    "portfolio_value": Decimal("0"),
                }
            
            portfolio_value = Decimal(str(getattr(portfolio, "investment_amount", 0)))
            
            # Calculate total allocated across all allocations
            total_allocated = Decimal("0")
            for allocation in portfolio.allocations:
                # Skip the allocation being updated
                if exclude_allocation_id and allocation.id == exclude_allocation_id:
                    continue
                total_allocated += Decimal(str(getattr(allocation, "allocated_amount", 0)))
            
            # Add new allocation amount
            total_allocated += new_allocation_amount
            
            if total_allocated > portfolio_value:
                return {
                    "valid": False,
                    "error": (
                        f"Total allocation ₹{total_allocated} exceeds portfolio value ₹{portfolio_value}. "
                        f"Over-allocation: ₹{total_allocated - portfolio_value}"
                    ),
                    "total_allocated": total_allocated,
                    "portfolio_value": portfolio_value,
                }
            
            return {
                "valid": True,
                "error": None,
                "total_allocated": total_allocated,
                "portfolio_value": portfolio_value,
            }
            
        except Exception as e:
            self.logger.error("Failed to validate total allocation: %s", e, exc_info=True)
            return {
                "valid": False,
                "error": f"Validation error: {str(e)}",
                "total_allocated": Decimal("0"),
                "portfolio_value": Decimal("0"),
            }

    async def create_trade_log(
        self,
        job_row: Dict[str, Any],
        *,
        client: Optional[Any] = None,
    ) -> TradeExecutionRecord:
        """Persist a trade execution job into the database.

        Creates both a Trade record (containing all trade details) and a TradeExecutionLog
        record (tracking execution attempts) linked by trade_id.
        
        PRODUCTION SAFETY:
        - Enforces market hours (9:15 AM - 3:30 PM IST) unless DEMO_MODE=true
        - Fails fast if outside trading hours
        - Supports SHORT_SELL and COVER trades
        """

        # PRODUCTION: Enforce market hours before creating trade (respects DEMO_MODE)
        try:
            enforce_market_hours()  # Automatically checks DEMO_MODE inside
        except ValueError as e:
            self.logger.error("❌ Market hours violation: %s", e)
            raise ValueError(f"Cannot create trade outside market hours: {e}") from e

        client = client or await self._ensure_client()

        metadata = {}
        metadata_json = job_row.get("metadata_json")
        if isinstance(metadata_json, str) and metadata_json:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                metadata = {"raw_metadata": metadata_json}

        # Add triggering agent information to metadata
        if "triggered_by" not in metadata:
            metadata["triggered_by"] = job_row.get("triggered_by", "high_risk_agent")

        # Store agent_id and agent_type in metadata for fallback retrieval
        if job_row.get("agent_id"):
            metadata["agent_id"] = job_row["agent_id"]
        if job_row.get("agent_type"):
            metadata["agent_type"] = job_row["agent_type"]

        # Get portfolio information for Trade record creation
        portfolio_id = job_row.get("portfolio_id")
        portfolio = None
        organization_id = job_row.get("organization_id")  # Get from job_row first
        customer_id = job_row.get("customer_id")  # Get from job_row first
        
        if portfolio_id:
            try:
                portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
                if not portfolio:
                    self.logger.warning(
                        "⚠️ Portfolio %s not found in database, creating trade with values from job_row",
                        portfolio_id
                    )
                else:
                    # Override with actual portfolio values if fetch succeeded
                    organization_id = getattr(portfolio, "organization_id", organization_id)
                    customer_id = getattr(portfolio, "customer_id", customer_id)
            except Exception as portfolio_check_exc:
                self.logger.warning(
                    "⚠️ Failed to verify portfolio %s exists: %s, using values from job_row",
                    portfolio_id, portfolio_check_exc
                )
        
        # Validate required fields
        if not organization_id or not customer_id:
            raise ValueError(
                f"Missing required fields: organization_id={organization_id}, customer_id={customer_id}. "
                f"These must be provided in job_row or fetchable from portfolio {portfolio_id}"
            )

        # Prepare Trade record data (contains all trade details)
        from datetime import datetime, timedelta
        
        # Default TP/SL percentages for NSE trades if not provided
        DEFAULT_TP_PCT = Decimal("0.02")  # 2% take profit
        DEFAULT_SL_PCT = Decimal("0.01")  # 1% stop loss
        
        reference_price = self._as_decimal(job_row["reference_price"])
        side = job_row["side"]
        
        # Calculate TP/SL percentages (use provided or defaults)
        tp_pct = self._as_decimal(job_row.get("take_profit_pct"), "0.000001") if job_row.get("take_profit_pct") else DEFAULT_TP_PCT
        sl_pct = self._as_decimal(job_row.get("stop_loss_pct"), "0.000001") if job_row.get("stop_loss_pct") else DEFAULT_SL_PCT
        
        # Calculate fixed TP/SL prices based on side
        if side.upper() == "BUY":
            # For BUY (LONG): TP above entry, SL below entry
            tp_price = reference_price * (Decimal("1") + tp_pct)
            sl_price = reference_price * (Decimal("1") - sl_pct)
        elif side.upper() == "SHORT_SELL":
            # For SHORT_SELL: TP below entry (profit when price drops), SL above entry
            tp_price = reference_price * (Decimal("1") - tp_pct)
            sl_price = reference_price * (Decimal("1") + sl_pct)
        else:  # SELL or COVER
            # For SELL/COVER: TP below entry, SL above entry
            tp_price = reference_price * (Decimal("1") - tp_pct)
            sl_price = reference_price * (Decimal("1") + sl_pct)
        
        # Set 15-minute auto-close window based on trade side
        auto_close_time = datetime.utcnow() + timedelta(minutes=15)
        
        trade_data = {
            "organization_id": organization_id,  # From job_row or portfolio
            "customer_id": customer_id,  # From job_row or portfolio
            "trade_type": "auto",  # NSE pipeline trades are auto-trades
            "symbol": job_row["symbol"],
            "exchange": "NSE",
            "segment": "EQUITY",
            "side": side,
            "order_type": "market",
            "quantity": int(job_row["quantity"]),
            "price": reference_price,
            "status": "pending",
            "source": "nse_pipeline",
            "metadata": json.dumps(metadata),
            "take_profit_pct": tp_pct,
            "stop_loss_pct": sl_pct,
            "take_profit_price": tp_price,
            "stop_loss_price": sl_price,
        }
        
        # Set appropriate auto-close timestamp based on trade side
        if side.upper() == "SHORT_SELL":
            # SHORT_SELL: Set auto_cover_at (buy to close after 15 min)
            trade_data["auto_cover_at"] = auto_close_time.isoformat() + "Z"
        elif side.upper() == "BUY":
            # BUY (LONG): Set auto_sell_at (sell to close after 15 min)
            trade_data["auto_sell_at"] = auto_close_time.isoformat() + "Z"
        # SELL and COVER don't need auto-close (they ARE closing trades)

        # Add NSE-specific fields to Trade record
        if job_row.get("signal_id"):
            trade_data["signal_id"] = job_row["signal_id"]
        if job_row.get("allocated_capital"):
            trade_data["allocated_capital"] = self._as_decimal(job_row["allocated_capital"])
        if job_row.get("confidence"):
            trade_data["confidence"] = self._as_decimal(job_row["confidence"], "0.000001")

        # Set agent_id if available (direct field, not relation)
        if job_row.get("agent_id"):
            trade_data["agent_id"] = job_row["agent_id"]
        
        # Note: allocation_id is NOT stored in Trade model, only in Position model
        # The allocation is tracked through the agent relationship
        
        # Set portfolio_id (direct field, not relation)
        if portfolio_id:
            trade_data["portfolio_id"] = portfolio_id

        # ============================================================
        # DEDUPLICATION: Check for existing trades before creating
        # ============================================================
        # Check 1: Is there already a PENDING/ACTIVE trade for this symbol?
        # Check 2: Was there a recent trade in the last 5 minutes?
        # Check 3: For BUY/SHORT_SELL: Is there already an OPEN position?
        
        symbol = trade_data["symbol"]
        trade_side = trade_data["side"].upper()
        dedup_window_minutes = 5
        cutoff_time = datetime.utcnow() - timedelta(minutes=dedup_window_minutes)
        
        # Check for pending/active trades for this symbol in this portfolio
        existing_pending_trades = await client.trade.find_many(
            where={
                "symbol": symbol,
                "portfolio_id": portfolio_id,
                "status": {"in": ["pending", "active"]},
            },
            take=1,
        )
        
        if existing_pending_trades:
            existing_trade = existing_pending_trades[0]
            self.logger.warning(
                "⚠️ DUPLICATE TRADE PREVENTED: Trade %s already exists for %s (status: %s, side: %s) in portfolio %s. Skipping new %s trade.",
                existing_trade.id,
                symbol,
                existing_trade.status,
                existing_trade.side,
                portfolio_id,
                trade_side,
            )
            # Return the existing trade wrapped in a TradeExecutionRecord
            # We need to find or create a TradeExecutionLog for it
            existing_log = await client.tradeexecutionlog.find_first(
                where={"trade_id": existing_trade.id},
            )
            if existing_log:
                return TradeExecutionRecord(
                    id=existing_log.id,
                    request_id=existing_log.request_id,
                    status=existing_log.status,
                    broker_order_id=getattr(existing_log, "broker_order_id", None),
                )
            else:
                # Create a minimal log if none exists (shouldn't happen)
                self.logger.warning("Creating fallback TradeExecutionLog for existing trade %s", existing_trade.id)
                fallback_log = await client.tradeexecutionlog.create(
                    data={
                        "trade_id": existing_trade.id,
                        "request_id": job_row["request_id"],
                        "status": "pending",
                        "order_type": "market",
                        "metadata": json.dumps({"deduplication": "fallback_log"}),
                    }
                )
                return TradeExecutionRecord(
                    id=fallback_log.id,
                    request_id=fallback_log.request_id,
                    status=fallback_log.status,
                    broker_order_id=None,
                )
        
        # Check for recent trades (within last 5 minutes)
        recent_trades = await client.trade.find_many(
            where={
                "symbol": symbol,
                "portfolio_id": portfolio_id,
                "created_at": {"gte": cutoff_time},
            },
            take=1,
        )
        
        if recent_trades:
            recent_trade = recent_trades[0]
            self.logger.warning(
                "⚠️ DUPLICATE TRADE PREVENTED: Recent trade %s for %s created at %s (within %d min window) in portfolio %s. Skipping new %s trade.",
                recent_trade.id,
                symbol,
                recent_trade.created_at,
                dedup_window_minutes,
                portfolio_id,
                trade_side,
            )
            # Return existing log
            existing_log = await client.tradeexecutionlog.find_first(
                where={"trade_id": recent_trade.id},
            )
            if existing_log:
                return TradeExecutionRecord(
                    id=existing_log.id,
                    request_id=existing_log.request_id,
                    status=existing_log.status,
                    broker_order_id=getattr(existing_log, "broker_order_id", None),
                )
        
        # ============================================================
        # All deduplication checks passed - create the trade
        # ============================================================
        # Note: We don't check for open positions here because:
        # 1. Layer 1 (signal deduplication) already prevents duplicate signals
        # 2. Recent trade check (5 min window) catches duplicates
        # 3. Pending/active trade check prevents concurrent duplicates
        # 4. Position checks would prevent legitimate adding to positions

        # Create Trade record first
        trade_record = await client.trade.create(data=trade_data)
        self.logger.debug("✅ Created Trade record: %s", trade_record.id)

        # Prepare TradeExecutionLog data (minimal execution tracking)
        # Determine order_type from metadata or default to "market"
        order_type = metadata.get("order_type") or trade_data.get("order_type") or "market"
        
        # Store additional trade details in metadata for easy access
        execution_metadata = metadata.copy()
        execution_metadata.update({
            "user_id": job_row["user_id"],
            "portfolio_id": job_row["portfolio_id"],
            "agent_id": job_row.get("agent_id"),
            "agent_type": job_row.get("agent_type"),
            "agent_status": job_row.get("agent_status"),
        })
        
        execution_log_data = {
            "trade_id": trade_record.id,
            "request_id": job_row["request_id"],
            "status": "pending",
            "order_type": order_type,
            "metadata": json.dumps(execution_metadata),
        }

        # Create TradeExecutionLog record
        execution_record = await client.tradeexecutionlog.create(data=execution_log_data)
        self.logger.debug("✅ Created TradeExecutionLog record: %s", execution_record.id)

        # Extract agent information for logging
        agent_id = job_row.get("agent_id")
        agent_type = job_row.get("agent_type")
        agent_status = job_row.get("agent_status")

        if agent_id:
            self.logger.info(
                "✅ Logged trade request %s (Trade: %s) for portfolio %s | Agent %s (%s, %s) | %s %s x %d | Triggered by %s",
                execution_record.id,
                trade_record.id,
                portfolio_id or "unknown",
                agent_id,
                agent_type or "unknown",
                agent_status or "unknown",
                trade_data["side"],
                trade_data["symbol"],
                trade_data["quantity"],
                metadata.get("triggered_by", "unknown"),
            )
        else:
            self.logger.info(
                "✅ Logged trade request %s (Trade: %s) for portfolio %s (%s %s x %s) - triggered by %s (no agent)",
                execution_record.id,
                trade_record.id,
                portfolio_id or "unknown",
                trade_data["side"],
                trade_data["symbol"],
                trade_data["quantity"],
                metadata.get("triggered_by", "unknown"),
            )

        return TradeExecutionRecord(
            id=execution_record.id,
            request_id=execution_log_data["request_id"],
            status=execution_record.status,
            broker_order_id=getattr(execution_record, "broker_order_id", None),
        )

    async def persist_and_publish(
        self,
        job_rows: Iterable[Dict[str, Any]],
        *,
        publish_kafka: bool = True,
    ) -> List[TradeExecutionEvent]:
        """Persist trade jobs and optionally publish them onto Kafka."""

        client = await self._ensure_client()
        events: List[TradeExecutionEvent] = []
        job_list = list(job_rows)  # Convert to list to get length
        self.logger.info("💾 persist_and_publish: Processing %d job row(s)...", len(job_list))

        for idx, row in enumerate(job_list, 1):
            try:
                self.logger.debug("Creating trade log %d/%d: %s %s x %d", idx, len(job_list), row.get("symbol"), row.get("side"), row.get("quantity"))
                record = await self.create_trade_log(row, client=client)
                self.logger.debug("✅ Created trade log: %s", record.id)
                
                metadata_json = row.get("metadata_json") or "{}"
                try:
                    metadata = json.loads(metadata_json)
                    if not isinstance(metadata, dict):
                        metadata = {}
                except json.JSONDecodeError:
                    metadata = {"raw_metadata": metadata_json}

                # Get the TradeExecutionLog to access the trade_id
                execution_log = await client.tradeexecutionlog.find_unique(
                    where={"id": record.id},
                    include={"trade": True}
                )
                
                event = TradeExecutionEvent(
                    trade_id=execution_log.trade_id,  # Use Trade ID from TradeExecutionLog
                    request_id=row["request_id"],
                    signal_id=row.get("signal_id", ""),
                    user_id=row["user_id"],
                    portfolio_id=row["portfolio_id"],
                    symbol=row["symbol"],
                    side=row["side"],
                    quantity=int(row["quantity"]),
                    allocated_capital=float(row["allocated_capital"]),
                    confidence=float(row["confidence"]),
                    reference_price=float(row["reference_price"]),
                    take_profit_pct=float(row["take_profit_pct"]),
                    stop_loss_pct=float(row["stop_loss_pct"]),
                    explanation=row.get("explanation", ""),
                    filing_time=row.get("filing_time", ""),
                    generated_at=row.get("generated_at", ""),
                    metadata=metadata,
                    status="pending",
                    agent_id=row.get("agent_id"),
                    agent_type=row.get("agent_type"),
                    agent_status=row.get("agent_status"),
                )
                events.append(event)
            except Exception as exc:
                self.logger.error("❌ Failed to persist trade log for job row %d/%d: %s", idx, len(job_list), exc, exc_info=True)
                continue

        self.logger.info("✅ persist_and_publish: Created %d trade execution log(s) and %d event(s)", len(events), len(events))
        
        if publish_kafka and events:
            self.logger.info("📤 Publishing %d trade execution event(s) to Kafka (async)...", len(events))
            # Run Kafka publishing in thread pool to avoid blocking
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: publish_trade_execution_events(events, logger=self.logger))
            except Exception as kafka_exc:
                # Don't fail the entire operation if Kafka is down - trades are already persisted
                self.logger.warning("⚠️ Kafka publishing failed (trades still persisted): %s", str(kafka_exc))
        elif not events:
            self.logger.warning("⚠️ No events to publish to Kafka")

        return events

    async def update_status(
        self,
        trade_id: str,
        *,
        status: str,
        broker_order_id: Optional[str] = None,
        error_message: Optional[str] = None,
        executed_price: Optional[float] = None,
        executed_quantity: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update persisted trade execution log with execution results.

        Updates both TradeExecutionLog and corresponding Trade record.
        Note: executed_price and executed_quantity are only used to update Trade record,
        not TradeExecutionLog (which doesn't store these fields).
        """

        client = await self._ensure_client()
        
        # First fetch the execution record to validate it exists and get the trade_id
        # trade_id here is expected to be the TradeExecutionLog ID
        try:
            execution_record = await client.tradeexecutionlog.find_unique(
                where={"id": trade_id},
                include={"trade": True}
            )
        except Exception:
            execution_record = None
        
        if not execution_record:
            self.logger.error("❌ update_status: No TradeExecutionLog found with id=%s", trade_id)
            return
        
        # Store trade_id before updating (update might change the record structure)
        linked_trade_id = execution_record.trade_id
        
        data: Dict[str, Any] = {
            "status": status,
        }
        if broker_order_id:
            data["broker_order_id"] = broker_order_id
        if error_message:
            data["error_message"] = error_message
        # Note: executed_price and executed_quantity removed from TradeExecutionLog
        # They are only used to update the Trade record below
        if metadata:
            data["metadata"] = json.dumps(metadata)

        # Update TradeExecutionLog
        await client.tradeexecutionlog.update(
            where={"id": trade_id},
            data=data,
        )

        # Also update corresponding Trade record if execution was successful
        if status in ["executed", "executed"] and (executed_price is not None or executed_quantity is not None):
            trade_update_data = {}  # Remove status update from here - done atomically in execute_trade
            if executed_price is not None:
                trade_update_data["executed_price"] = self._as_decimal(executed_price)
                trade_update_data["price"] = self._as_decimal(executed_price)  # Update price to executed price
            if executed_quantity is not None:
                trade_update_data["executed_quantity"] = executed_quantity
            if executed_price is not None and executed_quantity is not None:
                trade_update_data["execution_time"] = datetime.utcnow()
                # Calculate net amount
                net_amount = Decimal(str(executed_price * executed_quantity))
                trade_update_data["net_amount"] = net_amount

            try:
                await client.trade.update(
                    where={"id": linked_trade_id},
                    data=trade_update_data,
                )
                self.logger.debug("Updated Trade %s with execution details", linked_trade_id)
            except Exception as trade_update_exc:
                self.logger.warning("Failed to update Trade record %s: %s", linked_trade_id, trade_update_exc)

        self.logger.info("Updated trade execution %s -> status=%s", trade_id, status)

    async def fetch_trade_log(self, trade_id: str) -> Optional[Any]:
        client = await self._ensure_client()
        result = await client.tradeexecutionlog.find_first(
            where={"trade_id": trade_id},
            include={"trade": True}  # Include linked Trade for TP/SL price access
        )
        if not result:
            self.logger.warning("❌ fetch_trade_log: No TradeExecutionLog found for trade_id=%s", trade_id)
        else:
            self.logger.debug("✅ fetch_trade_log: Found TradeExecutionLog %s for trade_id=%s", result.id, trade_id)
        return result

    async def execute_trade(
        self,
        trade_id: str,
        *,
        simulate: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Execute a trade job using the configured broker integration.

        Args:
            trade_id: The Trade record ID (not TradeExecutionLog ID)
        
        When simulation mode is enabled (default when ANGELONE_TRADING_ENABLED is false),
        the trade is marked as executed immediately without contacting the broker.
        
        After successful execution:
        1. Updates the trade log status
        2. Adds the trade to portfolio's allocation trades array
        3. Triggers portfolio value recalculation
        
        Note: Take-profit and stop-loss orders are NOT automatically created.
        They should only be created when explicitly specified in the trading strategy.
        """

        record = await self.fetch_trade_log(trade_id)  # Fetches by Trade ID
        if record is None:
            self.logger.warning("Trade %s not found for execution", trade_id)
            return {"status": "missing", "trade_id": trade_id}
        
        # record is the TradeExecutionLog, record.id is its ID
        execution_log_id = record.id
        
        # Ensure agent_id is available from the record
        # If not in the record, try to get it from metadata
        agent_id = getattr(record, "agent_id", None)
        if not agent_id:
            # Try to get from metadata
            if hasattr(record, "metadata") and record.metadata:
                import json
                meta = record.metadata
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        self.logger.warning(f"Failed to parse record metadata: {e}")
                        meta = {}
                if isinstance(meta, dict) and "agent_id" in meta:
                    agent_id = meta["agent_id"]

        simulate = simulate if simulate is not None else (
            os.getenv("ANGELONE_TRADING_ENABLED", "false").lower() not in {"1", "true", "yes"}
        )

        if simulate:
            # Use the linked Trade record when available for price/quantity/symbol
            trade = getattr(record, "trade", None)

            if trade is None:
                self.logger.warning("No linked Trade found for TradeExecutionLog %s", trade_id)
                return {"status": "missing_trade", "trade_id": trade_id}

            # Ensure client is available for all operations
            client = await self._ensure_client()

            # PRE-EXECUTION CASH CHECK WITH DATABASE-LEVEL LOCKING
            # Uses SELECT FOR UPDATE to prevent race conditions at database level
            trade_side = str(getattr(trade, "side", "")).upper()
            if trade_side == "BUY" and agent_id:
                agent = await client.tradingagent.find_unique(
                    where={"id": agent_id},
                    include={"allocation": True}
                )
                if agent and agent.allocation:
                    allocation_id = agent.allocation.id
                    
                    # Use distributed lock AND database-level locking for defense in depth
                    async with allocation_lock(allocation_id, timeout=15.0) as lock_acquired:
                        # Use SELECT FOR UPDATE to lock the row at database level
                        # This prevents concurrent modifications even if Redis lock fails
                        allocation_result = await client.query_raw(
                            '''SELECT id, available_cash, allocated_amount 
                               FROM "portfolio_allocations" 
                               WHERE id = $1 
                               FOR UPDATE''',
                            allocation_id
                        )
                        
                        if not allocation_result or len(allocation_result) == 0:
                            self.logger.error("❌ Allocation %s not found during cash check", allocation_id)
                            return {"status": "rejected", "trade_id": trade_id, "reason": "allocation_not_found"}
                        
                        allocation_data = allocation_result[0]
                        available_cash = float(allocation_data.get("available_cash", 0) or 0)
                        allocated_capital = float(getattr(trade, "allocated_capital", 0) or 0)
                        trade_value = float(getattr(trade, "quantity", 0) or 0) * float(getattr(trade, "price", 0) or 0)
                        required_capital = max(allocated_capital, trade_value)
                        
                        if available_cash < required_capital:
                            self.logger.error(
                                "❌ INSUFFICIENT CASH: Trade %s requires ₹%.2f but only ₹%.2f available. REJECTING.",
                                trade_id, required_capital, available_cash
                            )
                            # Mark trade as rejected
                            await client.trade.update(
                                where={"id": trade_id},
                                data={"status": "rejected"}
                            )
                            await self.update_status(
                                execution_log_id,
                                status="rejected",
                                error_message=f"Insufficient cash: requires ₹{required_capital:.2f}, available ₹{available_cash:.2f}"
                            )
                            return {
                                "status": "rejected",
                                "trade_id": trade_id,
                                "reason": "insufficient_cash",
                                "required": required_capital,
                                "available": available_cash,
                            }
                        
                        # ATOMIC: Reserve the cash NOW using raw SQL UPDATE
                        # Row is already locked by SELECT FOR UPDATE above
                        new_available_cash = Decimal(str(available_cash)) - Decimal(str(required_capital))
                        await client.execute_raw(
                            '''UPDATE "portfolio_allocations" 
                               SET available_cash = $1, updated_at = NOW() 
                               WHERE id = $2''',
                            float(new_available_cash),
                            allocation_id
                        )
                        
                        self.logger.info(
                            "✅ ATOMIC cash reserved (DB-locked): Trade %s | ₹%.2f → ₹%.2f (reserved ₹%.2f) | Lock: %s",
                            trade_id, available_cash, float(new_available_cash), required_capital,
                            "acquired" if lock_acquired else "not_acquired"
                        )
                        
                        # Store reserved amount for potential rollback
                        reserved_cash_amount = required_capital
                        cash_rollback_needed = True

            # Prefer explicit trade price and quantity (fall back to execution log if present)
            executed_price = float(getattr(trade, "price", None) or getattr(record, "reference_price", 0.0) or 0.0)
            executed_quantity = int(getattr(trade, "quantity", None) or getattr(record, "quantity", 0) or 0)
            
            # CRITICAL VALIDATION: Ensure price and quantity are positive
            if executed_price <= 0:
                error_msg = f"Invalid execution price: {executed_price} (must be > 0)"
                self.logger.error("❌ %s", error_msg)
                await self.update_status(
                    execution_log_id,
                    status="rejected",
                    error_message=error_msg
                )
                await client.trade.update(
                    where={"id": trade_id},
                    data={"status": "rejected", "rejection_reason": error_msg}
                )
                return {"status": "rejected", "trade_id": trade_id, "reason": error_msg}
            
            if executed_quantity <= 0:
                error_msg = f"Invalid execution quantity: {executed_quantity} (must be > 0)"
                self.logger.error("❌ %s", error_msg)
                await self.update_status(
                    execution_log_id,
                    status="rejected",
                    error_message=error_msg
                )
                await client.trade.update(
                    where={"id": trade_id},
                    data={"status": "rejected", "rejection_reason": error_msg}
                )
                return {"status": "rejected", "trade_id": trade_id, "reason": error_msg}
            
            execution_time = datetime.utcnow()
            
            # Pass the underlying Trade record so NSE detection uses trade metadata
            auto_sell_at = _calculate_auto_sell_at(trade, execution_time, self.logger, trade_id)
            
            update_data = {"simulation": True}
            if auto_sell_at:
                update_data["auto_sell_at"] = auto_sell_at.isoformat()
            
            await self.update_status(
                execution_log_id,  # Use TradeExecutionLog ID, not Trade ID
                status="executed",
                executed_price=executed_price,
                executed_quantity=executed_quantity,
                metadata=update_data,
            )
            
            # ATOMIC trade status update - prevent duplicate execution
            client = await self._ensure_client()
            trade_update_data = {"status": "executed"}
            if auto_sell_at:
                # Pass datetime object directly instead of string for Prisma
                trade_update_data["auto_sell_at"] = auto_sell_at
            
            # Only update if still pending (atomic check-and-set)
            updated_count = await client.trade.update_many(
                where={"id": trade_id, "status": "pending"},
                data=trade_update_data,
            )
            
            if updated_count == 0:
                self.logger.warning(
                    "⚠️ Trade %s already executed by another worker, skipping duplicate",
                    trade_id
                )
                return {"status": "already_executed", "trade_id": trade_id}
            
            agent_type = getattr(record, "agent_type", None)
            if not agent_type and agent_id:
                # Try to get agent_type from metadata
                if hasattr(record, "metadata") and record.metadata:
                    import json
                    meta = record.metadata
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except:
                            meta = {}
                    if isinstance(meta, dict) and "agent_type" in meta:
                        agent_type = meta["agent_type"]
            # Use trade fields for symbol, side, quantity
            symbol = str(getattr(trade, "symbol", ""))
            side = str(getattr(trade, "side", ""))
            quantity = int(getattr(trade, "quantity", 0) or 0)
            
            if agent_id:
                self.logger.info(
                    "✅ Simulated trade execution: Trade %s | Agent %s (%s) | %s %s x %d @ ₹%.2f",
                    trade_id,
                    agent_id,
                    agent_type or "unknown",
                    side,
                    symbol,
                    quantity,
                    executed_price,
                )
            else:
                self.logger.info(
                    "✅ Simulated trade execution: Trade %s | %s %s x %d @ ₹%.2f (no agent)",
                    trade_id,
                    side,
                    symbol,
                    quantity,
                    executed_price,
                )
            
            # Create TP/SL orders for NSE pipeline trades
            await self._create_tp_sl_orders(
                record,
                executed_price=executed_price,
                executed_quantity=executed_quantity,
            )
            
            # Add trade to portfolio allocation and trigger portfolio update
            try:
                await self._update_portfolio_allocation(
                    record,
                    executed_price=executed_price,
                    executed_quantity=executed_quantity,
                    auto_sell_at=auto_sell_at,
                )
                # Mark cash as successfully used (no rollback needed)
                cash_rollback_needed = False
            except Exception as portfolio_error:
                # CRITICAL: Portfolio update failed - mark trade as failed AND rollback cash
                self.logger.error(
                    "❌ Portfolio update failed for trade %s: %s - marking trade as FAILED and rolling back cash",
                    trade_id,
                    portfolio_error,
                    exc_info=True
                )
                
                # ROLLBACK: Return reserved cash to allocation
                if 'reserved_cash_amount' in locals() and 'allocation_id' in locals() and cash_rollback_needed:
                    try:
                        async with allocation_lock(allocation_id, timeout=15.0):
                            rollback_allocation = await client.portfolioallocation.find_unique(
                                where={"id": allocation_id}
                            )
                            if rollback_allocation:
                                rollback_cash = Decimal(str(getattr(rollback_allocation, "available_cash", 0))) + Decimal(str(reserved_cash_amount))
                                await client.portfolioallocation.update(
                                    where={"id": allocation_id},
                                    data={"available_cash": rollback_cash}
                                )
                                self.logger.info(
                                    "✅ ROLLBACK: Returned ₹%.2f to allocation %s after failed trade",
                                    reserved_cash_amount, allocation_id
                                )
                    except Exception as rollback_error:
                        self.logger.error(
                            "❌ CRITICAL: Cash rollback failed for trade %s: %s - MANUAL RECONCILIATION REQUIRED",
                            trade_id, rollback_error
                        )
                
                await self.update_status(
                    execution_log_id,
                    status="failed",
                    error_message=f"Portfolio update failed: {str(portfolio_error)}",
                )
                await client.trade.update(
                    where={"id": trade_id},
                    data={"status": "failed"},
                )
                return {
                    "status": "failed",
                    "trade_id": trade_id,
                    "error": f"Portfolio update failed: {str(portfolio_error)}",
                }
            
            # P&L calculation now happens INSIDE transaction with position update
            # (removed duplicate call - see _update_portfolio_allocation transaction block)

            return {
                "status": "executed",
                "trade_id": trade_id,
                "executed_price": executed_price,
                "executed_quantity": executed_quantity,
            }

        # Placeholder for real broker integration
        await self.update_status(
            trade_id,
            status="failed",
            error_message="Live broker integration not configured",
        )
        self.logger.error("Live execution not configured for trade %s", trade_id)
        return {
            "status": "failed",
            "trade_id": trade_id,
            "error": "Live broker integration not configured",
        }
    
    async def _create_tp_sl_orders(
        self,
        trade_record: Any,
        *,
        executed_price: float,
        executed_quantity: int,
    ) -> None:
        """
        Create take-profit and stop-loss orders for an executed trade.

        This creates pending orders that will be monitored by the order monitor worker.
        Uses the fixed TP/SL prices calculated during trade creation.

        Args:
            trade_record: The executed TradeExecutionLog record (with linked Trade)
            executed_price: Price at which the trade was executed
            executed_quantity: Quantity that was executed
        """

        client = await self._ensure_client()

        # Get the linked Trade record to access TP/SL prices and other fields
        if not hasattr(trade_record, "trade") or not trade_record.trade:
            self.logger.warning(
                "Cannot create TP/SL orders: no linked Trade for TradeExecutionLog %s",
                getattr(trade_record, "id", ""),
            )
            return
        
        parent_trade = trade_record.trade
        
        # Skip TP/SL orders for alpha signals - they manage their own exit strategy
        metadata = {}
        if hasattr(parent_trade, "metadata") and parent_trade.metadata:
            meta_raw = parent_trade.metadata
            if isinstance(meta_raw, str):
                try:
                    metadata = json.loads(meta_raw)
                except:
                    metadata = {}
            elif isinstance(meta_raw, dict):
                metadata = meta_raw
        
        triggered_by = metadata.get("triggered_by", "")
        if triggered_by.startswith("alpha_signal:"):
            self.logger.info(
                "⏭️ Skipping TP/SL orders for alpha signal trade %s (triggered_by=%s)",
                getattr(parent_trade, "id", ""),
                triggered_by,
            )
            return
        
        # Extract fields from parent trade
        portfolio_id = str(getattr(parent_trade, "portfolio_id", ""))
        symbol = str(getattr(parent_trade, "symbol", ""))
        side = str(getattr(parent_trade, "side", "BUY"))
        
        # Get fixed TP/SL prices from parent trade
        tp_price_raw = getattr(parent_trade, "take_profit_price", None)
        sl_price_raw = getattr(parent_trade, "stop_loss_price", None)
        
        if not tp_price_raw or not sl_price_raw:
            self.logger.warning(
                "Cannot create TP/SL orders: missing TP/SL prices for trade %s",
                getattr(parent_trade, "id", ""),
            )
            return
        
        tp_price = float(tp_price_raw)
        sl_price = float(sl_price_raw)
        
        # Get TP/SL percentages for logging
        tp_pct = float(getattr(parent_trade, "take_profit_pct", Decimal("0.02")))
        sl_pct = float(getattr(parent_trade, "stop_loss_pct", Decimal("0.01")))

        self.logger.debug(
            "Creating TP/SL orders for %s: TP @ ₹%.2f (%.1f%%), SL @ ₹%.2f (%.1f%%)",
            symbol, tp_price, tp_pct * 100, sl_price, sl_pct * 100
        )

        if not portfolio_id or not symbol:
            self.logger.warning(
                "Cannot create TP/SL orders: missing required fields for trade %s",
                getattr(parent_trade, "id", ""),
            )
            return

        try:
            # Get portfolio for organization/customer info
            portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})

            # Determine TP/SL sides based on original trade side
            if side == "BUY":
                # For long positions, TP and SL are both SELL
                tp_side = "SELL"
                sl_side = "SELL"
            else:
                # For short positions, TP and SL are both BUY
                tp_side = "BUY"
                sl_side = "BUY"

            # Create Take-Profit Order
            tp_metadata = {
                "order_type": "take_profit",
                "parent_trade_id": str(parent_trade.id),
                "triggered_by": "nse_pipeline_tp",
                "target_price": tp_price,
                "target_pct": tp_pct,
            }

            # Create TP Trade record
            tp_trade_data = {
                "portfolio_id": portfolio_id,
                "organization_id": getattr(portfolio, "organization_id", None) if portfolio else None,
                "customer_id": getattr(portfolio, "customer_id", None) if portfolio else None,
                "trade_type": "auto",
                "symbol": symbol,
                "exchange": "NSE",
                "segment": "EQUITY",
                "side": tp_side,
                "order_type": "limit",  # TP is a limit order
                "quantity": executed_quantity,
                "limit_price": self._as_decimal(tp_price),
                "price": self._as_decimal(tp_price),
                "trigger_price": self._as_decimal(tp_price),
                "status": "pending",
                "source": "nse_pipeline_tp_sl",
                "metadata": json.dumps(tp_metadata),
            }

            # Copy NSE fields from parent trade
            if hasattr(parent_trade, "signal_id") and parent_trade.signal_id:
                tp_trade_data["signal_id"] = parent_trade.signal_id
            if hasattr(parent_trade, "allocated_capital"):
                tp_trade_data["allocated_capital"] = parent_trade.allocated_capital
            if hasattr(parent_trade, "confidence"):
                tp_trade_data["confidence"] = parent_trade.confidence
            if hasattr(parent_trade, "agent_id") and parent_trade.agent_id:
                tp_trade_data["agent_id"] = parent_trade.agent_id

            tp_trade_record = await client.trade.create(data=tp_trade_data)

            # Create TP TradeExecutionLog
            tp_execution_record = await client.tradeexecutionlog.create(
                data={
                    "trade_id": tp_trade_record.id,
                    "request_id": f"tp_{uuid.uuid4().hex[:12]}",
                    "status": "pending",
                    "order_type": "take_profit",
                    "metadata": json.dumps(tp_metadata),
                }
            )

            self.logger.info(
                "✅ Created TP order %s (Trade: %s): %s %s x %d @ ₹%.2f (%.1f%% profit target)",
                tp_execution_record.id,
                tp_trade_record.id,
                tp_side,
                symbol,
                executed_quantity,
                tp_price,
                tp_pct * 100,
            )

            # Create Stop-Loss Order
            sl_metadata = {
                "order_type": "stop_loss",
                "parent_trade_id": str(parent_trade.id),
                "triggered_by": "nse_pipeline_sl",
                "target_price": sl_price,
                "target_pct": sl_pct,
            }

            # Create SL Trade record
            sl_trade_data = {
                "portfolio_id": portfolio_id,
                "organization_id": getattr(portfolio, "organization_id", None) if portfolio else None,
                "customer_id": getattr(portfolio, "customer_id", None) if portfolio else None,
                "trade_type": "auto",
                "symbol": symbol,
                "exchange": "NSE",
                "segment": "EQUITY",
                "side": sl_side,
                "order_type": "stop",  # SL is a stop-loss order
                "quantity": executed_quantity,
                "limit_price": self._as_decimal(sl_price),
                "price": self._as_decimal(sl_price),
                "trigger_price": self._as_decimal(sl_price),
                "status": "pending",
                "source": "nse_pipeline_tp_sl",
                "metadata": json.dumps(sl_metadata),
            }

            # Copy NSE fields from parent trade
            if hasattr(parent_trade, "signal_id") and parent_trade.signal_id:
                sl_trade_data["signal_id"] = parent_trade.signal_id
            if hasattr(parent_trade, "allocated_capital"):
                sl_trade_data["allocated_capital"] = parent_trade.allocated_capital
            if hasattr(parent_trade, "confidence"):
                sl_trade_data["confidence"] = parent_trade.confidence
            if hasattr(parent_trade, "agent_id") and parent_trade.agent_id:
                sl_trade_data["agent_id"] = parent_trade.agent_id

            sl_trade_record = await client.trade.create(data=sl_trade_data)

            # Create SL TradeExecutionLog
            sl_execution_record = await client.tradeexecutionlog.create(
                data={
                    "trade_id": sl_trade_record.id,
                    "request_id": f"sl_{uuid.uuid4().hex[:12]}",
                    "status": "pending",
                    "order_type": "stop_loss",
                    "metadata": json.dumps(sl_metadata),
                }
            )

            self.logger.info(
                "✅ Created SL order %s (Trade: %s): %s %s x %d @ ₹%.2f (%.1f%% loss limit)",
                sl_execution_record.id,
                sl_trade_record.id,
                sl_side,
                symbol,
                executed_quantity,
                sl_price,
                sl_pct * 100,
            )

        except Exception as exc:
            self.logger.error(
                "Failed to create TP/SL orders for trade %s: %s",
                getattr(trade_record, "id", ""),
                exc,
                exc_info=True
            )
    
    async def _calculate_realized_pnl(
        self,
        trade_record: Any,
        *,
        executed_price: float,
        executed_quantity: int,
    ) -> None:
        """
        Calculate and accumulate realized P&L for SELL trades only.
        
        Realized P&L = (sell_price - average_buy_price) * quantity
        Accumulates at Trade, TradingAgent, PortfolioAllocation, and Portfolio levels.
        
        Args:
            trade_record: The executed trade log record (TradeExecutionLog with linked Trade)
            executed_price: Price at which the trade was executed
            executed_quantity: Quantity that was executed
        """
        client = await self._ensure_client()
        
        # DEBUG: Log function entry
        self.logger.info("🔍 _calculate_realized_pnl called for trade_record: %s", getattr(trade_record, "id", "unknown"))
        
        # Get the linked Trade record to access side and other fields
        if not hasattr(trade_record, "trade") or not trade_record.trade:
            self.logger.warning(
                "Cannot calculate realized P&L: no linked Trade for TradeExecutionLog %s",
                getattr(trade_record, "id", ""),
            )
            return
        
        parent_trade = trade_record.trade
        side = str(getattr(parent_trade, "side", "")).upper()
        
        # DEBUG: Log trade side
        self.logger.info("🔍 Trade side: %s (will calculate P&L only for SELL)", side)
        
        # Only calculate realized P&L for SELL trades
        if side != "SELL":
            self.logger.debug("Skipping P&L calculation for non-SELL trade")
            return
        
        portfolio_id = str(getattr(parent_trade, "portfolio_id", ""))
        symbol = str(getattr(parent_trade, "symbol", ""))
        agent_id = getattr(parent_trade, "agent_id", None)
        trade_id = str(parent_trade.id)
        
        if not portfolio_id or not symbol:
            self.logger.warning(
                "Cannot calculate realized P&L: missing portfolio_id or symbol for trade %s",
                trade_id,
            )
            return
        
        self.logger.info("🔍 Looking for position: portfolio=%s, symbol=%s", portfolio_id, symbol)
        
        try:
            # Find the position for this symbol to get average_buy_price
            # Query for ANY position (open or closed) since position might be updated during execution
            position = await client.position.find_first(
                where={
                    "portfolio_id": portfolio_id,
                    "symbol": {"equals": symbol, "mode": "insensitive"},
                },
                order={"updated_at": "desc"}  # Get most recent position
            )
            
            if not position:
                self.logger.warning(
                    "Cannot calculate realized P&L: no position found for %s in portfolio %s",
                    symbol,
                    portfolio_id,
                )
                return
            
            self.logger.info("🔍 Found position: avg_buy_price=₹%.2f, quantity=%d", 
                           float(getattr(position, "average_buy_price", 0)),
                           int(getattr(position, "quantity", 0)))
            
            average_buy_price = float(getattr(position, "average_buy_price", 0))
            if average_buy_price == 0:
                self.logger.warning(
                    "Cannot calculate realized P&L: invalid average_buy_price for position %s",
                    symbol,
                )
                return
            
            # Calculate realized P&L
            realized_pnl = (executed_price - average_buy_price) * executed_quantity
            realized_pnl_decimal = self._as_decimal(realized_pnl)
            
            self.logger.info(
                "💰 Realized P&L for SELL trade %s: %s %d @ ₹%.2f (avg buy: ₹%.2f) = ₹%.2f",
                trade_id,
                symbol,
                executed_quantity,
                executed_price,
                average_buy_price,
                realized_pnl,
            )
            
            # Update Trade record with realized P&L
            try:
                await client.trade.update(
                    where={"id": trade_id},
                    data={"realized_pnl": realized_pnl_decimal},
                )
                self.logger.debug("Updated Trade %s with realized P&L: ₹%.2f", trade_id, realized_pnl)
            except Exception as trade_exc:
                self.logger.warning("Failed to update Trade %s with realized P&L: %s", trade_id, trade_exc)
            
            # Accumulate realized P&L at Portfolio level
            portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
            if portfolio:
                current_portfolio_pnl = float(getattr(portfolio, "total_realized_pnl", 0) or 0)
                new_portfolio_pnl = self._as_decimal(current_portfolio_pnl + realized_pnl)
                await client.portfolio.update(
                    where={"id": portfolio_id},
                    data={"total_realized_pnl": new_portfolio_pnl},
                )
            
            # Accumulate realized P&L at Allocation and Agent levels
            if agent_id:
                try:
                    agent = await client.tradingagent.find_unique(
                        where={"id": str(agent_id)},
                        include={"allocation": True},
                    )
                    
                    if agent:
                        # Update TradingAgent realized P&L
                        current_agent_pnl = float(getattr(agent, "realized_pnl", 0) or 0)
                        new_agent_pnl = self._as_decimal(current_agent_pnl + realized_pnl)
                        await client.tradingagent.update(
                            where={"id": str(agent_id)},
                            data={"realized_pnl": new_agent_pnl},
                        )
                        
                        # Update PortfolioAllocation realized P&L
                        allocation = agent.allocation
                        if allocation:
                            current_allocation_pnl = float(getattr(allocation, "realized_pnl", 0) or 0)
                            new_allocation_pnl = self._as_decimal(current_allocation_pnl + realized_pnl)
                            await client.portfolioallocation.update(
                                where={"id": allocation.id},
                                data={"realized_pnl": new_allocation_pnl},
                            )
                            
                            self.logger.info(
                                "✅ Accumulated realized P&L: Agent %s (+₹%.2f), Allocation %s (+₹%.2f), Portfolio %s (+₹%.2f)",
                                agent_id,
                                realized_pnl,
                                allocation.id,
                                realized_pnl,
                                portfolio_id,
                                realized_pnl,
                            )
                except Exception as agent_exc:
                    self.logger.warning(
                        "Failed to update agent/allocation realized P&L: %s",
                        agent_exc,
                    )
            
        except Exception as exc:
            self.logger.error(
                "Failed to calculate realized P&L for trade %s: %s",
                trade_id,
                exc,
                exc_info=True,
            )
    
    async def _update_portfolio_allocation(
        self,
        trade_record: Any,
        *,
        executed_price: float,
        executed_quantity: int,
        auto_sell_at: Optional[datetime] = None,
    ) -> None:
        """
        Update portfolio allocation and trigger value recalculation after trade execution.
        
        This method:
        1. Adds the trade to the portfolio's allocation trades array
        2. Triggers portfolio value recalculation
        
        Args:
            trade_record: The executed trade log record
            executed_price: Price at which the trade was executed
            executed_quantity: Quantity that was executed
            auto_sell_at: Optional timestamp for auto-selling NSE pipeline trades
        """
        
        client = await self._ensure_client()
        
        # Get the linked Trade record to access portfolio_id and other fields
        # trade_record is a TradeExecutionLog which doesn't have portfolio_id directly
        if not hasattr(trade_record, "trade") or not trade_record.trade:
            self.logger.warning(
                "Cannot update portfolio allocation: no linked Trade for TradeExecutionLog %s",
                getattr(trade_record, "id", ""),
            )
            return
        
        parent_trade = trade_record.trade
        
        portfolio_id = str(getattr(parent_trade, "portfolio_id", ""))
        symbol = str(getattr(parent_trade, "symbol", ""))
        side = str(getattr(parent_trade, "side", "BUY"))
        
        if not portfolio_id:
            self.logger.warning(
                "Cannot update portfolio allocation: missing portfolio_id in Trade %s for TradeExecutionLog %s",
                getattr(parent_trade, "id", ""),
                getattr(trade_record, "id", ""),
            )
            return
        
        try:
            # Fetch current portfolio
            portfolio = await client.portfolio.find_unique(
                where={"id": portfolio_id},
                include={"positions": True}
            )
            
            if not portfolio:
                self.logger.warning("Portfolio %s not found", portfolio_id)
                return
            
            # Get current allocation trades (parse JSON)
            current_allocations = []
            if portfolio.allocation_trades:
                if isinstance(portfolio.allocation_trades, str):
                    try:
                        current_allocations = json.loads(portfolio.allocation_trades)
                    except json.JSONDecodeError:
                        current_allocations = []
                elif isinstance(portfolio.allocation_trades, list):
                    current_allocations = portfolio.allocation_trades
            
            # Parse metadata to get triggered_by information
            metadata = {}
            if hasattr(trade_record, "metadata"):
                meta = getattr(trade_record, "metadata")
                if isinstance(meta, dict):
                    metadata = meta
                elif isinstance(meta, str) and meta:
                    try:
                        metadata = json.loads(meta)
                    except json.JSONDecodeError:
                        pass
            
            # Create allocation entry
            allocation_entry = {
                "trade_log_id": str(getattr(trade_record, "id", "")),
                "symbol": symbol,
                "side": side,
                "quantity": executed_quantity,
                "executed_price": executed_price,
                "allocated_capital": float(getattr(trade_record, "allocated_capital", 0)),
                "confidence": float(getattr(trade_record, "confidence", 0)),
                "triggered_by": metadata.get("triggered_by", "high_risk_agent"),
                "executed_at": str(getattr(trade_record, "created_at", "")),
            }
            
            # Append to allocation trades
            updated_allocations = [*current_allocations, allocation_entry]
            
            # Update portfolio - serialize to JSON string
            await client.portfolio.update(
                where={"id": portfolio_id},
                data={"allocation_trades": json.dumps(updated_allocations)}
            )
            
            self.logger.info(
                "✅ Added trade to portfolio allocation (triggered by %s): %s %s x %d @ ₹%.2f",
                allocation_entry["triggered_by"],
                side,
                symbol,
                executed_quantity,
                executed_price,
            )
            
            # Update existing Trade record (created in create_trade_log)
            # We already have parent_trade from the linked TradeExecutionLog
            trade_id = str(parent_trade.id)
            existing_trade = parent_trade

            # Calculate fees and taxes (simulation mode - minimal fees)
            fees = Decimal("0.0")
            taxes = Decimal("0.0")
            net_amount = Decimal(str(executed_price * executed_quantity))

            # Use auto_sell_at from parameter if provided, otherwise check record
            if auto_sell_at is None:
                if hasattr(trade_record, "auto_sell_at") and trade_record.auto_sell_at:
                    auto_sell_at = trade_record.auto_sell_at
                elif isinstance(metadata, dict) and "auto_sell_at" in metadata:
                    try:
                        auto_sell_at = datetime.fromisoformat(metadata["auto_sell_at"])
                    except (ValueError, TypeError, AttributeError) as e:
                        self.logger.warning(f"Invalid auto_sell_at in metadata: {e}")
                        pass

            if auto_sell_at:
                self.logger.info(
                    "⏰ Setting auto_sell_at for Trade record: %s (from %s)",
                    auto_sell_at,
                    "parameter" if auto_sell_at else "trade_record/metadata"
                )

            # Update Trade record with execution details
            trade_update_data = {
                "status": "executed",
                "executed_price": executed_price,
                "executed_quantity": executed_quantity,
                "execution_time": datetime.utcnow(),
                "fees": fees,
                "taxes": taxes,
                "net_amount": net_amount,
            }

            if auto_sell_at:
                trade_update_data["auto_sell_at"] = auto_sell_at

            # Update metadata to include execution details
            existing_metadata = {}
            if hasattr(existing_trade, "metadata") and existing_trade.metadata:
                if isinstance(existing_trade.metadata, str):
                    try:
                        existing_metadata = json.loads(existing_trade.metadata)
                    except json.JSONDecodeError:
                        existing_metadata = {}
                elif isinstance(existing_trade.metadata, dict):
                    existing_metadata = existing_trade.metadata

            # Add execution details to metadata
            existing_metadata.update({
                "executed_at": str(datetime.utcnow()),
                "execution_price": executed_price,
                "execution_quantity": executed_quantity,
            })

            trade_update_data["metadata"] = json.dumps(existing_metadata)

            await client.trade.update(
                where={"id": trade_id},
                data=trade_update_data
            )

            self.logger.info(
                "✅ Updated Trade record %s: %s %s x %d @ ₹%.2f",
                trade_id,
                side,
                symbol,
                executed_quantity,
                executed_price,
            )

            # Get agent_id and agent_type from the existing Trade record
            agent_id = getattr(existing_trade, "agent_id", None)
            agent_type = None

            # Try to get agent_type from metadata if not in record
            if not agent_type:
                if hasattr(existing_trade, "metadata") and existing_trade.metadata:
                    meta = existing_trade.metadata
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except:
                            meta = {}
                    if isinstance(meta, dict) and "agent_type" in meta:
                        agent_type = meta["agent_type"]

            if agent_id:
                try:
                    # Get current agent to update trades array
                    agent = await client.tradingagent.find_unique(
                        where={"id": str(agent_id)},
                        include={"allocation": True},
                    )
                    
                    if not agent:
                        self.logger.warning("Agent %s not found for trade update", agent_id)
                        return
                    
                    # Get current trades array from metadata
                    agent_metadata = {}
                    if hasattr(agent, "metadata"):
                        meta = getattr(agent, "metadata")
                        if isinstance(meta, dict):
                            agent_metadata = meta
                        elif isinstance(meta, str) and meta:
                            try:
                                agent_metadata = json.loads(meta)
                            except json.JSONDecodeError:
                                pass
                    
                    # Get or initialize trades array
                    trades_array = agent_metadata.get("trades", [])
                    if not isinstance(trades_array, list):
                        trades_array = []
                    
                    # Add new trade to agent's trades array
                    trade_entry = {
                        "trade_id": str(trade_id),  # Trade record ID
                        "trade_log_id": str(getattr(trade_record, "id", "")),  # TradeExecutionLog ID
                        "symbol": symbol,
                        "side": side,
                        "quantity": executed_quantity,
                        "executed_price": executed_price,
                        "allocated_capital": float(getattr(trade_record, "allocated_capital", 0)),
                        "confidence": float(getattr(trade_record, "confidence", 0)),
                        "executed_at": str(getattr(trade_record, "created_at", "")),
                        "triggered_by": metadata.get("triggered_by", "high_risk_agent"),
                    }
                    trades_array.append(trade_entry)
                    agent_metadata["trades"] = trades_array
                    
                    # Update trading agent with trades array and last_executed_at
                    from prisma import fields
                    agent = await client.tradingagent.update(
                        where={"id": str(agent_id)},
                        data={
                            "last_executed_at": datetime.utcnow(),
                            "metadata": fields.Json(agent_metadata),
                        },
                        include={"allocation": True},
                    )
                    
                    self.logger.info(
                        "✅ Updated trading agent %s (%s) after trade execution: %s %s x %d @ ₹%.2f | Trades in array: %d",
                        agent_id,
                        agent_type or "unknown",
                        side,
                        symbol,
                        executed_quantity,
                        executed_price,
                        len(trades_array),
                    )
                    
                except Exception as agent_exc:
                    self.logger.warning(
                        "Failed to update trading agent %s (%s) after execution: %s",
                        agent_id,
                        agent_type or "unknown",
                        agent_exc,
                    )

            # Create or update position for this trade
            import time
            position_start = time.time()
            
            self.logger.info(
                "🔄 Calling _create_or_update_position: portfolio=%s, symbol=%s, side=%s, qty=%d, price=%.2f, trade=%s, agent=%s",
                portfolio_id,
                symbol,
                side,
                executed_quantity,
                executed_price,
                trade_id,
                agent_id or "None"
            )
            
            # CRITICAL: Wrap position update + P&L calculation in database transaction
            # This ensures atomic execution - either both succeed or both fail
            try:
                # Start transaction
                await client.execute_raw('BEGIN')
                self.logger.debug("🔒 Started database transaction for position update")
                
                # Update position atomically
                await self._create_or_update_position(
                    portfolio_id=portfolio_id,
                    symbol=symbol,
                    side=side,
                    quantity=executed_quantity,
                    executed_price=executed_price,
                    trade_id=trade_id,
                    client=client,
                    agent_id=agent_id,  # Link position to trading agent
                )
                
                # Calculate P&L within same transaction (if SELL trade)
                if side.upper() in ["SELL", "COVER"]:
                    # P&L calculation happens in same transaction - uses same position data
                    parent_trade = trade_record.trade
                    symbol_for_pnl = str(getattr(parent_trade, "symbol", ""))
                    
                    # Query position WITHIN transaction to ensure consistency
                    position = await client.position.find_first(
                        where={
                            "portfolio_id": portfolio_id,
                            "symbol": {"equals": symbol_for_pnl, "mode": "insensitive"},
                        },
                        order={"updated_at": "desc"}
                    )
                    
                    if position:
                        average_buy_price = float(getattr(position, "average_buy_price", 0))
                        if average_buy_price > 0:
                            realized_pnl = (executed_price - average_buy_price) * executed_quantity
                            realized_pnl_decimal = self._as_decimal(realized_pnl)
                            
                            # Update Trade, Portfolio, Allocation, Agent P&L atomically
                            await client.trade.update(
                                where={"id": trade_id},
                                data={"realized_pnl": realized_pnl_decimal}
                            )
                            
                            # Accumulate at Portfolio level
                            await client.execute_raw(
                                '''UPDATE "portfolios" 
                                   SET total_realized_pnl = total_realized_pnl + $1 
                                   WHERE id = $2''',
                                float(realized_pnl_decimal),
                                portfolio_id
                            )
                            
                            # Accumulate at Allocation and Agent levels if applicable
                            if agent_id:
                                agent = await client.tradingagent.find_unique(
                                    where={"id": agent_id},
                                    include={"allocation": True}
                                )
                                if agent:
                                    # Update agent P&L
                                    await client.execute_raw(
                                        '''UPDATE "trading_agents" 
                                           SET realized_pnl = realized_pnl + $1 
                                           WHERE id = $2''',
                                        float(realized_pnl_decimal),
                                        agent_id
                                    )
                                    
                                    # Update allocation P&L
                                    if agent.allocation:
                                        await client.execute_raw(
                                            '''UPDATE "portfolio_allocations" 
                                               SET realized_pnl = realized_pnl + $1 
                                               WHERE id = $2''',
                                            float(realized_pnl_decimal),
                                            agent.allocation.id
                                        )
                            
                            self.logger.info(
                                "💰 [TRANSACTION] Realized P&L for SELL: %s @ ₹%.2f (avg: ₹%.2f) = ₹%.2f",
                                symbol, executed_price, average_buy_price, realized_pnl
                            )
                
                # Commit transaction
                await client.execute_raw('COMMIT')
                self.logger.debug("✅ Committed database transaction")
                
            except Exception as tx_error:
                # Rollback on any error
                try:
                    await client.execute_raw('ROLLBACK')
                    self.logger.error("❌ Rolled back database transaction due to error: %s", tx_error)
                except:
                    pass
                raise  # Re-raise to trigger outer error handling
            
            position_time = (time.time() - position_start) * 1000
            self.logger.info("✅ [PERF] Position update + P&L (transactional) took %.1fms", position_time)

            # Trigger portfolio value recalculation
            portfolio_start = time.time()
            await self._recalculate_portfolio_value(portfolio_id, client)
            portfolio_time = (time.time() - portfolio_start) * 1000
            if portfolio_time > 10:
                self.logger.info("✅ [PERF] Portfolio recalc took %.1fms", portfolio_time)
            
        except Exception as exc:
            self.logger.error(
                "Failed to update portfolio allocation for trade %s: %s",
                getattr(trade_record, "id", ""),
                exc,
                exc_info=True
            )
            # Re-raise to ensure trade is marked as failed
            raise
    
    async def _cancel_pending_tp_sl_orders(
        self,
        portfolio_id: str,
        symbol: str,
        client: Any,
    ) -> None:
        """
        Cancel all pending TP/SL orders for a symbol when position is closed.
        
        Args:
            portfolio_id: Portfolio ID
            symbol: Stock symbol
            client: Prisma client
        """
        try:
            # Find all pending TP/SL orders for this symbol
            pending_orders = await client.trade.find_many(
                where={
                    "portfolio_id": portfolio_id,
                    "symbol": {"equals": symbol, "mode": "insensitive"},
                    "status": "pending",
                    "source": "nse_pipeline_tp_sl",
                }
            )
            
            if not pending_orders:
                return
            
            # Cancel each pending order
            for order in pending_orders:
                metadata = {}
                if hasattr(order, "metadata") and order.metadata:
                    meta = getattr(order, "metadata")
                    if isinstance(meta, str):
                        try:
                            metadata = json.loads(meta)
                        except:
                            metadata = {}
                    elif isinstance(meta, dict):
                        metadata = meta
                
                metadata["cancelled_at"] = datetime.utcnow().isoformat()
                metadata["cancel_reason"] = "position_closed"
                
                await client.trade.update(
                    where={"id": order.id},
                    data={
                        "status": "cancelled",
                        "metadata": json.dumps(metadata),
                    }
                )
                
                order_type = metadata.get("order_type", "unknown")
                self.logger.info(
                    "✅ Cancelled pending %s order for %s (position closed)",
                    order_type.upper(),
                    symbol,
                )
        except Exception as exc:
            self.logger.warning(
                "Failed to cancel pending TP/SL orders for %s: %s",
                symbol,
                exc,
            )
    
    async def _create_or_update_position(
        self,
        portfolio_id: str,
        symbol: str,
        side: str,
        quantity: int,
        executed_price: float,
        trade_id: str,
        client: Any,
        agent_id: str = None,
        exchange: str = "NSE",
        segment: str = "EQ",
    ) -> None:
        """
        Create a new position or update existing position after trade execution.
        
        For BUY trades: increases quantity (or creates new position)
        For SELL trades: decreases quantity (or closes position if quantity reaches 0)
        
        Includes:
        - Pre-trade validation (sufficient cash for BUY, sufficient holdings for SELL)
        - Cash tracking (deduct for BUY, add for SELL)
        
        Args:
            portfolio_id: Portfolio ID
            symbol: Stock symbol
            side: Trade side (BUY/SELL)
            quantity: Trade quantity
            executed_price: Execution price
            trade_id: Trade ID to link
            client: Prisma client
            agent_id: Optional trading agent ID
            exchange: Exchange (default NSE)
            segment: Segment (default EQ)
        """
        
        try:
            # Initialize validation service
            validation_service = TradeValidationService()
            
            # Validate trade before execution
            # Note: Cash validation for BUY is already done at execution time with SELECT FOR UPDATE
            # This secondary validation is for position checks only
            if side.upper() == "SELL":
                # SELL (close LONG) - requires existing long position
                validation_result = await validation_service.validate_sell_order(
                    portfolio_id=portfolio_id,
                    agent_id=agent_id,
                    symbol=symbol,
                    quantity=quantity,
                )
                
                if not validation_result["valid"]:
                    error_msg = validation_result.get("reason", "Unknown error")
                    self.logger.error(
                        "❌ SELL validation failed for %s: %s",
                        symbol,
                        error_msg
                    )
                    # Raise ValueError to trigger rollback if cash was already reserved
                    raise ValueError(f"Insufficient holdings: {error_msg}")
            
            elif side.upper() == "SHORT_SELL":
                # SHORT_SELL: Require margin to prevent unlimited loss exposure
                # Industry standard: 150% margin (50% initial + 100% short value)
                short_value = Decimal(str(executed_price * quantity))
                required_margin = short_value * Decimal("1.5")  # 150% of short value
                
                # Check if agent has sufficient margin (use available_cash as margin)
                if agent_id:
                    client = await self._ensure_client()
                    agent = await client.tradingagent.find_unique(
                        where={"id": agent_id},
                        include={"allocation": True}
                    )
                    if agent and agent.allocation:
                        available_cash = float(getattr(agent.allocation, "available_cash", 0) or 0)
                        
                        if available_cash < float(required_margin):
                            error_msg = (
                                f"Insufficient margin for SHORT_SELL: requires ₹{required_margin:.2f} "
                                f"(150% of ₹{short_value:.2f}), available ₹{available_cash:.2f}"
                            )
                            self.logger.error("❌ %s", error_msg)
                            raise ValueError(error_msg)
                        
                        self.logger.info(
                            "✅ SHORT_SELL margin check passed: %s | ₹%.2f short value, ₹%.2f margin required, ₹%.2f available",
                            symbol, float(short_value), float(required_margin), available_cash
                        )
                else:
                    # No agent_id - skip margin check (legacy compatibility)
                    self.logger.warning(
                        "⚠️ SHORT_SELL without agent_id - margin check skipped for %s",
                        symbol
                    )
            
            # Check if position already exists
            existing_position = await client.position.find_first(
                where={
                    "portfolio_id": portfolio_id,
                    "symbol": symbol,
                    "status": "open",
                }
            )
            
            if side.upper() == "BUY":
                if existing_position:
                    # ATOMIC UPDATE: Use raw SQL to prevent race conditions
                    old_quantity = int(getattr(existing_position, "quantity", 0))
                    old_avg_price = float(getattr(existing_position, "average_buy_price", 0))
                    position_id = str(existing_position.id)
                    
                    # Get existing trade IDs array from metadata
                    position_metadata = {}
                    if hasattr(existing_position, "metadata") and existing_position.metadata:
                        meta = getattr(existing_position, "metadata")
                        if isinstance(meta, str):
                            try:
                                position_metadata = json.loads(meta)
                            except:
                                position_metadata = {}
                        elif isinstance(meta, dict):
                            position_metadata = meta
                    
                    trade_ids = position_metadata.get("trade_ids", [])
                    if not isinstance(trade_ids, list):
                        trade_ids = []
                    trade_ids.append(trade_id)
                    position_metadata["trade_ids"] = trade_ids
                    position_metadata["last_updated"] = datetime.utcnow().isoformat()
                    
                    # ATOMIC position update using raw SQL with OPTIMISTIC LOCKING
                    # WHERE clause checks quantity matches expected value to detect concurrent modifications
                    result = await client.execute_raw(
                        '''UPDATE "positions" SET 
                            quantity = quantity + $1,
                            average_buy_price = ((quantity * average_buy_price) + ($1 * $2)) / (quantity + $1),
                            updated_at = NOW(),
                            metadata = $3::jsonb,
                            agent_id = COALESCE(agent_id, $4)
                            WHERE id = $5 AND quantity = $6 AND status = 'open'
                            RETURNING id''',
                        quantity,
                        executed_price,
                        json.dumps(position_metadata),
                        agent_id if agent_id and not getattr(existing_position, "agent_id", None) else None,
                        position_id,
                        old_quantity  # Optimistic lock: only update if quantity hasn't changed
                    )
                    
                    # Check if update succeeded (RETURNING clause)
                    if not result or len(result) == 0:
                        self.logger.warning(
                            "⚠️ Optimistic lock failed for BUY %s - position modified concurrently, retrying...",
                            symbol
                        )
                        # Retry with fresh data
                        fresh_position = await client.position.find_first(
                            where={"id": position_id, "status": "open"}
                        )
                        if not fresh_position:
                            raise ValueError(f"Position {position_id} not found or closed during update")
                        
                        # Retry update with fresh quantity
                        old_quantity = int(getattr(fresh_position, "quantity", 0))
                        result = await client.execute_raw(
                            '''UPDATE "positions" SET 
                                quantity = quantity + $1,
                                average_buy_price = ((quantity * average_buy_price) + ($1 * $2)) / (quantity + $1),
                                updated_at = NOW(),
                                metadata = $3::jsonb,
                                agent_id = COALESCE(agent_id, $4)
                                WHERE id = $5 AND quantity = $6 AND status = 'open'
                                RETURNING id''',
                            quantity,
                            executed_price,
                            json.dumps(position_metadata),
                            agent_id if agent_id and not getattr(fresh_position, "agent_id", None) else None,
                            position_id,
                            old_quantity
                        )
                        if not result or len(result) == 0:
                            raise ValueError(f"Failed to update position {position_id} after retry - concurrent modification")
                    
                    # Calculate new values for logging (not used in update)
                    new_quantity = old_quantity + quantity
                    new_avg_price = ((old_quantity * old_avg_price) + (quantity * executed_price)) / new_quantity
                    
                    self.logger.info(
                        "✅ ATOMIC position update (optimistic lock) %s: %s qty %d→%d, avg price ₹%.2f→₹%.2f",
                        position_id,
                        symbol,
                        old_quantity,
                        new_quantity,
                        old_avg_price,
                        new_avg_price,
                    )
                else:
                    # Create new position (with race condition handling)
                    position_metadata = {
                        "trade_ids": [trade_id],
                        "created_at": datetime.utcnow().isoformat(),
                        "last_updated": datetime.utcnow().isoformat(),
                    }
                    
                    create_data = {
                        "portfolio_id": portfolio_id,
                        "symbol": symbol,
                        "exchange": exchange,
                        "segment": segment,
                        "quantity": quantity,
                        "average_buy_price": self._as_decimal(executed_price),
                        "position_type": "LONG",  # BUY = LONG position
                        "status": "open",
                        "opened_at": datetime.utcnow(),
                        "metadata": json.dumps(position_metadata),
                    }
                    
                    # Link agent and allocation if available
                    if agent_id:
                        create_data["agent_id"] = agent_id
                        # Fetch allocation_id from agent
                        agent = await client.tradingagent.find_unique(where={"id": agent_id})
                        if agent and hasattr(agent, "portfolio_allocation_id") and agent.portfolio_allocation_id:
                            create_data["allocation_id"] = agent.portfolio_allocation_id
                        else:
                            self.logger.warning(
                                "⚠️ Agent %s has no allocation_id, position will be created without allocation link",
                                agent_id
                            )
                    else:
                        self.logger.warning(
                            "⚠️ No agent_id provided for position creation, position will be created without agent/allocation link"
                        )
                    
                    try:
                        new_position = await client.position.create(data=create_data)
                        self.logger.info(
                            "✅ Created new position %s: %s x %d @ ₹%.2f",
                            new_position.id,
                            symbol,
                            quantity,
                            executed_price,
                        )
                    except Exception as create_error:
                        # Race condition: Another worker created position, retry update
                        if "Unique constraint" in str(create_error) or "duplicate key" in str(create_error).lower():
                            self.logger.warning(
                                "⚠️ Position creation race detected for %s, retrying as update",
                                symbol
                            )
                            # Refetch and update atomically
                            existing_position = await client.position.find_first(
                                where={
                                    "portfolio_id": portfolio_id,
                                    "symbol": symbol,
                                    "status": "open",
                                }
                            )
                            if existing_position:
                                position_id = str(existing_position.id)
                                await client.execute_raw(
                                    '''UPDATE "positions" SET 
                                        quantity = quantity + $1,
                                        average_buy_price = ((quantity * average_buy_price) + ($1 * $2)) / (quantity + $1),
                                        updated_at = NOW(),
                                        metadata = $3::jsonb
                                        WHERE id = $4''',
                                    quantity,
                                    executed_price,
                                    json.dumps(position_metadata),
                                    position_id
                                )
                                self.logger.info(
                                    "✅ Recovered from race: Updated position %s: %s + %d",
                                    position_id,
                                    symbol,
                                    quantity
                                )
                        else:
                            raise
                
                # Update cash tracking after BUY
                # NOTE: Allocation cash is ALREADY deducted atomically in execute_trade()
                # Here we only update portfolio-level cash
                total_cost = Decimal(str(executed_price)) * Decimal(str(quantity))
                
                # ATOMIC portfolio cash update using raw SQL
                portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
                if portfolio:
                    portfolio_cash = Decimal(str(getattr(portfolio, "available_cash", 0)))
                    
                    # Atomic decrement prevents race conditions
                    await client.execute_raw(
                        'UPDATE "portfolios" SET available_cash = available_cash - $1 WHERE id = $2',
                        float(total_cost),
                        portfolio_id
                    )
                    
                    new_portfolio_cash = portfolio_cash - total_cost
                    self.logger.info(
                        "💰 ATOMIC BUY deducted ₹%.2f from portfolio %s: ₹%.2f → ₹%.2f",
                        float(total_cost),
                        portfolio_id,
                        float(portfolio_cash),
                        float(new_portfolio_cash)
                    )
                    
            elif side.upper() == "SELL":
                if existing_position:
                    # Update existing position - reduce quantity
                    old_quantity = int(getattr(existing_position, "quantity", 0))
                    avg_buy_price = float(getattr(existing_position, "average_buy_price", 0))
                    new_quantity = old_quantity - quantity
                    
                    # Calculate realized P&L for sold portion
                    realized_pnl = quantity * (executed_price - avg_buy_price)
                    old_realized_pnl = float(getattr(existing_position, "realized_pnl", 0))
                    total_realized_pnl = old_realized_pnl + realized_pnl
                    
                    # Get existing trade IDs
                    position_metadata = {}
                    if hasattr(existing_position, "metadata") and existing_position.metadata:
                        meta = getattr(existing_position, "metadata")
                        if isinstance(meta, str):
                            try:
                                position_metadata = json.loads(meta)
                            except:
                                position_metadata = {}
                        elif isinstance(meta, dict):
                            position_metadata = meta
                    
                    trade_ids = position_metadata.get("trade_ids", [])
                    if not isinstance(trade_ids, list):
                        trade_ids = []
                    trade_ids.append(trade_id)
                    position_metadata["trade_ids"] = trade_ids
                    position_metadata["last_updated"] = datetime.utcnow().isoformat()
                    
                    position_id = str(existing_position.id)
                    
                    if new_quantity <= 0:
                        # ATOMIC close position with raw SQL
                        # Use optimistic locking: only close if current quantity matches expected
                        result = await client.execute_raw(
                            '''UPDATE "positions" SET 
                                quantity = 0,
                                status = 'closed',
                                realized_pnl = $1,
                                closed_at = NOW(),
                                updated_at = NOW(),
                                metadata = $2::jsonb
                                WHERE id = $3 AND status = 'open' AND quantity = $4
                                RETURNING id''',
                            float(total_realized_pnl),
                            json.dumps(position_metadata),
                            position_id,
                            old_quantity  # Optimistic lock: only update if quantity hasn't changed
                        )
                        
                        if not result:
                            self.logger.warning(
                                "⚠️ Position %s concurrent update detected during close, retrying...",
                                position_id
                            )
                            # Retry once with fresh data
                            existing_position = await client.position.find_first(
                                where={
                                    "portfolio_id": portfolio_id,
                                    "symbol": symbol,
                                    "status": "open",
                                }
                            )
                            if existing_position and existing_position.quantity >= quantity:
                                # Recursive retry with fresh position data
                                return await self._create_or_update_position(
                                    portfolio_id, symbol, side, quantity, executed_price,
                                    trade_id, client, agent_id, exchange, segment
                                )
                            else:
                                raise ValueError(
                                    f"Position {symbol} concurrent modification: insufficient quantity for SELL"
                                )
                        
                        self.logger.info(
                            "✅ ATOMIC closed position %s: %s qty %d→0 (SELL %d), realized P&L ₹%.2f",
                            position_id,
                            symbol,
                            old_quantity,
                            quantity,
                            realized_pnl,
                        )
                        
                        # Cancel pending TP/SL orders for this symbol
                        await self._cancel_pending_tp_sl_orders(portfolio_id, symbol, client)
                    else:
                        # ATOMIC reduce quantity with raw SQL using optimistic locking
                        result = await client.execute_raw(
                            '''UPDATE "positions" SET 
                                quantity = GREATEST(0, quantity - $1),
                                realized_pnl = $2,
                                updated_at = NOW(),
                                metadata = $3::jsonb
                                WHERE id = $4 AND status = 'open' AND quantity = $5
                                RETURNING id''',
                            quantity,
                            float(total_realized_pnl),
                            json.dumps(position_metadata),
                            position_id,
                            old_quantity  # Optimistic lock: only update if quantity hasn't changed
                        )
                        
                        if not result:
                            self.logger.warning(
                                "⚠️ Position %s concurrent update detected, retrying...",
                                position_id
                            )
                            # Retry once with fresh data
                            existing_position = await client.position.find_first(
                                where={
                                    "portfolio_id": portfolio_id,
                                    "symbol": symbol,
                                    "status": "open",
                                }
                            )
                            if existing_position and existing_position.quantity >= quantity:
                                # Recursive retry with fresh position data
                                return await self._create_or_update_position(
                                    portfolio_id, symbol, side, quantity, executed_price,
                                    trade_id, client, agent_id, exchange, segment
                                )
                            else:
                                raise ValueError(
                                    f"Position {symbol} concurrent modification: insufficient quantity for partial SELL"
                                )
                        
                        self.logger.info(
                            "✅ ATOMIC updated position %s: %s qty %d→%d (SELL %d), realized P&L ₹%.2f",
                            position_id,
                            symbol,
                            old_quantity,
                            new_quantity,
                            quantity,
                            realized_pnl,
                        )
                    
                    # Update cash tracking after SELL
                    sale_proceeds = Decimal(str(executed_price)) * Decimal(str(quantity))
                    
                    # Get allocation_id from position or agent
                    allocation_id = getattr(existing_position, "allocation_id", None)
                    
                    if allocation_id:
                        # ATOMIC allocation cash update with distributed lock
                        async with allocation_lock(allocation_id):
                            allocation = await client.portfolioallocation.find_unique(where={"id": allocation_id})
                            if allocation:
                                current_cash = Decimal(str(getattr(allocation, "available_cash", 0)))
                                
                                # Atomic increment
                                await client.execute_raw(
                                    'UPDATE "portfolio_allocations" SET available_cash = available_cash + $1 WHERE id = $2',
                                    float(sale_proceeds),
                                    allocation_id
                                )
                                
                                new_cash = current_cash + sale_proceeds
                                self.logger.info(
                                    "💰 ATOMIC added ₹%.2f to allocation %s: ₹%.2f → ₹%.2f",
                                    float(sale_proceeds),
                                    allocation_id,
                                    float(current_cash),
                                    float(new_cash)
                                )
                    
                    # ATOMIC portfolio cash update
                    portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
                    if portfolio:
                        portfolio_cash = Decimal(str(getattr(portfolio, "available_cash", 0)))
                        
                        await client.execute_raw(
                            'UPDATE "portfolios" SET available_cash = available_cash + $1 WHERE id = $2',
                            float(sale_proceeds),
                            portfolio_id
                        )
                        
                        new_portfolio_cash = portfolio_cash + sale_proceeds
                        self.logger.info(
                            "💰 ATOMIC added ₹%.2f to portfolio %s: ₹%.2f → ₹%.2f",
                            float(sale_proceeds),
                            portfolio_id,
                            float(portfolio_cash),
                            float(new_portfolio_cash)
                        )
                else:
                    self.logger.warning(
                        "⚠️ Cannot SELL %s x %d: no open position found in portfolio %s",
                        symbol,
                        quantity,
                        portfolio_id,
                    )
            
            elif side.upper() == "SHORT_SELL":
                # SHORT_SELL: Open new short position (sell without owning)
                # Check if short position already exists
                existing_short = await client.position.find_first(
                    where={
                        "portfolio_id": portfolio_id,
                        "symbol": symbol,
                        "position_type": "SHORT",
                        "status": "open",
                    }
                )
                
                if existing_short:
                    # Add to existing short position
                    old_quantity = int(getattr(existing_short, "quantity", 0))
                    old_avg_price = float(getattr(existing_short, "average_buy_price", 0))  # avg short price
                    
                    new_quantity = old_quantity + quantity
                    new_avg_price = ((old_quantity * old_avg_price) + (quantity * executed_price)) / new_quantity
                    
                    position_metadata = {}
                    if hasattr(existing_short, "metadata") and existing_short.metadata:
                        meta = getattr(existing_short, "metadata")
                        if isinstance(meta, str):
                            try:
                                position_metadata = json.loads(meta)
                            except:
                                position_metadata = {}
                        elif isinstance(meta, dict):
                            position_metadata = meta
                    
                    trade_ids = position_metadata.get("trade_ids", [])
                    if not isinstance(trade_ids, list):
                        trade_ids = []
                    trade_ids.append(trade_id)
                    position_metadata["trade_ids"] = trade_ids
                    position_metadata["last_updated"] = datetime.utcnow().isoformat()
                    
                    # ATOMIC SHORT position update using raw SQL
                    short_id = str(existing_short.id)
                    await client.execute_raw(
                        '''UPDATE "positions" SET 
                            quantity = quantity + $1,
                            average_buy_price = ((quantity * average_buy_price) + ($1 * $2)) / (quantity + $1),
                            updated_at = NOW(),
                            metadata = $3::jsonb
                            WHERE id = $4 AND position_type = 'SHORT' ''',
                        quantity,
                        executed_price,
                        json.dumps(position_metadata),
                        short_id
                    )
                    
                    # Calculate for logging
                    new_quantity = old_quantity + quantity
                    new_avg_price = ((old_quantity * old_avg_price) + (quantity * executed_price)) / new_quantity
                    
                    self.logger.info(
                        "✅ ATOMIC updated SHORT position %s: %s qty %d→%d, avg short price ₹%.2f→₹%.2f",
                        short_id,
                        symbol,
                        old_quantity,
                        new_quantity,
                        old_avg_price,
                        new_avg_price,
                    )
                else:
                    # Create new short position
                    position_metadata = {
                        "trade_ids": [trade_id],
                        "created_at": datetime.utcnow().isoformat(),
                        "last_updated": datetime.utcnow().isoformat(),
                    }
                    
                    create_data = {
                        "portfolio_id": portfolio_id,
                        "symbol": symbol,
                        "exchange": exchange,
                        "segment": segment,
                        "quantity": quantity,
                        "average_buy_price": self._as_decimal(executed_price),  # Short entry price
                        "position_type": "SHORT",
                        "status": "open",
                        "opened_at": datetime.utcnow(),
                        "metadata": json.dumps(position_metadata),
                    }
                    
                    if agent_id:
                        create_data["agent_id"] = agent_id
                        agent = await client.tradingagent.find_unique(where={"id": agent_id})
                        if agent and hasattr(agent, "portfolio_allocation_id") and agent.portfolio_allocation_id:
                            create_data["allocation_id"] = agent.portfolio_allocation_id
                        else:
                            self.logger.warning("⚠️ Agent %s has no allocation_id, SHORT position will be created without allocation link", agent_id)
                    else:
                        self.logger.warning("⚠️ No agent_id provided for SHORT position creation, position will be created without agent/allocation link")
                    
                    try:
                        new_position = await client.position.create(data=create_data)
                        self.logger.info(
                            "✅ Created new SHORT position %s: %s x %d @ ₹%.2f",
                            new_position.id,
                            symbol,
                            quantity,
                            executed_price,
                        )
                    except Exception as create_error:
                        # Race condition: Another worker created SHORT position, retry update
                        if "Unique constraint" in str(create_error) or "duplicate key" in str(create_error).lower():
                            self.logger.warning(
                                "⚠️ SHORT position creation race detected for %s, retrying as update",
                                symbol
                            )
                            # Refetch and update atomically
                            existing_short = await client.position.find_first(
                                where={
                                    "portfolio_id": portfolio_id,
                                    "symbol": symbol,
                                    "position_type": "SHORT",
                                    "status": "open",
                                }
                            )
                            if existing_short:
                                short_id = str(existing_short.id)
                                await client.execute_raw(
                                    '''UPDATE "positions" SET 
                                        quantity = quantity + $1,
                                        average_buy_price = ((quantity * average_buy_price) + ($1 * $2)) / (quantity + $1),
                                        updated_at = NOW(),
                                        metadata = $3::jsonb
                                        WHERE id = $4 AND position_type = 'SHORT' ''',
                                    quantity,
                                    executed_price,
                                    json.dumps(position_metadata),
                                    short_id
                                )
                                self.logger.info(
                                    "✅ Recovered from race: Updated SHORT position %s: %s + %d",
                                    short_id,
                                    symbol,
                                    quantity
                                )
                        else:
                            raise
                
                # SHORT_SELL receives cash (we sell shares we don't own)
                sale_proceeds = Decimal(str(executed_price)) * Decimal(str(quantity))
                
                allocation_id = None
                if agent_id:
                    agent = await client.tradingagent.find_unique(where={"id": agent_id})
                    if agent:
                        allocation_id = getattr(agent, "portfolio_allocation_id", None)
                
                if allocation_id:
                    # ATOMIC allocation cash update with distributed lock
                    async with allocation_lock(allocation_id):
                        allocation = await client.portfolioallocation.find_unique(where={"id": allocation_id})
                        if allocation:
                            current_cash = Decimal(str(getattr(allocation, "available_cash", 0)))
                            
                            # Atomic increment
                            await client.execute_raw(
                                'UPDATE "portfolio_allocations" SET available_cash = available_cash + $1 WHERE id = $2',
                                float(sale_proceeds),
                                allocation_id
                            )
                            
                            new_cash = current_cash + sale_proceeds
                            self.logger.info(
                                "💰 ATOMIC SHORT_SELL added ₹%.2f to allocation %s: ₹%.2f → ₹%.2f",
                                float(sale_proceeds),
                                allocation_id,
                                float(current_cash),
                                float(new_cash)
                            )
                
                # ATOMIC portfolio cash update
                portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
                if portfolio:
                    portfolio_cash = Decimal(str(getattr(portfolio, "available_cash", 0)))
                    
                    await client.execute_raw(
                        'UPDATE "portfolios" SET available_cash = available_cash + $1 WHERE id = $2',
                        float(sale_proceeds),
                        portfolio_id
                    )
                    
                    new_portfolio_cash = portfolio_cash + sale_proceeds
                    self.logger.info(
                        "💰 ATOMIC SHORT_SELL added ₹%.2f to portfolio %s: ₹%.2f → ₹%.2f",
                        float(sale_proceeds),
                        portfolio_id,
                        float(portfolio_cash),
                        float(new_portfolio_cash)
                    )
            
            elif side.upper() == "COVER":
                # COVER: Close short position (buy to cover)
                existing_short = await client.position.find_first(
                    where={
                        "portfolio_id": portfolio_id,
                        "symbol": symbol,
                        "position_type": "SHORT",
                        "status": "open",
                    }
                )
                
                if existing_short:
                    old_quantity = int(getattr(existing_short, "quantity", 0))
                    avg_short_price = float(getattr(existing_short, "average_buy_price", 0))
                    new_quantity = old_quantity - quantity
                    
                    # Calculate realized P&L for SHORT: profit when cover price < short price
                    # P&L = (short_entry_price - cover_price) * quantity
                    # Positive when cover_price < short_entry_price (profit)
                    # Negative when cover_price > short_entry_price (loss)
                    realized_pnl = (avg_short_price - executed_price) * quantity
                    old_realized_pnl = float(getattr(existing_short, "realized_pnl", 0))
                    total_realized_pnl = old_realized_pnl + realized_pnl
                    
                    position_metadata = {}
                    if hasattr(existing_short, "metadata") and existing_short.metadata:
                        meta = getattr(existing_short, "metadata")
                        if isinstance(meta, str):
                            try:
                                position_metadata = json.loads(meta)
                            except:
                                position_metadata = {}
                        elif isinstance(meta, dict):
                            position_metadata = meta
                    
                    trade_ids = position_metadata.get("trade_ids", [])
                    if not isinstance(trade_ids, list):
                        trade_ids = []
                    trade_ids.append(trade_id)
                    position_metadata["trade_ids"] = trade_ids
                    position_metadata["last_updated"] = datetime.utcnow().isoformat()
                    
                    short_id = str(existing_short.id)
                    
                    if new_quantity <= 0:
                        # ATOMIC close short position with raw SQL using optimistic locking
                        result = await client.execute_raw(
                            '''UPDATE "positions" SET 
                                quantity = 0,
                                status = 'closed',
                                realized_pnl = $1,
                                closed_at = NOW(),
                                updated_at = NOW(),
                                metadata = $2::jsonb
                                WHERE id = $3 AND position_type = 'SHORT' AND status = 'open' AND quantity = $4
                                RETURNING id''',
                            float(total_realized_pnl),
                            json.dumps(position_metadata),
                            short_id,
                            old_quantity  # Optimistic lock
                        )
                        
                        if not result:
                            self.logger.warning(
                                "⚠️ SHORT position %s concurrent update detected during close, retrying...",
                                short_id
                            )
                            existing_short = await client.position.find_first(
                                where={
                                    "portfolio_id": portfolio_id,
                                    "symbol": symbol,
                                    "position_type": "SHORT",
                                    "status": "open",
                                }
                            )
                            if existing_short and existing_short.quantity >= quantity:
                                return await self._create_or_update_position(
                                    portfolio_id, symbol, side, quantity, executed_price,
                                    trade_id, client, agent_id, exchange, segment
                                )
                            else:
                                raise ValueError(
                                    f"SHORT position {symbol} concurrent modification during COVER"
                                )
                        
                        self.logger.info(
                            "✅ ATOMIC closed SHORT position %s: %s qty %d→0 (COVER %d), realized P&L ₹%.2f",
                            short_id,
                            symbol,
                            old_quantity,
                            quantity,
                            realized_pnl,
                        )
                        
                        # Cancel pending TP/SL orders
                        await self._cancel_pending_tp_sl_orders(portfolio_id, symbol, client)
                    else:
                        # ATOMIC reduce short position quantity with raw SQL using optimistic locking
                        result = await client.execute_raw(
                            '''UPDATE "positions" SET 
                                quantity = GREATEST(0, quantity - $1),
                                realized_pnl = $2,
                                updated_at = NOW(),
                                metadata = $3::jsonb
                                WHERE id = $4 AND position_type = 'SHORT' AND status = 'open' AND quantity = $5
                                RETURNING id''',
                            quantity,
                            float(total_realized_pnl),
                            json.dumps(position_metadata),
                            short_id,
                            old_quantity  # Optimistic lock
                        )
                        
                        if not result:
                            self.logger.warning(
                                "⚠️ SHORT position %s concurrent update detected, retrying...",
                                short_id
                            )
                            existing_short = await client.position.find_first(
                                where={
                                    "portfolio_id": portfolio_id,
                                    "symbol": symbol,
                                    "position_type": "SHORT",
                                    "status": "open",
                                }
                            )
                            if existing_short and existing_short.quantity >= quantity:
                                return await self._create_or_update_position(
                                    portfolio_id, symbol, side, quantity, executed_price,
                                    trade_id, client, agent_id, exchange, segment
                                )
                            else:
                                raise ValueError(
                                    f"SHORT position {symbol} concurrent modification during partial COVER"
                                )
                        
                        self.logger.info(
                            "✅ ATOMIC updated SHORT position %s: %s qty %d→%d (COVER %d), realized P&L ₹%.2f",
                            short_id,
                            symbol,
                            old_quantity,
                            new_quantity,
                            quantity,
                            realized_pnl,
                        )
                    
                    # COVER costs cash (we buy back shares)
                    cover_cost = Decimal(str(executed_price)) * Decimal(str(quantity))
                    
                    allocation_id = getattr(existing_short, "allocation_id", None)
                    
                    if allocation_id:
                        # ATOMIC allocation cash update with distributed lock
                        async with allocation_lock(allocation_id):
                            allocation = await client.portfolioallocation.find_unique(where={"id": allocation_id})
                            if allocation:
                                current_cash = Decimal(str(getattr(allocation, "available_cash", 0)))
                                
                                # Atomic decrement
                                await client.execute_raw(
                                    'UPDATE "portfolio_allocations" SET available_cash = available_cash - $1 WHERE id = $2',
                                    float(cover_cost),
                                    allocation_id
                                )
                                
                                new_cash = current_cash - cover_cost
                                self.logger.info(
                                    "💰 ATOMIC COVER deducted ₹%.2f from allocation %s: ₹%.2f → ₹%.2f",
                                    float(cover_cost),
                                    allocation_id,
                                    float(current_cash),
                                    float(new_cash)
                                )
                    
                    # ATOMIC portfolio cash update
                    portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
                    if portfolio:
                        portfolio_cash = Decimal(str(getattr(portfolio, "available_cash", 0)))
                        
                        await client.execute_raw(
                            'UPDATE "portfolios" SET available_cash = available_cash - $1 WHERE id = $2',
                            float(cover_cost),
                            portfolio_id
                        )
                        
                        new_portfolio_cash = portfolio_cash - cover_cost
                        self.logger.info(
                            "💰 ATOMIC COVER deducted ₹%.2f from portfolio %s: ₹%.2f → ₹%.2f",
                            float(cover_cost),
                            portfolio_id,
                            float(portfolio_cash),
                            float(new_portfolio_cash)
                        )
                else:
                    error_msg = f"Cannot COVER {symbol} x {quantity}: no open SHORT position found in portfolio {portfolio_id}"
                    self.logger.error("❌ %s", error_msg)
                    raise ValueError(error_msg)
                    
        except ValueError as ve:
            # Re-raise validation errors (COVER without position, etc.)
            self.logger.error(
                "Validation error for %s %s x %d: %s",
                side, symbol, quantity, ve
            )
            raise
        except Exception as exc:
            self.logger.error(
                "Failed to create/update position for %s %s x %d: %s",
                side,
                symbol,
                quantity,
                exc,
                exc_info=True
            )
            raise RuntimeError(f"Position update failed for {symbol}: {exc}") from exc
    
    async def _recalculate_portfolio_value(
        self,
        portfolio_id: str,
        client: Any,
    ) -> None:
        """
        Update portfolio metrics after position changes.
        
        Note: With the new schema, portfolio uses available_cash (not current_value).
        Position values are calculated on-the-fly using live prices when needed.
        This method can be used for other portfolio-level updates if needed.
        
        Args:
            portfolio_id: Portfolio ID
            client: Prisma client
        """
        
        try:
            self.logger.debug(
                "Portfolio %s updated (position change tracked)",
                portfolio_id,
            )
            
        except Exception as exc:
            self.logger.error(
                "Failed to update portfolio metrics for %s: %s",
                portfolio_id,
                exc,
                exc_info=True
            )
    
    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """Convert value to float safely."""
        if value is None:
            return default
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    
    async def create_alpha_trade(
        self,
        alpha,
        symbol: str,
        signal_type: str,
        quantity: Optional[int] = None,
        confidence: float = 1.0,
        reference_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Create a trade from an alpha signal.
        
        This method:
        1. Gets or creates an alpha agent for the alpha's portfolio
        2. Validates the trade against available allocation
        3. Creates trade execution log and persists to database
        4. Optionally executes the trade in simulation mode
        
        Args:
            alpha: LiveAlpha Prisma model
            symbol: Stock symbol
            signal_type: 'buy' or 'sell'
            quantity: Number of shares (calculated from allocation if not provided)
            confidence: Signal confidence (0-1)
            reference_price: Current price (fetched if not provided)
            
        Returns:
            Dict with trade execution result
        """
        client = await self._ensure_client()
        
        portfolio_id = alpha.portfolio_id
        allocated_amount = float(alpha.allocated_amount)
        
        # Fetch portfolio with agents
        portfolio = await client.portfolio.find_unique(
            where={"id": portfolio_id},
            include={
                "agents": {
                    "where": {"agent_type": "alpha", "status": "active"},
                    "include": {"allocation": True}
                }
            }
        )
        
        if not portfolio:
            raise ValueError(f"Portfolio {portfolio_id} not found")
        
        # Get or create alpha agent
        alpha_agent = await self._get_or_create_alpha_agent(
            client=client,
            portfolio=portfolio,
            alpha=alpha,
        )
        
        if not alpha_agent or not alpha_agent.allocation:
            raise ValueError(f"Alpha agent or allocation not found for alpha {alpha.id}")
        
        allocation_id = alpha_agent.allocation.id
        agent_id = alpha_agent.id
        
        # Get reference price if not provided
        if reference_price is None:
            try:
                from market_data import await_live_price
                reference_price = await await_live_price(symbol, timeout=10.0)
            except Exception as e:
                self.logger.warning("Failed to get live price for %s: %s", symbol, e)
                # Try to get from cached data
                from market_data import get_market_data_service
                market_data = get_market_data_service()
                reference_price = market_data.get_latest_price(symbol)
                if reference_price is None:
                    raise ValueError(f"Unable to get price for {symbol}")
        
        # Calculate quantity if not provided
        if quantity is None or quantity <= 0:
            # Allocate based on strategy (equal weight for top-k)
            strategy_params = (alpha.workflow_config or {}).get("strategy", {}).get("params", {})
            topk = strategy_params.get("topk", 10)
            allocation_per_stock = allocated_amount / topk if topk > 0 else allocated_amount
            quantity = int(allocation_per_stock / reference_price) if reference_price > 0 else 0
        
        if quantity <= 0:
            self.logger.warning(
                "Calculated quantity is 0 for %s (allocation: ₹%.2f, price: ₹%.2f)",
                symbol, allocated_amount, reference_price
            )
            return {"status": "skipped", "reason": "quantity_zero", "symbol": symbol}
        
        # Validate available cash in allocation
        available_cash = float(alpha_agent.allocation.available_cash or 0)
        required_amount = reference_price * quantity
        
        if signal_type.lower() == "buy" and available_cash < required_amount:
            self.logger.warning(
                "Insufficient allocation cash for alpha %s: need ₹%.2f, have ₹%.2f",
                alpha.id, required_amount, available_cash
            )
            return {
                "status": "skipped",
                "reason": "insufficient_cash",
                "required": required_amount,
                "available": available_cash,
                "symbol": symbol,
            }
        
        # Determine trade side
        side = "BUY" if signal_type.lower() == "buy" else "SELL"
        
        # Build job row for trade creation
        import uuid
        job_row = {
            "request_id": str(uuid.uuid4()),
            "user_id": portfolio.customer_id,
            "organization_id": portfolio.organization_id,
            "portfolio_id": portfolio_id,
            "customer_id": portfolio.customer_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "reference_price": float(reference_price),
            "exchange": "NSE",
            "segment": "EQUITY",
            "agent_id": agent_id,
            "agent_type": "alpha",
            "allocation_id": allocation_id,
            "triggered_by": f"alpha_signal_{alpha.id}",
            "confidence": confidence,
            "allocated_capital": required_amount,
            "take_profit_pct": 0.03,  # 3% TP for alpha trades
            "stop_loss_pct": 0.02,  # 2% SL for alpha trades
            "explanation": f"Alpha signal: {signal_type} {symbol} from {alpha.name}",
            "filing_time": "",
            "generated_at": datetime.utcnow().isoformat(),
            "metadata_json": json.dumps({
                "alpha_id": alpha.id,
                "alpha_name": alpha.name,
                "signal_type": signal_type,
                "confidence": confidence,
            }),
        }
        
        # Persist trade
        events = await self.persist_and_publish([job_row], publish_kafka=False)
        
        if not events:
            raise RuntimeError("Failed to create trade execution log")
        
        event = events[0]
        trade_id = event.trade_id
        
        # Execute trade in simulation mode
        result = await self.execute_trade(trade_id, simulate=True)
        
        self.logger.info(
            "✅ Alpha trade created: %s %s x %d @ ₹%.2f | Alpha: %s | Status: %s",
            side,
            symbol,
            quantity,
            reference_price,
            alpha.name,
            result.get("status", "unknown"),
        )
        
        return result
    
    async def _get_or_create_alpha_agent(
        self,
        client,
        portfolio,
        alpha,
    ):
        """
        Get or create an alpha agent for the given alpha and portfolio.
        
        Each LiveAlpha gets its own TradingAgent of type 'alpha' with
        dedicated allocation from the portfolio.
        """
        # Check if alpha already has an agent
        if alpha.agent_id:
            agent = await client.tradingagent.find_unique(
                where={"id": alpha.agent_id},
                include={"allocation": True}
            )
            if agent and agent.allocation:
                return agent
        
        # Look for existing alpha agents with this alpha's allocation
        existing_agents = [a for a in (portfolio.agents or []) if a.agent_type == "alpha"]
        
        for agent in existing_agents:
            # Check if this agent is for this alpha
            if hasattr(agent, "metadata") and agent.metadata:
                meta = agent.metadata
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except:
                        meta = {}
                if meta.get("alpha_id") == alpha.id:
                    # Found existing agent for this alpha
                    if agent.allocation:
                        return agent
        
        # Create new allocation for alpha
        allocation = await client.portfolioallocation.create(
            data={
                "portfolio_id": portfolio.id,
                "allocation_type": "alpha",
                "target_weight": Decimal("0"),  # Alpha allocations don't use weights
                "current_weight": Decimal("0"),
                "allocated_amount": alpha.allocated_amount,
                "available_cash": alpha.allocated_amount,
                "metadata": json.dumps({
                    "alpha_id": alpha.id,
                    "alpha_name": alpha.name,
                }),
            }
        )
        
        # Create alpha agent
        agent = await client.tradingagent.create(
            data={
                "portfolio_id": portfolio.id,
                "portfolio_allocation_id": allocation.id,
                "agent_type": "alpha",
                "agent_name": f"Alpha: {alpha.name}",
                "status": "active",
                "strategy_config": alpha.workflow_config,
                "metadata": json.dumps({
                    "alpha_id": alpha.id,
                    "alpha_name": alpha.name,
                    "hypothesis": alpha.hypothesis,
                }),
            },
            include={"allocation": True}
        )
        
        # Update alpha with agent_id
        await client.livealpha.update(
            where={"id": alpha.id},
            data={"agent_id": agent.id}
        )
        
        self.logger.info(
            "✅ Created alpha agent %s with allocation %s for alpha %s",
            agent.id,
            allocation.id,
            alpha.name,
        )
        
        return agent


__all__ = ["TradeExecutionService", "TradeExecutionRecord"]
