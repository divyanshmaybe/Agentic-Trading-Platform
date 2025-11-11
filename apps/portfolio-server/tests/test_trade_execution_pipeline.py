from __future__ import annotations
import sys
from datetime import datetime
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

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
        metadata={"source": "unit-test"},
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
    )


def test_prepare_trade_execution_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    prices = {"RELIANCE": Decimal("200")}
    stub_service = StubMarketDataService(prices)
    monkeypatch.setattr(trade_utils, "get_market_data_service", lambda: stub_service)

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


class FakeTradeExecutionLog:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    async def create(self, data: Dict[str, Any]) -> Any:
        row = dict(data)
        row.setdefault("id", row.get("request_id"))
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

    async def find_unique(self, where: Dict[str, Any]) -> Any:
        trade_id = where["id"]
        row = self.rows.get(trade_id)
        return SimpleNamespace(**row) if row else None


class FakeClient:
    def __init__(self) -> None:
        self.tradeexecutionlog = FakeTradeExecutionLog()


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


@pytest.mark.asyncio
async def test_trade_execution_service_persist_and_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_manager = FakeDBManager()
    monkeypatch.setattr(trade_execution_service, "get_db_manager", lambda: fake_manager)

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
        }
    ]

    events = await service.persist_and_publish(job_rows)
    assert len(events) == 1
    assert len(published_events) == 1
    record = await fake_manager.get_client().tradeexecutionlog.find_unique({"id": "req-1"})
    assert record.status == "pending"

    result = await service.execute_trade(events[0].trade_id, simulate=True)
    assert result["status"] == "simulated_executed"
    updated = await fake_manager.get_client().tradeexecutionlog.find_unique({"id": "req-1"})
    assert updated.status == "simulated_executed"


class FakePortfolioModel:
    def __init__(self, portfolios: List[Any]) -> None:
        self._portfolios = portfolios

    async def find_many(self, where=None, include=None):  # pragma: no cover - include unused
        return self._portfolios


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
    )

    fake_manager = FakePipelineManager([portfolio])
    monkeypatch.setattr("services.pipeline_service.get_db_manager", lambda: fake_manager, raising=False)

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
                )
                for row in rows
            ]

    monkeypatch.setattr("services.pipeline_service.TradeExecutionService", FakeTradeService, raising=False)

    dispatched: List[str] = []
    monkeypatch.setattr(
        "workers.trade_execution_tasks.execute_trade_job.delay",
        lambda trade_id: dispatched.append(trade_id),
        raising=False,
    )

    monkeypatch.setattr(PipelineService, "_load_environment", lambda self: None, raising=False)

    service = PipelineService(str(PORTFOLIO_SERVER_ROOT), logger=None)

    summary = await service._process_nse_trade_signals_async(
        signals=[{"symbol": "RELIANCE", "signal": 1, "confidence": 0.85}],
        publish_kafka=True,
    )

    assert summary == {
        "processed_signals": 1,
        "payloads": 1,
        "jobs": 1,
        "dispatched": 1,
    }
    assert len(persist_calls) == 1
    assert dispatched == ["req-1"]
    assert fake_manager.is_connected() is True

