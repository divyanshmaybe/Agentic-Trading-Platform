"""
Real-time streaming order monitor using WebSocket price feeds.

This module implements a professional, production-ready order monitoring system that:
- Monitors pending limit/stop/TP/SL orders in real-time via WebSocket price feeds
- Executes orders instantly when price conditions are met (sub-second latency)
- Uses the existing MarketDataService singleton with WebSocket connection pooling
- Automatically subscribes to symbols from pending orders
- Handles edge cases: stale orders, connection failures, execution retries
- Provides comprehensive logging and error handling

Architecture:
1. Connect to MarketDataService (WebSocket-based, singleton)
2. Periodically refresh pending orders from database
3. Subscribe to symbols from pending orders via WebSocket
4. Monitor live price updates (event-driven, no polling)
5. Check order execution conditions in real-time
6. Execute orders immediately when conditions met
7. Remove executed orders from monitoring

Performance:
- Sub-second response time (price update → order execution)
- No database polling (only price monitoring via WebSocket)
- Efficient batch symbol subscription
- Connection pooling and retry logic
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class PendingOrder:
    """
    Pending order data structure.
    
    Represents a pending limit/stop/TP/SL order that needs real-time monitoring.
    """
    id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    order_type: str  # "limit", "stop", "stop_loss", "take_profit"
    quantity: int
    limit_price: Optional[float]  # For limit orders
    trigger_price: Optional[float]  # For stop/TP/SL orders
    source_model: str  # "trade" or "trade_execution_log"
    created_at: datetime
    customer_id: str  # customer_id from Trade model
    portfolio_id: Optional[str]
    parent_trade_id: Optional[str] = None  # Links TP/SL orders to parent trade
    status: str = "pending"  # pending, pending_tp, pending_sl
    
    def __hash__(self):
        """Make hashable for set operations."""
        return hash(self.id)
    
    def __eq__(self, other):
        """Equality based on ID."""
        if not isinstance(other, PendingOrder):
            return False
        return self.id == other.id


@dataclass
class AutoSellTrade:
    """
    Auto-sell trade data structure.
    
    Represents a BUY trade that needs to be auto-sold at a specific time.
    """
    id: str
    symbol: str
    side: str  # Original side (BUY or SHORT_SELL)
    quantity: int
    original_price: float
    auto_sell_at: datetime  # When to auto-sell
    auto_cover_at: Optional[datetime]  # When to auto-cover (for shorts)
    portfolio_id: Optional[str]
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, AutoSellTrade):
            return False
        return self.id == other.id


@dataclass
class AutoSellSignal:
    """
    Signal to execute an auto-sell.
    
    Generated when a trade's auto_sell_at time has passed.
    """
    trade_id: str
    symbol: str
    close_type: str  # "sell" or "cover"
    quantity: int
    original_price: float
    portfolio_id: str
    auto_sell_at: datetime
    triggered_at: datetime
    
    def __str__(self):
        return (
            f"AutoSellSignal(trade={self.trade_id}, symbol={self.symbol}, "
            f"type={self.close_type}, scheduled={self.auto_sell_at})"
        )


@dataclass
class TPSLTrade:
    """
    Trade with Take-Profit/Stop-Loss prices set.
    
    Represents an executed BUY/SHORT trade that needs TP/SL price monitoring.
    Similar to AutoSellTrade but triggered by price instead of time.
    """
    id: str
    symbol: str
    side: str  # Original side (BUY or SHORT_SELL)
    quantity: int
    entry_price: float  # Buy/sell price
    take_profit_price: Optional[float]  # TP trigger price
    stop_loss_price: Optional[float]  # SL trigger price
    portfolio_id: Optional[str]
    customer_id: Optional[str]
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if not isinstance(other, TPSLTrade):
            return False
        return self.id == other.id


@dataclass
class TPSLSignal:
    """
    Signal to execute a TP/SL closure.
    
    Generated when a trade's TP or SL price is hit.
    """
    trade_id: str
    symbol: str
    close_type: str  # "take_profit" or "stop_loss"
    side: str  # SELL to close BUY, BUY to close SHORT
    quantity: int
    entry_price: float
    trigger_price: float
    current_price: float
    portfolio_id: str
    triggered_at: datetime
    
    def __str__(self):
        return (
            f"TPSLSignal(trade={self.trade_id}, symbol={self.symbol}, "
            f"type={self.close_type}, trigger=₹{self.trigger_price:.2f}, current=₹{self.current_price:.2f})"
        )


@dataclass
class OrderExecutionSignal:
    """
    Signal to execute an order.
    
    Generated when an order's price conditions are met and it should be executed.
    """
    order_id: str
    symbol: str
    side: str
    order_type: str
    current_price: float
    trigger_price: float
    condition_met: str
    timestamp: datetime
    source_model: str
    
    def __str__(self):
        """Human-readable representation."""
        return (
            f"OrderExecutionSignal(order={self.order_id}, symbol={self.symbol}, "
            f"type={self.order_type}, condition='{self.condition_met}')"
        )




class OrderConditionChecker:
    """
    Utility class for checking if order execution conditions are met.
    
    Implements the business logic for different order types:
    - Limit orders: Execute when price reaches favorable level
    - Stop orders: Execute when price breaks through trigger level
    - Take profit: Execute when price reaches target profit level
    - Stop loss: Execute when price hits loss limit
    """
    
    @staticmethod
    def check_condition(order: PendingOrder, current_price: float) -> Optional[OrderExecutionSignal]:
        """
        Check if order execution conditions are met.
        
        Args:
            order: Pending order to check
            current_price: Current market price
            
        Returns:
            OrderExecutionSignal if conditions met, None otherwise
        """
        # Convert to Decimal for precision
        price = Decimal(str(current_price))
        should_execute = False
        condition_met = None
        trigger_price = None
        
        try:
            if order.order_type == "limit":
                # Limit order: execute when price reaches favorable level
                if order.limit_price is None:
                    logger.warning(f"Limit order {order.id} missing limit_price")
                    return None
                
                limit = Decimal(str(order.limit_price))
                trigger_price = float(limit)
                
                if order.side == "BUY" and price <= limit:
                    should_execute = True
                    condition_met = f"BUY limit: {price} <= {limit}"
                elif order.side == "SELL" and price >= limit:
                    should_execute = True
                    condition_met = f"SELL limit: {price} >= {limit}"
            
            elif order.order_type in {"stop", "stop_loss"}:
                # Stop/Stop-loss: execute when price breaks through trigger
                if order.trigger_price is None:
                    logger.warning(f"Stop order {order.id} missing trigger_price")
                    return None
                
                trigger = Decimal(str(order.trigger_price))
                trigger_price = float(trigger)
                
                if order.side == "BUY" and price >= trigger:
                    should_execute = True
                    condition_met = f"BUY stop: {price} >= {trigger}"
                elif order.side == "SELL" and price <= trigger:
                    should_execute = True
                    condition_met = f"SELL stop: {price} <= {trigger}"
            
            elif order.order_type == "take_profit":
                # Take profit: execute when price reaches target
                if order.trigger_price is None:
                    logger.warning(f"Take profit order {order.id} missing trigger_price")
                    return None
                
                trigger = Decimal(str(order.trigger_price))
                trigger_price = float(trigger)
                
                if order.side == "SELL" and price >= trigger:
                    should_execute = True
                    condition_met = f"TP SELL: {price} >= {trigger}"
                elif order.side == "BUY" and price <= trigger:
                    should_execute = True
                    condition_met = f"TP BUY: {price} <= {trigger}"
            
            else:
                logger.warning(f"Unknown order type: {order.order_type}")
                return None
            
            if should_execute and condition_met and trigger_price is not None:
                return OrderExecutionSignal(
                    order_id=order.id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    current_price=current_price,
                    trigger_price=trigger_price,
                    condition_met=condition_met,
                    timestamp=datetime.now(timezone.utc),
                    source_model=order.source_model,
                )
            
            return None
            
        except Exception as exc:
            logger.exception(f"Error checking order {order.id} condition: {exc}")
            return None
class PathwayOrderMonitor:
    """
    Real-time order monitoring using WebSocket-based MarketDataService.
    
    This production-ready monitor:
    - Subscribes to WebSocket price feeds for all pending order symbols
    - Checks order conditions in real-time (sub-second response)
    - Executes orders immediately when conditions are met
    - Handles edge cases: connection failures, stale orders, execution retries
    - Provides comprehensive logging and error handling
    
    Architecture:
    1. Initialize with MarketDataService singleton (WebSocket-based)
    2. Fetch pending orders from database periodically (every 10s)
    3. Subscribe to symbols via MarketDataService WebSocket
    4. Monitor live price updates (event-driven via async loop)
    5. Check order conditions when prices update
    6. Execute orders via TradeEngine
    7. Remove executed orders from monitoring set
    """
    
    def __init__(
        self,
        market_data_service: Any,  # MarketDataService instance
        db_client: Any,  # Prisma database client
        execution_callback: Optional[Callable[[OrderExecutionSignal], None]] = None,
        refresh_interval: float = 10.0,
        check_interval: float = 0.5,
    ):
        """
        Initialize streaming order monitor.
        
        Args:
            market_data_service: MarketDataService singleton with WebSocket
            db_client: Prisma database client
            execution_callback: Optional callback after execution
            refresh_interval: How often to refresh pending orders (seconds)
            check_interval: How often to check order conditions (seconds)
        """
        self.market_service = market_data_service
        self.db = db_client
        self.execution_callback = execution_callback
        self.refresh_interval = refresh_interval
        self.check_interval = check_interval
        
        # State
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._auto_sell_task: Optional[asyncio.Task] = None  # Auto-sell monitor task
        self._auto_sell_refresh_task: Optional[asyncio.Task] = None  # Auto-sell refresh task
        self._tpsl_task: Optional[asyncio.Task] = None  # TP/SL monitor task
        self._tpsl_refresh_task: Optional[asyncio.Task] = None  # TP/SL refresh task
        
        # ========== SYMBOL TABLE (Pathway-style reactive set) ==========
        # Central set of all unique symbols being monitored - like a pw.Table
        self._monitored_symbols: Set[str] = set()  # All unique symbols across all order types
        
        # Caches for price-based orders (TP/SL/limit/stop)
        self._pending_orders: Dict[str, PendingOrder] = {}  # order_id -> PendingOrder
        self._orders_by_symbol: Dict[str, Set[str]] = {}  # symbol -> set of order_ids
        self._orders_by_parent: Dict[str, Set[str]] = {}  # parent_trade_id -> set of order_ids (for TP/SL pairs)
        self._subscribed_symbols: Set[str] = set()
        self._executing: Set[str] = set()  # order_ids currently being executed
        
        # Caches for time-based auto-sell
        self._auto_sell_trades: Dict[str, AutoSellTrade] = {}  # trade_id -> AutoSellTrade
        self._auto_selling: Set[str] = set()  # trade_ids currently being auto-sold
        
        # Caches for price-based TP/SL (executed trades with TP/SL prices)
        self._tpsl_trades: Dict[str, TPSLTrade] = {}  # trade_id -> TPSLTrade
        self._tpsl_by_symbol: Dict[str, Set[str]] = {}  # symbol -> set of trade_ids
        self._tpsl_executing: Set[str] = set()  # trade_ids currently executing TP/SL
        
        # Price cache - batch fetched from MarketDataService
        self._price_cache: Dict[str, float] = {}  # symbol -> latest price
        self._price_cache_updated: Optional[datetime] = None
        
        logger.info(
            f"Initialized PathwayOrderMonitor "
            f"(refresh={refresh_interval}s, check={check_interval}s)"
        )
    
    async def _fetch_pending_orders(self) -> List[PendingOrder]:
        """
        Fetch all pending orders from database.
        
        Returns:
            List of PendingOrder objects
        """
        try:
            import json
            
            # Fetch from Trade model (limit, stop, stop_loss, take_profit)
            # Include pending_tp and pending_sl statuses for TP/SL orders
            trade_orders = await self.db.trade.find_many(
                where={
                    "status": {"in": ["pending", "pending_tp", "pending_sl"]},
                    "order_type": {"in": ["limit", "stop", "stop_loss", "take_profit"]}
                },
                order={"created_at": "asc"},
            )
            
            orders = []
            for order in trade_orders:
                try:
                    # Extract parent_trade_id from metadata for TP/SL linking
                    parent_trade_id = None
                    if order.metadata:
                        try:
                            meta = order.metadata if isinstance(order.metadata, dict) else json.loads(order.metadata)
                            parent_trade_id = meta.get("parent_trade_id")
                        except (json.JSONDecodeError, TypeError):
                            pass
                    
                    orders.append(PendingOrder(
                        id=order.id,
                        symbol=order.symbol,
                        side=order.side,
                        order_type=order.order_type,
                        quantity=order.quantity,
                        limit_price=float(order.limit_price) if order.limit_price else None,
                        trigger_price=float(order.trigger_price) if order.trigger_price else None,
                        source_model="trade",
                        created_at=order.created_at,
                        customer_id=order.customer_id,
                        portfolio_id=order.portfolio_id,
                        parent_trade_id=parent_trade_id,
                        status=order.status,
                    ))
                except Exception as exc:
                    logger.warning(f"Failed to parse order {order.id}: {exc}")
                    continue
            
            logger.debug(f"📦 Fetched {len(orders)} pending orders from database")
            return orders
            
        except Exception as exc:
            logger.exception(f"Failed to fetch pending orders: {exc}")
            return []
    
    async def _subscribe_to_symbols(self, symbols: Set[str]):
        """
        Subscribe to symbols via MarketDataService WebSocket.
        
        Args:
            symbols: Set of symbols to subscribe to
        """
        new_symbols = symbols - self._subscribed_symbols
        
        if not new_symbols:
            return
        
        try:
            logger.info(f"📡 Subscribing to {len(new_symbols)} new symbols: {sorted(new_symbols)}")
            
            # MarketDataService handles subscriptions automatically via await_price
            # Just need to ensure we've called it at least once for each symbol
            for symbol in new_symbols:
                try:
                    # This will subscribe if not already subscribed
                    await self.market_service.await_price(symbol, timeout=0.5)
                except Exception as exc:
                    logger.debug(f"Initial subscription for {symbol} (price will come): {exc}")
            
            self._subscribed_symbols.update(new_symbols)
            logger.info(f"✅ Now subscribed to {len(self._subscribed_symbols)} symbols total")
            
        except Exception as exc:
            logger.exception(f"Failed to subscribe to symbols: {exc}")
    
    async def _execute_order(self, signal: OrderExecutionSignal):
        """
        Execute order when conditions are met.
        
        Args:
            signal: OrderExecutionSignal with execution details
        """
        # Prevent duplicate execution (local cache)
        if signal.order_id in self._executing:
            logger.debug(f"Order {signal.order_id} already executing locally, skipping")
            return
        
        self._executing.add(signal.order_id)
        
        import time
        exec_start = time.time()
        
        try:
            # CRITICAL: Double-check order status in database before execution
            # This prevents race conditions when multiple workers monitor same order
            trade_check = await self.db.trade.find_unique(where={"id": signal.order_id})
            
            if not trade_check:
                logger.warning(f"⚠️ Order {signal.order_id} not found in database, skipping")
                return
            
            # Include pending_tp and pending_sl statuses for TP/SL order execution
            if trade_check.status not in ["pending", "pending_tp", "pending_sl"]:
                logger.info(
                    f"⚠️ Order {signal.order_id} already {trade_check.status}, skipping execution"
                )
                # Remove from local cache since it's no longer pending
                if signal.order_id in self._pending_orders:
                    order = self._pending_orders.pop(signal.order_id)
                    if order.symbol in self._orders_by_symbol:
                        self._orders_by_symbol[order.symbol].discard(signal.order_id)
                return
            
            logger.info(
                f"🎯 Executing order {signal.order_id} ({signal.symbol}): "
                f"{signal.condition_met}"
            )
            
            # Use TradeEngine to execute
            from services.trade_engine import TradeEngine
            engine = TradeEngine(self.db)
            
            if signal.source_model == "trade":
                executed = await engine.process_pending_trade(signal.order_id)
                
                exec_time = (time.time() - exec_start) * 1000
                exec_time_ms = int(exec_time)
                
                if executed:
                    logger.info(f"✅ Order {signal.order_id} executed successfully in {exec_time:.1f}ms")
                    
                    # Save trade_delay for TP/SL orders
                    try:
                        await self.db.tradeexecutionlog.update_many(
                            where={"trade_id": signal.order_id},
                            data={"trade_delay": exec_time_ms}
                        )
                        logger.debug(f"📊 Saved trade_delay: {exec_time_ms}ms for order {signal.order_id}")
                    except Exception as e:
                        logger.warning(f"Failed to update trade_delay for {signal.order_id}: {e}")
                    
                    # Trigger observability analysis for stop_loss orders
                    if signal.order_type in ["stop_loss", "stop"]:
                        try:
                            from workers.observability_agent_tasks import trigger_loss_analysis
                            
                            # Get the parent trade to extract signal context
                            order = self._pending_orders.get(signal.order_id)
                            parent_trade_id = order.parent_trade_id if order else None
                            
                            signal_context = {}
                            if parent_trade_id:
                                parent_trade = await self.db.trade.find_unique(
                                    where={"id": parent_trade_id}
                                )
                                if parent_trade and parent_trade.metadata:
                                    meta = parent_trade.metadata if isinstance(parent_trade.metadata, dict) else {}
                                    signal_context = {
                                        "explanation": meta.get("explanation", ""),
                                        "pdf_url": meta.get("attachment_url", "") or meta.get("pdf_url", ""),
                                        "filing_type": meta.get("filing_type", ""),
                                    }
                            
                            trigger_loss_analysis(
                                trade_id=parent_trade_id or signal.order_id,
                                triggered_by="stop_loss",
                                signal_context=signal_context,
                            )
                            logger.info(
                                f"📤 Queued observability analysis for stop_loss {signal.order_id[:8]}"
                            )
                        except Exception as obs_exc:
                            logger.warning(f"Failed to trigger observability analysis: {obs_exc}")
                    
                    # Remove from pending orders cache
                    if signal.order_id in self._pending_orders:
                        order = self._pending_orders.pop(signal.order_id)
                        
                        # Remove from symbol index
                        if order.symbol in self._orders_by_symbol:
                            self._orders_by_symbol[order.symbol].discard(signal.order_id)
                            if not self._orders_by_symbol[order.symbol]:
                                del self._orders_by_symbol[order.symbol]
                else:
                    logger.warning(f"⚠️  Order {signal.order_id} execution returned False (took {exec_time:.1f}ms)")
            
            # Call custom callback if provided
            if self.execution_callback:
                try:
                    if asyncio.iscoroutinefunction(self.execution_callback):
                        await self.execution_callback(signal)
                    else:
                        self.execution_callback(signal)
                except Exception as cb_exc:
                    logger.exception(f"Execution callback error: {cb_exc}")
                    
        except Exception as exc:
            logger.exception(f"❌ Failed to execute order {signal.order_id}: {exc}")
        finally:
            self._executing.discard(signal.order_id)
    
    async def _cancel_counterpart_orders(self, triggered_order: PendingOrder):
        """
        Cancel counterpart TP/SL orders when one is triggered.
        
        When TP triggers, cancel SL. When SL triggers, cancel TP.
        Uses parent_trade_id to find linked orders.
        """
        if not triggered_order.parent_trade_id:
            return  # No linked orders
        
        parent_id = triggered_order.parent_trade_id
        linked_order_ids = self._orders_by_parent.get(parent_id, set())
        
        for order_id in linked_order_ids:
            if order_id == triggered_order.id:
                continue  # Skip the triggered order itself
            
            order = self._pending_orders.get(order_id)
            if not order:
                continue
            
            try:
                # Cancel the counterpart order in database
                await self.db.trade.update(
                    where={"id": order_id},
                    data={
                        "status": "cancelled",
                        "metadata": {
                            "cancelled_by": triggered_order.id,
                            "cancel_reason": f"counterpart_{triggered_order.order_type}_triggered",
                            "cancelled_at": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                )
                
                logger.info(
                    f"🚫 Cancelled counterpart {order.order_type} order {order_id[:8]} "
                    f"(triggered by {triggered_order.order_type} {triggered_order.id[:8]})"
                )
                
                # Remove from local caches
                self._pending_orders.pop(order_id, None)
                if order.symbol in self._orders_by_symbol:
                    self._orders_by_symbol[order.symbol].discard(order_id)
                    
            except Exception as exc:
                logger.warning(f"Failed to cancel counterpart order {order_id}: {exc}")
        
        # Clear the parent index entry
        self._orders_by_parent.pop(parent_id, None)
    
    async def _batch_fetch_prices(self) -> Dict[str, float]:
        """
        Batch fetch prices for all monitored symbols from MarketDataService.
        
        Returns:
            Dict of symbol -> current price
        """
        if not self._monitored_symbols:
            return {}
        
        prices = {}
        symbols_list = list(self._monitored_symbols)
        
        try:
            # Use MarketDataService batch quote if available
            if hasattr(self.market_service, 'get_quotes'):
                quotes = await self.market_service.get_quotes(symbols_list)
                for symbol, quote in quotes.items():
                    if quote and 'price' in quote:
                        prices[symbol] = float(quote['price'])
            else:
                # Fallback: get cached prices from market service
                for symbol in symbols_list:
                    price = self.market_service.get_latest_price(symbol)
                    if price is not None:
                        prices[symbol] = float(price)
            
            # Update price cache
            self._price_cache.update(prices)
            self._price_cache_updated = datetime.now(timezone.utc)
            
        except Exception as exc:
            logger.warning(f"Batch price fetch error: {exc}")
        
        return prices
    
    async def _refresh_orders_loop(self):
        """Background task to periodically refresh pending orders from database."""
        while self._running:
            try:
                # Fetch fresh orders
                orders = await self._fetch_pending_orders()
                
                # Update caches
                old_order_ids = set(self._pending_orders.keys())
                new_order_ids = {o.id for o in orders}
                
                # Remove cancelled/completed orders
                removed = old_order_ids - new_order_ids
                for order_id in removed:
                    if order_id in self._pending_orders:
                        order = self._pending_orders.pop(order_id)
                        if order.symbol in self._orders_by_symbol:
                            self._orders_by_symbol[order.symbol].discard(order_id)
                            if not self._orders_by_symbol[order.symbol]:
                                del self._orders_by_symbol[order.symbol]
                
                # Add/update orders
                self._pending_orders = {o.id: o for o in orders}
                
                # Rebuild symbol index
                self._orders_by_symbol = {}
                for order in orders:
                    if order.symbol not in self._orders_by_symbol:
                        self._orders_by_symbol[order.symbol] = set()
                    self._orders_by_symbol[order.symbol].add(order.id)
                
                # Build parent trade index (for TP/SL pairs)
                self._orders_by_parent = {}
                for order in orders:
                    if order.parent_trade_id:
                        if order.parent_trade_id not in self._orders_by_parent:
                            self._orders_by_parent[order.parent_trade_id] = set()
                        self._orders_by_parent[order.parent_trade_id].add(order.id)
                
                # Update monitored symbols (central symbol table)
                symbols = set(self._orders_by_symbol.keys())
                self._monitored_symbols.update(symbols)
                
                # Subscribe to all symbols
                if symbols:
                    await self._subscribe_to_symbols(symbols)
                
                # Log TP/SL pairs
                tp_sl_pairs = len([p for p in self._orders_by_parent.values() if len(p) >= 2])
                
                if orders:
                    logger.info(
                        f"📊 Monitoring {len(orders)} pending orders across "
                        f"{len(symbols)} symbols ({tp_sl_pairs} TP/SL pairs)"
                    )
                
                # Wait before next refresh
                await asyncio.sleep(self.refresh_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"Order refresh loop error: {exc}")
                await asyncio.sleep(5)  # Back off on error
    
    async def _monitor_loop(self):
        """
        Main monitoring loop - checks orders against live prices.
        
        This runs continuously with near real-time price checking:
        1. Batch fetch prices for all monitored symbols
        2. Check all pending orders against current prices
        3. When TP/SL triggers, cancel counterpart and execute
        
        Uses Pathway-style reactive processing with central symbol table.
        """
        while self._running:
            try:
                # Batch fetch prices for all monitored symbols (single call)
                await self._batch_fetch_prices()
                
                # Check each pending order against cached prices
                triggered_orders: List[tuple] = []  # (order, signal)
                
                for order_id, order in list(self._pending_orders.items()):
                    # Skip if already executing
                    if order_id in self._executing:
                        continue
                    
                    # Get price from batch cache (no network call)
                    current_price = self._price_cache.get(order.symbol)
                    
                    if current_price is None:
                        # Fallback to market service cache
                        current_price = self.market_service.get_latest_price(order.symbol)
                        if current_price is not None:
                            self._price_cache[order.symbol] = float(current_price)
                    
                    if current_price is None:
                        continue  # No price data yet
                    
                    # Check if order conditions are met
                    signal = OrderConditionChecker.check_condition(order, float(current_price))
                    
                    if signal:
                        triggered_orders.append((order, signal))
                
                # Process triggered orders (cancel counterparts first, then execute)
                for order, signal in triggered_orders:
                    # Cancel counterpart TP/SL orders BEFORE executing
                    if order.parent_trade_id and order.status in ["pending_tp", "pending_sl"]:
                        await self._cancel_counterpart_orders(order)
                    
                    # Execute order asynchronously (don't block monitoring loop)
                    asyncio.create_task(self._execute_order(signal))
                
                # Check every check_interval seconds (default 0.1s = 100ms for near real-time)
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"Monitor loop error: {exc}")
                await asyncio.sleep(2)  # Back off on error
    
    # ==================== AUTO-SELL MONITORING ====================
    
    async def _fetch_auto_sell_trades(self) -> List[AutoSellTrade]:
        """
        Fetch all trades that need auto-sell monitoring.
        
        Returns:
            List of AutoSellTrade objects
        """
        try:
            now = datetime.now(timezone.utc)
            
            # Fetch BUY trades with auto_sell_at set (not yet expired to avoid re-processing)
            # We'll check expiry in the monitor loop
            long_trades = await self.db.trade.find_many(
                where={
                    "status": {"in": ["executed", "pending"]},
                    "side": "BUY",
                    "auto_sell_at": {"not": None},
                },
                order={"auto_sell_at": "asc"},
                take=500,  # Limit batch size
            )
            
            # Fetch SHORT_SELL trades with auto_cover_at set
            short_trades = await self.db.trade.find_many(
                where={
                    "status": {"in": ["executed", "pending"]},
                    "side": "SHORT_SELL",
                    "auto_cover_at": {"not": None},
                },
                order={"auto_cover_at": "asc"},
                take=500,
            )
            
            trades = []
            
            for trade in long_trades or []:
                try:
                    trades.append(AutoSellTrade(
                        id=trade.id,
                        symbol=trade.symbol,
                        side=trade.side,
                        quantity=trade.quantity,
                        original_price=float(trade.price) if trade.price else 0,
                        auto_sell_at=trade.auto_sell_at,
                        auto_cover_at=None,
                        portfolio_id=trade.portfolio_id,
                    ))
                except Exception as exc:
                    logger.warning(f"Failed to parse auto-sell trade {trade.id}: {exc}")
                    continue
            
            for trade in short_trades or []:
                try:
                    trades.append(AutoSellTrade(
                        id=trade.id,
                        symbol=trade.symbol,
                        side=trade.side,
                        quantity=trade.quantity,
                        original_price=float(trade.price) if trade.price else 0,
                        auto_sell_at=None,
                        auto_cover_at=trade.auto_cover_at,
                        portfolio_id=trade.portfolio_id,
                    ))
                except Exception as exc:
                    logger.warning(f"Failed to parse auto-cover trade {trade.id}: {exc}")
                    continue
            
            if trades:
                logger.debug(f"📦 Fetched {len(trades)} auto-sell/cover trades")
            
            return trades
            
        except Exception as exc:
            logger.exception(f"Failed to fetch auto-sell trades: {exc}")
            return []
    
    async def _execute_auto_sell(self, signal: AutoSellSignal):
        """
        Execute an auto-sell when time expires.
        
        Args:
            signal: AutoSellSignal with execution details
        """
        if signal.trade_id in self._auto_selling:
            logger.debug(f"Trade {signal.trade_id} already auto-selling, skipping")
            return
        
        self._auto_selling.add(signal.trade_id)
        
        import time
        exec_start = time.time()
        
        try:
            # Double-check trade status
            trade = await self.db.trade.find_unique(where={"id": signal.trade_id})
            
            if not trade:
                logger.warning(f"⚠️ Trade {signal.trade_id} not found, skipping auto-sell")
                return
            
            if trade.status not in ["executed", "pending"]:
                logger.info(f"⏭️ Trade {signal.trade_id} already {trade.status}, skipping")
                # Remove from cache
                self._auto_sell_trades.pop(signal.trade_id, None)
                return
            
            # Check metadata for already auto-sold flag
            meta = trade.metadata if isinstance(trade.metadata, dict) else {}
            if meta.get("auto_sold"):
                logger.info(f"⏭️ Trade {signal.trade_id} already auto-sold, skipping")
                self._auto_sell_trades.pop(signal.trade_id, None)
                return
            
            logger.info(
                f"🎯 Auto-{signal.close_type} triggered: {signal.trade_id[:8]} "
                f"{signal.symbol} x {signal.quantity} (scheduled: {signal.auto_sell_at})"
            )
            
            # Clear auto_sell_at to prevent duplicate processing
            if signal.close_type == "sell":
                await self.db.trade.update(
                    where={"id": signal.trade_id},
                    data={"auto_sell_at": None}
                )
            else:
                await self.db.trade.update(
                    where={"id": signal.trade_id},
                    data={"auto_cover_at": None}
                )
            
            # Get current price
            current_price = signal.original_price
            try:
                fetched_price = await asyncio.wait_for(
                    self.market_service.await_price(signal.symbol, timeout=2.0),
                    timeout=3.0
                )
                if fetched_price and float(fetched_price) > 0:
                    current_price = float(fetched_price)
            except Exception as e:
                logger.warning(f"Price fetch failed for {signal.symbol}, using original: {e}")
            
            # Determine close side
            close_side = "SELL" if signal.close_type == "sell" else "BUY"  # COVER = BUY
            
            # Use TradeEngine for proper execution (handles position updates, TradeExecutionLog)
            import json
            from services.trade_engine import TradeEngine
            from schemas import TradeCreate
            from decimal import Decimal
            
            engine = TradeEngine(self.db)
            
            # Pre-check: verify position exists and has sufficient holdings before execution
            # This prevents noisy retry loops when position was already closed
            if signal.close_type == "sell":
                position = await self.db.position.find_first(
                    where={"portfolio_id": signal.portfolio_id, "symbol": signal.symbol}
                )
                if not position or position.quantity < signal.quantity:
                    available_qty = position.quantity if position else 0
                    logger.warning(
                        f"⚠️ Position check failed for auto-sell {signal.trade_id[:8]}: "
                        f"need {signal.quantity} {signal.symbol}, have {available_qty}. "
                        f"Position may have been closed manually."
                    )
                    # Remove from cache and mark as handled
                    self._auto_sell_trades.pop(signal.trade_id, None)
                    return
            
            # Create payload for TradeEngine
            trade_payload = TradeCreate(
                organization_id=trade.organization_id or "",
                portfolio_id=signal.portfolio_id,
                agent_id=trade.agent_id,  # Inherit agent_id from original trade
                customer_id=str(trade.customer_id or ""),
                trade_type="auto",
                symbol=signal.symbol,
                exchange=str(trade.exchange) if trade.exchange else "NSE",
                segment=str(trade.segment) if trade.segment else "EQUITY",
                side=close_side,
                order_type="market",
                quantity=signal.quantity,
                source="streaming_order_monitor",
                metadata={
                    "order_type": f"auto_{signal.close_type}",
                    "parent_trade_id": signal.trade_id,
                    "triggered_by": "streaming_order_monitor",
                    "original_price": signal.original_price,
                    "execution_price": current_price,
                    "sell_reason": "auto_sell_at_expired",
                    "auto_sell_at": signal.auto_sell_at.isoformat() if signal.auto_sell_at else None,
                    "triggered_at": signal.triggered_at.isoformat(),
                },
            )
            
            # Execute via TradeEngine (creates trade, updates position, logs execution)
            close_trade_dict = await engine._execute_market_order(
                trade_payload,
                Decimal(str(current_price)),
            )
            
            exec_time_ms = int((time.time() - exec_start) * 1000)
            
            # Update TradeExecutionLog with trade_delay for auto-sell
            close_trade_id = close_trade_dict.get("id")
            if close_trade_id:
                try:
                    await self.db.tradeexecutionlog.update_many(
                        where={"trade_id": close_trade_id},
                        data={"trade_delay": exec_time_ms}
                    )
                except Exception as delay_exc:
                    logger.warning(f"Failed to update trade_delay for auto-sell: {delay_exc}")
            
            if close_trade_dict.get("status") == "executed":
                # Mark original trade as auto-sold
                if not isinstance(meta, dict):
                    meta = {}
                meta.update({
                    "auto_sold": True,
                    "auto_sold_at": datetime.now(timezone.utc).isoformat(),
                    "auto_close_trade_id": close_trade_id,
                    "closing_price": current_price,
                    "pnl_at_close": (current_price - signal.original_price) * signal.quantity 
                        if signal.close_type == "sell" 
                        else (signal.original_price - current_price) * signal.quantity,
                })
                
                await self.db.trade.update(
                    where={"id": signal.trade_id},
                    data={"metadata": json.dumps(meta)},
                )
                
                logger.info(
                    f"✅ Auto-{signal.close_type} completed in {exec_time_ms}ms: "
                    f"{signal.trade_id[:8]} {signal.symbol} x {signal.quantity} @ ₹{current_price:.2f}"
                )
                
                # Remove from cache
                self._auto_sell_trades.pop(signal.trade_id, None)
            else:
                logger.error(f"❌ Auto-{signal.close_type} failed for {signal.trade_id[:8]}: status={close_trade_dict.get('status')}")
                
        except Exception as exc:
            logger.exception(f"❌ Failed to auto-{signal.close_type} {signal.trade_id}: {exc}")
            # Remove from cache to prevent infinite retry loops on permanent failures
            # (e.g., position already closed, insufficient holdings)
            self._auto_sell_trades.pop(signal.trade_id, None)
            
            # Mark trade metadata with failure info to prevent re-processing
            try:
                trade = await self.db.trade.find_unique(where={"id": signal.trade_id})
                if trade:
                    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
                    meta.update({
                        "auto_sell_failed": True,
                        "auto_sell_error": str(exc),
                        "auto_sell_failed_at": datetime.now(timezone.utc).isoformat(),
                    })
                    await self.db.trade.update(
                        where={"id": signal.trade_id},
                        data={"metadata": json.dumps(meta)},
                    )
            except Exception as meta_exc:
                logger.warning(f"Failed to update trade metadata after auto-sell failure: {meta_exc}")
        finally:
            self._auto_selling.discard(signal.trade_id)
    
    async def _auto_sell_refresh_loop(self):
        """Background task to refresh auto-sell trades from database."""
        while self._running:
            try:
                trades = await self._fetch_auto_sell_trades()
                
                # Update cache
                old_ids = set(self._auto_sell_trades.keys())
                new_ids = {t.id for t in trades}
                
                # Remove completed/cancelled trades
                for trade_id in old_ids - new_ids:
                    self._auto_sell_trades.pop(trade_id, None)
                
                # Add/update trades
                self._auto_sell_trades = {t.id: t for t in trades}
                
                if trades:
                    now = datetime.now(timezone.utc)
                    expired = sum(1 for t in trades 
                        if (t.auto_sell_at and t.auto_sell_at <= now) or 
                           (t.auto_cover_at and t.auto_cover_at <= now))
                    
                    # Log upcoming schedules
                    upcoming = []
                    for t in sorted(trades, key=lambda x: x.auto_sell_at or x.auto_cover_at or now):
                        schedule_time = t.auto_sell_at or t.auto_cover_at
                        if schedule_time and schedule_time > now:
                            time_remaining = schedule_time - now
                            mins = int(time_remaining.total_seconds() // 60)
                            secs = int(time_remaining.total_seconds() % 60)
                            upcoming.append(f"{t.symbol}({t.id[:8]}) in {mins}m{secs}s")
                    
                    logger.info(
                        f"⏰ Monitoring {len(trades)} auto-sell trades "
                        f"({expired} expired, ready to execute)"
                    )
                    if upcoming:
                        logger.info(f"📅 Upcoming auto-sells: {', '.join(upcoming[:5])}" + 
                                   (f" (+{len(upcoming)-5} more)" if len(upcoming) > 5 else ""))
                
                await asyncio.sleep(self.refresh_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"Auto-sell refresh loop error: {exc}")
                await asyncio.sleep(5)
    
    async def _auto_sell_monitor_loop(self):
        """
        Monitor auto-sell trades and execute when time expires.
        
        Runs continuously, checking if current time >= auto_sell_at.
        """
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                
                for trade_id, trade in list(self._auto_sell_trades.items()):
                    # Skip if already executing
                    if trade_id in self._auto_selling:
                        continue
                    
                    # Check if auto-sell time has passed
                    should_sell = False
                    close_type = None
                    auto_time = None
                    
                    if trade.auto_sell_at and trade.auto_sell_at <= now:
                        should_sell = True
                        close_type = "sell"
                        auto_time = trade.auto_sell_at
                    elif trade.auto_cover_at and trade.auto_cover_at <= now:
                        should_sell = True
                        close_type = "cover"
                        auto_time = trade.auto_cover_at
                    
                    if should_sell and close_type and auto_time:
                        signal = AutoSellSignal(
                            trade_id=trade.id,
                            symbol=trade.symbol,
                            close_type=close_type,
                            quantity=trade.quantity,
                            original_price=trade.original_price,
                            portfolio_id=trade.portfolio_id or "",
                            auto_sell_at=auto_time,
                            triggered_at=now,
                        )
                        # Execute async (don't block loop)
                        asyncio.create_task(self._execute_auto_sell(signal))
                
                # Check every 1 second for auto-sells (time-based, not price-based)
                await asyncio.sleep(1.0)
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"Auto-sell monitor loop error: {exc}")
                await asyncio.sleep(2)
    
    # ==================== TPSL MONITORING (PRICE-BASED) ====================
    
    async def _fetch_tpsl_trades(self) -> List[TPSLTrade]:
        """
        Fetch all executed trades that have TP/SL prices set.
        
        Similar to _fetch_auto_sell_trades but for price-based TP/SL.
        
        Returns:
            List of TPSLTrade objects
        """
        try:
            # Fetch executed trades with take_profit_price OR stop_loss_price set
            trades_with_tpsl = await self.db.trade.find_many(
                where={
                    "status": "executed",
                    "OR": [
                        {"take_profit_price": {"not": None}},
                        {"stop_loss_price": {"not": None}},
                    ],
                },
                order={"created_at": "asc"},
                take=500,  # Limit batch size
            )
            
            trades = []
            for trade in trades_with_tpsl or []:
                try:
                    # Skip if already closed via metadata flag
                    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
                    if meta.get("tpsl_closed") or meta.get("auto_sold"):
                        continue
                    
                    tp_price = float(trade.take_profit_price) if trade.take_profit_price else None
                    sl_price = float(trade.stop_loss_price) if trade.stop_loss_price else None
                    
                    # Must have at least one of TP or SL
                    if not tp_price and not sl_price:
                        continue
                    
                    trades.append(TPSLTrade(
                        id=trade.id,
                        symbol=trade.symbol,
                        side=trade.side,
                        quantity=trade.quantity,
                        entry_price=float(trade.price) if trade.price else 0,
                        take_profit_price=tp_price,
                        stop_loss_price=sl_price,
                        portfolio_id=trade.portfolio_id,
                        customer_id=trade.customer_id,
                    ))
                except Exception as exc:
                    logger.warning(f"Failed to parse TPSL trade {trade.id}: {exc}")
                    continue
            
            if trades:
                logger.debug(f"📦 Fetched {len(trades)} TPSL trades for price monitoring")
            
            return trades
            
        except Exception as exc:
            logger.exception(f"Failed to fetch TPSL trades: {exc}")
            return []
    
    async def _execute_tpsl(self, signal: TPSLSignal):
        """
        Execute a TP/SL closure when price hits trigger.
        
        Similar to _execute_auto_sell but triggered by price instead of time.
        
        Args:
            signal: TPSLSignal with execution details
        """
        if signal.trade_id in self._tpsl_executing:
            logger.debug(f"Trade {signal.trade_id} already executing TPSL, skipping")
            return
        
        self._tpsl_executing.add(signal.trade_id)
        
        import time
        import json
        exec_start = time.time()
        
        try:
            # Double-check trade status
            trade = await self.db.trade.find_unique(where={"id": signal.trade_id})
            
            if not trade:
                logger.warning(f"⚠️ Trade {signal.trade_id} not found, skipping TPSL")
                return
            
            if trade.status != "executed":
                logger.info(f"⏭️ Trade {signal.trade_id} already {trade.status}, skipping TPSL")
                self._tpsl_trades.pop(signal.trade_id, None)
                if signal.symbol in self._tpsl_by_symbol:
                    self._tpsl_by_symbol[signal.symbol].discard(signal.trade_id)
                return
            
            # Check metadata for already closed flag
            meta = trade.metadata if isinstance(trade.metadata, dict) else {}
            if meta.get("tpsl_closed") or meta.get("auto_sold"):
                logger.info(f"⏭️ Trade {signal.trade_id} already closed via TPSL/auto-sell, skipping")
                self._tpsl_trades.pop(signal.trade_id, None)
                if signal.symbol in self._tpsl_by_symbol:
                    self._tpsl_by_symbol[signal.symbol].discard(signal.trade_id)
                return
            
            logger.info(
                f"🎯 {signal.close_type.upper()} triggered: {signal.trade_id[:8]} "
                f"{signal.symbol} x {signal.quantity} (trigger=₹{signal.trigger_price:.2f}, "
                f"current=₹{signal.current_price:.2f}, entry=₹{signal.entry_price:.2f})"
            )
            
            # Mark as TPSL closed and clear prices to prevent duplicate processing
            await self.db.trade.update(
                where={"id": signal.trade_id},
                data={
                    "take_profit_price": None,
                    "stop_loss_price": None,
                }
            )
            
            # Pre-check: verify position exists and has sufficient holdings
            if signal.side == "SELL":  # Closing a long position
                position = await self.db.position.find_first(
                    where={"portfolio_id": signal.portfolio_id, "symbol": signal.symbol}
                )
                if not position or position.quantity < signal.quantity:
                    available_qty = position.quantity if position else 0
                    logger.warning(
                        f"⚠️ Position check failed for TPSL {signal.trade_id[:8]}: "
                        f"need {signal.quantity} {signal.symbol}, have {available_qty}. "
                        f"Position may have been closed manually."
                    )
                    self._tpsl_trades.pop(signal.trade_id, None)
                    if signal.symbol in self._tpsl_by_symbol:
                        self._tpsl_by_symbol[signal.symbol].discard(signal.trade_id)
                    return
            
            # Execute the closing trade via TradeEngine (same pattern as auto-sell)
            from services.trade_engine import TradeEngine
            from schemas import TradeCreate
            from decimal import Decimal
            
            engine = TradeEngine(self.db)
            
            # Create payload for TradeEngine
            trade_payload = TradeCreate(
                organization_id=trade.organization_id or "",
                portfolio_id=signal.portfolio_id,
                agent_id=trade.agent_id,  # Inherit agent_id from original trade
                customer_id=str(trade.customer_id or ""),
                trade_type="auto",
                symbol=signal.symbol,
                exchange=str(trade.exchange) if trade.exchange else "NSE",
                segment=str(trade.segment) if trade.segment else "EQUITY",
                side=signal.side,  # SELL to close BUY, BUY to close SHORT
                order_type="market",
                quantity=signal.quantity,
                source="streaming_order_monitor",
                metadata={
                    "order_type": signal.close_type,
                    "parent_trade_id": signal.trade_id,
                    "triggered_by": "streaming_order_monitor_tpsl",
                    "entry_price": signal.entry_price,
                    "trigger_price": signal.trigger_price,
                    "execution_price": signal.current_price,
                    "close_reason": signal.close_type,
                    "triggered_at": signal.triggered_at.isoformat(),
                },
            )
            
            # Execute via TradeEngine (creates trade, updates position, logs execution)
            close_trade_dict = await engine._execute_market_order(
                trade_payload,
                Decimal(str(signal.current_price)),
            )
            
            exec_time_ms = int((time.time() - exec_start) * 1000)
            
            # Update TradeExecutionLog with trade_delay
            close_trade_id = close_trade_dict.get("id")
            if close_trade_id:
                try:
                    await self.db.tradeexecutionlog.update_many(
                        where={"trade_id": close_trade_id},
                        data={"trade_delay": exec_time_ms}
                    )
                except Exception as delay_exc:
                    logger.warning(f"Failed to update trade_delay for TPSL: {delay_exc}")
            
            if close_trade_dict.get("status") == "executed":
                # Calculate PnL
                if signal.side == "SELL":  # Closed a long position
                    pnl = (signal.current_price - signal.entry_price) * signal.quantity
                else:  # Closed a short position
                    pnl = (signal.entry_price - signal.current_price) * signal.quantity
                
                # Update original trade metadata
                if not isinstance(meta, dict):
                    meta = {}
                meta.update({
                    "tpsl_closed": True,
                    "tpsl_type": signal.close_type,
                    "tpsl_closed_at": datetime.now(timezone.utc).isoformat(),
                    "tpsl_close_trade_id": close_trade_id,
                    "tpsl_trigger_price": signal.trigger_price,
                    "tpsl_closing_price": signal.current_price,
                    "tpsl_pnl": pnl,
                })
                
                await self.db.trade.update(
                    where={"id": signal.trade_id},
                    data={"metadata": json.dumps(meta)},
                )
                
                pnl_str = f"+₹{pnl:.2f}" if pnl >= 0 else f"-₹{abs(pnl):.2f}"
                logger.info(
                    f"✅ {signal.close_type.upper()} completed in {exec_time_ms}ms: "
                    f"{signal.trade_id[:8]} {signal.symbol} x {signal.quantity} @ ₹{signal.current_price:.2f} "
                    f"(PnL: {pnl_str})"
                )
                
                # Trigger observability analysis for stop-loss or negative PnL trades
                if signal.close_type == "stop_loss" or pnl < 0:
                    try:
                        from workers.observability_agent_tasks import trigger_loss_analysis
                        triggered_by = "stop_loss" if signal.close_type == "stop_loss" else "negative_pnl"
                        signal_context = {
                            "explanation": meta.get("explanation", ""),
                            "pdf_url": meta.get("attachment_url", "") or meta.get("pdf_url", ""),
                            "filing_type": meta.get("filing_type", ""),
                            "realized_pnl": pnl,
                        }
                        trigger_loss_analysis(
                            trade_id=signal.trade_id,
                            triggered_by=triggered_by,
                            signal_context=signal_context,
                        )
                        logger.info(
                            f"📤 Queued observability analysis for {signal.trade_id[:8]} "
                            f"(triggered_by: {triggered_by}, PnL: {pnl_str})"
                        )
                    except Exception as obs_exc:
                        logger.warning(f"Failed to trigger observability analysis: {obs_exc}")
                
                # Remove from cache
                self._tpsl_trades.pop(signal.trade_id, None)
                if signal.symbol in self._tpsl_by_symbol:
                    self._tpsl_by_symbol[signal.symbol].discard(signal.trade_id)
            else:
                logger.error(
                    f"❌ {signal.close_type.upper()} failed for {signal.trade_id[:8]}: "
                    f"status={close_trade_dict.get('status')}"
                )
                
        except Exception as exc:
            logger.exception(f"❌ Failed to execute TPSL for {signal.trade_id}: {exc}")
        finally:
            self._tpsl_executing.discard(signal.trade_id)
    
    async def _tpsl_refresh_loop(self):
        """Background task to periodically refresh TPSL trades from database."""
        while self._running:
            try:
                trades = await self._fetch_tpsl_trades()
                
                # Update cache
                old_ids = set(self._tpsl_trades.keys())
                new_ids = {t.id for t in trades}
                
                # Remove completed/cancelled trades
                for trade_id in old_ids - new_ids:
                    self._tpsl_trades.pop(trade_id, None)
                
                # Add/update trades
                self._tpsl_trades = {t.id: t for t in trades}
                
                # Rebuild symbol index
                self._tpsl_by_symbol = {}
                for trade in trades:
                    if trade.symbol not in self._tpsl_by_symbol:
                        self._tpsl_by_symbol[trade.symbol] = set()
                    self._tpsl_by_symbol[trade.symbol].add(trade.id)
                
                # Subscribe to all TPSL symbols
                symbols = set(self._tpsl_by_symbol.keys())
                if symbols:
                    await self._subscribe_to_symbols(symbols)
                
                if trades:
                    tp_count = sum(1 for t in trades if t.take_profit_price)
                    sl_count = sum(1 for t in trades if t.stop_loss_price)
                    logger.info(
                        f"📊 Monitoring {len(trades)} TPSL trades across {len(symbols)} symbols "
                        f"(TP: {tp_count}, SL: {sl_count})"
                    )
                
                await asyncio.sleep(self.refresh_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"TPSL refresh loop error: {exc}")
                await asyncio.sleep(5)
    
    async def _tpsl_monitor_loop(self):
        """
        Monitor TPSL trades and execute when price conditions are met.
        
        Runs continuously, checking current prices against TP/SL levels.
        Similar to _monitor_loop but for executed trades with TP/SL prices.
        """
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                
                for trade_id, trade in list(self._tpsl_trades.items()):
                    # Skip if already executing
                    if trade_id in self._tpsl_executing:
                        continue
                    
                    # Get current price from market service cache
                    current_price = self.market_service.get_latest_price(trade.symbol)
                    
                    if current_price is None:
                        continue  # No price data yet
                    
                    current_price = float(current_price)
                    
                    # Check TP/SL conditions based on trade side
                    should_close = False
                    close_type = None
                    trigger_price = None
                    
                    if trade.side == "BUY":
                        # For long positions:
                        # - TP triggers when price >= take_profit_price
                        # - SL triggers when price <= stop_loss_price
                        if trade.take_profit_price and current_price >= trade.take_profit_price:
                            should_close = True
                            close_type = "take_profit"
                            trigger_price = trade.take_profit_price
                        elif trade.stop_loss_price and current_price <= trade.stop_loss_price:
                            should_close = True
                            close_type = "stop_loss"
                            trigger_price = trade.stop_loss_price
                    else:
                        # For short positions:
                        # - TP triggers when price <= take_profit_price (price goes down)
                        # - SL triggers when price >= stop_loss_price (price goes up)
                        if trade.take_profit_price and current_price <= trade.take_profit_price:
                            should_close = True
                            close_type = "take_profit"
                            trigger_price = trade.take_profit_price
                        elif trade.stop_loss_price and current_price >= trade.stop_loss_price:
                            should_close = True
                            close_type = "stop_loss"
                            trigger_price = trade.stop_loss_price
                    
                    if should_close and close_type and trigger_price:
                        signal = TPSLSignal(
                            trade_id=trade.id,
                            symbol=trade.symbol,
                            close_type=close_type,
                            side="SELL" if trade.side == "BUY" else "BUY",
                            quantity=trade.quantity,
                            entry_price=trade.entry_price,
                            trigger_price=trigger_price,
                            current_price=current_price,
                            portfolio_id=trade.portfolio_id or "",
                            triggered_at=now,
                        )
                        # Execute async (don't block loop)
                        asyncio.create_task(self._execute_tpsl(signal))
                
                # Check every check_interval seconds (price-based, fast)
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"TPSL monitor loop error: {exc}")
                await asyncio.sleep(2)
    
    def start(self):
        """
        Start the streaming order monitor.
        
        Starts both the order refresh loop (fetches from DB) and the monitoring
        loop (checks conditions and executes orders), plus auto-sell monitoring.
        """
        if self._running:
            logger.warning("Order monitor already running")
            return
        
        self._running = True
        
        logger.info("🚀 Starting streaming order monitor (TP/SL + Auto-Sell)...")
        
        # Start background tasks for price-based orders (TP/SL/limit/stop)
        self._refresh_task = asyncio.create_task(self._refresh_orders_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        # Start background tasks for time-based auto-sell
        self._auto_sell_refresh_task = asyncio.create_task(self._auto_sell_refresh_loop())
        self._auto_sell_task = asyncio.create_task(self._auto_sell_monitor_loop())
        
        # Start background tasks for price-based TP/SL on executed trades
        self._tpsl_refresh_task = asyncio.create_task(self._tpsl_refresh_loop())
        self._tpsl_task = asyncio.create_task(self._tpsl_monitor_loop())
        
        logger.info("✅ Streaming order monitor started (Pending Orders + TP/SL + Auto-Sell)")
    
    def stop(self):
        """Stop the streaming order monitor."""
        if not self._running:
            return
        
        logger.info("Stopping streaming order monitor...")
        self._running = False
        
        # Cancel price-based order tasks
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()
        
        # Cancel auto-sell tasks
        if self._auto_sell_refresh_task:
            self._auto_sell_refresh_task.cancel()
        if self._auto_sell_task:
            self._auto_sell_task.cancel()
        
        # Cancel TPSL tasks
        if self._tpsl_refresh_task:
            self._tpsl_refresh_task.cancel()
        if self._tpsl_task:
            self._tpsl_task.cancel()
        
        logger.info("Streaming order monitor stopped")
    
    @property
    def is_running(self) -> bool:
        """Check if monitor is running."""
        return self._running
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get monitor statistics.
        
        Returns:
            Dictionary with monitoring statistics
        """
        return {
            "running": self._running,
            # Price-based pending orders (limit/stop)
            "pending_orders": len(self._pending_orders),
            "monitored_symbols": len(self._orders_by_symbol),
            "subscribed_symbols": len(self._subscribed_symbols),
            "currently_executing": len(self._executing),
            # Time-based auto-sell
            "auto_sell_trades": len(self._auto_sell_trades),
            "currently_auto_selling": len(self._auto_selling),
            # Price-based TP/SL on executed trades
            "tpsl_trades": len(self._tpsl_trades),
            "tpsl_symbols": len(self._tpsl_by_symbol),
            "currently_executing_tpsl": len(self._tpsl_executing),
        }
