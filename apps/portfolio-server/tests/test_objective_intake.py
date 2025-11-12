from __future__ import annotations

import sys
from datetime import datetime
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

from pipelines.objectives.objective_intake_pipeline import (
    ObjectiveIntakePayload,
    run_objective_intake_pipeline,
)
from schemas import (
    AllocationResultSummary,
    ObjectiveCreateResponse,
    ObjectiveIntakeRequest,
    ObjectiveIntakeResponse,
    ObjectiveResponse,
)
from services.objective_intake_service import ObjectiveIntakeService


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
        self.rows[obj_id] = row
        return SimpleNamespace(**row)

    async def update(self, where: Dict[str, Any], data: Dict[str, Any]) -> Any:
        obj_id = where["id"]
        row = self.rows[obj_id]
        row.update(data)
        row["updated_at"] = datetime.utcnow()
        self.rows[obj_id] = row
        return SimpleNamespace(**row)

    async def find_unique(self, where: Dict[str, Any]) -> Any:
        obj_id = where["id"]
        row = self.rows.get(obj_id)
        return SimpleNamespace(**row) if row else None


class FakePrismaClient:
    def __init__(self) -> None:
        self.objective = FakeObjectiveModel()


class StubPipelineService:
    def __init__(self) -> None:
        self.logger = None


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

    allocation_summary = AllocationResultSummary(
        weights={"NIFTYBEES": 0.6, "BANKBEES": 0.4},
        expected_return=0.12,
        expected_risk=0.08,
        objective_value=0.0,
        message="Allocation complete",
        regime="bull",
        progress_ratio=1.0,
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
            allocation=allocation_summary,
            last_rebalanced_at=datetime.utcnow(),
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
    assert response.allocation == allocation_summary
    assert response.message == "Objective finalised and portfolio rebalanced."

