from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class PortfolioResponse(BaseModel):
    id: str
    organization_id: str
    customer_id: str
    portfolio_name: str
    investment_amount: Decimal
    current_value: Decimal
    investment_horizon_years: int
    expected_return_target: Decimal
    risk_tolerance: str
    liquidity_needs: str
    rebalancing_frequency: Optional[dict] = None
    allocation_strategy: Optional[dict] = None
    metadata: Optional[dict] = None

    class Config:
        from_attributes = True


class HoldingResponse(BaseModel):
    portfolio_id: str
    position_id: str
    symbol: str
    exchange: str
    segment: str
    quantity: int
    average_buy_price: Decimal
    current_price: Decimal
    current_value: Decimal
    pnl: Decimal
    pnl_percentage: Decimal
    position_type: str
    status: str
    metadata: Optional[dict] = None
    last_updated: datetime

    class Config:
        from_attributes = True


class PositionSummary(BaseModel):
    id: str
    portfolio_id: str
    symbol: str
    exchange: str
    segment: str
    quantity: int
    average_buy_price: Decimal
    current_price: Decimal
    current_value: Decimal
    pnl: Decimal
    pnl_percentage: Decimal
    position_type: str
    status: str
    updated_at: datetime

    class Config:
        from_attributes = True


class PositionListResponse(BaseModel):
    items: List[PositionSummary]
    page: int
    limit: int
    total: int


class TradeSummary(BaseModel):
    id: str
    portfolio_id: str
    symbol: str
    side: str
    order_type: str
    quantity: int
    executed_quantity: int
    executed_price: Optional[Decimal] = None
    status: str
    net_amount: Optional[Decimal] = None
    trade_type: str
    created_at: datetime
    execution_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class TradeListResponse(BaseModel):
    items: List[TradeSummary]
    page: int
    limit: int
    total: int


class TradingAgentSummary(BaseModel):
    id: str
    portfolio_id: Optional[str]
    portfolio_allocation_id: str
    agent_type: str
    agent_name: str
    status: str
    strategy_config: Optional[dict] = None
    performance_metrics: Optional[dict] = None
    last_executed_at: Optional[datetime] = None
    error_count: int
    last_error_message: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TradingAgentListResponse(BaseModel):
    items: List[TradingAgentSummary]
    total: int


class PortfolioAllocationSummary(BaseModel):
    id: str
    portfolio_id: str
    allocation_type: str
    target_weight: Decimal
    current_weight: Decimal
    allocated_amount: Decimal
    current_value: Decimal
    expected_return: Optional[Decimal] = None
    expected_risk: Optional[Decimal] = None
    regime: Optional[str] = None
    pnl: Decimal
    pnl_percentage: Decimal
    drift_percentage: Decimal
    requires_rebalancing: bool
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    trading_agent: Optional[TradingAgentSummary] = None

    class Config:
        from_attributes = True


class PortfolioAllocationListResponse(BaseModel):
    items: List[PortfolioAllocationSummary]
    total: int
