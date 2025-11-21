"""
Trade Validation Service

Validates trades before execution:
- Cash availability for BUY orders
- Holdings availability for SELL orders
- Portfolio allocation limits
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from db_client import get_db_client


class TradeValidationService:
    """Service for validating trades before execution."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def _as_decimal(self, value: Any, default: Decimal = Decimal("0")) -> Decimal:
        """Safely convert value to Decimal."""
        if value is None:
            return default
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return default

    async def validate_buy_order(
        self,
        portfolio_id: str,
        agent_id: Optional[str],
        symbol: str,
        quantity: int,
        price: Decimal,
    ) -> Dict[str, Any]:
        """
        Validate BUY order against available cash.
        
        Args:
            portfolio_id: Portfolio ID
            agent_id: Trading agent ID (optional for manual trades)
            symbol: Stock symbol
            quantity: Number of shares
            price: Price per share
            
        Returns:
            Dict with 'valid' (bool), 'reason' (str), and 'available_cash' (Decimal)
        """
        client = await get_db_client()
        try:
            # Calculate required cash
            required_cash = self._as_decimal(price * Decimal(str(quantity)))
            
            # Get available cash from portfolio allocation
            if agent_id:
                agent = await client.tradingagent.find_unique(
                    where={"id": agent_id},
                    include={"allocation": True},
                )
                
                if not agent:
                    return {
                        "valid": False,
                        "reason": "Trading agent not found",
                        "available_cash": Decimal("0"),
                    }
                
                allocation = getattr(agent, "allocation", None)
                if not allocation:
                    return {
                        "valid": False,
                        "reason": "No allocation found for agent",
                        "available_cash": Decimal("0"),
                    }
                
                # Get liquid cash from allocation
                available_cash = self._as_decimal(getattr(allocation, "available_cash", 0))
                
            else:
                # Manual trade - check portfolio-level cash
                portfolio = await client.portfolio.find_unique(
                    where={"id": portfolio_id}
                )
                
                if not portfolio:
                    return {
                        "valid": False,
                        "reason": "Portfolio not found",
                        "available_cash": Decimal("0"),
                    }
                
                available_cash = self._as_decimal(getattr(portfolio, "available_cash", 0))
            
            # Validate
            if available_cash < required_cash:
                return {
                    "valid": False,
                    "reason": f"Insufficient cash: ₹{float(available_cash):.2f} available, ₹{float(required_cash):.2f} required",
                    "available_cash": available_cash,
                    "required_cash": required_cash,
                }
            
            self.logger.info(
                "✅ BUY validation passed: %s x %d @ ₹%.2f (cash: ₹%.2f)",
                symbol,
                quantity,
                float(price),
                float(available_cash),
            )
            
            return {
                "valid": True,
                "reason": "Sufficient cash available",
                "available_cash": available_cash,
                "required_cash": required_cash,
            }
                
        except Exception as exc:
            self.logger.error("Buy validation failed: %s", exc, exc_info=True)
            return {
                "valid": False,
                "reason": f"Validation error: {str(exc)}",
                "available_cash": Decimal("0"),
            }

    async def validate_sell_order(
        self,
        portfolio_id: str,
        agent_id: Optional[str],
        symbol: str,
        quantity: int,
    ) -> Dict[str, Any]:
        """
        Validate SELL order against available holdings.
        
        Args:
            portfolio_id: Portfolio ID
            agent_id: Trading agent ID (optional for manual trades)
            symbol: Stock symbol
            quantity: Number of shares to sell
            
        Returns:
            Dict with 'valid' (bool), 'reason' (str), and 'available_quantity' (int)
        """
        client = await get_db_client()
        try:
            # Find position
            where_clause = {
                "portfolio_id": portfolio_id,
                "symbol": symbol,
                "status": "open",
            }
            
            if agent_id:
                where_clause["agent_id"] = agent_id
            
            position = await client.position.find_first(where=where_clause)
            
            if not position:
                return {
                    "valid": False,
                    "reason": f"No open position found for {symbol}",
                    "available_quantity": 0,
                }
            
            available_quantity = int(getattr(position, "quantity", 0))
            
            if available_quantity < quantity:
                return {
                    "valid": False,
                    "reason": f"Insufficient holdings: {available_quantity} available, {quantity} requested",
                    "available_quantity": available_quantity,
                    "requested_quantity": quantity,
                }
            
            self.logger.info(
                "✅ SELL validation passed: %s x %d (holdings: %d)",
                symbol,
                quantity,
                available_quantity,
            )
            
            return {
                "valid": True,
                "reason": "Sufficient holdings available",
                "available_quantity": available_quantity,
                "requested_quantity": quantity,
            }
                
        except Exception as exc:
            self.logger.error("Sell validation failed: %s", exc, exc_info=True)
            return {
                "valid": False,
                "reason": f"Validation error: {str(exc)}",
                "available_quantity": 0,
            }
