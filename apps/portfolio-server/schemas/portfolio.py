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
    available_cash: Decimal
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
    realized_pnl: Decimal
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
    realized_pnl: Decimal
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
    llm_delay: Optional[str] = None  # LLM processing delay in ms or "N/A"
    trade_delay: Optional[str] = None  # Trade execution delay in ms or "N/A"
    agent_id: Optional[str] = None  # Trading agent ID
    agent_name: Optional[str] = None  # Trading agent name
    triggered_by: Optional[str] = None  # What triggered the trade (e.g., alpha signal, user)

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
    available_cash: Decimal
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


class SnapshotResponse(BaseModel):
    """Single snapshot data point for timeline charts"""
    snapshot_at: datetime
    current_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal


class SnapshotListResponse(BaseModel):
    """List of snapshots for timeline charts"""
    items: List[SnapshotResponse]
    total: int


class AllocationSnapshotResponse(BaseModel):
    """Allocation snapshot for tracking allocation weight and value over time"""
    id: str
    portfolio_allocation_id: str
    allocation_type: str
    current_value: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    snapshot_at: datetime

    class Config:
        from_attributes = True


class AllocationSnapshotListResponse(BaseModel):
    items: List[AllocationSnapshotResponse]
    total: int


class AllocationDashboardSummary(BaseModel):
    """Allocation summary for dashboard"""
    allocation_type: str
    target_weight: Decimal
    allocated_amount: Decimal
    available_cash: Decimal
    realized_pnl: Decimal
    pnl_percentage: Decimal


class RecentTradeSummary(BaseModel):
    """Recent trade summary for dashboard"""
    id: str
    symbol: str
    side: str
    quantity: int
    executed_price: Optional[Decimal] = None
    executed_at: Optional[datetime] = None
    realized_pnl: Optional[Decimal] = None
    llm_delay: Optional[str] = None  # LLM processing delay in ms or "N/A"
    trade_delay: Optional[str] = None  # Trade execution delay in ms or "N/A"


class PortfolioDashboardResponse(BaseModel):
    """Main portfolio dashboard data"""
    portfolio_id: str
    portfolio_name: str
    investment_amount: Decimal
    available_cash: Decimal
    total_realized_pnl: Decimal
    total_positions: int
    active_agents: int
    allocations: List[AllocationDashboardSummary]
    recent_trades: List[RecentTradeSummary]


class AgentDashboardResponse(BaseModel):
    """Agent-specific dashboard data"""
    agent_id: str
    agent_name: str
    agent_type: str
    portfolio_id: str
    status: str
    current_value: Decimal
    realized_pnl: Decimal
    positions_count: int
    positions: List[PositionSummary]
    allocation: Optional[PortfolioAllocationSummary] = None
    performance_metrics: Optional[dict] = None
    recent_trades: List[TradeSummary]
