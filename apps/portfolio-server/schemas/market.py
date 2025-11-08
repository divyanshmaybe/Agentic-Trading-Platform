from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CandleData(BaseModel):
    """Individual OHLCV candle data point."""
    timestamp: str = Field(..., description="ISO format timestamp or Unix timestamp")
    open: Decimal = Field(..., gt=Decimal("0"), description="Opening price")
    high: Decimal = Field(..., gt=Decimal("0"), description="Highest price")
    low: Decimal = Field(..., gt=Decimal("0"), description="Lowest price")
    close: Decimal = Field(..., gt=Decimal("0"), description="Closing price")
    volume: Decimal = Field(..., ge=Decimal("0"), description="Trading volume")

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}


class MarketQuote(BaseModel):
    symbol: str
    price: Decimal = Field(..., gt=Decimal("0"))
    provider: str
    source: str


class MarketQuoteResponse(BaseModel):
    data: List[MarketQuote]
    count: int
    requested_at: datetime
    missing: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}

