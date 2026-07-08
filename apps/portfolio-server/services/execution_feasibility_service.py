import math
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio

from config import (
    MAX_ORDER_SIZE_PCT_OF_ADV,
    LIVE_LIQUIDITY_BLOCK,
    SLIPPAGE_BASE_SPREAD_BPS,
    SLIPPAGE_IMPACT_FACTOR,
    DEFAULT_FREEZE_QUANTITY,
    DEFAULT_FALLBACK_ADV,
    DEMO_MODE,
)
from market_data import get_market_data_service

logger = logging.getLogger(__name__)

# Known freeze quantity limits for major symbols (indices/F&O)
INDEX_FREEZE_LIMITS = {
    "NIFTY": 1800,
    "BANKNIFTY": 600,
    "FINNIFTY": 1200,
    "MIDCPNIFTY": 2800,
    "NIFTYNXT50": 600,
}

@dataclass
class FeasibilityResult:
    is_feasible: bool
    adjusted_quantity: int
    warnings: List[str]
    blocking_reason: Optional[str] = None
    slippage_bps: float = 0.0
    simulated_price: Optional[float] = None
    naive_price: Optional[float] = None


class ExecutionFeasibilityService:
    """
    Dedicated service to perform safety and realism checks for trade execution.
    Handles liquidity (ADV), order size limits (freeze quantity), and delivery-only classification (T2T).
    """

    def __init__(self, logger_instance: Optional[logging.Logger] = None):
        self.logger = logger_instance or logger
        self.market_service = get_market_data_service()
        # In-memory ADV cache: symbol -> (adv_value, expiry_time)
        self._adv_cache: Dict[str, tuple] = {}

    async def get_average_daily_volume(self, symbol: str) -> float:
        """
        Fetch and calculate 30-day Average Daily Volume (ADV) for the symbol.
        Uses cached values if available and not expired.
        """
        normalized = self.market_service._normalize_symbol(symbol).upper()
        now = datetime.utcnow()

        # Check cache
        if normalized in self._adv_cache:
            adv, expiry = self._adv_cache[normalized]
            if now < expiry:
                return adv

        # Fetch historical daily candles
        todate = now.strftime("%Y-%m-%d %H:%M")
        fromdate = (now - timedelta(days=45)).strftime("%Y-%m-%d %H:%M")

        try:
            self.logger.info("Fetching historical daily candles to calculate ADV for %s", normalized)
            # Run the synchronous HTTP call in an executor thread to prevent blocking
            candles = await asyncio.to_thread(
                self.market_service.get_historical_candles,
                symbol=normalized,
                interval="ONE_DAY",
                fromdate=fromdate,
                todate=todate,
            )

            volumes = [candle["volume"] for candle in candles if isinstance(candle, dict) and "volume" in candle]
            if volumes:
                adv = sum(volumes) / len(volumes)
                self.logger.info("Calculated 30-day ADV for %s: %s", normalized, adv)
            else:
                self.logger.warning("No daily volumes found for %s, using fallback ADV", normalized)
                adv = float(DEFAULT_FALLBACK_ADV)
        except Exception as e:
            self.logger.error("Failed to fetch historical candles for %s ADV: %s. Using fallback ADV.", normalized, e)
            adv = float(DEFAULT_FALLBACK_ADV)

        # Cache calculated ADV for 24 hours
        self._adv_cache[normalized] = (adv, now + timedelta(hours=24))
        return adv

    def is_t2t_symbol(self, symbol: str) -> bool:
        """
        Check if the symbol is in the Trade-to-Trade (T2T) segment.
        T2T stocks trade with series ending in '-BE' in the Angel One scrip master.
        """
        try:
            token_info = self.market_service._get_token_info(symbol)
            if not token_info:
                return False
            matched_key = token_info.get("_matched_key", "").upper()
            symbol_name = token_info.get("symbol", "").upper()
            return matched_key.endswith("-BE") or symbol_name.endswith("-BE")
        except Exception as e:
            self.logger.error("Error looking up T2T classification for %s: %s", symbol, e)
            return False

    def get_freeze_quantity(self, symbol: str) -> int:
        """
        Lookup freeze quantity limit for a symbol.
        Checks known indices first, then falls back to config defaults.
        """
        upper = symbol.upper()
        # Check indices or derivative underlyings
        for index_name, limit in INDEX_FREEZE_LIMITS.items():
            if index_name in upper:
                return limit
        return DEFAULT_FREEZE_QUANTITY

    async def check_execution_feasibility(
        self,
        symbol: str,
        quantity: int,
        side: str,
        intended_holding: str = "delivery",
        price: Optional[float] = None,
    ) -> FeasibilityResult:
        """
        Perform safety and realism checks before execution or signal dispatch.
        
        Args:
            symbol: Symbol being traded (e.g., RELIANCE)
            quantity: Intended order quantity
            side: BUY, SELL, SHORT_SELL, COVER
            intended_holding: "intraday" or "delivery" (T2T check)
            price: Naive execution price (used for slippage calculation)
        """
        warnings = []
        is_feasible = True
        blocking_reason = None
        adjusted_quantity = quantity

        # ==========================================
        # 1. TRADE-TO-TRADE (T2T) SEGMENT CHECK
        # ==========================================
        is_t2t = self.is_t2t_symbol(symbol)
        if is_t2t:
            if intended_holding.lower() == "intraday":
                self.logger.warning("Blocking trade: %s is a T2T stock and strategy intends intraday holding", symbol)
                return FeasibilityResult(
                    is_feasible=False,
                    adjusted_quantity=quantity,
                    warnings=["Intraday square-off is not allowed on Trade-to-Trade (T2T) stocks."],
                    blocking_reason="T2T_INTRADAY_RESTRICTED",
                )
            else:
                warnings.append(f"Symbol {symbol} is in T2T segment. Trade is allowed for delivery/overnight holding.")

        # ==========================================
        # 2. FREEZE QUANTITY / MAX ORDER SIZE CHECK
        # ==========================================
        freeze_limit = self.get_freeze_quantity(symbol)
        if quantity > freeze_limit:
            self.logger.warning("Blocking trade: quantity %d exceeds freeze limit of %d for %s", quantity, freeze_limit, symbol)
            return FeasibilityResult(
                is_feasible=False,
                adjusted_quantity=quantity,
                warnings=[f"Order quantity {quantity} exceeds exchange freeze limit of {freeze_limit}."],
                blocking_reason="EXCEEDS_FREEZE_QUANTITY",
            )

        # ==========================================
        # 3. LIQUIDITY & SLIPPAGE SIMULATION (ADV)
        # ==========================================
        adv = await self.get_average_daily_volume(symbol)
        adv = max(adv, 1.0) # Avoid division by zero
        order_pct_of_adv = (quantity / adv) * 100.0

        slippage_bps = 0.0
        simulated_price = price
        naive_price = price

        if order_pct_of_adv >= MAX_ORDER_SIZE_PCT_OF_ADV:
            warning_msg = f"Order size ({quantity}) is {order_pct_of_adv:.2f}% of ADV ({int(adv)}), exceeding threshold of {MAX_ORDER_SIZE_PCT_OF_ADV}%"
            warnings.append(warning_msg)
            
            # Apply warnings or blocks based on Demo/Live mode
            if DEMO_MODE:
                self.logger.warning("DEMO MODE WARNING: %s. Trade will still simulate.", warning_msg)
            else:
                if LIVE_LIQUIDITY_BLOCK:
                    self.logger.warning("LIVE MODE BLOCK: %s. Blocking execution.", warning_msg)
                    return FeasibilityResult(
                        is_feasible=False,
                        adjusted_quantity=quantity,
                        warnings=[warning_msg],
                        blocking_reason="LIQUIDITY_LIMIT_EXCEEDED",
                    )
                else:
                    self.logger.warning("LIVE MODE WARNING (Unblocked): %s. Proceeding with explicit warning.", warning_msg)

        # Always calculate slippage for Demo Mode price realism when quantity is a meaningful fraction
        # Let's apply slippage model: slippage = base_spread_bps + impact_factor * sqrt(quantity / ADV)
        if price is not None:
            # We scale impact by sqrt(quantity/ADV)
            slippage_bps = SLIPPAGE_BASE_SPREAD_BPS + SLIPPAGE_IMPACT_FACTOR * math.sqrt(quantity / adv)
            slippage_fraction = slippage_bps / 10000.0

            # Slippage is ALWAYS against the trader:
            # BUY/COVER -> higher price (worse)
            # SELL/SHORT_SELL -> lower price (worse)
            if side.upper() in {"BUY", "COVER"}:
                simulated_price = price * (1.0 + slippage_fraction)
            else:
                simulated_price = price * (1.0 - slippage_fraction)

            self.logger.info(
                "Slippage applied to %s (%s): naive ₹%.2f -> realistic ₹%.2f (slippage: %.2f bps)",
                symbol, side, price, simulated_price, slippage_bps
            )

        return FeasibilityResult(
            is_feasible=is_feasible,
            adjusted_quantity=adjusted_quantity,
            warnings=warnings,
            blocking_reason=blocking_reason,
            slippage_bps=slippage_bps,
            simulated_price=simulated_price,
            naive_price=naive_price,
        )
