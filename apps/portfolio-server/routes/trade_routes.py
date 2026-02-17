from __future__ import annotations

import os
import sys

from fastapi import APIRouter, Depends, Request
from prisma import Prisma

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "../../..")
MIDDLEWARE_PATH = os.path.join(PROJECT_ROOT, "middleware/py")
if MIDDLEWARE_PATH not in sys.path:
    sys.path.insert(0, MIDDLEWARE_PATH)

from controllers.trade_controller import TradeController
from db import prisma_client
from schemas import (
    TradeRequest,
    TradeResponse,
)
from utils.auth import get_authenticated_user

router = APIRouter(prefix="/trades", tags=["Trades"])


def get_trade_controller(prisma: Prisma = Depends(prisma_client)) -> TradeController:
    return TradeController(prisma)


@router.post("/", response_model=TradeResponse)
async def create_trade(
    payload: TradeRequest,
    request: Request,
    controller: TradeController = Depends(get_trade_controller),
    user: dict = Depends(get_authenticated_user),
) -> TradeResponse:
    return await controller.submit_trade(payload, request, user)
