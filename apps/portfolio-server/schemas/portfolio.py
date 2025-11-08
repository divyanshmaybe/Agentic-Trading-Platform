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
