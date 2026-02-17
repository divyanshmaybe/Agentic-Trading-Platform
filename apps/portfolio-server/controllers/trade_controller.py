from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List

from fastapi import HTTPException, Request, status
from prisma import Prisma

from schemas import (
    PortfolioSnapshot,
    TradeCreate,
    TradeRequest,
    TradeResponse,
    TradeSummary,
)
from services.trade_engine import TradeEngine
from services.trade_execution_service import TradeExecutionService
from services.trade_validation_service import TradeValidationService

logger = logging.getLogger(__name__)


class TradeController:
    """Coordinates trade submission flow and integrates with the trade engine."""

    def __init__(self, prisma: Prisma) -> None:
        self.prisma = prisma
        self.engine = TradeEngine(prisma)

    async def submit_trade(self, payload: TradeRequest, request: Request, user: Dict) -> TradeResponse:
        import time
        request_start_time = time.time()  # Track request start time for trade_delay calculation
        
        organization_id = user.get("organization_id")
        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated user is not linked to an organization",
            )

        portfolio = await self.prisma.portfolio.find_unique(
            where={"id": payload.portfolio_id},
            include={
                "agents": {
                    "where": {"agent_type": "liquid", "status": "active"},
                    "include": {"allocation": True}
                }
            }
        )
        if not portfolio:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

        if portfolio.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Portfolio access denied")

        resolved_customer = self._resolve_customer(payload, portfolio, user)
        role = (user.get("role") or "").lower()
        if role not in {"admin", "staff"} and resolved_customer not in {user.get("id"), user.get("customer_id")}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not permitted to trade on behalf of this customer",
            )

        # Find active liquid agent allocation
        allocation_id = payload.allocation_id
        agent_id = None
        agent_type = None
        liquid_agent = None
        
        if not allocation_id:
            # Auto-detect liquid agent
            liquid_agents = [a for a in (portfolio.agents or []) if a.agent_type == "liquid" and a.status == "active"]
            if not liquid_agents:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No active liquid trading agent found for this portfolio. Please activate liquid agent first."
                )
            
            liquid_agent = liquid_agents[0]
            agent_id = liquid_agent.id
            agent_type = liquid_agent.agent_type
            
            # Check if agent is paused
            if liquid_agent.status == "paused":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Liquid trading agent is currently paused. Please resume the agent before trading."
                )
            
            if not liquid_agent.allocation:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Liquid agent has no allocation configured"
                )
            
            allocation_id = liquid_agent.allocation.id
            logger.info(
                "✅ Auto-detected liquid agent %s with allocation %s for manual trade",
                agent_id,
                allocation_id
            )
        else:
            # Verify allocation exists and get agent info
            allocation = await self.prisma.portfolioallocation.find_unique(
                where={"id": allocation_id},
                include={"tradingAgent": True}
            )
            if not allocation:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid allocation_id"
                )
            if allocation.portfolio_id != payload.portfolio_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Allocation does not belong to specified portfolio"
                )
            if allocation.tradingAgent:
                liquid_agent = allocation.tradingAgent
                agent_id = liquid_agent.id
                agent_type = liquid_agent.agent_type
                
                # Check if agent is paused
                if liquid_agent.status == "paused":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Trading agent is currently paused. Please resume the agent before trading."
                    )

        # Check available cash in allocation
        allocation = await self.prisma.portfolioallocation.find_unique(where={"id": allocation_id})
        if not allocation:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to fetch allocation details"
            )
        
        available_cash = Decimal(str(allocation.available_cash))
        if available_cash <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient cash in liquid allocation: ₹{available_cash:.2f}"
            )
        
        # Use TradeValidationService for pre-trade validation
        validation_service = TradeValidationService(logger=logger)
        
        # Get current price for validation using async method
        from market_data import await_live_price
        
        try:
            # Try to get live price with timeout
            price = await await_live_price(payload.symbol, timeout=15.0)
        except RuntimeError:
            # Fallback: register symbol and try again
            from market_data import get_market_data_service
            market_data = get_market_data_service()
            market_data.register_symbol(payload.symbol)
            
            # Try getting cached price first
            price = market_data.get_latest_price(payload.symbol)
            if price is None:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Unable to fetch current price for {payload.symbol}. Please try again."
                )
        
        price_decimal = Decimal(str(price))
        
        # Validate based on order side
        if payload.side == "BUY":
            validation_result = await validation_service.validate_buy_order(
                portfolio_id=payload.portfolio_id,
                agent_id=agent_id,
                symbol=payload.symbol,
                quantity=payload.quantity,
                price=price_decimal,
            )
            
            if not validation_result["valid"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=validation_result["reason"]
                )
        
        elif payload.side == "SELL":
            validation_result = await validation_service.validate_sell_order(
                portfolio_id=payload.portfolio_id,
                agent_id=agent_id,
                symbol=payload.symbol,
                quantity=payload.quantity,
            )
            
            if not validation_result["valid"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=validation_result["reason"]
                )

        trade_input = self._build_trade_create(payload, request, user, organization_id, resolved_customer, allocation_id)

        # Use TradeExecutionService for proper agent-aware trade execution
        try:
            trade_service = TradeExecutionService(logger=logger)
            
            # Build job_row similar to NSE pipeline
            from market_data import await_live_price, get_market_data_service
            
            # Get current price using async method (already fetched above, but get latest)
            try:
                current_price = await await_live_price(payload.symbol, timeout=10.0)
            except RuntimeError:
                # Use the price from validation
                current_price = float(price_decimal)
            
            # Calculate allocated capital (trade cost)
            import uuid
            allocated_capital = float(current_price) * float(payload.quantity)
            
            job_row = {
                "request_id": str(uuid.uuid4()),  # Generate unique request ID
                "user_id": user.get("id") or resolved_customer,  # Required field
                "organization_id": organization_id,
                "portfolio_id": payload.portfolio_id,
                "customer_id": resolved_customer,
                "symbol": payload.symbol,
                "side": payload.side,
                "quantity": payload.quantity,
                "reference_price": float(current_price),
                "exchange": payload.exchange or "NSE",
                "segment": payload.segment or "EQUITY",
                "agent_id": agent_id,
                "agent_type": agent_type,
                "allocation_id": allocation_id,
                "triggered_by": "manual_api_trade",
                "confidence": 1.0,  # Manual trades have 100% confidence
                "allocated_capital": allocated_capital,  # Required for event
                # NO TP/SL for manual trades - user manages exits manually
                "take_profit_pct": None,
                "stop_loss_pct": None,
                "explanation": f"Manual {payload.side} order via API",
                "filing_time": "",
                "generated_at": "",
                # auto_sell_after: seconds until auto-sell (for manual trades with auto-sell enabled)
                "auto_sell_after": payload.auto_sell_after,
            }
            
            # Persist trade execution log
            job_rows = [job_row]
            events = await trade_service.persist_and_publish(job_rows, publish_kafka=False)
            
            if not events or len(events) == 0:
                raise RuntimeError("Failed to create trade execution log")
            
            event = events[0]
            trade_id = event.trade_id
            
            # Execute trade immediately in simulation mode
            result = await trade_service.execute_trade(trade_id, simulate=True)
            
            logger.info(
                "✅ Manual trade executed: Trade %s | Agent %s (%s) | %s %s x %d @ ₹%.2f | Status: %s",
                trade_id,
                agent_id or "unknown",
                agent_type or "unknown",
                payload.side,
                payload.symbol,
                payload.quantity,
                float(current_price),
                result.get("status", "unknown"),
            )
            
            # Set auto_sell_at if requested (only for BUY orders)
            # The streaming_order_monitor will handle execution when time expires
            if payload.auto_sell_after and payload.side == "BUY":
                from datetime import datetime, timedelta
                auto_sell_at = datetime.utcnow() + timedelta(seconds=payload.auto_sell_after)
                
                await self.prisma.trade.update(
                    where={"id": trade_id},
                    data={"auto_sell_at": auto_sell_at}  # Pass datetime directly, not string
                )
                
                logger.info(
                    "🕒 Auto-sell scheduled for trade %s at %s (%d seconds from now, streaming monitor will handle)",
                    trade_id,
                    auto_sell_at.isoformat(),
                    payload.auto_sell_after
                )
            
            # Calculate trade_delay_ms: time from request received to trade stored in DB
            trade_delay_ms = int((time.time() - request_start_time) * 1000)
            
            # Update TradeExecutionLog with trade_delay
            if trade_id:
                await self.prisma.tradeexecutionlog.update_many(
                    where={"trade_id": trade_id},
                    data={"trade_delay": trade_delay_ms}
                )
            
            # Fetch completed trade with execution log
            trade = await self.prisma.trade.find_unique(
                where={"id": trade_id},
                include={"executions": True}
            )
            if not trade:
                raise RuntimeError("Trade execution completed but trade record not found")
            
            # Extract llm_delay_ms from metadata
            metadata = trade.metadata
            if isinstance(metadata, str):
                try:
                    import json
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            elif not isinstance(metadata, dict):
                metadata = {}
            llm_delay_ms = metadata.get("llm_delay_ms")
            
            summaries = [TradeSummary(
                id=trade.id,
                symbol=trade.symbol,
                side=trade.side,
                order_type=trade.order_type,
                status=trade.status,
                quantity=trade.quantity,
                price=trade.price,
                execution_time=trade.execution_time,
                trade_delay_ms=trade_delay_ms,
                llm_delay_ms=llm_delay_ms,
            )]
            
            # Build portfolio snapshot
            portfolio_snapshot = await self._build_portfolio_snapshot_for_agent(
                payload.portfolio_id,
                allocation_id
            )
            
            return TradeResponse(
                success=True,
                message="Trade executed via liquid agent",
                trades=summaries,
                pending_orders=0,
                portfolio=portfolio_snapshot,
            )
            
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    @staticmethod
    def _resolve_customer(payload: TradeRequest, portfolio, user: Dict) -> str:
        resolved = (
            payload.customer_id
            or getattr(portfolio, "customer_id", None)
            or user.get("customer_id")
            or user.get("id")
        )
        if not resolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to resolve customer for trade",
            )
        return resolved

    @staticmethod
    def _build_trade_create(
        payload: TradeRequest,
        request: Request,
        user: Dict,
        organization_id: str,
        customer_id: str,
        allocation_id: str,
    ) -> TradeCreate:
        metadata: Dict = {
            **(payload.metadata or {}),
            "requested_by": user.get("id"),
            "requested_role": user.get("role"),
            "ip": request.client.host if request.client else None,
        }

        return TradeCreate(
            organization_id=organization_id,
            portfolio_id=payload.portfolio_id,
            customer_id=customer_id,
            trade_type=payload.trade_type,
            symbol=payload.symbol,
            exchange=payload.exchange,
            segment=payload.segment,
            side=payload.side,
            order_type=payload.order_type,
            quantity=payload.quantity,
            limit_price=payload.limit_price,
            trigger_price=payload.trigger_price,
            source=payload.source or "user",
            metadata=metadata,
            auto_sell_after=payload.auto_sell_after,
            allocation_id=allocation_id,
        )

    async def _build_portfolio_snapshot_for_agent(
        self,
        portfolio_id: str,
        allocation_id: str,
    ) -> PortfolioSnapshot:
        """Build portfolio snapshot including allocation-level cash and positions."""
        from market_data import get_market_data_service
        
        market_data = get_market_data_service()
        
        # Get allocation details
        allocation = await self.prisma.portfolioallocation.find_unique(
            where={"id": allocation_id},
            include={
                "tradingAgent": {"include": {"positions": {"where": {"status": "open"}}}}
            }
        )
        
        if not allocation:
            raise ValueError(f"Allocation {allocation_id} not found")
        
        available_cash = Decimal(str(allocation.available_cash))
        current_value = available_cash
        
        # Add value of open positions for this agent
        if allocation.tradingAgent and allocation.tradingAgent.positions:
            for position in allocation.tradingAgent.positions:
                if position.status == "open":
                    try:
                        price = market_data.get_latest_price(position.symbol)
                        if price is None:
                            price = position.average_price
                        position_value = Decimal(str(price)) * Decimal(str(position.quantity))
                        current_value += position_value
                    except Exception as exc:
                        logger.warning(
                            "Failed to calculate position value for %s: %s",
                            position.symbol,
                            exc
                        )
        
        return PortfolioSnapshot(
            id=allocation_id,
            available_cash=available_cash,
            current_value=current_value,
            updated_at=allocation.updated_at,
        )

    @staticmethod
    def _summaries_from_result(trades: List[Dict]) -> List[TradeSummary]:
        return [
            TradeSummary(
                id=trade_dict["id"],
                symbol=trade_dict["symbol"],
                side=trade_dict["side"],
                order_type=trade_dict["order_type"],
                status=trade_dict["status"],
                quantity=trade_dict["quantity"],
                price=trade_dict.get("price"),
                execution_time=trade_dict.get("execution_time"),
                trade_delay_ms=trade_dict.get("trade_delay_ms"),
                llm_delay_ms=trade_dict.get("llm_delay_ms"),
            )
            for trade_dict in trades
        ]
