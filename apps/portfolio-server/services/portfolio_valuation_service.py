"""
Portfolio Valuation Service

Handles comprehensive portfolio valuation calculations including:
- Current portfolio value
- Total position value
- Unrealized P&L
- Total P&L (realized + unrealized)
- Return percentages
- Margin calculations (SEBI-compliant interfaces)

Ground Truth Formula (from snapshot_service.py):
    current_value = available_cash + Σ(position_quantity × current_price)
    unrealized_pnl = Σ((current_price - average_buy_price) × quantity)
    total_pnl = realized_pnl + unrealized_pnl
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from dbManager import DBManager


class PortfolioValuationService:
    """Service for calculating portfolio valuations and metrics."""

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
        """
        Get live price from market data service.
        
        For now, returns fallback (average_buy_price).
        TODO: Integrate with market_data WebSocket service.
        """
        try:
            # Import market data service (if available)
            # from market_data import get_market_data_service
            # service = get_market_data_service()
            # price = service.get_latest_price(symbol)
            # if price is not None:
            #     return self._as_decimal(price)
            
            # For snapshots and backend calculations, use position avg_price
            # This avoids timeouts and provides consistent historical analysis
            return fallback
        except Exception as e:
            self.logger.debug("Failed to fetch live price for %s: %s", symbol, e)
            return fallback

    async def calculate_portfolio_metrics(
        self, 
        portfolio_id: str,
        client: Any = None,
    ) -> Dict[str, Decimal]:
        """
        Calculate comprehensive portfolio metrics.
        
        Returns:
            Dict with keys:
            - total_position_value: Sum of all position market values
            - total_unrealized_pnl: Sum of unrealized P&L from open positions
            - current_portfolio_value: available_cash + total_position_value
            - total_pnl: realized_pnl + unrealized_pnl
            - total_return_pct: ((current_value - investment) / investment) * 100
            - margin_used: Total margin blocked (placeholder)
            - free_margin: Available margin for new trades (placeholder)
        
        Args:
            portfolio_id: Portfolio ID
            client: Optional Prisma client (if inside a transaction)
        """
        if client is None:
            db_manager = DBManager.get_instance()
            async with db_manager.session() as client:
                return await self._calculate_metrics_internal(portfolio_id, client)
        else:
            return await self._calculate_metrics_internal(portfolio_id, client)

    async def _calculate_metrics_internal(
        self,
        portfolio_id: str,
        client: Any,
    ) -> Dict[str, Decimal]:
        """Internal implementation of portfolio metrics calculation."""
        
        # Fetch portfolio with open positions
        portfolio = await client.portfolio.find_unique(
            where={"id": portfolio_id},
            include={"positions": {"where": {"status": "open"}}}
        )
        
        if not portfolio:
            self.logger.warning("Portfolio %s not found", portfolio_id)
            return self._empty_metrics()
        
        # Extract portfolio-level data
        investment_amount = self._as_decimal(getattr(portfolio, "investment_amount", 0))
        available_cash = self._as_decimal(getattr(portfolio, "available_cash", 0))
        realized_pnl = self._as_decimal(getattr(portfolio, "total_realized_pnl", 0))
        
        # Get positions
        positions = getattr(portfolio, "positions", []) or []
        
        # Calculate position values and unrealized P&L
        total_position_value = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        
        # Batch fetch symbols for live pricing
        symbols_needed = {
            str(getattr(p, "symbol", "")) 
            for p in positions 
            if str(getattr(p, "symbol", "")) and int(getattr(p, "quantity", 0)) != 0
        }
        
        # Pre-fetch prices (currently uses avg_buy_price as fallback)
        price_cache: Dict[str, Decimal] = {}
        for symbol in symbols_needed:
            price_cache[symbol] = Decimal("0")  # Will be fetched per position below
        
        for position in positions:
            symbol = str(getattr(position, "symbol", ""))
            quantity = int(getattr(position, "quantity", 0))
            avg_buy_price = self._as_decimal(getattr(position, "average_buy_price", 0))
            position_type = str(getattr(position, "position_type", "long")).lower()
            
            if not symbol or quantity == 0:
                continue
            
            # Get live price (fallback to average_buy_price for now)
            current_price = self._get_live_price(symbol, avg_buy_price)
            if current_price == Decimal("0"):
                current_price = avg_buy_price
            
            # Calculate position value and unrealized P&L
            # Use absolute quantity for value calculation
            abs_quantity = abs(quantity)
            
            if position_type == "short":
                # SHORT position: we OWE shares (liability)
                # position_value is NEGATIVE (reduces portfolio value)
                # unrealized_pnl = (avg_buy_price - current_price) × |quantity|
                position_value = -(current_price * Decimal(str(abs_quantity)))
                cost_basis = -(avg_buy_price * Decimal(str(abs_quantity)))
                unrealized_pnl = cost_basis - position_value  # Profit when price drops
            else:
                # LONG position: we OWN shares (asset)
                # position_value is POSITIVE (increases portfolio value)
                # unrealized_pnl = (current_price - avg_buy_price) × quantity
                position_value = current_price * Decimal(str(quantity))
                cost_basis = avg_buy_price * Decimal(str(quantity))
                unrealized_pnl = position_value - cost_basis
            
            total_position_value += position_value
            total_unrealized_pnl += unrealized_pnl
        
        # Calculate aggregated metrics
        # GROUND TRUTH FORMULA (from snapshot_service.py):
        current_portfolio_value = available_cash + total_position_value
        total_pnl = realized_pnl + total_unrealized_pnl
        
        # Calculate return percentage
        if investment_amount > 0:
            total_return_pct = (
                (current_portfolio_value - investment_amount) / investment_amount
            ) * Decimal("100")
        else:
            total_return_pct = Decimal("0")
        
        # Margin calculations (SEBI-compliant placeholders)
        # TODO: Implement actual SEBI margin rules (VAR + ELM, 20% minimum)
        margin_used = self._calculate_margin_used(positions)
        free_margin = available_cash - margin_used
        
        self.logger.info(
            "📊 Portfolio %s metrics: value=₹%.2f, positions=₹%.2f, unrealized=₹%.2f, total_pnl=₹%.2f (%.2f%%)",
            portfolio_id[:8],
            float(current_portfolio_value),
            float(total_position_value),
            float(total_unrealized_pnl),
            float(total_pnl),
            float(total_return_pct),
        )
        
        return {
            "total_position_value": total_position_value,
            "total_unrealized_pnl": total_unrealized_pnl,
            "current_portfolio_value": current_portfolio_value,
            "total_pnl": total_pnl,
            "total_return_pct": total_return_pct,
            "margin_used": margin_used,
            "free_margin": free_margin,
        }

    def _calculate_margin_used(self, positions: List[Any]) -> Decimal:
        """
        Calculate total margin used by open positions.
        
        SEBI-compliant margin rules:
        - Intraday: min(20% of trade value, VAR + ELM)
        - Delivery: 100% upfront (or margin based on pledged securities)
        - Max leverage: ~5x (i.e., 20% minimum margin)
        
        For now, returns placeholder based on position notional.
        TODO: Integrate with broker margin calculator.
        
        Args:
            positions: List of open positions
            
        Returns:
            Total margin blocked
        """
        total_margin = Decimal("0")
        
        for position in positions:
            quantity = int(getattr(position, "quantity", 0))
            avg_buy_price = self._as_decimal(getattr(position, "average_buy_price", 0))
            
            if quantity == 0:
                continue
            
            # Calculate notional value
            notional = avg_buy_price * Decimal(str(abs(quantity)))
            
            # Placeholder: Assume 20% margin for intraday, 100% for delivery
            # In production, this should query broker/risk engine
            # For now, assume all positions are delivery (100% margin)
            margin = notional
            
            total_margin += margin
        
        return total_margin

    def _empty_metrics(self) -> Dict[str, Decimal]:
        """Return empty metrics dict."""
        return {
            "total_position_value": Decimal("0"),
            "total_unrealized_pnl": Decimal("0"),
            "current_portfolio_value": Decimal("0"),
            "total_pnl": Decimal("0"),
            "total_return_pct": Decimal("0"),
            "margin_used": Decimal("0"),
            "free_margin": Decimal("0"),
        }

    async def calculate_buying_power(
        self,
        portfolio_id: str,
        segment: str = "EQUITY",
        is_intraday: bool = False,
    ) -> Dict[str, Decimal]:
        """
        Calculate buying power for new orders.
        
        SEBI-compliant buying power rules:
        - Delivery: available_cash (100% upfront)
        - Intraday: available_cash × leverage_factor (max ~5x, i.e., 20% margin)
        - Must account for:
          - Margin blocked in open positions
          - VAR + ELM (Value at Risk + Extreme Loss Margin)
          - Peak margin requirements
        
        Returns:
            Dict with:
            - available_cash: Liquid cash
            - margin_used: Blocked margin
            - free_margin: Available for new trades
            - max_order_size_delivery: Max order notional for delivery
            - max_order_size_intraday: Max order notional for intraday
        
        Args:
            portfolio_id: Portfolio ID
            segment: Market segment (EQUITY, FO, etc.)
            is_intraday: Whether calculating for intraday or delivery
        """
        db_manager = DBManager.get_instance()
        
        async with db_manager.session() as client:
            portfolio = await client.portfolio.find_unique(
                where={"id": portfolio_id},
                include={"positions": {"where": {"status": "open"}}}
            )
            
            if not portfolio:
                return self._empty_buying_power()
            
            available_cash = self._as_decimal(getattr(portfolio, "available_cash", 0))
            positions = getattr(portfolio, "positions", []) or []
            
            # Calculate margin used
            margin_used = self._calculate_margin_used(positions)
            free_margin = available_cash - margin_used
            
            # Buying power calculations
            # Delivery: 1x (100% upfront)
            max_order_size_delivery = free_margin
            
            # Intraday: ~5x leverage (20% margin)
            # In production, use broker-specific leverage limits
            leverage_factor = Decimal("5.0")
            max_order_size_intraday = free_margin * leverage_factor
            
            self.logger.info(
                "💰 Buying power for %s: cash=₹%.2f, margin_used=₹%.2f, free=₹%.2f, max_delivery=₹%.2f, max_intraday=₹%.2f",
                portfolio_id[:8],
                float(available_cash),
                float(margin_used),
                float(free_margin),
                float(max_order_size_delivery),
                float(max_order_size_intraday),
            )
            
            return {
                "available_cash": available_cash,
                "margin_used": margin_used,
                "free_margin": free_margin,
                "max_order_size_delivery": max_order_size_delivery,
                "max_order_size_intraday": max_order_size_intraday,
            }

    def _empty_buying_power(self) -> Dict[str, Decimal]:
        """Return empty buying power dict."""
        return {
            "available_cash": Decimal("0"),
            "margin_used": Decimal("0"),
            "free_margin": Decimal("0"),
            "max_order_size_delivery": Decimal("0"),
            "max_order_size_intraday": Decimal("0"),
        }
