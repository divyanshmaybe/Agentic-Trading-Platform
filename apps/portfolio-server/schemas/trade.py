from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, PositiveInt, condecimal, model_validator


Price = condecimal(gt=0, max_digits=20, decimal_places=4)


class TradeRequest(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, max_length=32)
    exchange: Optional[str] = Field(default=None, max_length=32)
    segment: Optional[str] = Field(default=None, max_length=32)
    side: Literal["BUY", "SELL", "SHORT_SELL"]
    order_type: Literal["market", "limit", "stop", "stop_loss", "take_profit"]
    quantity: PositiveInt
    limit_price: Optional[Price] = None
    trigger_price: Optional[Price] = None
    trade_type: Optional[str] = Field(default="cash", max_length=32)
    customer_id: Optional[str] = Field(default=None, max_length=64)
    source: Optional[str] = Field(default=None, max_length=64)
    metadata: Optional[dict] = None
    auto_sell_after: Optional[int] = Field(default=None, ge=1, description="Auto-sell after this many seconds (only for BUY orders)")
    allocation_id: Optional[str] = Field(default=None, description="Portfolio allocation ID (will auto-detect liquid agent if not provided)")

    @model_validator(mode="after")
    def _validate_order_constraints(self) -> "TradeRequest":
        if self.order_type == "market":
            if self.limit_price is not None or self.trigger_price is not None:
                raise ValueError("market orders cannot include limit or trigger prices")
        elif self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        elif self.order_type in {"stop", "stop_loss", "take_profit"} and self.trigger_price is None:
            raise ValueError("stop and take-profit orders require trigger_price")
        return self


class TradeCreate(BaseModel):
    organization_id: str = Field(..., min_length=1)
    portfolio_id: str = Field(..., min_length=1)
    customer_id: str = Field(..., min_length=1)
    trade_type: Optional[str] = Field(default="cash", max_length=32)
    symbol: str = Field(..., min_length=1, max_length=32)
    exchange: Optional[str] = Field(default=None, max_length=32)
    segment: Optional[str] = Field(default=None, max_length=32)
    side: Literal["BUY", "SELL", "SHORT_SELL"]
    order_type: Literal["market", "limit", "stop", "stop_loss", "take_profit"]
    quantity: PositiveInt
    limit_price: Optional[Price] = None
    trigger_price: Optional[Price] = None
    source: Optional[str] = Field(default=None, max_length=64)
    metadata: Optional[dict] = None
    auto_sell_after: Optional[int] = Field(default=None, ge=1, description="Auto-sell after this many seconds (only for BUY orders)")
    allocation_id: Optional[str] = Field(default=None, description="Portfolio allocation ID")

    model_config = {
        "json_schema_extra": {
            "example": {
                "organization_id": "org-001",
                "portfolio_id": "portfolio-xyz",
                "customer_id": "cust-123",
                "symbol": "AAPL",
                "exchange": "NASDAQ",
                "segment": "EQUITY",
                "side": "BUY",
                "order_type": "market",
                "quantity": 10,
                "source": "automation",
            }
        }
    }


class TradeSummary(BaseModel):
    id: str
    symbol: str
    side: str
    order_type: str
    status: str
    quantity: int
    price: Optional[Decimal] = None
    execution_time: Optional[datetime] = None
    trade_delay_ms: Optional[int] = Field(default=None, description="Trade execution delay in milliseconds")
    llm_delay_ms: Optional[int] = Field(default=None, description="LLM processing delay in milliseconds")

    class Config:
        from_attributes = True


class PortfolioSnapshot(BaseModel):
    id: str
    available_cash: Decimal
    current_value: Decimal
    updated_at: datetime

    class Config:
        from_attributes = True


class TradeResponse(BaseModel):
    success: bool
    message: str
    trades: List[TradeSummary]
    pending_orders: int
    portfolio: PortfolioSnapshot
