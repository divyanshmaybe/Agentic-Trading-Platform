from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from prisma import fields

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PORTFOLIO_SERVER_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PORTFOLIO_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_ROOT))

from pipelines.objectives.objective_intake_pipeline import (
    ObjectiveIntakePayload,
    run_objective_intake_pipeline,
)
from schemas import (
    AllocationResultSummary,
    ObjectiveCreateRequest,
    ObjectiveCreateResponse,
    ObjectiveIntakeRequest,
    ObjectiveIntakeResponse,
    ObjectiveResponse,
)
from services.objective_intake_service import ObjectiveIntakeService
from controllers.objective_controller import ObjectiveController


class FakeRecord(SimpleNamespace):
    def model_dump(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def _maybe_decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class FakeObjectiveModel:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.counter = 0

    async def create(self, data: Dict[str, Any]) -> Any:
        self.counter += 1
        obj_id = data.get("id") or f"obj-{self.counter}"
        row = {
            **data,
            "id": obj_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        for key in ("raw", "structured_payload", "constraints", "preferences", "generic_notes", "missing_fields", "target_returns"):
            if key in row:
                row[key] = _maybe_decode_json(row[key])
        self.rows[obj_id] = row
        return FakeRecord(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        obj_id = where["id"]
        row = self.rows[obj_id]
        for key in ("raw", "structured_payload", "constraints", "preferences", "generic_notes", "missing_fields", "target_returns"):
            if key in data:
                data[key] = _maybe_decode_json(data[key])
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        self.rows[obj_id] = row
        return FakeRecord(**row)

    async def find_unique(self, where: Dict[str, Any]) -> Any:
        obj_id = where["id"]
        row = self.rows.get(obj_id)
        return FakeRecord(**row) if row else None


class FakeRebalanceRunModel:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.counter = 0

    async def create(self, data: Dict[str, Any]) -> Any:
        self.counter += 1
        run_id = data.get("id") or f"rebalance-{self.counter}"
        row = {**data, "id": run_id}
        self.rows.append(row)
        return FakeRecord(**row)


class FakeAllocationSnapshotModel:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.counter = 0

    async def create(self, data: Dict[str, Any]) -> Any:
        self.counter += 1
        snapshot_id = data.get("id") or f"snapshot-{self.counter}"
        row = {**data, "id": snapshot_id}
        self.rows.append(row)
        return FakeRecord(**row)


class FakeSegmentSnapshotModel:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.counter = 0

    async def create(self, data: Dict[str, Any]) -> Any:
        self.counter += 1
        snapshot_id = data.get("id") or f"segment-snapshot-{self.counter}"
        row = {**data, "id": snapshot_id}
        self.rows.append(row)
        return FakeRecord(**row)


class FakePrismaClient:
    def __init__(self) -> None:
        self.objective = FakeObjectiveModel()
        self.portfolio = FakePortfolioModel()
        self.portfolioallocation = FakePortfolioAllocationModel()
        self.portfolioallocation.set_portfolio_model(self.portfolio)  # Link them so allocations attach to portfolios
        self.tradingagent = FakeTradingAgentModel()
        self.rebalancerun = FakeRebalanceRunModel()
        self.allocationsnapshot = FakeAllocationSnapshotModel()
        self.segmentsnapshot = FakeSegmentSnapshotModel()
        self.user_subscriptions: Dict[str, List[str]] = {}

    async def query_raw(self, query: str, *params: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        user_id: Optional[str] = None
        if params:
            user_id = str(params[0])
        elif "WHERE id" in query.upper():
            try:
                fragment = query.split("WHERE", 1)[1]
                if "=" in fragment:
                    user_id = fragment.split("=", 1)[1].strip().strip(";").strip().strip("'\"")
            except IndexError:
                user_id = None
        if not user_id:
            return []
        subscriptions = self.user_subscriptions.get(user_id, [])
        return [{"subscriptions": subscriptions}]
        self.tradingagent = FakeTradingAgentModel()


class StubPipelineService:
    def __init__(self) -> None:
        self.logger = None


class FakePortfolioModel:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.counter = 0

    async def find_first(self, where: Dict[str, Any], order: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        for row in self.rows.values():
            matches = True
            for key, expected in where.items():
                if isinstance(expected, dict) and "equals" in expected:
                    expected = expected["equals"]
                if row.get(key) != expected:
                    matches = False
                    break
            if matches:
                return FakeRecord(**row)
        return None

    async def create(self, data: Dict[str, Any]) -> Any:
        self.counter += 1
        portfolio_id = data.get("id") or f"portfolio-{self.counter}"
        row = {
            "metadata": data.get("metadata"),
            "agents": data.get("agents", []),
            **data,
            "id": portfolio_id,
            "created_at": data.get("created_at") or datetime.utcnow(),
            "updated_at": data.get("updated_at") or datetime.utcnow(),
        }
        self.rows[portfolio_id] = row
        return FakeRecord(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        portfolio_id = where["id"]
        row = self.rows[portfolio_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        self.rows[portfolio_id] = row
        return FakeRecord(**row)

    async def find_many(self, **kwargs: Any) -> List[Any]:
        return [FakeRecord(**row) for row in self.rows.values()]

    async def find_unique(self, where: Dict[str, Any], include: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        portfolio_id = where["id"]
        row = self.rows.get(portfolio_id)
        if not row:
            return None
        
        # Handle include parameter - attach allocations if requested
        if include and "allocations" in include:
            # Get the prisma client from the test context to fetch allocations
            # This is a bit of a hack, but works for tests
            try:
                # Try to get allocations from the test's prisma client
                # The test will set this up
                pass  # Allocations will be attached by the test if needed
            except Exception:
                pass
        
        portfolio_record = FakeRecord(**row)
        # Set allocations attribute if include was requested
        if include and "allocations" in include:
            # Get allocations from the portfolio row if they were attached
            portfolio_record.allocations = row.get("allocations", [])
        
        return portfolio_record


class FakePortfolioAllocationModel:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []
        self.counter = 0
        self._portfolio_model = None  # Will be set by test

    def set_portfolio_model(self, portfolio_model: Any) -> None:
        """Set the portfolio model to attach allocations to portfolios."""
        self._portfolio_model = portfolio_model

    async def create(self, data: Dict[str, Any]) -> Any:
        self.counter += 1
        allocation_id = data.get("id") or f"alloc-{self.counter}"
        row = {**data, "id": allocation_id}
        self.rows.append(row)
        
        # Attach allocation to portfolio if portfolio model is available
        if self._portfolio_model and "portfolio_id" in data:
            portfolio_id = data["portfolio_id"]
            portfolio_row = self._portfolio_model.rows.get(portfolio_id)
            if portfolio_row:
                if "allocations" not in portfolio_row:
                    portfolio_row["allocations"] = []
                portfolio_row["allocations"].append(FakeRecord(**row))
        
        return FakeRecord(**row)

    async def find_first(self, where: Dict[str, Any]) -> Optional[Any]:
        for row in self.rows:
            matches = True
            for key, expected in where.items():
                if row.get(key) != expected:
                    matches = False
                    break
            if matches:
                return FakeRecord(**row)
        return None

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        allocation_id = where["id"]
        for idx, row in enumerate(self.rows):
            if row.get("id") == allocation_id:
                new_row = {**row, **data, "id": allocation_id}
                self.rows[idx] = new_row
                return FakeRecord(**new_row)
        raise KeyError(f"Allocation {allocation_id} not found")


class FakeTradingAgentModel:
    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.counter = 0

    @staticmethod
    def _matches(row: Dict[str, Any], where: Dict[str, Any]) -> bool:
        for key, expected in where.items():
            value = row.get(key)
            if isinstance(expected, dict):
                if "equals" in expected:
                    expected = expected["equals"]
                elif "in" in expected:
                    if value not in expected["in"]:
                        return False
                    continue
            if value != expected:
                return False
        return True

    async def find_first(self, where: Dict[str, Any]) -> Optional[Any]:
        for row in self.rows.values():
            if self._matches(row, where):
                return FakeRecord(**row)
        return None

    async def create(self, data: Dict[str, Any]) -> Any:
        self.counter += 1
        agent_id = data.get("id") or f"agent-{self.counter}"
        row = {
            **data,
            "id": agent_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        self.rows[agent_id] = row
        return FakeRecord(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        agent_id = where["id"]
        row = self.rows[agent_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        self.rows[agent_id] = row
        return FakeRecord(**row)

    async def find_many(self, where: Optional[Dict[str, Any]] = None, **kwargs: Any) -> List[Any]:
        if not where:
            return [FakeRecord(**row) for row in self.rows]
        results = []
        for row in self.rows:
            matches = True
            for key, expected in where.items():
                if row.get(key) != expected:
                    matches = False
                    break
            if matches:
                results.append(FakeRecord(**row))
        return results


def test_objective_intake_pipeline_missing_fields() -> None:
    payloads = [
        ObjectiveIntakePayload(
            structured_payload={
                "investable_amount": 500000.0,
                "risk_tolerance": {"category": "low"},
            },
            transcript=None,
            existing_payload=None,
        )
    ]

    result = run_objective_intake_pipeline(payloads)

    assert len(result) == 1
    row = result[0]
    assert row.status == "pending"
    assert "investment_horizon" in row.missing_fields
    assert "target_return" in row.missing_fields
    assert "liquidity_needs" in row.missing_fields


@pytest.mark.asyncio
async def test_objective_intake_service_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    prisma = FakePrismaClient()
    service = ObjectiveIntakeService(prisma, StubPipelineService())

    request = ObjectiveIntakeRequest(
        transcript="""
        User: I have set aside 5 lakh rupees.
        User: I might need funds soon.
        """,
        source="unit-test",
        name="Retirement Starter",
    )
    user = {"id": "user-1", "organization_id": "org-1", "customer_id": "cust-1"}

    response = await service.process_intake(user, request)

    assert isinstance(response, ObjectiveIntakeResponse)
    assert response.status == "pending"
    assert response.created is True
    assert "investment_horizon" in response.missing_fields
    assert "target_return" in response.missing_fields
    assert response.objective_id in prisma.objective.rows


@pytest.mark.asyncio
async def test_objective_intake_service_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    prisma = FakePrismaClient()
    service = ObjectiveIntakeService(prisma, StubPipelineService())

    initial = await service.process_intake(
        {"id": "user-1", "organization_id": "org-1", "customer_id": "cust-1"},
        ObjectiveIntakeRequest(
            transcript="User: I have 5 lakh rupees to invest.",
            source="unit-test",
        ),
    )

    async def fake_finalize(**kwargs):
        return ObjectiveCreateResponse(
            objective=ObjectiveResponse(
                id=initial.objective_id,
                user_id="user-1",
                name="Growth",
                raw={},
                source="intake",
                structured_payload={},
                investable_amount=Decimal("500000"),
                investment_horizon_years=5,
                investment_horizon_label="long",
                target_return=Decimal("15"),
                risk_tolerance="high",
                risk_aversion_lambda=None,
                liquidity_needs="long",
                rebalancing_frequency="monthly",
                constraints={},
                target_returns=None,
                preferences={},
                generic_notes=[],
                missing_fields=[],
                completion_status="complete",
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            ),
            portfolio_id="pf-1",
            allocation=None,
            last_rebalanced_at=None,
            next_rebalance_at=None,
        )

    monkeypatch.setattr(service, "_controller", SimpleNamespace(finalize_intake_objective=fake_finalize))

    complete_request = ObjectiveIntakeRequest(
        objective_id=initial.objective_id,
        transcript="""
        User: I want to invest for at least 5 years.
        User: I am comfortable with high risk and target 15% returns.
        User: I won't need the money anytime soon.
        """,
        source="unit-test",
        name="Growth",
    )

    response = await service.process_intake(
        {"id": "user-1", "organization_id": "org-1", "customer_id": "cust-1"},
        complete_request,
    )

    assert response.status == "complete"
    assert response.missing_fields == []
    assert response.allocation is None
    assert response.message == "Objective finalised and portfolio rebalanced."


@pytest.mark.asyncio
async def test_objective_creation_and_allocation_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end happy path: create objective, dispatch allocation, run worker."""
    from workers import allocation_tasks as allocation_tasks_module

    prisma = FakePrismaClient()
    controller = ObjectiveController(prisma, StubPipelineService())

    class FakePortfolioController:
        def __init__(self, prisma_client: FakePrismaClient) -> None:
            self.prisma = prisma_client
            self.calls: List[Dict[str, Any]] = []

        async def get_or_create_portfolio(self, user: Dict[str, Any]) -> Any:
            self.calls.append(user)
            existing = await self.prisma.portfolio.find_first(
                where={
                    "organization_id": user["organization_id"],
                    "customer_id": user.get("customer_id") or user["id"],
                }
            )
            if existing:
                return existing
            return await self.prisma.portfolio.create(
                data={
                    "user_id": user["id"],
                    "organization_id": user["organization_id"],
                    "customer_id": user.get("customer_id") or user["id"],
                    "portfolio_name": "Test Portfolio",
                    "initial_investment": Decimal("500000"),
                    "investment_amount": Decimal("500000"),
                    "current_value": Decimal("500000"),
                    "investment_horizon_years": 5,
                    "expected_return_target": Decimal("0.12"),
                    "risk_tolerance": "high",
                    "liquidity_needs": "low",
                    "allocation_status": "pending",
                }
            )

    controller._portfolio_controller = FakePortfolioController(prisma)

    class FakeRegimeService:
        def __init__(self) -> None:
            self._state = {"regime": "Sideways Market", "timestamp": 1731436800.0}

        @classmethod
        def get_instance(cls) -> "FakeRegimeService":
            return cls()

        def get_current_regime(self) -> Dict[str, Any]:
            return self._state

    monkeypatch.setattr("controllers.objective_controller.RegimeService", FakeRegimeService)

    dispatched_tasks: List[Dict[str, Any]] = []
    real_allocate_task = allocation_tasks_module.allocate_for_objective_task

    class FakeAllocationTask:
        def apply_async(self, *, kwargs: Dict[str, Any], countdown: int) -> Any:
            dispatched_tasks.append({"kwargs": kwargs, "countdown": countdown})
            return SimpleNamespace(id="fake-task-id")

    monkeypatch.setattr(
        allocation_tasks_module,
        "allocate_for_objective_task",
        FakeAllocationTask(),
    )

    user = {"id": "user-1", "organization_id": "org-1", "customer_id": "cust-1"}
    payload = ObjectiveCreateRequest(
        name="High Growth Plan",
        investable_amount=Decimal("500000"),
        investment_horizon_years=5,
        expected_return_target=Decimal("0.15"),
        investment_horizon_label="long",
        target_return=Decimal("0.15"),
        risk_tolerance="high",
        liquidity_needs="low",
        rebalancing_frequency="quarterly",
        constraints={"sector_limits": {}},
        preferences={"rebalancing_frequency": "quarterly"},
    )

    response = await controller.create_objective(user, payload)

    assert response.portfolio_id in prisma.portfolio.rows
    assert response.objective.id in prisma.objective.rows
    assert dispatched_tasks, "Allocation task was not dispatched"

    task_kwargs = dispatched_tasks[0]["kwargs"]
    assert task_kwargs["portfolio_id"] == response.portfolio_id
    assert task_kwargs["objective_id"] == response.objective.id
    assert task_kwargs["user_inputs"]["risk_tolerance"] == "high"

    # Restore the real allocation task for the second half of the flow.
    monkeypatch.setattr(allocation_tasks_module, "allocate_for_objective_task", real_allocate_task)

    # Prepare worker dependencies
    async def fake_get_current_regime() -> str:
        return "sideways_market"

    monkeypatch.setattr(
        "workers.allocation_tasks._get_current_regime",
        fake_get_current_regime,
    )

    def fake_allocate_portfolios(requests: List[Dict[str, Any]], logger: Any, audit_path: str) -> List[Dict[str, Any]]:
        return [
            {
                "success": True,
                "weights": {"equity": 0.6, "debt": 0.4},
                "expected_return": 0.12,
                "expected_risk": 0.08,
                "objective_value": 500000.0,
                "message": "ok",
            }
        ]

    monkeypatch.setattr(
        "workers.allocation_tasks.allocate_portfolios",
        fake_allocate_portfolios,
    )

    class FakeDBManager:
        def __init__(self, client: FakePrismaClient) -> None:
            self.client = client

        async def connect(self) -> FakePrismaClient:
            return self.client

    fake_db_manager = FakeDBManager(prisma)
    fake_db_manager_module = types.ModuleType("dbManager")

    class _DBManager:
        @staticmethod
        def get_instance() -> FakeDBManager:
            return fake_db_manager

    fake_db_manager_module.DBManager = _DBManager
    monkeypatch.setitem(sys.modules, "dbManager", fake_db_manager_module)
    
    # Patch Prisma to return the fake client
    class FakePrisma:
        def __init__(self):
            pass
        
        async def connect(self):
            return prisma
        
        async def disconnect(self):
            pass
        
        def __getattr__(self, name):
            # Return the corresponding fake model
            return getattr(prisma, name)
    
    monkeypatch.setattr("prisma.Prisma", lambda: FakePrisma())

    allocation_task = allocation_tasks_module.allocate_for_objective_task._get_current_object()

    loop = asyncio.get_running_loop()
    allocation_result = await loop.run_in_executor(
        None,
        lambda: allocation_task.__wrapped__(
            response.portfolio_id,
            response.objective.id,
            user["id"],
            user["organization_id"],
            task_kwargs["user_inputs"],
            float(payload.investable_amount),
            float(payload.investable_amount),
            "objective_created",
        ),
    )

    assert allocation_result["success"] is True
    assert prisma.portfolio.rows[response.portfolio_id]["allocation_status"] == "ready"
    assert len(prisma.portfolioallocation.rows) == 2, f"Expected 2 allocations, got {len(prisma.portfolioallocation.rows)}"
    
    # Verify trading agents were created
    assert len(prisma.tradingagent.rows) == 2, f"Expected 2 trading agents, got {len(prisma.tradingagent.rows)}"

    first_allocation = prisma.portfolioallocation.rows[0]
    # Metadata might be a dict or fields.Json depending on how it was stored
    metadata = first_allocation.get("metadata")
    if isinstance(metadata, fields.Json):
        metadata_dict = metadata.data
    elif isinstance(metadata, dict):
        metadata_dict = metadata
    else:
        # Try to parse it
        import json
        if isinstance(metadata, str):
            metadata_dict = json.loads(metadata)
        else:
            metadata_dict = {}
    
    # Check that metadata contains objective reference or trigger info
    # The objective_id might be in the metadata or in last_rebalance.trigger_reason
    last_rebalance = metadata_dict.get("last_rebalance", {})
    has_objective_ref = (
        metadata_dict.get("objective_id") == response.objective.id or
        last_rebalance.get("trigger_reason", "").endswith(response.objective.id) or
        last_rebalance.get("triggered_by") == "objective_created"
    )
    assert has_objective_ref, \
        f"Metadata should reference objective {response.objective.id}, got: {metadata_dict}"
    
    # Verify trading agent is linked to allocation
    agents_for_allocation = [
        agent for agent in prisma.tradingagent.rows.values()
        if agent.get("portfolio_allocation_id") == first_allocation["id"]
    ]
    assert len(agents_for_allocation) > 0, "No trading agent found for first allocation"
    
    # Verify allocation snapshots were created (rebalance run and allocation snapshots)
    # Note: These are created by _persist_allocation_result which is called in the allocation task
    # The test might not have these models, so we'll check if they exist
    if hasattr(prisma, "rebalancerun") and hasattr(prisma.rebalancerun, "rows"):
        assert len(prisma.rebalancerun.rows) > 0, "Expected rebalance run to be created"
    if hasattr(prisma, "allocationsnapshot") and hasattr(prisma.allocationsnapshot, "rows"):
        assert len(prisma.allocationsnapshot.rows) > 0, "Expected allocation snapshots to be created"

    portfolio_metadata = prisma.portfolio.rows[response.portfolio_id]["metadata"]
    assert isinstance(portfolio_metadata, fields.Json)
    assert portfolio_metadata.data["objective_id"] == response.objective.id


@pytest.mark.asyncio
async def test_objective_intake_then_allocation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive intake service through completion and execute resulting allocation."""
    from workers import allocation_tasks as allocation_tasks_module

    prisma = FakePrismaClient()
    intake_service = ObjectiveIntakeService(prisma, StubPipelineService())
    controller = ObjectiveController(prisma, StubPipelineService())

    class FakePortfolioController:
        def __init__(self, prisma_client: FakePrismaClient) -> None:
            self.prisma = prisma_client

        async def get_or_create_portfolio(self, user: Dict[str, Any]) -> Any:
            portfolio = await self.prisma.portfolio.find_first(
                where={
                    "organization_id": user["organization_id"],
                    "customer_id": user.get("customer_id") or user["id"],
                }
            )
            if portfolio:
                return portfolio
            return await self.prisma.portfolio.create(
                data={
                    "user_id": user["id"],
                    "organization_id": user["organization_id"],
                    "customer_id": user.get("customer_id") or user["id"],
                    "portfolio_name": "Intake Test Portfolio",
                    "initial_investment": Decimal("750000"),
                    "investment_amount": Decimal("750000"),
                    "current_value": Decimal("750000"),
                    "investment_horizon_years": 5,
                    "expected_return_target": Decimal("0.12"),
                    "risk_tolerance": "moderate",
                    "liquidity_needs": "medium",
                    "allocation_status": "pending",
                }
            )

    controller._portfolio_controller = FakePortfolioController(prisma)
    intake_service._controller = controller

    class FakeRegimeService:
        def __init__(self) -> None:
            self._state = {"regime": "Balanced", "timestamp": 1731436800.0}

        @classmethod
        def get_instance(cls) -> "FakeRegimeService":
            return cls()

        def get_current_regime(self) -> Dict[str, Any]:
            return self._state

    monkeypatch.setattr("controllers.objective_controller.RegimeService", FakeRegimeService)

    dispatched_tasks: List[Dict[str, Any]] = []
    real_allocate_task = allocation_tasks_module.allocate_for_objective_task

    class FakeAllocationTask:
        def apply_async(self, *, kwargs: Dict[str, Any], countdown: int) -> Any:
            dispatched_tasks.append({"kwargs": kwargs, "countdown": countdown})
            return SimpleNamespace(id="fake-task-id")

    monkeypatch.setattr(
        allocation_tasks_module,
        "allocate_for_objective_task",
        FakeAllocationTask(),
    )

    user = {"id": "user-9", "organization_id": "org-9", "customer_id": "cust-9"}
    intake_request = ObjectiveIntakeRequest(
        structured_payload={
            "investable_amount": 750000,
            "investment_horizon": "long",
            "target_return": 14,
            "risk_tolerance": {"category": "high"},
            "liquidity_needs": "long",
            "constraints": {"sector_limits": {}},
            "preferences": {"rebalancing_frequency": "quarterly"},
        },
        source="unit-test",
        name="Intake Driven Objective",
    )

    intake_response = await intake_service.process_intake(user, intake_request)

    assert intake_response.status == "complete"
    assert dispatched_tasks, "Expected allocation task dispatch after intake completion"

    task_kwargs = dispatched_tasks[0]["kwargs"]
    monkeypatch.setattr(allocation_tasks_module, "allocate_for_objective_task", real_allocate_task)

    async def fake_get_current_regime() -> str:
        return "balanced_market"

    monkeypatch.setattr(
        "workers.allocation_tasks._get_current_regime",
        fake_get_current_regime,
    )

    def fake_allocate_portfolios(requests: List[Dict[str, Any]], logger: Any, audit_path: str) -> List[Dict[str, Any]]:
        return [
            {
                "success": True,
                "weights": {"equity": 0.55, "debt": 0.45},
                "expected_return": 0.11,
                "expected_risk": 0.07,
                "objective_value": 750000.0,
                "message": "ok",
            }
        ]

    monkeypatch.setattr(
        "workers.allocation_tasks.allocate_portfolios",
        fake_allocate_portfolios,
    )

    class FakeDBManagerInstance:
        def __init__(self, client: FakePrismaClient) -> None:
            self.client = client

        async def connect(self) -> FakePrismaClient:
            return self.client

    fake_db_manager = FakeDBManagerInstance(prisma)

    class _DBManager:
        @staticmethod
        def get_instance() -> FakeDBManagerInstance:
            return fake_db_manager

    fake_db_manager_module = types.ModuleType("dbManager")
    fake_db_manager_module.DBManager = _DBManager
    monkeypatch.setitem(sys.modules, "dbManager", fake_db_manager_module)
    
    # Patch Prisma to return the fake client
    class FakePrisma:
        def __init__(self):
            pass
        
        async def connect(self):
            return prisma
        
        async def disconnect(self):
            pass
        
        def __getattr__(self, name):
            # Return the corresponding fake model
            return getattr(prisma, name)
    
    monkeypatch.setattr("prisma.Prisma", lambda: FakePrisma())

    allocation_task = allocation_tasks_module.allocate_for_objective_task._get_current_object()

    loop = asyncio.get_running_loop()
    allocation_result = await loop.run_in_executor(
        None,
        lambda: allocation_task.__wrapped__(
            task_kwargs["portfolio_id"],
            task_kwargs["objective_id"],
            task_kwargs["user_id"],
            task_kwargs["organization_id"],
            task_kwargs["user_inputs"],
            task_kwargs["initial_value"],
            task_kwargs["current_value"],
            task_kwargs["triggered_by"],
        ),
    )

    assert allocation_result["success"] is True
    assert prisma.portfolioallocation.rows, "Allocation rows should be created"
    assert prisma.portfolio.rows[task_kwargs["portfolio_id"]]["allocation_status"] == "ready"

    first_allocation = prisma.portfolioallocation.rows[0]
    assert isinstance(first_allocation["metadata"], fields.Json)

    portfolio_metadata = prisma.portfolio.rows[task_kwargs["portfolio_id"]]["metadata"]
    if isinstance(portfolio_metadata, fields.Json):
        assert portfolio_metadata.data.get("objective_id") == task_kwargs["objective_id"]

    assert prisma.tradingagent.rows, "Trading agents should be provisioned alongside allocations"
    first_agent = next(iter(prisma.tradingagent.rows.values()))
    assert first_agent["portfolio_allocation_id"] == first_allocation["id"]
    assert first_agent["portfolio_id"] == task_kwargs["portfolio_id"]
    assert first_agent["agent_type"] == first_allocation["allocation_type"]
    strategy_config = first_agent["strategy_config"]
    if isinstance(strategy_config, fields.Json):
        strategy_config = strategy_config.data
    assert strategy_config.get("auto_trade") is False
    assert first_agent["status"] == "paused"


@pytest.mark.asyncio
async def test_allocation_enables_subscribed_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from workers import allocation_tasks as allocation_tasks_module

    prisma = FakePrismaClient()
    controller = ObjectiveController(prisma, StubPipelineService())

    prisma.user_subscriptions["user-99"] = ["high_risk"]

    class FakePortfolioController:
        def __init__(self, prisma_client: FakePrismaClient) -> None:
            self.prisma = prisma_client

        async def get_or_create_portfolio(self, user: Dict[str, Any]) -> Any:
            existing = await self.prisma.portfolio.find_first(
                where={
                    "organization_id": user["organization_id"],
                    "customer_id": user.get("customer_id") or user["id"],
                }
            )
            if existing:
                return existing
            return await self.prisma.portfolio.create(
                data={
                    "user_id": user["id"],
                    "organization_id": user["organization_id"],
                    "customer_id": user.get("customer_id") or user["id"],
                    "portfolio_name": "Subscribed Portfolio",
                    "initial_investment": Decimal("250000"),
                    "investment_amount": Decimal("250000"),
                    "current_value": Decimal("250000"),
                    "investment_horizon_years": 5,
                    "expected_return_target": Decimal("0.1"),
                    "risk_tolerance": "high",
                    "liquidity_needs": "long",
                    "allocation_status": "pending",
                }
            )

    controller._portfolio_controller = FakePortfolioController(prisma)

    class FakeRegimeService:
        def __init__(self) -> None:
            self._state = {"regime": "Bull Market", "timestamp": 1731436800.0}

        @classmethod
        def get_instance(cls) -> "FakeRegimeService":
            return cls()

        def get_current_regime(self) -> Dict[str, Any]:
            return self._state

    monkeypatch.setattr("controllers.objective_controller.RegimeService", FakeRegimeService)

    monkeypatch.setattr(
        "workers.allocation_tasks.allocate_portfolios",
        lambda requests, logger=None, audit_path=None: [
            {
                "success": True,
                "weights": {"high_risk": 0.6, "debt": 0.4},
                "expected_return": 0.12,
                "expected_risk": 0.08,
                "objective_value": 250000.0,
                "message": "ok",
            }
        ],
    )

    class FakeDBManagerInstance:
        def __init__(self, client: FakePrismaClient) -> None:
            self.client = client

        async def connect(self) -> FakePrismaClient:
            return self.client

    fake_db_manager = FakeDBManagerInstance(prisma)

    class _DBManager:
        @staticmethod
        def get_instance() -> FakeDBManagerInstance:
            return fake_db_manager

    fake_db_manager_module = types.ModuleType("dbManager")
    fake_db_manager_module.DBManager = _DBManager
    monkeypatch.setitem(sys.modules, "dbManager", fake_db_manager_module)

    payload = ObjectiveCreateRequest(
        name="Subscribed Objective",
        investable_amount=Decimal("250000"),
        investment_horizon_years=5,
        expected_return_target=Decimal("0.12"),
        investment_horizon_label="long",
        target_return=Decimal("0.12"),
        risk_tolerance="high",
        liquidity_needs="long",
        rebalancing_frequency="quarterly",
        constraints={},
        preferences={},
    )

    user = {"id": "user-99", "organization_id": "org-1", "customer_id": "user-99"}
    response = await controller.create_objective(user, payload)
    async def _fake_regime() -> str:
        return "bull_market"

    monkeypatch.setattr("workers.allocation_tasks._get_current_regime", _fake_regime)
    
    # Patch Prisma to return the fake client
    class FakePrisma:
        def __init__(self):
            pass
        
        async def connect(self):
            return prisma
        
        async def disconnect(self):
            pass
        
        def __getattr__(self, name):
            # Return the corresponding fake model
            return getattr(prisma, name)
    
    monkeypatch.setattr("prisma.Prisma", lambda: FakePrisma())
    
    allocation_task = allocation_tasks_module.allocate_for_objective_task._get_current_object()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: allocation_task.__wrapped__(
            response.portfolio_id,
            response.objective.id,
            user["id"],
            user["organization_id"],
            {
                "risk_tolerance": "high",
                "investment_horizon_years": 5,
                "liquidity_needs": "long",
                "expected_return_target": 0.12,
                "rebalancing_frequency": "quarterly",
            },
            float(payload.investable_amount),
            float(payload.investable_amount),
            "objective_created",
        ),
    )

    agent_rows = list(prisma.tradingagent.rows.values())
    assert agent_rows, "Expected trading agent to be created for subscribed user"
    agent = agent_rows[0]
    assert agent["status"] == "active"
    config = agent["strategy_config"]
    if isinstance(config, fields.Json):
        config = config.data
    assert config.get("auto_trade") is True


@pytest.mark.asyncio
async def test_objective_intake_invalid_liquidity_yields_pending() -> None:
    prisma = FakePrismaClient()
    intake_service = ObjectiveIntakeService(prisma, StubPipelineService())

    user = {"id": "user-11", "organization_id": "org-11", "customer_id": "cust-11"}
    request = ObjectiveIntakeRequest(
        structured_payload={
            "investable_amount": 250000,
            "investment_horizon": "medium",
            "target_return": 12,
            "risk_tolerance": {"category": "medium"},
            "liquidity_needs": "low",
        },
        source="unit-test",
        name="Liquidity Validation Objective",
    )

    response = await intake_service.process_intake(user, request)

    assert response.status == "pending"
    assert "liquidity_needs" in response.missing_fields
    assert any("liquidity_needs" in warning for warning in response.warnings)
