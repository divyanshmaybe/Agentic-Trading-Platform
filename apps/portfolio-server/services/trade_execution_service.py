"""
Trade Execution Service

Provides helpers for persisting auto-trade jobs, publishing events, and delegating
execution to broker integrations.
"""

from __future__ import annotations

import json
import logging
import uuid
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


def _parse_metadata(metadata):
    """Parse metadata from string or dict."""
    if not metadata:
        return {}
    if isinstance(metadata, str):
        try:
            return json.loads(metadata)
        except:
            return {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _calculate_auto_sell_at(record, execution_time, logger, trade_id):
    """Calculate auto_sell_at timestamp for high-risk NSE pipeline trades."""
    metadata = _parse_metadata(getattr(record, "metadata", None))
    triggered_by = metadata.get("triggered_by", "")
    agent_type = getattr(record, "agent_type", None) or metadata.get("agent_type", "")
    
    logger.info(
        "🔍 AUTO_SELL_AT DEBUG for trade %s: triggered_by='%s', agent_type='%s', metadata=%s",
        trade_id, triggered_by, agent_type, metadata
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
        if not self._manager.is_connected():
            await self._manager.connect()
        return self._manager.get_client()

    @staticmethod
    def _as_decimal(value: Any, precision: str = "0.0001") -> Decimal:
        try:
            return Decimal(str(value)).quantize(Decimal(precision), rounding=ROUND_HALF_UP)
        except Exception:
            return Decimal("0")

    async def create_trade_log(
        self,
        job_row: Dict[str, Any],
        *,
        client: Optional[Any] = None,
    ) -> TradeExecutionRecord:
        """Persist a trade execution job into the database.

        Creates both a Trade record (containing all trade details) and a TradeExecutionLog
        record (tracking execution attempts) linked by trade_id.
        """

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
            # For BUY: TP above entry, SL below entry
            tp_price = reference_price * (Decimal("1") + tp_pct)
            sl_price = reference_price * (Decimal("1") - sl_pct)
        else:  # SELL
            # For SELL: TP below entry, SL above entry
            tp_price = reference_price * (Decimal("1") - tp_pct)
            sl_price = reference_price * (Decimal("1") + sl_pct)
        
        # Set 15-minute auto-sell window from now
        auto_sell_at = datetime.utcnow() + timedelta(minutes=15)
        
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
            "auto_sell_at": auto_sell_at.isoformat() + "Z",  # 15-minute window with timezone
            "take_profit_pct": tp_pct,
            "stop_loss_pct": sl_pct,
            "take_profit_price": tp_price,
            "stop_loss_price": sl_price,
        }

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
        
        # Set portfolio_id (direct field, not relation)
        if portfolio_id:
            trade_data["portfolio_id"] = portfolio_id

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
            self.logger.info("📤 Publishing %d trade execution event(s) to Kafka...", len(events))
            publish_trade_execution_events(events, logger=self.logger)
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
        if status in ["executed", "simulated_executed"] and (executed_price is not None or executed_quantity is not None):
            trade_update_data = {"status": "executed"}
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
                self.logger.debug("Updated Trade %s status to executed", linked_trade_id)
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
                    except:
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

            # Prefer explicit trade price and quantity (fall back to execution log if present)
            executed_price = float(getattr(trade, "price", None) or getattr(record, "reference_price", 0.0) or 0.0)
            executed_quantity = int(getattr(trade, "quantity", None) or getattr(record, "quantity", 0) or 0)
            execution_time = datetime.utcnow()
            
            # Pass the underlying Trade record so NSE detection uses trade metadata
            auto_sell_at = _calculate_auto_sell_at(trade, execution_time, self.logger, trade_id)
            
            update_data = {"simulation": True}
            if auto_sell_at:
                update_data["auto_sell_at"] = auto_sell_at.isoformat()
            
            await self.update_status(
                execution_log_id,  # Use TradeExecutionLog ID, not Trade ID
                status="simulated_executed",
                executed_price=executed_price,
                executed_quantity=executed_quantity,
                metadata=update_data,
            )
            
            # Update auto_sell_at on the Trade record (not TradeExecutionLog)
            if auto_sell_at:
                client = await self._ensure_client()
                await client.trade.update(
                    where={"id": trade_id},  # Use Trade ID
                    data={"auto_sell_at": auto_sell_at.isoformat() + "Z"},
                )
            
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
            
            # Calculate and update realized P&L for SELL trades
            await self._calculate_realized_pnl(
                record,
                executed_price=executed_price,
                executed_quantity=executed_quantity,
            )
            
            # Add trade to portfolio allocation and trigger portfolio update
            await self._update_portfolio_allocation(
                record,
                executed_price=executed_price,
                executed_quantity=executed_quantity,
                auto_sell_at=auto_sell_at,
            )
            
            return {
                "status": "simulated_executed",
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
        
        # Get the linked Trade record to access side and other fields
        if not hasattr(trade_record, "trade") or not trade_record.trade:
            self.logger.warning(
                "Cannot calculate realized P&L: no linked Trade for TradeExecutionLog %s",
                getattr(trade_record, "id", ""),
            )
            return
        
        parent_trade = trade_record.trade
        side = str(getattr(parent_trade, "side", "")).upper()
        
        # Only calculate realized P&L for SELL trades
        if side != "SELL":
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
        
        try:
            # Find the position for this symbol to get average_buy_price
            position = await client.position.find_first(
                where={
                    "portfolio_id": portfolio_id,
                    "symbol": {"equals": symbol, "mode": "insensitive"},
                    "status": "open",
                }
            )
            
            if not position:
                self.logger.warning(
                    "Cannot calculate realized P&L: no open position found for %s in portfolio %s",
                    symbol,
                    portfolio_id,
                )
                return
            
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
                current_portfolio_pnl = float(getattr(portfolio, "realized_pnl", 0) or 0)
                new_portfolio_pnl = self._as_decimal(current_portfolio_pnl + realized_pnl)
                await client.portfolio.update(
                    where={"id": portfolio_id},
                    data={"realized_pnl": new_portfolio_pnl},
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
                    except:
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
                    
                    # Update PortfolioAllocation allocated_amount
                    if agent.allocation:
                        allocation = agent.allocation
                        allocated_capital = float(getattr(trade_record, "allocated_capital", 0))
                        
                        # Calculate new allocated amount
                        current_allocated = float(getattr(allocation, "allocated_amount", 0) or 0)
                        new_allocated = self._as_decimal(current_allocated + allocated_capital)
                        
                        await client.portfolioallocation.update(
                            where={"id": allocation.id},
                            data={"allocated_amount": new_allocated},
                        )
                        
                        self.logger.info(
                            "✅ Updated allocation %s: allocated_amount %.2f → %.2f (+%.2f)",
                            allocation.id,
                            current_allocated,
                            float(new_allocated),
                            allocated_capital,
                        )
                        
                except Exception as agent_exc:
                    self.logger.warning(
                        "Failed to update trading agent %s (%s) after execution: %s",
                        agent_id,
                        agent_type or "unknown",
                        agent_exc,
                    )

            # Create or update position for this trade
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
            self.logger.info("✅ _create_or_update_position completed for %s", symbol)

            # Trigger portfolio value recalculation
            await self._recalculate_portfolio_value(portfolio_id, client)
            
        except Exception as exc:
            self.logger.error(
                "Failed to update portfolio allocation for trade %s: %s",
                getattr(trade_record, "id", ""),
                exc,
                exc_info=True
            )
    
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
            if side.upper() == "BUY":
                # Calculate total cost
                total_cost = Decimal(str(executed_price)) * Decimal(str(quantity))
                
                # Validate available cash at portfolio or allocation level
                validation_result = await validation_service.validate_buy_order(
                    portfolio_id=portfolio_id,
                    agent_id=agent_id,  # Pass agent_id (can be None for manual trades)
                    symbol=symbol,
                    quantity=quantity,
                    price=Decimal(str(executed_price)),
                )
                
                if not validation_result["valid"]:
                    self.logger.error(
                        "❌ BUY validation failed for %s: %s",
                        symbol,
                        validation_result.get("error", "Unknown error")
                    )
                    raise ValueError(f"Insufficient funds: {validation_result.get('error')}")
                
            elif side.upper() == "SELL":
                # Validate sufficient holdings
                validation_result = await validation_service.validate_sell_order(
                    portfolio_id=portfolio_id,
                    agent_id=agent_id,  # Pass agent_id to find position
                    symbol=symbol,
                    quantity=quantity,
                )
                
                if not validation_result["valid"]:
                    self.logger.error(
                        "❌ SELL validation failed for %s: %s",
                        symbol,
                        validation_result.get("error", "Unknown error")
                    )
                    raise ValueError(f"Insufficient holdings: {validation_result.get('error')}")
            
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
                    # Update existing position - add to quantity and recalculate average price
                    old_quantity = int(getattr(existing_position, "quantity", 0))
                    old_avg_price = float(getattr(existing_position, "average_buy_price", 0))
                    
                    new_quantity = old_quantity + quantity
                    # Calculate new average price: (old_total + new_total) / new_quantity
                    new_avg_price = ((old_quantity * old_avg_price) + (quantity * executed_price)) / new_quantity
                    
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
                    
                    # Update position
                    update_data = {
                        "quantity": new_quantity,
                        "average_buy_price": self._as_decimal(new_avg_price),
                        "updated_at": datetime.utcnow(),
                        "metadata": json.dumps(position_metadata),
                    }
                    
                    # Link agent if provided and not already linked
                    if agent_id and not getattr(existing_position, "agent_id", None):
                        update_data["agent_id"] = agent_id
                    
                    await client.position.update(
                        where={"id": existing_position.id},
                        data=update_data
                    )
                    
                    self.logger.info(
                        "✅ Updated position %s: %s qty %d→%d, avg price ₹%.2f→₹%.2f",
                        existing_position.id,
                        symbol,
                        old_quantity,
                        new_quantity,
                        old_avg_price,
                        new_avg_price,
                    )
                else:
                    # Create new position
                    
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
                    
                    # Position requires both agent_id and allocation_id
                    if agent_id:
                        create_data["agent_id"] = agent_id
                        # Fetch allocation_id from agent
                        agent = await client.tradingagent.find_unique(where={"id": agent_id})
                        if agent and hasattr(agent, "portfolio_allocation_id"):
                            create_data["allocation_id"] = agent.portfolio_allocation_id
                        else:
                            self.logger.warning(
                                "⚠️ Agent %s has no allocation_id, skipping position creation",
                                agent_id
                            )
                            return
                    else:
                        self.logger.warning(
                            "⚠️ No agent_id provided for position creation, skipping"
                        )
                        return
                    
                    new_position = await client.position.create(data=create_data)
                    
                    self.logger.info(
                        "✅ Created new position %s: %s x %d @ ₹%.2f",
                        new_position.id,
                        symbol,
                        quantity,
                        executed_price,
                    )
                
                # Update cash tracking after BUY
                total_cost = Decimal(str(executed_price)) * Decimal(str(quantity))
                
                # Get allocation_id from agent or position
                allocation_id = None
                if agent_id:
                    agent = await client.tradingagent.find_unique(where={"id": agent_id})
                    if agent:
                        allocation_id = getattr(agent, "portfolio_allocation_id", None)
                
                if allocation_id:
                    # Deduct from allocation cash
                    allocation = await client.portfolioallocation.find_unique(where={"id": allocation_id})
                    if allocation:
                        current_cash = Decimal(str(getattr(allocation, "available_cash", 0)))
                        new_cash = current_cash - total_cost
                        await client.portfolioallocation.update(
                            where={"id": allocation_id},
                            data={"available_cash": new_cash}
                        )
                        self.logger.info(
                            "💰 Deducted ₹%.2f from allocation %s: ₹%.2f → ₹%.2f",
                            float(total_cost),
                            allocation_id,
                            float(current_cash),
                            float(new_cash)
                        )
                
                # Also update portfolio available_cash
                portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
                if portfolio:
                    portfolio_cash = Decimal(str(getattr(portfolio, "available_cash", 0)))
                    new_portfolio_cash = portfolio_cash - total_cost
                    await client.portfolio.update(
                        where={"id": portfolio_id},
                        data={"available_cash": new_portfolio_cash}
                    )
                    self.logger.info(
                        "💰 Deducted ₹%.2f from portfolio %s: ₹%.2f → ₹%.2f",
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
                    
                    if new_quantity <= 0:
                        # Close position
                        await client.position.update(
                            where={"id": existing_position.id},
                            data={
                                "quantity": 0,
                                "status": "closed",
                                "realized_pnl": self._as_decimal(total_realized_pnl),
                                "closed_at": datetime.utcnow(),
                                "updated_at": datetime.utcnow(),
                                "metadata": json.dumps(position_metadata),
                            }
                        )
                        
                        self.logger.info(
                            "✅ Closed position %s: %s qty %d→0 (SELL %d), realized P&L ₹%.2f",
                            existing_position.id,
                            symbol,
                            old_quantity,
                            quantity,
                            realized_pnl,
                        )
                        
                        # Cancel pending TP/SL orders for this symbol
                        await self._cancel_pending_tp_sl_orders(portfolio_id, symbol, client)
                    else:
                        # Reduce quantity
                        await client.position.update(
                            where={"id": existing_position.id},
                            data={
                                "quantity": new_quantity,
                                "realized_pnl": self._as_decimal(total_realized_pnl),
                                "updated_at": datetime.utcnow(),
                                "metadata": json.dumps(position_metadata),
                            }
                        )
                        
                        self.logger.info(
                            "✅ Updated position %s: %s qty %d→%d (SELL %d), realized P&L ₹%.2f",
                            existing_position.id,
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
                        # Add to allocation cash
                        allocation = await client.portfolioallocation.find_unique(where={"id": allocation_id})
                        if allocation:
                            current_cash = Decimal(str(getattr(allocation, "available_cash", 0)))
                            new_cash = current_cash + sale_proceeds
                            await client.portfolioallocation.update(
                                where={"id": allocation_id},
                                data={"available_cash": new_cash}
                            )
                            self.logger.info(
                                "💰 Added ₹%.2f to allocation %s: ₹%.2f → ₹%.2f",
                                float(sale_proceeds),
                                allocation_id,
                                float(current_cash),
                                float(new_cash)
                            )
                    
                    # Also update portfolio available_cash
                    portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
                    if portfolio:
                        portfolio_cash = Decimal(str(getattr(portfolio, "available_cash", 0)))
                        new_portfolio_cash = portfolio_cash + sale_proceeds
                        await client.portfolio.update(
                            where={"id": portfolio_id},
                            data={"available_cash": new_portfolio_cash}
                        )
                        self.logger.info(
                            "💰 Added ₹%.2f to portfolio %s: ₹%.2f → ₹%.2f",
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
                    
        except Exception as exc:
            self.logger.error(
                "Failed to create/update position for %s %s x %d: %s",
                side,
                symbol,
                quantity,
                exc,
                exc_info=True
            )
    
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


__all__ = ["TradeExecutionService", "TradeExecutionRecord"]
