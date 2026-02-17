"""
Helpers for preparing automated trade execution payloads for the NSE signal pipeline.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, List, Mapping, Optional, Sequence

import json
import httpx
import os
import asyncio

DEFAULT_TAKE_PROFIT_PCT = 0.03
DEFAULT_STOP_LOSS_PCT = 0.01


async def fetch_market_price_via_http(symbol: str, timeout: float = 10.0) -> Optional[Decimal]:
    """
    Fetch market price via HTTP from portfolio-server's market API.
    
    This is used by Celery workers to avoid creating multiple WebSocket connections.
    The portfolio-server maintains a single WebSocket connection and serves prices via HTTP.
    
    Args:
        symbol: Stock symbol (e.g., 'RELIANCE', 'TCS')
        timeout: HTTP request timeout in seconds
        
    Returns:
        Price as Decimal, or None if unavailable
    """
    portfolio_server_url = os.getenv("PORTFOLIO_SERVER_URL", "http://portfolio_server:8000")
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{portfolio_server_url}/api/market/quotes",
                params={"symbols": symbol}
            )
            
            if response.status_code != 200:
                logging.getLogger(__name__).warning(
                    "Market API returned status %d for %s", 
                    response.status_code, 
                    symbol
                )
                return None
            
            data = response.json()
            quotes = data.get("data", [])
            
            if not quotes:
                logging.getLogger(__name__).warning(
                    "No market data returned for %s", 
                    symbol
                )
                return None
            
            # Get first quote (we only requested one symbol)
            quote = quotes[0]
            price = quote.get("price")
            
            if price is None:
                logging.getLogger(__name__).warning(
                    "Price is None in market data for %s", 
                    symbol
                )
                return None
            
            return Decimal(str(price))
            
    except httpx.TimeoutException:
        logging.getLogger(__name__).warning(
            "Timeout fetching market price for %s via HTTP", 
            symbol
        )
        return None
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Failed to fetch market price for %s via HTTP: %s", 
            symbol, 
            exc
        )
        return None


def get_allocation(capital: float, confidence: float) -> float:
    """
    Assign portfolio allocation based on model confidence tiers.

    Args:
        capital: Current portfolio value.
        confidence: Model confidence score (0–1).

    Returns:
        Allocated capital for the trade.
    """
    # Use Pathway's conditional logic for Pathway expressions
    import pathway as pw
    if isinstance(confidence, pw.ColumnExpression):
        # Pathway expression - use conditional logic
        fraction = pw.if_else(
            confidence > 0.8,
            0.40,  # 40% for high confidence (>0.8)
            pw.if_else(
                confidence > 0.49,
                0.25,  # 25% for medium confidence (>0.49)
                0.0  # 0% for low confidence
            )
        )
        return capital * fraction
    else:
        # Regular Python values
        if confidence > 0.8:
            fraction = 0.40
        elif confidence > 0.49:
            fraction = 0.25
        else:
            fraction = 0.0
        return capital * fraction


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, (int,)):
        return int(value)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalise_price(price: Any) -> float:
    as_float = _safe_float(price, 0.0)
    if as_float <= 0:
        return 0.0
    return round(as_float, 4)


@dataclass
class TradeSignal:
    """Represents a trading signal emitted from the NSE filings pipeline."""

    signal_id: str
    symbol: str
    signal: int
    confidence: float
    explanation: str
    filing_time: str
    generated_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioSnapshot:
    """Portfolio snapshot for trade allocation purposes."""

    portfolio_id: str
    portfolio_name: str
    user_id: str
    organization_id: Optional[str]
    customer_id: Optional[str]
    current_value: float
    investment_amount: float
    cash_available: float
    metadata: Mapping[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    agent_status: Optional[str] = None
    agent_metadata: Mapping[str, Any] = field(default_factory=dict)
    agent_config: Mapping[str, Any] = field(default_factory=dict)

    @property
    def capital_base(self) -> float:
        base_candidates = [
            self.cash_available,
            self.current_value,
            self.investment_amount,
        ]
        for value in base_candidates:
            numeric = _safe_float(value, 0.0)
            if numeric > 0:
                return numeric
        return 0.0


@dataclass
class TradeExecutionPayload:
    """Payload passed to the Pathway trade execution pipeline."""

    request_id: str
    signal_id: str
    signal: int
    user_id: str
    portfolio_id: str
    portfolio_name: str
    organization_id: Optional[str]
    customer_id: Optional[str]
    symbol: str
    confidence: float
    explanation: str
    filing_time: str
    generated_at: datetime
    capital: float
    reference_price: float
    take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT
    metadata: Mapping[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    agent_type: Optional[str] = None
    agent_status: Optional[str] = None
    agent_config: Mapping[str, Any] = field(default_factory=dict)
    agent_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_event(self) -> Mapping[str, Any]:
        """Serialise payload for queue-backed Pathway subject."""

        return {
            "request_id": self.request_id,
            "payload": json.dumps(
                {
                    "request_id": self.request_id,
                    "signal_id": self.signal_id,
                    "signal": self.signal,
                    "user_id": self.user_id,
                    "portfolio_id": self.portfolio_id,
                    "portfolio_name": self.portfolio_name,
                    "organization_id": self.organization_id,
                    "customer_id": self.customer_id,
                    "symbol": self.symbol,
                    "confidence": float(self.confidence),
                    "explanation": self.explanation,
                    "filing_time": self.filing_time,
                    "capital": float(self.capital),
                    "reference_price": float(self.reference_price),
                    "take_profit_pct": float(self.take_profit_pct),
                    "stop_loss_pct": float(self.stop_loss_pct),
                    "generated_at": self.generated_at.isoformat() + "Z",
                    "metadata": dict(self.metadata),
                    "agent_id": self.agent_id,
                    "agent_type": self.agent_type,
                    "agent_status": self.agent_status,
                    "agent_config": dict(self.agent_config or {}),
                },
                default=str,
            ),
        }


def prepare_trade_execution_payloads(
    signals: Iterable[TradeSignal],
    portfolios: Iterable[PortfolioSnapshot],
    *,
    logger: Optional[logging.Logger] = None,
    price_fetch_timeout: float = 2.0,
) -> List[TradeExecutionPayload]:
    """
    Prepare trade execution payloads by combining trading signals with eligible portfolios.
    """

    logger = logger or logging.getLogger(__name__)
    payloads: List[TradeExecutionPayload] = []

    eligible_portfolios = list(portfolios)
    logger.info(
        "📋 prepare_trade_execution_payloads called with %d signal(s) and %d portfolio(s)",
        len(list(signals)) if hasattr(signals, '__len__') else 'unknown',
        len(eligible_portfolios)
    )
    if not eligible_portfolios:
        logger.info("No eligible portfolios for trade execution")
        return []

    for signal in signals:
        logger.info(
            "🔄 Processing signal: symbol=%s, signal=%d, confidence=%.2f",
            signal.symbol,
            signal.signal,
            signal.confidence
        )
        if signal.signal not in (1, -1):
            logger.debug("Skipping non-directional signal %s", signal.signal_id)
            continue
        if signal.confidence <= 0:
            logger.debug("Skipping signal %s with non-positive confidence", signal.signal_id)
            continue

        # Fetch price directly from market data service (more reliable than HTTP API)
        reference_price = 0.0
        
        # Check if we're running in a Celery worker (avoid multiple WebSocket connections)
        is_celery_worker = os.getenv("CELERY_WORKER_RUNNING") == "1"
        
        if is_celery_worker:
            # Use HTTP API to fetch price from portfolio-server
            try:
                import asyncio
                
                # Run async HTTP fetch
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Use asyncio.run_coroutine_threadsafe or nest_asyncio
                import nest_asyncio
                nest_asyncio.apply()
                price_decimal = loop.run_until_complete(
                    fetch_market_price_via_http(signal.symbol, timeout=price_fetch_timeout)
                )
                
                if price_decimal:
                    reference_price = float(price_decimal)
                    logger.info("✅ Fetched live price via HTTP for %s: ₹%.2f", signal.symbol, reference_price)
                else:
                    raise RuntimeError("HTTP price fetch returned None")
                    
            except Exception as exc:
                logger.warning("⚠️ Failed to fetch price via HTTP for %s: %s", signal.symbol, exc)
                reference_price = 0.0
        else:
            # Use WebSocket connection (only in main portfolio-server process)
            try:
                from market_data import await_live_price
                import asyncio
                
                # Run async price fetch in sync context
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                price_decimal = loop.run_until_complete(
                    await_live_price(signal.symbol, timeout=price_fetch_timeout)
                )
                reference_price = float(price_decimal)
                logger.info("✅ Fetched live price via WebSocket for %s: ₹%.2f", signal.symbol, reference_price)
            except RuntimeError as price_error:
                logger.warning("⚠️ Failed to fetch live price via WebSocket for %s: %s", signal.symbol, price_error)
                reference_price = 0.0
            except Exception as exc:
                logger.warning("⚠️ Unexpected error fetching price via WebSocket for %s: %s", signal.symbol, exc)
                reference_price = 0.0

        # Fallback: Try to extract price from signal metadata if live fetch failed
        if reference_price <= 0:
            signal_meta = dict(signal.metadata or {})
            if "reference_price" in signal_meta:
                try:
                    reference_price = _normalise_price(signal_meta["reference_price"])
                    logger.info("Using reference_price from signal metadata: %.2f", reference_price)
                except:
                    pass
            else:
                logger.warning("⚠️ reference_price NOT found in signal metadata. Keys: %s", list(signal_meta.keys()))
            
            # If still no price, skip signal instead of using synthetic defaults
            if reference_price <= 0:
                demo_mode = os.getenv("DEMO_MODE", "false").lower() in {"1", "true", "yes"}
                logger.error(
                    "❌ No price available for %s (DEMO_MODE=%s). Skipping signal; ensure market data is reachable.",
                    signal.symbol,
                    demo_mode,
                )
                continue  # Never execute with a synthetic placeholder price

        for portfolio in eligible_portfolios:
            logger.info(
                "🔍 Checking portfolio %s: agent_id=%s, agent_status=%s, capital_base=%.2f",
                portfolio.portfolio_id,
                portfolio.agent_id,
                portfolio.agent_status,
                portfolio.capital_base,
            )
            
            if not portfolio.agent_id:
                logger.debug(
                    "Skipping portfolio %s: no trading agent registered",
                    portfolio.portfolio_id,
                )
                continue

            # status=active means auto-trade is enabled, no separate flag needed
            if portfolio.agent_status and str(portfolio.agent_status).lower() != "active":
                logger.debug(
                    "Skipping portfolio %s: trading agent %s not active",
                    portfolio.portfolio_id,
                    portfolio.agent_id,
                )
                continue

            capital = portfolio.capital_base
            if capital <= 0:
                logger.warning(
                    "⚠️ Skipping portfolio %s: capital_base=%.2f (non-positive). "
                    "Check portfolio allocation.allocated_amount and portfolio.investment_amount",
                    portfolio.portfolio_id,
                    capital,
                )
                continue

            logger.info(
                "✅ PORTFOLIO PASSED ALL CHECKS! Creating payload for portfolio %s, capital=%.2f, symbol=%s, signal=%d",
                portfolio.portfolio_id,
                capital,
                signal.symbol,
                signal.signal
            )

            payloads.append(
                TradeExecutionPayload(
                    request_id=str(uuid.uuid4()),
                    signal_id=signal.signal_id,
                    signal=signal.signal,
                    user_id=portfolio.user_id,
                    portfolio_id=portfolio.portfolio_id,
                    portfolio_name=portfolio.portfolio_name,
                    organization_id=portfolio.organization_id,
                    customer_id=portfolio.customer_id,
                    symbol=signal.symbol,
                    confidence=signal.confidence,
                    explanation=signal.explanation,
                    filing_time=signal.filing_time,
                    generated_at=signal.generated_at,
                    capital=capital,
                    reference_price=reference_price,
                    metadata={
                        **dict(signal.metadata),
                        **dict(portfolio.metadata),
                        "trading_agent": {
                            "id": portfolio.agent_id,
                            "type": portfolio.agent_type,
                            "status": portfolio.agent_status,
                            "config": dict(portfolio.agent_config or {}),
                            "metadata": dict(portfolio.agent_metadata or {}),
                        },
                    },
                    agent_id=portfolio.agent_id,
                    agent_type=portfolio.agent_type,
                    agent_status=portfolio.agent_status,
                    agent_config=dict(portfolio.agent_config or {}),
                    agent_metadata=portfolio.agent_metadata,
                )
            )

    logger.debug("Prepared %s trade execution payload(s)", len(payloads))
    return payloads


__all__ = [
    "TradeSignal",
    "PortfolioSnapshot",
    "TradeExecutionPayload",
    "prepare_trade_execution_payloads",
    "get_allocation",
    "DEFAULT_TAKE_PROFIT_PCT",
    "DEFAULT_STOP_LOSS_PCT",
]


# HTTP Market Data Helper (added for Celery workers)
async def fetch_market_price_via_http(symbol: str, timeout: float = 10.0):
    """Fetch market price via HTTP from portfolio server"""
    import httpx
    import logging
    from decimal import Decimal
    
    logger = logging.getLogger(__name__)
    portfolio_server_url = os.getenv("PORTFOLIO_SERVER_URL", "http://portfolio.agentinvest.space")
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{portfolio_server_url}/api/market/quotes",
                params={"symbols": symbol}
            )
            
            if response.status_code != 200:
                logger.warning("Market API returned status %d for %s", response.status_code, symbol)
                return None
            
            data = response.json()
            quotes = data.get("data", [])
            
            if not quotes:
                logger.warning("No market data returned for %s", symbol)
                return None
            
            quote = quotes[0]
            price = quote.get("price")
            
            if price is None:
                logger.warning("Price is None in market data for %s", symbol)
                return None
            
            return Decimal(str(price))
            
    except Exception as exc:
        logger.warning("Failed to fetch market price for %s via HTTP: %s", symbol, exc)
        return None
