"""Market data routes exposing live quotes via the shared price stream."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from controllers.market_controller import MarketController
from schemas import MarketQuoteResponse
from utils.auth import get_authenticated_user

router = APIRouter(prefix="/market", tags=["Market"])


def get_market_controller() -> MarketController:
    return MarketController()


@router.get("/quotes", response_model=MarketQuoteResponse)
async def get_market_quotes(
    symbols: List[str] = Query(..., alias="symbols"),
    candle: Optional[str] = Query(None, description="Candle interval: 1h, 1d, 5d, 7d, 1y"),
    start: Optional[datetime] = Query(None, description="Start datetime for candle range"),
    end: Optional[datetime] = Query(None, description="End datetime for candle range"),
    _: dict = Depends(get_authenticated_user),
    controller: MarketController = Depends(get_market_controller),
) -> MarketQuoteResponse:
    """Get live market quotes for the given symbols."""
    return await controller.get_quotes(symbols, candle=candle, start=start, end=end)


@router.get("/subscribed-symbols")
async def get_subscribed_symbols(
    _: dict = Depends(get_authenticated_user),
    controller: MarketController = Depends(get_market_controller),
) -> dict:
    """Get list of all currently subscribed symbols from the WebSocket stream."""
    return controller.get_subscribed_symbols()

