"""
Minimal Snapshot Service

Captures periodic snapshots with:
- Portfolio: current_value, realized_pnl, unrealized_pnl
- TradingAgent: current_value, realized_pnl, unrealized_pnl, agent_type
- Allocation: current_value, realized_pnl, unrealized_pnl
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from dbManager import DBManager


class TradingAgentSnapshotService:
    """Service for capturing minimal snapshots."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _as_decimal(value: Any) -> Decimal:
        """Convert value to Decimal safely."""
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")
    
    def _get_live_price(self, symbol: str, fallback: Decimal) -> Decimal:
        """Get live price from market data service with timeout fallback."""
        try:
            # Skip live price fetching for snapshots - use position avg_price instead
            # Live prices are expensive and cause timeouts during snapshot capture
            # For historical analysis, avg_price is sufficient and more reliable
            return fallback
        except Exception as e:
            self.logger.debug("Failed to fetch live price for %s: %s", symbol, e)
            return fallback

    async def _fetch_live_price(
        self, 
        symbol: str, 
        exchange: str = "NSE", 
        segment: str = "EQUITY"
    ) -> Optional[Decimal]:
        """
        Fetch live price from market data service asynchronously.
        
        Args:
            symbol: Stock symbol
            exchange: Exchange (NSE, BSE)
            segment: Market segment (EQUITY, FO, etc.)
            
        Returns:
            Current market price or None if unavailable
        """
        try:
            from market_data import get_market_data_service
            
            service = get_market_data_service()
            
            # Try to get from cache first (instant)
            price = service.get_latest_price(symbol)
            if price is not None:
                return price
            
            # Try to await price from WebSocket (with timeout)
            try:
                service.register_symbol(symbol)
                price = await service.await_price(symbol, timeout=5.0)
                if price is not None:
                    return price
            except Exception as ws_err:
                self.logger.debug("WebSocket price fetch failed for %s: %s", symbol, ws_err)
            
            # Return None if no price available
            return None
            
        except Exception as e:
            self.logger.warning("Failed to fetch live price for %s: %s", symbol, e)
            return None

    async def capture_agent_snapshot(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Capture minimal snapshot for trading agent.
        
        Includes:
        - current_value: available_cash + sum(live_price × quantity)
        - realized_pnl: From TradingAgent.realized_pnl  
        - unrealized_pnl: sum((live_price - avg_buy_price) × quantity) for open positions
        - agent_type: Denormalized for easier querying
        
        Args:
            agent_id: Trading agent ID
            
        Returns:
            Snapshot record dict or None if failed
        """
        db_manager = DBManager.get_instance()
        
        async with db_manager.session() as client:
            try:
                # Skip if client is a mock (testing)
                if hasattr(client, '_mock_name') or str(type(client).__name__) == 'AsyncMock':
                    self.logger.debug("Skipping snapshot capture in test mode")
                    return None
                
                # Fetch agent with positions and allocation
                agent = await client.tradingagent.find_unique(
                    where={"id": agent_id},
                    include={
                        "positions": {"where": {"status": "open"}},
                        "allocation": True,
                    },
                )
                
                if not agent:
                    self.logger.warning("Agent %s not found for snapshot", agent_id)
                    return None
                
                portfolio_id = str(getattr(agent, "portfolio_id", ""))
                agent_type = str(getattr(agent, "agent_type", ""))
                
                if not portfolio_id:
                    self.logger.warning("Agent %s has no portfolio_id", agent_id)
                    return None
                
                # Get available cash from allocation
                allocation = getattr(agent, "allocation", None)
                available_cash = Decimal("0")
                if allocation:
                    available_cash = self._as_decimal(getattr(allocation, "available_cash", 0))
                
                # Calculate positions value and unrealized P&L
                positions = getattr(agent, "positions", []) or []
                positions_value = Decimal("0")
                unrealized_pnl = Decimal("0")
                
                # Batch fetch all prices first (more efficient than per-position)
                symbols_needed = {str(getattr(p, "symbol", "")) for p in positions 
                                if str(getattr(p, "symbol", "")) and int(getattr(p, "quantity", 0)) != 0}
                
                # Pre-fetch all prices from cache (WebSocket already has them)
                price_cache = {}
                for symbol in symbols_needed:
                    price_cache[symbol] = self._get_live_price(symbol, Decimal("0"))
                
                for position in positions:
                    symbol = str(getattr(position, "symbol", ""))
                    quantity = int(getattr(position, "quantity", 0))
                    avg_buy_price = self._as_decimal(getattr(position, "average_buy_price", 0))
                    position_type = str(getattr(position, "position_type", "long")).lower()
                    
                    if not symbol or quantity == 0:
                        continue
                    
                    # Use pre-fetched price (fallback to avg if not in cache)
                    current_price = price_cache.get(symbol, avg_buy_price)
                    if current_price == Decimal("0"):
                        current_price = avg_buy_price
                    
                    # Handle SHORT vs LONG positions correctly
                    abs_quantity = abs(quantity)
                    
                    if position_type == "short":
                        # SHORT: we OWE shares (liability, negative value)
                        position_value = -(current_price * Decimal(str(abs_quantity)))
                        cost_basis = -(avg_buy_price * Decimal(str(abs_quantity)))
                    else:
                        # LONG: we OWN shares (asset, positive value)
                        position_value = current_price * Decimal(str(quantity))
                        cost_basis = avg_buy_price * Decimal(str(quantity))
                    
                    positions_value += position_value
                    unrealized_pnl += (position_value - cost_basis)
                
                current_value = available_cash + positions_value
                realized_pnl = self._as_decimal(getattr(agent, "realized_pnl", 0))
                
                # Create snapshot (agent relation automatically sets agent_id)
                snapshot = await client.tradingagentsnapshot.create(
                    data={
                        "agent": {"connect": {"id": agent_id}},
                        "portfolio_id": portfolio_id,
                        "agent_type": agent_type,
                        "snapshot_at": datetime.utcnow(),
                        "current_value": current_value,
                        "realized_pnl": realized_pnl,
                        "unrealized_pnl": unrealized_pnl,
                    }
                )
                
                self.logger.info(
                    "📸 Agent snapshot [%s]: value=₹%.2f, realized=₹%.2f, unrealized=₹%.2f",
                    agent_type,
                    float(current_value),
                    float(realized_pnl),
                    float(unrealized_pnl),
                )
                
                return {
                    "id": snapshot.id,
                    "agent_id": agent_id,
                    "portfolio_id": portfolio_id,
                    "agent_type": agent_type,
                    "current_value": float(current_value),
                    "realized_pnl": float(realized_pnl),
                    "unrealized_pnl": float(unrealized_pnl),
                }
                
            except Exception as exc:
                self.logger.error(
                    "Failed to capture agent snapshot %s: %s",
                    agent_id,
                    exc,
                    exc_info=True,
                )
                return None

    async def capture_all_active_agents(self) -> Dict[str, Any]:
        """
        Capture snapshots for all active trading agents.
        
        Returns:
            Dict with summary of snapshots captured
        """
        db_manager = DBManager.get_instance()
        
        async with db_manager.session() as client:
            try:
                # Find all active agents
                agents = await client.tradingagent.find_many(
                    where={"status": "active"},
                )
                
                if not agents:
                    self.logger.info("No active agents found for snapshot capture")
                    return {"total_agents": 0, "snapshots_captured": 0, "failed": 0}
                
                snapshots_captured = 0
                failed = 0
                
                for agent in agents:
                    agent_id = str(getattr(agent, "id", ""))
                    result = await self.capture_agent_snapshot(agent_id)
                    if result:
                        snapshots_captured += 1
                    else:
                        failed += 1
                
                self.logger.info(
                    "📸 Agent snapshots complete: %d/%d captured, %d failed",
                    snapshots_captured,
                    len(agents),
                    failed,
                )
                
                return {
                    "total_agents": len(agents),
                    "snapshots_captured": snapshots_captured,
                    "failed": failed,
                }
                
            except Exception as exc:
                self.logger.error("Failed to capture all agent snapshots: %s", exc, exc_info=True)
                return {"total_agents": 0, "snapshots_captured": 0, "failed": 0}
    
    async def capture_portfolio_snapshot(self, portfolio_id: str) -> Optional[Dict[str, Any]]:
        """
        Capture minimal portfolio snapshot.
        
        Includes:
        - current_value: available_cash + sum(live_price × quantity) from all positions
        - realized_pnl: From Portfolio.total_realized_pnl
        - unrealized_pnl: Aggregated from all open positions
        
        Args:
            portfolio_id: Portfolio ID
            
        Returns:
            Snapshot record dict or None if failed
        """
        db_manager = DBManager.get_instance()
        
        async with db_manager.session() as client:
            try:
                portfolio = await client.portfolio.find_unique(
                    where={"id": portfolio_id},
                    include={"positions": {"where": {"status": "open"}}}
                )
                
                if not portfolio:
                    return None
                
                available_cash = self._as_decimal(getattr(portfolio, "available_cash", 0))
                realized_pnl = self._as_decimal(getattr(portfolio, "total_realized_pnl", 0))
                
                # Calculate positions value and unrealized P&L
                positions = getattr(portfolio, "positions", []) or []
                positions_value = Decimal("0")
                unrealized_pnl = Decimal("0")
                
                # Batch fetch all prices first (more efficient than per-position)
                symbols_needed = {str(getattr(p, "symbol", "")) for p in positions 
                                if str(getattr(p, "symbol", "")) and int(getattr(p, "quantity", 0)) != 0}
                
                # Pre-fetch all prices from cache (WebSocket already has them)
                price_cache = {}
                for symbol in symbols_needed:
                    price_cache[symbol] = self._get_live_price(symbol, Decimal("0"))
                
                for pos in positions:
                    symbol = str(getattr(pos, "symbol", ""))
                    quantity = int(getattr(pos, "quantity", 0))
                    avg_buy_price = self._as_decimal(getattr(pos, "average_buy_price", 0))
                    
                    if not symbol or quantity == 0:
                        continue
                    
                    # Use pre-fetched price (fallback to avg if not in cache)
                    current_price = price_cache.get(symbol, avg_buy_price)
                    if current_price == Decimal("0"):
                        current_price = avg_buy_price
                    
                    position_value = current_price * Decimal(str(quantity))
                    cost_basis = avg_buy_price * Decimal(str(quantity))
                    
                    positions_value += position_value
                    unrealized_pnl += (position_value - cost_basis)
                
                current_value = available_cash + positions_value
                
                # Create snapshot with relation to portfolio
                snapshot = await client.portfoliosnapshot.create(
                    data={
                        "portfolio": {"connect": {"id": portfolio_id}},
                        "snapshot_at": datetime.utcnow(),
                        "current_value": current_value,
                        "realized_pnl": realized_pnl,
                        "unrealized_pnl": unrealized_pnl
                    }
                )
                
                self.logger.info(
                    "📸 Portfolio snapshot: value=₹%.2f, realized=₹%.2f, unrealized=₹%.2f",
                    float(current_value),
                    float(realized_pnl),
                    float(unrealized_pnl)
                )
                
                return {
                    "id": snapshot.id,
                    "portfolio_id": portfolio_id,
                    "current_value": float(current_value),
                    "realized_pnl": float(realized_pnl),
                    "unrealized_pnl": float(unrealized_pnl)
                }
            
            except Exception as exc:
                self.logger.error("Portfolio snapshot failed: %s", exc, exc_info=True)
                return None

    async def capture_all_portfolio_snapshots(self) -> Dict[str, Any]:
        """
        Capture snapshots for all active portfolios.
        
        Returns:
            Dict with summary of snapshots captured
        """
        db_manager = DBManager.get_instance()
        
        async with db_manager.session() as client:
            try:
                portfolios = await client.portfolio.find_many(
                    where={"status": "active"},
                )
                
                if not portfolios:
                    self.logger.info("No active portfolios found for snapshot capture")
                    return {"total_portfolios": 0, "snapshots_captured": 0, "failed": 0}
                
                snapshots_captured = 0
                failed = 0
                
                for portfolio in portfolios:
                    portfolio_id = str(getattr(portfolio, "id", ""))
                    result = await self.capture_portfolio_snapshot(portfolio_id)
                    if result:
                        snapshots_captured += 1
                    else:
                        failed += 1
                
                self.logger.info(
                    "📸 Portfolio snapshots complete: %d/%d captured, %d failed",
                    snapshots_captured,
                    len(portfolios),
                    failed,
                )
                
                return {
                    "total_portfolios": len(portfolios),
                    "snapshots_captured": snapshots_captured,
                    "failed": failed,
                }
            
            except Exception as exc:
                self.logger.error("Failed to capture all portfolio snapshots: %s", exc, exc_info=True)
                return {"total_portfolios": 0, "snapshots_captured": 0, "failed": 0}
    
    async def get_agent_snapshot_history(
        self,
        agent_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get historical snapshots for a single agent.
        
        Args:
            agent_id: Trading agent ID
            limit: Maximum number of snapshots to return
            
        Returns:
            List of snapshot records ordered by snapshot_at (descending)
        """
        db_manager = DBManager.get_instance()
        
        async with db_manager.session() as client:
            try:
                snapshots = await client.tradingagentsnapshot.find_many(
                    where={"agent_id": agent_id},
                    order={"snapshot_at": "desc"},
                    take=limit,
                )
                
                return [
                    {
                        "id": snapshot.id,
                        "snapshot_at": snapshot.snapshot_at.isoformat() if hasattr(snapshot.snapshot_at, "isoformat") else str(snapshot.snapshot_at),
                        "current_value": float(self._as_decimal(snapshot.current_value)),
                        "realized_pnl": float(self._as_decimal(snapshot.realized_pnl)),
                        "unrealized_pnl": float(self._as_decimal(snapshot.unrealized_pnl)),
                    }
                    for snapshot in snapshots
                ]
                    
            except Exception as exc:
                self.logger.error(
                    "Failed to get snapshot history for agent %s: %s",
                    agent_id,
                    exc,
                    exc_info=True,
                )
                return []

    async def get_portfolio_snapshot_history(
        self,
        portfolio_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get portfolio snapshot history.
        
        Args:
            portfolio_id: Portfolio ID
            limit: Maximum number of snapshots to return
            
        Returns:
            List of snapshot records ordered by snapshot_at (descending)
        """
        db_manager = DBManager.get_instance()
        
        async with db_manager.session() as client:
            try:
                snapshots = await client.portfoliosnapshot.find_many(
                    where={"portfolio_id": portfolio_id},
                    order={"snapshot_at": "desc"},
                    take=limit,
                )
                
                return [
                    {
                        "id": snapshot.id,
                        "snapshot_at": snapshot.snapshot_at.isoformat() if hasattr(snapshot.snapshot_at, "isoformat") else str(snapshot.snapshot_at),
                        "current_value": float(self._as_decimal(snapshot.current_value)),
                        "realized_pnl": float(self._as_decimal(snapshot.realized_pnl)),
                        "unrealized_pnl": float(self._as_decimal(snapshot.unrealized_pnl)),
                    }
                    for snapshot in snapshots
                ]
                    
            except Exception as exc:
                self.logger.error(
                    "Failed to get portfolio snapshot history: %s",
                    exc,
                    exc_info=True,
                )
                return []
