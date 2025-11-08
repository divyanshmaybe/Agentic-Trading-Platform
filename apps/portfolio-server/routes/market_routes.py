"""Market data routes exposing live quotes via the shared price stream."""

from __future__ import annotations

from typing import List

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
    _: dict = Depends(get_authenticated_user),
    controller: MarketController = Depends(get_market_controller),
) -> MarketQuoteResponse:
    """Get live market quotes for the given symbols."""
    return await controller.get_quotes(symbols)

