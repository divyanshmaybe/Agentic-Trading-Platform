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

DEFAULT_TAKE_PROFIT_PCT = 0.03
DEFAULT_STOP_LOSS_PCT = 0.01


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

        # Fetch price via HTTP API instead of direct WebSocket connection
        reference_price = 0.0
        try:
            portfolio_server_url = os.getenv("PORTFOLIO_SERVER_URL", "http://localhost:8000")
            internal_secret = os.getenv("INTERNAL_SERVICE_SECRET", "agentinvest-secret")
            
            url = f"{portfolio_server_url}/api/market/quotes"
            params = {"symbols": signal.symbol}
            headers = {
                "X-Internal-Service": "true",
                "X-Service-Secret": internal_secret,
            }
            
            with httpx.Client(timeout=price_fetch_timeout) as client:
                response = client.get(url, params=params, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("data") and len(data["data"]) > 0:
                        price = data["data"][0].get("price")
                        if price:
                            reference_price = _normalise_price(price)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to fetch price for %s via HTTP API: %s", signal.symbol, exc)
            reference_price = 0.0

        # Fallback: Use a default price if fetch fails (for testing/development)
        if reference_price <= 0:
            # Try to extract price from signal metadata if available
            signal_meta = dict(signal.metadata or {})
            if "reference_price" in signal_meta:
                try:
                    reference_price = _normalise_price(signal_meta["reference_price"])
                    logger.info("Using reference_price from signal metadata: %.2f", reference_price)
                except:
                    pass
            else:
                logger.warning("⚠️ reference_price NOT found in signal metadata. Keys: %s", list(signal_meta.keys()))
            
            # If still no price, use a reasonable default for testing
            if reference_price <= 0:
                logger.warning(
                    "No price available for %s, using default price 100.0 for testing. "
                    "This should be replaced with actual market data in production.",
                    signal.symbol
                )
                reference_price = 100.0  # Default fallback price for testing

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

