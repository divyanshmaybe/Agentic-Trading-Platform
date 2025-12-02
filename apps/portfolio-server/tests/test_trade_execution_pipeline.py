from __future__ import annotations
import sys
from contextlib import asynccontextmanager
from datetime import datetime
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
import uuid

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PORTFOLIO_SERVER_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PORTFOLIO_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_ROOT))

from utils import trade_execution as trade_utils
from pipelines.nse import trade_execution_pipeline as trade_pipeline
from services import trade_execution_service
from services.pipeline_service import PipelineService


class StubMarketDataService:
    def __init__(self, prices: Dict[str, Decimal]) -> None:
        self.prices = {symbol.upper(): price for symbol, price in prices.items()}
        self.registered: List[str] = []

    def register_symbol(self, symbol: str) -> None:
        self.registered.append(symbol.upper())

    def get_latest_price(self, symbol: str):
        return self.prices.get(symbol.upper())

    def get_or_fetch_price(self, symbol: str):
        return self.prices[symbol.upper()]


def make_trade_signal(confidence: float = 0.85) -> trade_utils.TradeSignal:
    return trade_utils.TradeSignal(
        signal_id="sig-1",
        symbol="RELIANCE",
        signal=1,
        confidence=confidence,
        explanation="Positive filing",
        filing_time="2025-11-11 09:15:00",
        generated_at=datetime(2025, 11, 11, 9, 15, 30),
        metadata={"source": "unit-test", "reference_price": 200.0},
    )


def make_portfolio_snapshot() -> trade_utils.PortfolioSnapshot:
    return trade_utils.PortfolioSnapshot(
        portfolio_id="pf-1",
        portfolio_name="High Risk Sleeve",
        user_id="user-1",
        organization_id="org-1",
        customer_id="cust-1",
        current_value=150_000.0,
        investment_amount=120_000.0,
        cash_available=250_000.0,
        metadata={"cash": 250_000.0},
        agent_id="agent-1",
        agent_type="high_risk",
        agent_status="active",
        agent_config={"auto_trade": True},
        agent_metadata={"source": "unit-test"},
    )


def test_prepare_trade_execution_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = {"RELIANCE": Decimal("200")}
    stub_service = StubMarketDataService(prices)
    monkeypatch.setattr("market_data.get_market_data_service", lambda: stub_service)

    # Mock the HTTP call to return the expected price
    import httpx
    def mock_get(url, params=None, headers=None, timeout=None):
        class MockResponse:
            status_code = 200
            def json(self):
                return {"data": [{"price": 200.0}]}
        return MockResponse()
    
    monkeypatch.setattr(httpx.Client, "get", mock_get)

    payloads = trade_utils.prepare_trade_execution_payloads(
        [make_trade_signal()],
        [make_portfolio_snapshot()],
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.symbol == "RELIANCE"
    assert payload.confidence == pytest.approx(0.85)
    assert payload.capital == pytest.approx(250_000.0)
    assert payload.reference_price == pytest.approx(200.0)
    assert payload.take_profit_pct == pytest.approx(trade_utils.DEFAULT_TAKE_PROFIT_PCT)
    assert payload.stop_loss_pct == pytest.approx(trade_utils.DEFAULT_STOP_LOSS_PCT)
    assert payload.agent_id == "agent-1"
    assert payload.agent_type == "high_risk"
    assert payload.agent_status == "active"
    assert payload.agent_config.get("auto_trade") is True
    assert payload.agent_metadata.get("source") == "unit-test"

    event = payload.to_event()
    payload_dict = json.loads(event["payload"])
    assert payload_dict["capital"] == pytest.approx(250_000.0)
    assert payload_dict["reference_price"] == pytest.approx(200.0)
    assert payload_dict["take_profit_pct"] == pytest.approx(trade_utils.DEFAULT_TAKE_PROFIT_PCT)
    assert payload_dict["stop_loss_pct"] == pytest.approx(trade_utils.DEFAULT_STOP_LOSS_PCT)
    expected_allocation = trade_utils.get_allocation(250_000.0, 0.85)
    expected_quantity = int(expected_allocation // 200.0)
    assert expected_allocation == pytest.approx(100_000.0)
    assert expected_quantity == 500
    assert payload_dict["agent_id"] == "agent-1"
    assert payload_dict["agent_type"] == "high_risk"
    assert payload_dict["agent_status"] == "active"
    assert payload_dict["agent_config"]["auto_trade"] is True


def test_prepare_trade_execution_payloads_skips_without_active_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prices = {"RELIANCE": Decimal("200")}
    stub_service = StubMarketDataService(prices)
    monkeypatch.setattr("market_data.get_market_data_service", lambda: stub_service)

    snapshot = trade_utils.PortfolioSnapshot(
        portfolio_id="pf-1",
        portfolio_name="High Risk Sleeve",
        user_id="user-1",
        organization_id="org-1",
        customer_id="cust-1",
        current_value=150_000.0,
        investment_amount=120_000.0,
        cash_available=250_000.0,
        metadata={"cash": 250_000.0},
        agent_id=None,
        agent_type=None,
        agent_status=None,
        agent_config={"auto_trade": True},
    )

    payloads = trade_utils.prepare_trade_execution_payloads(
        [make_trade_signal()],
        [snapshot],
    )

    assert payloads == []


class FakeTradeExecutionLog:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self._trade_model: Optional[Any] = None

    def set_trade_model(self, trade_model: Any) -> None:
        """Set the trade model for fetching linked trades."""
        self._trade_model = trade_model

    async def create(self, data: Dict[str, Any]) -> Any:
        row = dict(data)
        row.setdefault("id", row.get("request_id"))
        row.setdefault("created_at", datetime.utcnow())
        row.setdefault("updated_at", datetime.utcnow())
        # Add agent_id from metadata if available
        if "metadata" in row and isinstance(row["metadata"], str):
            try:
                import json
                metadata = json.loads(row["metadata"])
                if "agent_id" in metadata:
                    row["agent_id"] = metadata["agent_id"]
            except:
                pass
        self.rows[row["id"]] = row
        return SimpleNamespace(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        trade_id = where["id"]
        row = self.rows[trade_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        return SimpleNamespace(**row)

    async def find_unique(self, where: Dict[str, Any], include: Optional[Dict[str, Any]] = None) -> Any:
        trade_id = where["id"]
        row = self.rows.get(trade_id)
        if row and include:
            # Add trade relation if requested
            if "trade" in include and row.get("trade_id") and self._trade_model:
                trade_row = self._trade_model.rows.get(row["trade_id"])
                if trade_row:
                    result = SimpleNamespace(**row)
                    result.trade = SimpleNamespace(**trade_row)
                    return result
        return SimpleNamespace(**row) if row else None

    async def find_first(self, where: Dict[str, Any], include: Optional[Dict[str, Any]] = None) -> Any:
        # For find_first, we need to search by trade_id, not id
        if "trade_id" in where:
            trade_id = where["trade_id"]
            for row_id, row in self.rows.items():
                if row.get("trade_id") == trade_id:
                    result = SimpleNamespace(**row)
                    if include and "trade" in include and self._trade_model:
                        # Add full trade object if requested
                        trade_row = self._trade_model.rows.get(trade_id)
                        if trade_row:
                            result.trade = SimpleNamespace(**trade_row)
                    return result
        return None


class FakeTrade:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    async def create(self, data: Dict[str, Any]) -> Any:
        row = dict(data)
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        row.setdefault("created_at", datetime.utcnow())
        row.setdefault("updated_at", datetime.utcnow())
        self.rows[row["id"]] = row
        return SimpleNamespace(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        trade_id = where["id"]
        row = self.rows[trade_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        return SimpleNamespace(**row)

    async def update_many(self, where: Dict[str, Any], data: Dict[str, Any]) -> int:
        """Simulate update_many by finding matching rows and updating them."""
        count = 0
        for trade_id, row in self.rows.items():
            matches = True
            for key, value in where.items():
                if key == "status":
                    if isinstance(value, dict) and "in" in value:
                        if row.get(key) not in value["in"]:
                            matches = False
                            break
                    elif row.get(key) != value:
                        matches = False
                        break
                elif row.get(key) != value:
                    matches = False
                    break
            if matches:
                row.update(data)
                row["updated_at"] = datetime.utcnow()
                count += 1
        return count

    async def find_unique(self, where: Dict[str, Any], include: Optional[Dict[str, Any]] = None) -> Any:
        trade_id = where["id"]
        row = self.rows.get(trade_id)
        if row and include:
            # Add trade relation if requested
            if "trade" in include and row.get("trade_id"):
                result = SimpleNamespace(**row)
                result.trade = SimpleNamespace(id=row["trade_id"])
                return result
        return SimpleNamespace(**row) if row else None

    async def find_many(self, where: Optional[Dict[str, Any]] = None, take: Optional[int] = None, include: Optional[Dict[str, Any]] = None, order: Optional[Dict[str, Any]] = None) -> List[Any]:
        """Find multiple trades matching the where clause."""
        results = []
        for row in self.rows.values():
            if where:
                matches = True
                for key, value in where.items():
                    if key == "symbol":
                        if row.get(key) != value:
                            matches = False
                            break
                    elif key == "portfolio_id":
                        if row.get(key) != value:
                            matches = False
                            break
                    elif key == "status":
                        if isinstance(value, dict) and "in" in value:
                            # Handle {"in": ["pending", "active"]}
                            if row.get(key) not in value["in"]:
                                matches = False
                                break
                        elif row.get(key) != value:
                            matches = False
                            break
                    elif key == "created_at":
                        if isinstance(value, dict) and "gte" in value:
                            # Handle {"gte": cutoff_time}
                            if row.get(key) and row[key] < value["gte"]:
                                matches = False
                                break
                        else:
                            if row.get(key) != value:
                                matches = False
                                break
                    else:
                        if row.get(key) != value:
                            matches = False
                            break
                if not matches:
                    continue
            result = SimpleNamespace(**row)
            if include and "trade" in include:
                # Add trade relation if requested
                result.trade = SimpleNamespace(id=row.get("trade_id"))
            results.append(result)
            if take and len(results) >= take:
                break
        return results


class FakeClient:
    def __init__(self) -> None:
        self.tradeexecutionlog = FakeTradeExecutionLog()
        self.trade = FakeTrade()
        self.portfolio = FakePortfolioModel([])
        self.position = FakePositionModel()
        self.tradingagent = FakeTradingAgentModel()
        self.portfolioallocation = FakePortfolioAllocationModel()
        # Wire up the trade model to execution log for proper includes
        self.tradeexecutionlog.set_trade_model(self.trade)

    @asynccontextmanager
    async def tx(self, max_wait=None, timeout=None):
        """Transaction context manager using Prisma's native tx() method."""
        try:
            yield self  # Return self as transaction client
        except Exception:
            raise

    async def query_raw(self, query: str, *params) -> List[Dict[str, Any]]:
        """Simulate raw SQL queries for SELECT FOR UPDATE and other operations."""
        # For allocation cash check (SELECT FOR UPDATE)
        if "portfolio_allocations" in query and "FOR UPDATE" in query:
            allocation_id = params[0] if params else None
            if allocation_id:
                # Return mock allocation data
                return [{
                    "id": allocation_id,
                    "available_cash": 250000.0,
                    "allocated_amount": 100000.0
                }]
        # For transaction control (BEGIN/COMMIT/ROLLBACK)
        elif query in ("BEGIN", "COMMIT", "ROLLBACK"):
            return []
        return []

    async def execute_raw(self, query: str, *params) -> List[Any]:
        """Simulate raw SQL executions for UPDATE and other operations."""
        # For allocation cash updates
        if "portfolio_allocations" in query and "UPDATE" in query:
            return []  # Success
        # For position updates with RETURNING clause
        elif "positions" in query and "RETURNING" in query:
            return [{"id": "pos-1"}]  # Return fake position ID
        # For P&L updates
        elif query in ("portfolios", "trading_agents") and "UPDATE" in query:
            return []
        # For transaction control
        elif query in ("BEGIN", "COMMIT", "ROLLBACK"):
            return []
        return []


class FakePortfolioModel:
    def __init__(self, portfolios: List[Any] = None) -> None:
        self._portfolios = portfolios or []

    async def find_unique(self, where=None, include=None):
        # Return a fake portfolio for testing
        return SimpleNamespace(
            id="pf-1",
            organization_id="org-1", 
            customer_id="cust-1",
            allocation_trades=None,
            realized_pnl=Decimal("0"),
            total_realized_pnl=Decimal("0"),
            metadata=None
        )

    async def update(self, where=None, data=None):
        # Mock portfolio update - just return success
        return SimpleNamespace(
            id=where.get("id") if where else "pf-1",
            allocation_trades=data.get("allocation_trades") if data else None,
            total_realized_pnl=data.get("total_realized_pnl", Decimal("0")) if data else Decimal("0"),
        )

    async def find_many(self, where=None, include=None):  # pragma: no cover - include unused
        return self._portfolios


class FakePositionModel:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    async def find_first(self, where=None, include=None):
        # Return None for no existing position
        return None

    async def create(self, data: Dict[str, Any]) -> Any:
        row = dict(data)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", datetime.utcnow())
        row.setdefault("updated_at", datetime.utcnow())
        self.rows[row["id"]] = row
        return SimpleNamespace(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        position_id = where["id"]
        row = self.rows[position_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        return SimpleNamespace(**row)


class FakeTradingAgentModel:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    async def find_unique(self, where=None, include=None):
        # Return a fake agent
        return SimpleNamespace(
            id="agent-1",
            allocation=SimpleNamespace(
                id="alloc-1",
                allocated_amount=Decimal("100000"),
                realized_pnl=Decimal("0")
            ),
            realized_pnl=Decimal("0"),
            metadata=None
        )

    async def find_many(self, where=None, include=None):
        # Return fake agents for find_many calls
        agents = []
        if where and where.get("agent_type") == "high_risk" and where.get("status") == "active":
            agent = SimpleNamespace(
                id="agent-1",
                agent_type="high_risk",
                status="active",
                strategy_config={"auto_trade": True},
                metadata={"source": "unit-test"},
                portfolio_id="pf-1",
                portfolio=SimpleNamespace(
                    id="pf-1",
                    user_id="user-1",
                    portfolio_name="High Risk Sleeve",
                ),
                allocation=SimpleNamespace(
                    id="alloc-1",
                    allocated_amount=Decimal("100000"),
                    realized_pnl=Decimal("0")
                ),
                realized_pnl=Decimal("0")
            )
            agents.append(agent)
        return agents

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        agent_id = where["id"]
        if agent_id not in self.rows:
            self.rows[agent_id] = {"id": agent_id}
        row = self.rows[agent_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        return SimpleNamespace(**row)


class FakePortfolioAllocationModel:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    async def find_unique(self, where: Dict[str, Any]) -> Any:
        allocation_id = where["id"]
        if allocation_id not in self.rows:
            # Return default allocation for testing
            return SimpleNamespace(
                id=allocation_id,
                available_cash=Decimal("250000.0"),
                allocated_amount=Decimal("100000.0"),
                realized_pnl=Decimal("0"),
            )
        row = self.rows[allocation_id]
        return SimpleNamespace(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        allocation_id = where["id"]
        if allocation_id not in self.rows:
            self.rows[allocation_id] = {"id": allocation_id, "available_cash": Decimal("250000.0")}
        row = self.rows[allocation_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        return SimpleNamespace(**row)


class FakeDBManager:
    def __init__(self) -> None:
        self._client = FakeClient()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    def get_client(self) -> FakeClient:
        return self._client

    @asynccontextmanager
    async def session(self):
        yield self._client


@pytest.mark.asyncio
async def test_trade_execution_service_persist_and_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_manager = FakeDBManager()
    monkeypatch.setattr(trade_execution_service, "get_db_manager", lambda: fake_manager)

    # Mock market hours enforcement to allow tests to run outside market hours
    def mock_enforce_market_hours(*args, **kwargs):
        pass  # Skip market hours check in tests
    
    monkeypatch.setattr("services.trade_execution_service.enforce_market_hours", mock_enforce_market_hours)

    published_events: List[trade_pipeline.TradeExecutionEvent] = []

    def capture_publish(events, logger=None):  # type: ignore[override]
        published_events.extend(events)
        return len(events)

    monkeypatch.setattr(trade_execution_service, "publish_trade_execution_events", capture_publish)

    service = trade_execution_service.TradeExecutionService()

    job_rows = [
        {
            "request_id": "req-1",
            "signal_id": "sig-1",
            "user_id": "user-1",
            "portfolio_id": "pf-1",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": 500,
            "allocated_capital": 100_000.0,
            "confidence": 0.85,
            "reference_price": 200.0,
            "take_profit_pct": 0.03,
            "stop_loss_pct": 0.01,
            "explanation": "Positive",
            "filing_time": "2025-11-11 09:15:00",
            "generated_at": "2025-11-11T09:15:30Z",
            "metadata_json": "{}",
            "agent_id": "agent-1",
        }
    ]

    events = await service.persist_and_publish(job_rows)
    assert len(events) == 1
    assert len(published_events) == 1
    record = await fake_manager.get_client().tradeexecutionlog.find_unique({"id": "req-1"})
    assert record.status == "pending"
    assert record.agent_id == "agent-1"

    result = await service.execute_trade(events[0].trade_id, simulate=True)
    assert result["status"] == "executed"
    updated = await fake_manager.get_client().tradeexecutionlog.find_unique({"id": "req-1"})
    assert updated.status == "executed"


class FakePipelineClient(FakeClient):
    def __init__(self, portfolios: List[Any]) -> None:
        super().__init__()
        self.portfolio = FakePortfolioModel(portfolios)

    async def query_raw(self, query: str):
        assert "high_risk" in query.lower()
        return [{"id": "user-1"}]


class FakePipelineManager(FakeDBManager):
    def __init__(self, portfolios: List[Any]) -> None:
        super().__init__()
        self._client = FakePipelineClient(portfolios)


@pytest.mark.asyncio
async def test_pipeline_service_process_trade_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio = SimpleNamespace(
        id="pf-1",
        portfolio_name="High Risk Sleeve",
        user_id="user-1",
        organization_id="org-1",
        customer_id="cust-1",
        current_value=Decimal("150000"),
        investment_amount=Decimal("120000"),
        metadata={"cash": 250_000.0},
        agents=[
            SimpleNamespace(
                id="agent-1",
                agent_type="high_risk",
                status="active",
                strategy_config={"auto_trade": True},
                metadata={"source": "unit-test"},
            )
        ],
        objective_id="obj-1",
    )

    class FakeDBManagerInstance:
        def __init__(self, client):
            self._client = client
        
        async def connect(self):
            pass
        
        def get_client(self):
            return self._client
        
        async def disconnect(self):
            pass

        @asynccontextmanager
        async def session(self):
            yield self._client
    
    fake_manager = FakePipelineManager([portfolio])
    
    def fake_get_db_client():
        return FakeDBManagerInstance(fake_manager.get_client())
    
    monkeypatch.setattr("dbManager.DBManager.get_instance", fake_get_db_client, raising=False)

    # Mock Prisma client - the service creates a new Prisma() instance
    class FakeTradingAgent:
        def __init__(self):
            self.id = "agent-1"
            self.agent_type = "high_risk"
            self.status = "active"
            self.strategy_config = {"auto_trade": True}
            self.metadata = {"source": "unit-test"}
            self.portfolio_id = "pf-1"  # Add portfolio_id attribute
            self.portfolio = SimpleNamespace(
                id="pf-1",
                user_id="user-1",
                portfolio_name="High Risk Sleeve",
            )
            self.allocation = SimpleNamespace(
                allocated_amount=Decimal("100000"),
            )

    class FakePortfolio:
        def __init__(self):
            self.id = "pf-1"
            self.portfolio_name = "High Risk Sleeve"
            self.user_id = "user-1"
            self.organization_id = "org-1"
            self.customer_id = "cust-1"
            self.status = "active"
            self.current_value = Decimal("150000")
            self.investment_amount = Decimal("120000")
            self.metadata = {"cash": 250_000.0}
            self.agents = [
                SimpleNamespace(
                    id="agent-1",
                    agent_type="high_risk",
                    status="active",
                    strategy_config={"auto_trade": True},
                    metadata={"source": "unit-test"},
                    allocation=SimpleNamespace(
                        allocated_amount=Decimal("100000"),
                    ),
                )
            ]

    class FakePrisma:
        def __init__(self):
            pass
        
        async def connect(self):
            pass
        
        async def disconnect(self):
            pass
        
        @property
        def tradingagent(self):
            class TradingAgentModel:
                async def find_many(self, where=None, include=None):
                    return [FakeTradingAgent()]
            return TradingAgentModel()
        
        @property
        def portfolio(self):
            class PortfolioModel:
                async def find_many(self, where=None, include=None):
                    return [FakePortfolio()]
            return PortfolioModel()

    monkeypatch.setattr("prisma.Prisma", FakePrisma)

    trade_payload = trade_utils.TradeExecutionPayload(
        request_id="req-1",
        signal_id="sig-1",
        signal=1,
        user_id="user-1",
        portfolio_id="pf-1",
        portfolio_name="High Risk Sleeve",
        organization_id="org-1",
        customer_id="cust-1",
        symbol="RELIANCE",
        confidence=0.85,
        explanation="Positive",
        filing_time="2025-11-11 09:15:00",
        generated_at=datetime(2025, 11, 11, 9, 15, 30),
        capital=250_000.0,
        reference_price=200.0,
        agent_id="agent-1",
        agent_type="high_risk",
        agent_status="active",
        agent_config={"auto_trade": True},
        agent_metadata={"source": "unit-test"},
    )

    def fake_prepare(signals, portfolios, logger=None):
        return [trade_payload]

    monkeypatch.setattr(
        "utils.trade_execution.prepare_trade_execution_payloads",
        fake_prepare,
        raising=False,
    )
    monkeypatch.setattr(
        "services.pipeline_service.prepare_trade_execution_payloads",
        fake_prepare,
        raising=False,
    )

    job_rows = [
        {
            "request_id": "req-1",
            "signal_id": "sig-1",
            "user_id": "user-1",
            "portfolio_id": "pf-1",
            "portfolio_name": "High Risk Sleeve",
            "organization_id": "org-1",
            "customer_id": "cust-1",
            "symbol": "RELIANCE",
            "side": "BUY",
            "quantity": 500,
            "allocated_capital": 100_000.0,
            "confidence": 0.85,
            "reference_price": 200.0,
            "take_profit_pct": 0.03,
            "stop_loss_pct": 0.01,
            "explanation": "Positive",
            "filing_time": "2025-11-11 09:15:00",
            "generated_at": "2025-11-11T09:15:30Z",
            "metadata_json": "{}",
            "agent_id": "agent-1",
            "agent_type": "high_risk",
            "agent_status": "active",
        }
    ]

    monkeypatch.setattr(
        trade_pipeline,
        "run_trade_execution_requests",
        lambda requests, logger=None: job_rows,
        raising=False,
    )
    monkeypatch.setattr(
        "services.pipeline_service.run_trade_execution_requests",
        lambda requests, logger=None: job_rows,
        raising=False,
    )

    persist_calls: List[List[Dict[str, Any]]] = []

    class FakeTradeService:
        def __init__(self, logger=None) -> None:
            self.logger = logger

        async def persist_and_publish(self, rows, publish_kafka=True):
            persist_calls.append(rows)
            return [
                trade_pipeline.TradeExecutionEvent(
                    trade_id=row["request_id"],
                    request_id=row["request_id"],
                    signal_id=row["signal_id"],
                    user_id=row["user_id"],
                    portfolio_id=row["portfolio_id"],
                    symbol=row["symbol"],
                    side=row["side"],
                    quantity=row["quantity"],
                    allocated_capital=row["allocated_capital"],
                    confidence=row["confidence"],
                    reference_price=row["reference_price"],
                    take_profit_pct=row["take_profit_pct"],
                    stop_loss_pct=row["stop_loss_pct"],
                    explanation=row["explanation"],
                    filing_time=row["filing_time"],
                    generated_at=row["generated_at"],
                    metadata={},
                    agent_id=row.get("agent_id"),
                    agent_type=row.get("agent_type"),
                    agent_status=row.get("agent_status"),
                )
                for row in rows
            ]

    # Add execute_trade method to FakeTradeService
    async def fake_execute_trade(trade_id: str, simulate: bool = True):
        return {"status": "executed", "trade_id": trade_id}
    
    FakeTradeService.execute_trade = fake_execute_trade

    monkeypatch.setattr("services.pipeline_service.TradeExecutionService", FakeTradeService, raising=False)

    dispatched: List[str] = []
    
    def fake_apply_async(args=None, kwargs=None, **extra):
        """Mock apply_async to capture dispatched trade IDs."""
        if args and len(args) > 0:
            dispatched.append(args[0])
        return None
    
    monkeypatch.setattr(
        "workers.trade_execution_tasks.execute_trade_job.apply_async",
        fake_apply_async,
        raising=False,
    )
    
    # Set USE_CELERY_FOR_TRADES to true to test Celery dispatch
    monkeypatch.setenv("USE_CELERY_FOR_TRADES", "true")

    monkeypatch.setattr(PipelineService, "_load_environment", lambda self: None, raising=False)

    service = PipelineService(str(PORTFOLIO_SERVER_ROOT), logger=None)

    summary = await service._process_nse_trade_signals_async(
        signals=[{"symbol": "RELIANCE", "signal": 1, "confidence": 0.85, "reference_price": 200.0}],
        publish_kafka=True,
    )

    assert summary == {
        "processed_signals": 1,
        "payloads": 1,
        "jobs": 1,
        "dispatched": 1,
        "executed": 0,  # No direct execution when using Celery
    }
    assert len(persist_calls) == 1
    assert dispatched == ["req-1"]
    # Note: Service now uses Prisma directly, not DBManager, so connection check is not applicable


@pytest.mark.asyncio
async def test_pipeline_service_skips_portfolios_with_inactive_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that portfolios with paused/inactive high_risk agents are skipped."""
    
    # Mock Prisma client - the service creates a new Prisma() instance
    class FakeTradingAgent:
        def __init__(self):
            self.id = "test-agent-1"
            self.agent_type = "high_risk"
            self.status = "paused"  # Agent is paused, not active
            self.strategy_config = {"auto_trade": True}
            self.metadata = {"source": "test"}
            self.portfolio_id = "test-portfolio-1"
            self.portfolio = SimpleNamespace(
                id="test-portfolio-1",
                user_id="test-user-1",
                portfolio_name="Test High Risk Portfolio",
            )
            self.allocation = SimpleNamespace(
                allocated_amount=Decimal("250000"),
            )

    class FakePrisma:
        def __init__(self):
            pass
        
        async def connect(self):
            pass
        
        async def disconnect(self):
            pass
        
        @property
        def tradingagent(self):
            class TradingAgentModel:
                async def find_many(self, where=None, include=None):
                    # Return the paused agent - should be filtered out
                    return [FakeTradingAgent()]
            return TradingAgentModel()
        
        @property
        def portfolio(self):
            class PortfolioModel:
                async def find_many(self, where=None, include=None):
                    return []  # No portfolios should be processed
            return PortfolioModel()

    monkeypatch.setattr("prisma.Prisma", FakePrisma)
    monkeypatch.setattr(PipelineService, "_load_environment", lambda self: None, raising=False)

    # Mock DBManager to return FakePrisma instance
    class FakeDBManagerInstance:
        def __init__(self):
            self._client = FakePrisma()
        
        async def connect(self):
            await self._client.connect()
        
        def get_client(self):
            return self._client
        
        async def disconnect(self):
            await self._client.disconnect()

        @asynccontextmanager
        async def session(self):
            yield self._client
    
    def fake_get_db_client():
        return FakeDBManagerInstance()
    
    monkeypatch.setattr("dbManager.DBManager.get_instance", fake_get_db_client)

    service = PipelineService(str(PORTFOLIO_SERVER_ROOT), logger=None)

    summary = await service._process_nse_trade_signals_async(
        signals=[{"symbol": "RELIANCE", "signal": 1, "confidence": 0.85}],
        publish_kafka=True,
    )

    assert summary == {
        "processed_signals": 1,
        "payloads": 0,
        "jobs": 0,
        "dispatched": 0,
    }

