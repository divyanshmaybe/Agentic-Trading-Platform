"""
Trading Agent Snapshot Service

Captures periodic snapshots of trading agent performance for historical tracking.
Each snapshot records portfolio_value and realized_pnl at a specific point in time.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from db import get_db_manager  # type: ignore


class TradingAgentSnapshotService:
    """Service for capturing and retrieving trading agent snapshots."""

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._manager = get_db_manager()

    async def _ensure_client(self):
        """Ensure database client is connected."""
        if not self._manager.is_connected():
            await self._manager.connect()
        return self._manager.get_client()

    @staticmethod
    def _as_decimal(value: Any) -> Decimal:
        """Convert value to Decimal safely."""
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")

    async def capture_agent_snapshot(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Capture a snapshot for a single trading agent.
        
        Calculates:
        - portfolio_value: Sum of (current_price * quantity) for agent's positions
        - realized_pnl: From TradingAgent.realized_pnl
        - positions_count: Number of active positions
        
        Args:
            agent_id: Trading agent ID
            
        Returns:
            Snapshot record dict or None if failed
        """
        client = await self._ensure_client()
        
        try:
            # Fetch agent with positions and allocation
            agent = await client.tradingagent.find_unique(
                where={"id": agent_id},
                include={
                    "positions": {
                        "where": {"status": "open"},
                    },
                    "allocation": True,
                },
            )
            
            if not agent:
                self.logger.warning("Agent %s not found for snapshot", agent_id)
                return None
            
            portfolio_id = str(getattr(agent, "portfolio_id", ""))
            if not portfolio_id:
                self.logger.warning("Agent %s has no portfolio_id", agent_id)
                return None
            
            # Calculate portfolio_value from positions
            positions = getattr(agent, "positions", []) or []
            portfolio_value = Decimal("0")
            positions_count = len(positions)
            
            for position in positions:
                current_price = self._as_decimal(getattr(position, "current_price", 0))
                quantity = int(getattr(position, "quantity", 0))
                position_value = current_price * Decimal(str(quantity))
                portfolio_value += position_value
            
            # Get realized_pnl from agent
            realized_pnl = self._as_decimal(getattr(agent, "realized_pnl", 0) or 0)
            
            # Create snapshot
            snapshot = await client.tradingagentsnapshot.create(
                data={
                    "agent": {"connect": {"id": agent_id}},
                    "portfolio_id": portfolio_id,
                    "snapshot_at": datetime.utcnow(),
                    "portfolio_value": portfolio_value,
                    "realized_pnl": realized_pnl,
                    "positions_count": positions_count,
                    "metadata": {
                        "agent_type": getattr(agent, "agent_type", ""),
                        "agent_name": getattr(agent, "agent_name", ""),
                        "captured_at": datetime.utcnow().isoformat(),
                    },
                }
            )
            
            self.logger.info(
                "📸 Captured snapshot for agent %s: portfolio_value=₹%.2f, realized_pnl=₹%.2f, positions=%d",
                agent_id,
                float(portfolio_value),
                float(realized_pnl),
                positions_count,
            )
            
            return {
                "id": snapshot.id,
                "agent_id": agent_id,
                "portfolio_id": portfolio_id,
                "snapshot_at": snapshot.snapshot_at.isoformat(),
                "portfolio_value": float(portfolio_value),
                "realized_pnl": float(realized_pnl),
                "positions_count": positions_count,
            }
            
        except Exception as exc:
            self.logger.error(
                "Failed to capture snapshot for agent %s: %s",
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
        client = await self._ensure_client()
        
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
                "📸 Snapshot capture complete: %d/%d agents captured, %d failed",
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

    async def capture_all_portfolio_snapshots(self) -> Dict[str, Any]:
        """
        Capture snapshots for ALL portfolios.
        
        For each active portfolio:
        - Gathers current_value from Portfolio.current_value
        - Calculates total_pnl = current_value - investment_amount + realized_pnl
        - Creates PortfolioSnapshot record
        
        Returns:
            Dict with summary of snapshots captured
        """
        client = await self._ensure_client()
        
        try:
            # Find all active portfolios
            portfolios = await client.portfolio.find_many(
                where={"status": "active"},
            )
            
            if not portfolios:
                self.logger.info("No active portfolios found for snapshot capture")
                return {"total_portfolios": 0, "snapshots_captured": 0, "failed": 0}
            
            snapshots_captured = 0
            failed = 0
            
            for portfolio in portfolios:
                try:
                    portfolio_id = str(getattr(portfolio, "id", ""))
                    current_value = self._as_decimal(getattr(portfolio, "current_value", 0) or 0)
                    investment_amount = self._as_decimal(getattr(portfolio, "investment_amount", 0) or 0)
                    realized_pnl = self._as_decimal(getattr(portfolio, "realized_pnl", 0) or 0)
                    
                    # Calculate total PnL = (current_value - investment_amount) + realized_pnl
                    total_pnl = current_value - investment_amount + realized_pnl
                    
                    # Create portfolio snapshot
                    await client.portfoliosnapshot.create(
                        data={
                            "portfolio_id": portfolio_id,
                            "current_value": current_value,
                            "total_pnl": total_pnl,
                        }
                    )
                    
                    self.logger.info(
                        "📸 Captured portfolio snapshot: portfolio=%s, value=₹%.2f, pnl=₹%.2f",
                        portfolio_id,
                        float(current_value),
                        float(total_pnl),
                    )
                    
                    snapshots_captured += 1
                    
                except Exception as exc:
                    self.logger.error(
                        "Failed to capture snapshot for portfolio %s: %s",
                        getattr(portfolio, "id", ""),
                        exc,
                    )
                    failed += 1
            
            self.logger.info(
                "📸 Portfolio snapshot capture complete: %d/%d portfolios captured, %d failed",
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
        client = await self._ensure_client()
        
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
                    "portfolio_value": float(self._as_decimal(snapshot.portfolio_value)),
                    "realized_pnl": float(self._as_decimal(snapshot.realized_pnl)),
                    "positions_count": snapshot.positions_count,
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
        Get aggregated portfolio snapshots (sum of all agents in portfolio).
        
        Groups snapshots by snapshot_at timestamp and sums portfolio_value and realized_pnl
        from all agents in the portfolio.
        
        Args:
            portfolio_id: Portfolio ID
            limit: Maximum number of snapshot timestamps to return
            
        Returns:
            List of aggregated snapshot records ordered by snapshot_at (descending)
        """
        client = await self._ensure_client()
        
        try:
            # Get all snapshots for agents in this portfolio
            snapshots = await client.tradingagentsnapshot.find_many(
                where={"portfolio_id": portfolio_id},
                order={"snapshot_at": "desc"},
                take=limit * 10,  # Get more to account for multiple agents per timestamp
            )
            
            if not snapshots:
                return []
            
            # Group by snapshot_at and aggregate
            grouped: Dict[str, Dict[str, Any]] = {}
            
            for snapshot in snapshots:
                snapshot_at_key = snapshot.snapshot_at.isoformat()
                
                if snapshot_at_key not in grouped:
                    grouped[snapshot_at_key] = {
                        "snapshot_at": snapshot_at_key,
                        "portfolio_value": Decimal("0"),
                        "realized_pnl": Decimal("0"),
                        "positions_count": 0,
                        "agents_count": 0,
                    }
                
                grouped[snapshot_at_key]["portfolio_value"] += self._as_decimal(snapshot.portfolio_value)
                grouped[snapshot_at_key]["realized_pnl"] += self._as_decimal(snapshot.realized_pnl)
                grouped[snapshot_at_key]["positions_count"] += snapshot.positions_count
                grouped[snapshot_at_key]["agents_count"] += 1
            
            # Convert to list and sort by snapshot_at (descending)
            aggregated = list(grouped.values())
            aggregated.sort(key=lambda x: x["snapshot_at"], reverse=True)
            
            # Take only the requested limit
            result = aggregated[:limit]
            
            # Convert Decimal to float for JSON serialization
            return [
                {
                    "snapshot_at": item["snapshot_at"],
                    "portfolio_value": float(item["portfolio_value"]),
                    "realized_pnl": float(item["realized_pnl"]),
                    "positions_count": item["positions_count"],
                    "agents_count": item["agents_count"],
                }
                for item in result
            ]
            
        except Exception as exc:
            self.logger.error(
                "Failed to get portfolio snapshot history for portfolio %s: %s",
                portfolio_id,
                exc,
                exc_info=True,
            )
            return []

