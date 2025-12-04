# I will create an in-memory Prisma stub and unit tests covering market, limit,
# stop-loss, take-profit, and sell order flows for the trade engine.

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PORTFOLIO_SERVER_ROOT = Path(__file__).resolve().parents[1]
SHARED_PY_ROOT = PROJECT_ROOT / "shared" / "py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PORTFOLIO_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_ROOT))
if str(SHARED_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_PY_ROOT))

from schemas.trade import TradeCreate
from services import trade_engine
from services.trade_engine import TradeEngine


class Record(dict):
    """Simple dict wrapper providing attribute access similar to Prisma models."""

    def __getattr__(self, item: str) -> Any:  # pragma: no cover - defensive
        try:
            return self[item]
        except KeyError:  # pragma: no cover
            # Return None for missing attributes instead of raising
            # This matches Prisma behavior for optional fields
            return None

    def dict(self) -> Dict[str, Any]:  # pragma: no cover - parity with Prisma
        return dict(self)


class InMemoryModel:
    def __init__(self, pk_field: str) -> None:
        self.pk_field = pk_field
        self.rows: Dict[str, Record] = {}

    @staticmethod
    def _clone(data: Dict[str, Any]) -> Record:
        return Record(json.loads(json.dumps(data, default=str)))

    async def create(self, data: Dict[str, Any]) -> Record:
        row = dict(data)
        pk = row.get(self.pk_field) or str(uuid.uuid4())
        row[self.pk_field] = pk
        now = datetime.utcnow()
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        self.rows[pk] = Record(row)
        return self.rows[pk]

    async def find_unique(self, where: Dict[str, Any]) -> Optional[Record]:
        key, value = next(iter(where.items()))
        if key == self.pk_field:
            return self.rows.get(value)
        for row in self.rows.values():
            if row.get(key) == value:
                return row
        return None

    async def find_unique_or_raise(self, where: Dict[str, Any]) -> Record:
        record = await self.find_unique(where)
        if record is None:
            raise ValueError(f"Record not found for {where}")
        return record

    async def find_first(self, where: Dict[str, Any]) -> Optional[Record]:
        for row in self.rows.values():
            if all(row.get(k) == v for k, v in where.items()):
                return row
        return None

    async def find_many(self, where: Optional[Dict[str, Any]] = None) -> List[Record]:
        if not where:
            return list(self.rows.values())
        return [row for row in self.rows.values() if all(row.get(k) == v for k, v in where.items())]

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Record:
        record = await self.find_unique(where)
        if record is None:
            raise ValueError(f"Cannot update missing record: {where}")
        record.update(data)
        record["updated_at"] = datetime.utcnow()
        return record

    async def delete(self, where: Dict[str, Any]) -> None:
        key, value = next(iter(where.items()))
        if key != self.pk_field:
            raise ValueError("Deletes only support primary key lookup in tests")
        self.rows.pop(value, None)


class FakeTransaction:
    """Fake transaction context manager that delegates to the same in-memory models."""
    def __init__(self, prisma: "FakePrisma") -> None:
        # Share the same models - in-memory doesn't need real transactions
        self.portfolio = prisma.portfolio
        self.portfolioallocation = prisma.portfolioallocation
        self.tradingagent = prisma.tradingagent
        self.position = prisma.position
        self.trade = prisma.trade
        self.tradeexecutionlog = prisma.tradeexecutionlog

    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass  # In-memory doesn't need commit/rollback


class FakePrisma:
    def __init__(self) -> None:
        self.portfolio = InMemoryModel("id")
        self.portfolioallocation = InMemoryModel("id")
        self.tradingagent = InMemoryModel("id")
        self.position = InMemoryModel("id")
        self.trade = InMemoryModel("id")
        self.tradeexecutionlog = InMemoryModel("id")

    def tx(self) -> FakeTransaction:
        """Return a fake transaction context manager."""
        return FakeTransaction(self)


@dataclass
class LivePriceStub:
    prices: Dict[str, Decimal]

    async def __call__(self, symbol: str, timeout: float = 10.0) -> Decimal:
        try:
            return self.prices[symbol.upper()]
        except KeyError as exc:
            raise RuntimeError(f"No live price for {symbol}") from exc


class FakeMarketData:
    def __init__(self, prices: Dict[str, Decimal]) -> None:
        self.prices = prices
        self.registered: List[str] = []

    def register_symbol(self, symbol: str) -> None:
        self.registered.append(symbol.upper())

    def get_latest_price(self, symbol: str) -> Optional[Decimal]:
        return self.prices.get(symbol.upper())


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    db = FakePrisma()
    prices: Dict[str, Decimal] = {}
    live_stub = LivePriceStub(prices)
    market = FakeMarketData(prices)

    monkeypatch.setattr(trade_engine, "await_live_price", live_stub)
    monkeypatch.setattr(trade_engine, "get_market_data_service", lambda: market)

    engine = TradeEngine(db)  # type: ignore[arg-type]

    # Prevent Celery enqueue during tests
    monkeypatch.setattr(TradeEngine, "_enqueue_pending_trade", lambda self, trade_id: None)

    return {
        "db": db,
        "engine": engine,
        "prices": prices,
        "market": market,
    }


def make_trade(**kwargs: Any) -> TradeCreate:
    defaults = {
        "organization_id": "org-1",
        "portfolio_id": "pf-1",
        "customer_id": "cust-1",
        "trade_type": "cash",
        "symbol": "TCS",
        "exchange": "NSE",
        "segment": "EQUITY",
        "side": "BUY",
        "order_type": "market",
        "quantity": 10,
        "source": "unit-test",
        "metadata": {"test": True},
    }
    defaults.update(kwargs)
    return TradeCreate(**defaults)


@pytest.mark.asyncio
async def test_market_buy_creates_position(fake_env: Dict[str, Any]) -> None:
    db: FakePrisma = fake_env["db"]
    engine: TradeEngine = fake_env["engine"]
    prices: Dict[str, Decimal] = fake_env["prices"]

    await db.portfolio.create(
        {
            "id": "pf-1",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "portfolio_name": "Primary",
            "investment_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
            "investment_horizon_years": 5,
            "expected_return_target": Decimal("0.10"),
            "risk_tolerance": "medium",
            "liquidity_needs": "moderate",
            "realized_pnl": Decimal("0"),
        }
    )

    # Create allocation and agent required for position
    allocation = await db.portfolioallocation.create(
        data={
            "portfolio_id": "pf-1",
            "agent_id": "agent-1",
            "asset_class": "equity",
            "weight": Decimal("1.0"),
            "available_cash": Decimal("100000"),
        }
    )
    agent = await db.tradingagent.create(
        data={
            "portfolio_id": "pf-1",
            "allocation_id": allocation.id,
            "name": "Test Agent",
            "is_active": True,
            "allocation_percentage": Decimal("100"),
        }
    )

    # Pre-create position since trade_engine no longer creates new positions
    # (position creation requires agent context via trade_execution_service)
    await db.position.create(
        data={
            "portfolio_id": "pf-1",
            "agent_id": agent.id,
            "allocation_id": allocation.id,
            "symbol": "TCS",
            "exchange": "NSE",
            "segment": "EQUITY",
            "quantity": 0,
            "average_buy_price": Decimal("0"),
            "status": "open",
        }
    )

    prices["TCS"] = Decimal("110.25")

    payload = make_trade(order_type="market")
    result = await engine.handle_trade(payload)

    assert result.pending_orders == 0
    assert result.trades[0]["status"] == "executed"
    position = await db.position.find_first({"portfolio_id": "pf-1", "symbol": "TCS"})
    assert position is not None
    assert position.quantity == 10
    assert Decimal(str(position.average_buy_price)) == Decimal("110.25")

    # Verify Trade record was created
    trade_record = await db.trade.find_first({"portfolio_id": "pf-1", "symbol": "TCS"})
    assert trade_record is not None
    assert trade_record.status == "executed"
    assert trade_record.side == "BUY"
    assert trade_record.quantity == 10

    # Verify TradeExecutionLog record was created and linked to Trade
    execution_logs = await db.tradeexecutionlog.find_many()
    assert len(execution_logs) == 1
    execution_log = execution_logs[0]
    assert execution_log.trade_id == trade_record.id
    assert execution_log.status == "executed"


@pytest.mark.asyncio
async def test_market_sell_reduces_position(fake_env: Dict[str, Any]) -> None:
    db: FakePrisma = fake_env["db"]
    engine: TradeEngine = fake_env["engine"]
    prices: Dict[str, Decimal] = fake_env["prices"]

    await db.portfolio.create(
        {
            "id": "pf-1",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "portfolio_name": "Primary",
            "investment_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
            "investment_horizon_years": 5,
            "expected_return_target": Decimal("0.10"),
            "risk_tolerance": "medium",
            "liquidity_needs": "moderate",
            "realized_pnl": Decimal("0"),
        }
    )

    # Create allocation and agent for position requirements
    allocation = await db.portfolioallocation.create(
        {
            "id": "alloc-1",
            "portfolio_id": "pf-1",
            "allocation_type": "test",
            "target_weight": Decimal("1.0"),
            "allocated_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
        }
    )
    
    agent = await db.tradingagent.create(
        {
            "id": "agent-1",
            "portfolio_id": "pf-1",
            "portfolio_allocation_id": "alloc-1",
            "organization_id": "org-1",
            "agent_name": "Test Agent",
            "agent_type": "test",
        }
    )

    position = await db.position.create(
        {
            "id": "pos-1",
            "portfolio_id": "pf-1",
            "agent_id": "agent-1",
            "allocation_id": "alloc-1",
            "symbol": "TCS",
            "exchange": "NSE",
            "segment": "EQUITY",
            "quantity": 15,
            "average_buy_price": Decimal("100"),
            "position_type": "long",
            "status": "open",
            "realized_pnl": Decimal("0"),
        }
    )

    prices["TCS"] = Decimal("125")

    payload = make_trade(order_type="market", side="SELL", quantity=5)
    await engine.handle_trade(payload)

    updated = await db.position.find_unique({"id": position.id})
    assert updated is not None
    assert updated.quantity == 10

    # Verify Trade record was created
    trade_record = await db.trade.find_first({"portfolio_id": "pf-1", "symbol": "TCS", "side": "SELL"})
    assert trade_record is not None
    assert trade_record.status == "executed"
    assert trade_record.side == "SELL"
    assert trade_record.quantity == 5

    # Verify TradeExecutionLog record was created and linked to Trade
    execution_logs = await db.tradeexecutionlog.find_many()
    assert len(execution_logs) == 1
    execution_log = execution_logs[0]
    assert execution_log.trade_id == trade_record.id
    assert execution_log.status == "executed"


@pytest.mark.asyncio
async def test_limit_order_creates_pending_trade(fake_env: Dict[str, Any]) -> None:
    db: FakePrisma = fake_env["db"]
    engine: TradeEngine = fake_env["engine"]

    await db.portfolio.create(
        {
            "id": "pf-1",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "portfolio_name": "Primary",
            "investment_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
            "investment_horizon_years": 5,
            "expected_return_target": Decimal("0.10"),
            "risk_tolerance": "medium",
            "liquidity_needs": "moderate",
            "realized_pnl": Decimal("0"),
        }
    )

    payload = make_trade(order_type="limit", limit_price=Decimal("95.00"))
    result = await engine.handle_trade(payload)

    assert result.pending_orders == 1
    trade_record = await db.trade.find_unique({"id": result.trades[0]["id"]})
    assert trade_record is not None
    assert trade_record.status == "pending"
    assert trade_record.limit_price == Decimal("95.00")

    # Pending orders create TradeExecutionLog records with status "pending"
    execution_logs = await db.tradeexecutionlog.find_many()
    assert len(execution_logs) == 1
    execution_log = execution_logs[0]
    assert execution_log.status == "pending"


@pytest.mark.asyncio
async def test_process_pending_limit_trade_executes(fake_env: Dict[str, Any]) -> None:
    db: FakePrisma = fake_env["db"]
    engine: TradeEngine = fake_env["engine"]
    prices: Dict[str, Decimal] = fake_env["prices"]

    await db.portfolio.create(
        {
            "id": "pf-1",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "portfolio_name": "Primary",
            "investment_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
            "investment_horizon_years": 5,
            "expected_return_target": Decimal("0.10"),
            "risk_tolerance": "medium",
            "liquidity_needs": "moderate",
            "realized_pnl": Decimal("0"),
        }
    )

    trade = await db.trade.create(
        {
            "organization_id": "org-1",
            "portfolio_id": "pf-1",
            "customer_id": "cust-1",
            "trade_type": "cash",
            "symbol": "TCS",
            "exchange": "NSE",
            "segment": "EQUITY",
            "side": "BUY",
            "order_type": "limit",
            "quantity": 10,
            "limit_price": Decimal("95.00"),
            "status": "pending",
            "source": "unit-test",
            "metadata": {},
        }
    )

    prices["TCS"] = Decimal("94.50")

    executed = await engine.process_pending_trade(trade.id)
    assert executed is True

    updated_trade = await db.trade.find_unique({"id": trade.id})
    assert updated_trade.status == "executed"
    assert updated_trade.executed_quantity == 10
    assert Decimal(str(updated_trade.executed_price)) == Decimal("94.50")

    # Verify TradeExecutionLog record was created and linked to Trade
    execution_logs = await db.tradeexecutionlog.find_many()
    assert len(execution_logs) == 1
    execution_log = execution_logs[0]
    assert execution_log.trade_id == trade.id
    assert execution_log.status == "executed"


@pytest.mark.asyncio
async def test_stop_loss_sell_triggers_on_price_drop(fake_env: Dict[str, Any]) -> None:
    db: FakePrisma = fake_env["db"]
    engine: TradeEngine = fake_env["engine"]
    prices: Dict[str, Decimal] = fake_env["prices"]

    await db.portfolio.create(
        {
            "id": "pf-1",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "portfolio_name": "Primary",
            "investment_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
            "investment_horizon_years": 5,
            "expected_return_target": Decimal("0.10"),
            "risk_tolerance": "medium",
            "liquidity_needs": "moderate",
            "realized_pnl": Decimal("0"),
        }
    )

    # Create allocation and agent for position requirements
    allocation = await db.portfolioallocation.create(
        {
            "id": "alloc-1",
            "portfolio_id": "pf-1",
            "allocation_type": "test",
            "target_weight": Decimal("1.0"),
            "allocated_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
        }
    )
    
    agent = await db.tradingagent.create(
        {
            "id": "agent-1",
            "portfolio_id": "pf-1",
            "portfolio_allocation_id": "alloc-1",
            "organization_id": "org-1",
            "agent_name": "Test Agent",
            "agent_type": "test",
        }
    )

    await db.position.create(
        {
            "id": "pos-1",
            "portfolio_id": "pf-1",
            "agent_id": "agent-1",
            "allocation_id": "alloc-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "segment": "EQUITY",
            "quantity": 20,
            "average_buy_price": Decimal("200"),
            "position_type": "long",
            "status": "open",
            "realized_pnl": Decimal("0"),
        }
    )

    pending = await db.trade.create(
        {
            "organization_id": "org-1",
            "portfolio_id": "pf-1",
            "customer_id": "cust-1",
            "trade_type": "cash",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "segment": "EQUITY",
            "side": "SELL",
            "order_type": "stop_loss",
            "quantity": 10,
            "trigger_price": Decimal("190"),
            "status": "pending",
            "source": "unit-test",
            "metadata": {},
        }
    )

    prices["RELIANCE"] = Decimal("185")

    executed = await engine.process_pending_trade(pending.id)
    assert executed is True
    remaining = await db.position.find_first({"portfolio_id": "pf-1", "symbol": "RELIANCE"})
    assert remaining.quantity == 10

    # Verify TradeExecutionLog record was created and linked to Trade
    execution_logs = await db.tradeexecutionlog.find_many()
    assert len(execution_logs) == 1
    execution_log = execution_logs[0]
    assert execution_log.trade_id == pending.id
    assert execution_log.status == "executed"


@pytest.mark.asyncio
async def test_take_profit_executes_on_target(fake_env: Dict[str, Any]) -> None:
    db: FakePrisma = fake_env["db"]
    engine: TradeEngine = fake_env["engine"]
    prices: Dict[str, Decimal] = fake_env["prices"]

    await db.portfolio.create(
        {
            "id": "pf-1",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "portfolio_name": "Primary",
            "investment_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
            "investment_horizon_years": 5,
            "expected_return_target": Decimal("0.10"),
            "risk_tolerance": "medium",
            "liquidity_needs": "moderate",
            "realized_pnl": Decimal("0"),
        }
    )

    # Create allocation and agent for position requirements
    allocation = await db.portfolioallocation.create(
        {
            "id": "alloc-1",
            "portfolio_id": "pf-1",
            "allocation_type": "test",
            "target_weight": Decimal("1.0"),
            "allocated_amount": Decimal("100000"),
            "available_cash": Decimal("100000"),
        }
    )
    
    agent = await db.tradingagent.create(
        {
            "id": "agent-1",
            "portfolio_id": "pf-1",
            "portfolio_allocation_id": "alloc-1",
            "organization_id": "org-1",
            "agent_name": "Test Agent",
            "agent_type": "test",
        }
    )

    await db.position.create(
        {
            "id": "pos-1",
            "portfolio_id": "pf-1",
            "agent_id": "agent-1",
            "allocation_id": "alloc-1",
            "symbol": "INFY",
            "exchange": "NSE",
            "segment": "EQUITY",
            "quantity": 12,
            "average_buy_price": Decimal("1000"),
            "position_type": "long",
            "status": "open",
            "realized_pnl": Decimal("0"),
        }
    )

    pending = await db.trade.create(
        {
            "organization_id": "org-1",
            "portfolio_id": "pf-1",
            "customer_id": "cust-1",
            "trade_type": "cash",
            "symbol": "INFY",
            "exchange": "NSE",
            "segment": "EQUITY",
            "side": "SELL",
            "order_type": "take_profit",
            "quantity": 6,
            "trigger_price": Decimal("1250"),
            "status": "pending",
            "source": "unit-test",
            "metadata": {},
        }
    )

    prices["INFY"] = Decimal("1265")

    executed = await engine.process_pending_trade(pending.id)
    assert executed is True
    remaining = await db.position.find_first({"portfolio_id": "pf-1", "symbol": "INFY"})
    assert remaining.quantity == 6

    # Verify TradeExecutionLog record was created and linked to Trade
    execution_logs = await db.tradeexecutionlog.find_many()
    assert len(execution_logs) == 1
    execution_log = execution_logs[0]
    assert execution_log.trade_id == pending.id
    assert execution_log.status == "executed"
