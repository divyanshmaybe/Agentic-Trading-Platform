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
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional

import os

from db import get_db_manager  # type: ignore  # noqa: E402
from pipelines.nse.trade_execution_pipeline import (  # type: ignore  # noqa: E402
    TradeExecutionEvent,
    publish_trade_execution_events,
)


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
    
    is_nse_trade = (
        triggered_by == "nse_filings_pipeline" or
        agent_type == "high_risk" or
        "nse" in triggered_by.lower() or
        "nse_filings" in triggered_by.lower()
    )
    
    if not is_nse_trade:
        return None
    
    auto_sell_window_minutes = int(os.getenv("NSE_FILINGS_AUTO_SELL_WINDOW_MINUTES", "15"))
    auto_sell_at = execution_time + timedelta(minutes=auto_sell_window_minutes)
    
    if auto_sell_at.hour > 15 or (auto_sell_at.hour == 15 and auto_sell_at.minute > 30):
        logger.warning(
            "Auto-sell time %s would be after market close, skipping auto-sell for trade %s",
            auto_sell_at, trade_id
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
        """Persist a trade execution job into the database."""

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

        data = {
            "request_id": job_row["request_id"],
            "user_id": job_row["user_id"],
            "symbol": job_row["symbol"],
            "side": job_row["side"],
            "quantity": int(job_row["quantity"]),
            "reference_price": self._as_decimal(job_row["reference_price"]),
            "status": "pending",
            "metadata": json.dumps(metadata),
        }
        
        if job_row.get("portfolio_id"):
            data["portfolio_id"] = job_row["portfolio_id"]
        if job_row.get("agent_id"):
            data["agent_id"] = job_row["agent_id"]
        if job_row.get("agent_type"):
            data["agent_type"] = job_row["agent_type"]
        if job_row.get("signal_id"):
            data["signal_id"] = job_row["signal_id"]
        
        if job_row.get("allocated_capital"):
            data["allocated_capital"] = self._as_decimal(job_row["allocated_capital"])
        if job_row.get("confidence"):
            data["confidence"] = self._as_decimal(job_row["confidence"], "0.000001")
        if job_row.get("take_profit_pct"):
            data["take_profit_pct"] = self._as_decimal(job_row["take_profit_pct"], "0.000001")
        if job_row.get("stop_loss_pct"):
            data["stop_loss_pct"] = self._as_decimal(job_row["stop_loss_pct"], "0.000001")

        record = await client.tradeexecutionlog.create(data=data)
        
        # Extract agent information for logging
        agent_id = job_row.get("agent_id")
        agent_type = job_row.get("agent_type")
        agent_status = job_row.get("agent_status")
        
        if agent_id:
            self.logger.info(
                "✅ Logged trade request %s for portfolio %s | Agent %s (%s, %s) | %s %s x %d | Triggered by %s",
                record.id,
                data.get("portfolio_id", "unknown"),
                agent_id,
                agent_type or "unknown",
                agent_status or "unknown",
                data["side"],
                data["symbol"],
                data["quantity"],
                metadata.get("triggered_by", "unknown"),
            )
        else:
            self.logger.info(
                "✅ Logged trade request %s for portfolio %s (%s %s x %s) - triggered by %s (no agent)",
                record.id,
                data.get("portfolio_id", "unknown"),
                data["side"],
                data["symbol"],
                data["quantity"],
                metadata.get("triggered_by", "unknown"),
            )
        return TradeExecutionRecord(
            id=record.id,
            request_id=data["request_id"],
            status=record.status,
            broker_order_id=record.broker_order_id if hasattr(record, "broker_order_id") else None,
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

                event = TradeExecutionEvent(
                    trade_id=record.id,
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
        """Update persisted trade log with execution results."""

        client = await self._ensure_client()
        data: Dict[str, Any] = {
            "status": status,
        }
        if broker_order_id:
            data["broker_order_id"] = broker_order_id
        if error_message:
            data["error_message"] = error_message
        if executed_price is not None:
            data["executed_price"] = self._as_decimal(executed_price)
        if executed_quantity is not None:
            data["executed_quantity"] = int(executed_quantity)
        if metadata:
            data["metadata"] = json.dumps(metadata)

        await client.tradeexecutionlog.update(
            where={"id": trade_id},
            data=data,
        )
        self.logger.info("Updated trade %s -> status=%s", trade_id, status)

    async def fetch_trade_log(self, trade_id: str) -> Optional[Any]:
        client = await self._ensure_client()
        return await client.tradeexecutionlog.find_unique(where={"id": trade_id})

    async def execute_trade(
        self,
        trade_id: str,
        *,
        simulate: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Execute a trade job using the configured broker integration.

        When simulation mode is enabled (default when ANGELONE_TRADING_ENABLED is false),
        the trade is marked as executed immediately without contacting the broker.
        
        After successful execution:
        1. Updates the trade log status
        2. Adds the trade to portfolio's allocation trades array
        3. Triggers portfolio value recalculation
        
        Note: Take-profit and stop-loss orders are NOT automatically created.
        They should only be created when explicitly specified in the trading strategy.
        """

        record = await self.fetch_trade_log(trade_id)
        if record is None:
            self.logger.warning("Trade %s not found for execution", trade_id)
            return {"status": "missing", "trade_id": trade_id}
        
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
            executed_price = float(record.reference_price)
            executed_quantity = int(record.quantity)
            execution_time = datetime.utcnow()
            
            auto_sell_at = _calculate_auto_sell_at(record, execution_time, self.logger, trade_id)
            
            update_data = {"simulation": True}
            if auto_sell_at:
                update_data["auto_sell_at"] = auto_sell_at.isoformat()
            
            await self.update_status(
                trade_id,
                status="simulated_executed",
                executed_price=executed_price,
                executed_quantity=executed_quantity,
                metadata=update_data,
            )
            
            if auto_sell_at:
                client = await self._ensure_client()
                await client.tradeexecutionlog.update(
                    where={"id": trade_id},
                    data={"auto_sell_at": auto_sell_at},
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
            symbol = str(getattr(record, "symbol", ""))
            side = str(getattr(record, "side", ""))
            quantity = int(record.quantity)
            
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
        The TP/SL percentages come from the original trade record.
        
        Args:
            trade_record: The executed trade log record
            executed_price: Price at which the trade was executed
            executed_quantity: Quantity that was executed
        """
        
        client = await self._ensure_client()
        
        # Extract fields from trade record
        user_id = str(getattr(trade_record, "user_id", ""))
        portfolio_id = str(getattr(trade_record, "portfolio_id", ""))
        symbol = str(getattr(trade_record, "symbol", ""))
        side = str(getattr(trade_record, "side", "BUY"))
        
        # Get TP/SL percentages (they are stored as decimals like 0.03 for 3%)
        tp_pct_raw = getattr(trade_record, "take_profit_pct", Decimal("0.03"))
        sl_pct_raw = getattr(trade_record, "stop_loss_pct", Decimal("0.01"))
        tp_pct = float(tp_pct_raw)
        sl_pct = float(sl_pct_raw)
        
        self.logger.debug(
            "TP/SL percentages for %s: TP=%.4f (%.1f%%), SL=%.4f (%.1f%%)",
            symbol, tp_pct, tp_pct * 100, sl_pct, sl_pct * 100
        )
        
        if not user_id or not portfolio_id or not symbol:
            self.logger.warning(
                "Cannot create TP/SL orders: missing required fields for trade %s",
                getattr(trade_record, "id", ""),
            )
            return
        
        try:
            # Calculate TP/SL prices
            if side == "BUY":
                # For long positions
                tp_price = executed_price * (1 + tp_pct)
                sl_price = executed_price * (1 - sl_pct)
                tp_side = "SELL"
                sl_side = "SELL"
            else:
                # For short positions
                tp_price = executed_price * (1 - tp_pct)
                sl_price = executed_price * (1 + sl_pct)
                tp_side = "BUY"
                sl_side = "BUY"
            
            # Create Take-Profit Order
            tp_metadata = {
                "order_type": "take_profit",
                "parent_trade_id": str(getattr(trade_record, "id", "")),
                "triggered_by": "nse_pipeline_tp",
                "target_pct": tp_pct,
            }
            
            tp_order = await client.tradeexecutionlog.create(
                data={
                    "request_id": f"tp_{uuid.uuid4().hex[:12]}",
                    "user_id": user_id,
                    "portfolio_id": portfolio_id,
                    "symbol": symbol,
                    "side": tp_side,
                    "quantity": executed_quantity,
                    "reference_price": self._as_decimal(tp_price),
                    "status": "pending",
                    "metadata": json.dumps(tp_metadata),
                }
            )
            
            self.logger.info(
                "✅ Created TP order %s: %s %s @ ₹%.2f (%.1f%% profit)",
                tp_order.id,
                tp_side,
                symbol,
                tp_price,
                tp_pct * 100,
            )
            
            # Create Stop-Loss Order
            sl_metadata = {
                "order_type": "stop_loss",
                "parent_trade_id": str(getattr(trade_record, "id", "")),
                "triggered_by": "nse_pipeline_sl",
                "target_pct": sl_pct,
            }
            
            sl_order = await client.tradeexecutionlog.create(
                data={
                    "request_id": f"sl_{uuid.uuid4().hex[:12]}",
                    "user_id": user_id,
                    "portfolio_id": portfolio_id,
                    "symbol": symbol,
                    "side": sl_side,
                    "quantity": executed_quantity,
                    "reference_price": self._as_decimal(sl_price),
                    "status": "pending",
                    "metadata": json.dumps(sl_metadata),
                }
            )
            
            self.logger.info(
                "✅ Created SL order %s: %s %s @ ₹%.2f (%.1f%% loss)",
                sl_order.id,
                sl_side,
                symbol,
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
            trade_record: The executed trade log record
            executed_price: Price at which the trade was executed
            executed_quantity: Quantity that was executed
        """
        client = await self._ensure_client()
        
        side = str(getattr(trade_record, "side", "")).upper()
        
        # Only calculate realized P&L for SELL trades
        if side != "SELL":
            return
        
        portfolio_id = str(getattr(trade_record, "portfolio_id", ""))
        symbol = str(getattr(trade_record, "symbol", ""))
        agent_id = getattr(trade_record, "agent_id", None)
        trade_log_id = str(getattr(trade_record, "id", ""))
        
        if not portfolio_id or not symbol:
            self.logger.warning(
                "Cannot calculate realized P&L: missing portfolio_id or symbol for trade %s",
                trade_log_id,
            )
            return
        
        try:
            # Find the position for this symbol to get average_buy_price
            position = await client.position.find_first(
                where={
                    "portfolio_id": portfolio_id,
                    "symbol": {"equals": symbol, "mode": "insensitive"},
                    "status": "open",
                },
                order={"created_at": "desc"},  # Get most recent position
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
                "💰 Realized P&L for SELL trade: %s %d @ ₹%.2f (avg buy: ₹%.2f) = ₹%.2f",
                symbol,
                executed_quantity,
                executed_price,
                average_buy_price,
                realized_pnl,
            )
            
            # Update Trade record (if exists - TradeExecutionLog may not have a Trade yet)
            # Try to find Trade by trade_log_id or create reference
            try:
                # Try to find existing Trade linked to this execution
                existing_trade = await client.trade.find_first(
                    where={
                        "portfolio_id": portfolio_id,
                        "symbol": {"equals": symbol, "mode": "insensitive"},
                        "side": side,
                        "executed_price": executed_price,
                        "executed_quantity": executed_quantity,
                    },
                    order={"created_at": "desc"},
                )
                
                if existing_trade:
                    await client.trade.update(
                        where={"id": existing_trade.id},
                        data={"realized_pnl": realized_pnl_decimal},
                    )
            except Exception as trade_exc:
                self.logger.debug("No Trade record found to update with realized P&L: %s", trade_exc)
            
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
                trade_log_id,
                exc,
                exc_info=True,
            )
    
    async def _update_portfolio_allocation(
        self,
        trade_record: Any,
        *,
        executed_price: float,
        executed_quantity: int,
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
        """
        
        client = await self._ensure_client()
        
        portfolio_id = str(getattr(trade_record, "portfolio_id", ""))
        symbol = str(getattr(trade_record, "symbol", ""))
        side = str(getattr(trade_record, "side", "BUY"))
        
        if not portfolio_id:
            self.logger.warning(
                "Cannot update portfolio allocation: missing portfolio_id for trade %s",
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
            
            # Create Trade record (like manual trades do)
            organization_id = getattr(portfolio, "organization_id", None)
            customer_id = getattr(portfolio, "customer_id", None)
            
            # Calculate fees and taxes (simulation mode - minimal fees)
            fees = Decimal("0.0")
            taxes = Decimal("0.0")
            net_amount = Decimal(str(executed_price * executed_quantity))
            
            auto_sell_at = None
            if hasattr(trade_record, "auto_sell_at") and trade_record.auto_sell_at:
                auto_sell_at = trade_record.auto_sell_at
            elif isinstance(metadata, dict) and "auto_sell_at" in metadata:
                try:
                    auto_sell_at = datetime.fromisoformat(metadata["auto_sell_at"])
                except:
                    pass
            
            # Create Trade record
            trade_data = {
                "organization_id": organization_id,
                "portfolio_id": portfolio_id,
                "customer_id": customer_id,
                "trade_type": "auto",  # Auto-trade from pipeline
                "symbol": symbol,
                "exchange": "NSE",
                "segment": "EQUITY",
                "side": side,
                "order_type": "market",
                "quantity": executed_quantity,
                "status": "executed",
                "price": executed_price,
                "executed_price": executed_price,
                "executed_quantity": executed_quantity,
                "execution_time": datetime.utcnow(),
                "fees": fees,
                "taxes": taxes,
                "net_amount": net_amount,
                "source": "nse_pipeline_auto_trade",
                "metadata": json.dumps({
                    "trade_log_id": str(getattr(trade_record, "id", "")),
                    "agent_id": getattr(trade_record, "agent_id", None),
                    "agent_type": getattr(trade_record, "agent_type", None),
                    "triggered_by": metadata.get("triggered_by", "high_risk_agent"),
                    "confidence": float(getattr(trade_record, "confidence", 0)),
                    "allocated_capital": float(getattr(trade_record, "allocated_capital", 0)),
                }),
            }
            
            if auto_sell_at:
                trade_data["auto_sell_at"] = auto_sell_at
            
            trade_record_db = await client.trade.create(data=trade_data)
            self.logger.info(
                "✅ Created Trade record %s: %s %s x %d @ ₹%.2f",
                trade_record_db.id,
                side,
                symbol,
                executed_quantity,
                executed_price,
            )
            
            # Get agent_id and agent_type - try record first, then metadata
            agent_id = getattr(trade_record, "agent_id", None)
            agent_type = getattr(trade_record, "agent_type", None)
            
            # Fallback to metadata if not in record
            if not agent_id or not agent_type:
                if hasattr(trade_record, "metadata") and trade_record.metadata:
                    meta = trade_record.metadata
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except:
                            meta = {}
                    if isinstance(meta, dict):
                        if not agent_id and "agent_id" in meta:
                            agent_id = meta["agent_id"]
                        if not agent_type and "agent_type" in meta:
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
                        "trade_id": str(trade_record_db.id),  # Trade record ID
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

            # Trigger portfolio value recalculation
            await self._recalculate_portfolio_value(portfolio_id, client)
            
        except Exception as exc:
            self.logger.error(
                "Failed to update portfolio allocation for trade %s: %s",
                getattr(trade_record, "id", ""),
                exc,
                exc_info=True
            )
    
    async def _recalculate_portfolio_value(
        self,
        portfolio_id: str,
        client: Any,
    ) -> None:
        """
        Recalculate portfolio value based on current positions.
        
        This fetches all positions, gets their current prices from the market data service,
        and updates the portfolio's current_value field.
        
        Args:
            portfolio_id: Portfolio ID to recalculate
            client: Prisma client
        """
        
        try:
            # Fetch all positions for this portfolio
            positions = await client.position.find_many(
                where={"portfolio_id": portfolio_id, "status": "open"}
            )
            
            if not positions:
                self.logger.info("No open positions for portfolio %s", portfolio_id)
                return
            
            # Calculate total value from positions
            total_value = Decimal("0")
            
            for position in positions:
                # Use current_price from position (updated by market data service)
                # or average_buy_price as fallback
                price = getattr(position, "current_price", None) or getattr(position, "average_buy_price", Decimal("0"))
                quantity = getattr(position, "quantity", 0)
                
                position_value = Decimal(str(price)) * Decimal(str(quantity))
                total_value += position_value
            
            # Update portfolio current value
            await client.portfolio.update(
                where={"id": portfolio_id},
                data={"current_value": total_value}
            )
            
            self.logger.info(
                "✅ Recalculated portfolio %s value: ₹%.2f (%d positions)",
                portfolio_id,
                float(total_value),
                len(positions),
            )
            
        except Exception as exc:
            self.logger.error(
                "Failed to recalculate portfolio value for %s: %s",
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
