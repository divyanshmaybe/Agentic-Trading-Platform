from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


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

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
