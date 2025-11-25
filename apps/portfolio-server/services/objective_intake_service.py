from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from prisma import Prisma

from controllers.objective_controller import ObjectiveController
from pipelines.objectives.objective_intake_pipeline import (
    ObjectiveIntakePayload,
    run_objective_intake_pipeline,
)
from schemas import (
    ObjectiveCreateRequest,
    ObjectiveIntakeRequest,
    ObjectiveIntakeResponse,
)
from services.pipeline_service import PipelineService
from utils.objective_intake import merge_structured_payload


def _as_decimal(value: Optional[float]) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


def _horizon_to_years(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        mapping = {"short": 1, "medium": 3, "long": 5}
        if value.lower() in mapping:
            return mapping[value.lower()]
        if "year" in value.lower():
            digits = "".join(ch for ch in value if ch.isdigit())
            if digits:
                return int(digits)
    return None


def _extract_risk_tolerance(payload: Dict[str, Any]) -> Optional[str]:
    risk = payload.get("risk_tolerance")
    if isinstance(risk, dict):
        category = risk.get("category")
        if isinstance(category, str):
            return category.lower()
    if isinstance(risk, str):
        return risk.lower()
    return None


def _extract_risk_lambda(payload: Dict[str, Any]) -> Optional[Decimal]:
    risk = payload.get("risk_tolerance")
    if isinstance(risk, dict):
        value = risk.get("risk_aversion_lambda")
        if value is not None:
            return Decimal(str(value))
    return None


def _build_create_request(
    *,
    intake_payload: Dict[str, Any],
    objective_name: Optional[str],
    raw_payload: Dict[str, Any],
) -> ObjectiveCreateRequest:
    investable_amount = intake_payload.get("investable_amount")
    if investable_amount is None:
        raise ValueError("investable_amount missing from intake payload.")

    liquidity_needs = intake_payload.get("liquidity_needs")
    target_return_pct = intake_payload.get("target_return")
    investment_horizon = intake_payload.get("investment_horizon")
    constraints = intake_payload.get("constraints", {})
    preferences = intake_payload.get("preferences", {})
    generic_notes = intake_payload.get("generic_notes", [])

    risk_tolerance = _extract_risk_tolerance(intake_payload)
    risk_lambda = _extract_risk_lambda(intake_payload)
    horizon_years = _horizon_to_years(investment_horizon)

    expected_return_target = (
        Decimal(str(target_return_pct)) / Decimal("100")
        if target_return_pct is not None
        else None
    )

    return ObjectiveCreateRequest(
        name=objective_name,
        investable_amount=Decimal(str(investable_amount)),
        investment_horizon_years=horizon_years or 1,
        investment_horizon_label=investment_horizon if isinstance(investment_horizon, str) else None,
        expected_return_target=expected_return_target,
        target_return=_as_decimal(target_return_pct),
        risk_tolerance=risk_tolerance,
        risk_aversion_lambda=risk_lambda,
        liquidity_needs=liquidity_needs,
        rebalancing_frequency=preferences.get("rebalancing_frequency"),
        constraints=constraints,
        target_returns=None,
        raw=raw_payload,
        preferences=preferences,
        generic_notes=generic_notes,
    )


class ObjectiveIntakeService:
    """Coordinates the interactive objective intake workflow."""

    def __init__(
        self,
        prisma: Prisma,
        pipeline_service: PipelineService,
        *,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.prisma = prisma
        self.pipeline_service = pipeline_service
        self.logger = logger or logging.getLogger(__name__)
        self._controller = ObjectiveController(
            prisma, pipeline_service, logger=self.logger
        )

    @staticmethod
    def _prepare_json_field(value: Any) -> str:
        """
        Prepare a value for Prisma JSON field by converting to JSON string.
        Converts Decimals to floats while preserving dict/list structure.
        Returns a JSON string representation.
        """
        def _encode_value(val: Any) -> Any:
            if val is None:
                return None
            if isinstance(val, Decimal):
                return float(val)
            if isinstance(val, dict):
                return {k: _encode_value(v) for k, v in val.items()}
            if isinstance(val, list):
                return [_encode_value(item) for item in val]
            if isinstance(val, (str, int, float, bool)):
                return val
            # For other types, try jsonable_encoder
            return jsonable_encoder(val)
        
        prepared = _encode_value(value)
        return json.dumps(prepared)

    async def process_intake(
        self,
        user: Dict[str, Any],
        request: ObjectiveIntakeRequest,
    ) -> ObjectiveIntakeResponse:
        user_id = user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authenticated user id is required.",
            )

        if not request.transcript and not request.structured_payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either transcript or structured_payload must be provided.",
            )

        objective_record = None
        created = False
        if request.objective_id:
            objective_record = await self.prisma.objective.find_unique(
                where={"id": request.objective_id}
            )
            if not objective_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Objective {request.objective_id} not found.",
                )
            if objective_record.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Objective does not belong to the authenticated user.",
                )
        else:
            # Check if user already has an active objective
            existing_objective = await self.prisma.objective.find_first(
                where={
                    "user_id": user_id,
                    "status": "active",
                }
            )
            if existing_objective:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You already have an active objective. Please update or deactivate your existing objective before creating a new one.",
                )
            
            # Create new objective - omit JSON fields with defaults to avoid Prisma type errors
            from prisma import fields
            objective_record = await self.prisma.objective.create(
                data={
                    "user_id": user_id,
                    "name": request.name,
                    "source": request.source or "intake",
                    "completion_status": "pending",
                    "status": "draft",
                    "sector_constraints": fields.Json({}),
                }
            )
            created = True

        existing_payload = getattr(objective_record, "structured_payload", None) or {}
        overlay_payload = request.structured_payload or {}

        pipeline_result = run_objective_intake_pipeline(
            [
                ObjectiveIntakePayload(
                    structured_payload=overlay_payload,
                    transcript=request.transcript,
                    existing_payload=existing_payload,
                )
            ]
        )[0]

        completion_status = (
            "complete" if not pipeline_result.missing_fields else "pending"
        )

        base_raw = getattr(objective_record, "raw", None) or {}
        if isinstance(base_raw, str):
            try:
                base_raw = json.loads(base_raw)
            except json.JSONDecodeError:
                base_raw = {}
        updated_raw = merge_structured_payload(
            base_raw,
            {"structured": pipeline_result.structured_payload},
        )
        if request.transcript:
            history = updated_raw.get("transcripts", [])
            history.append(
                {
                    "captured_at": datetime.utcnow().isoformat() + "Z",
                    "text": request.transcript,
                }
            )
            updated_raw["transcripts"] = history

        if request.metadata:
            updated_raw["metadata"] = merge_structured_payload(
                updated_raw.get("metadata") or {}, request.metadata
            )

        update_payload: Dict[str, Any] = {
            "name": request.name or getattr(objective_record, "name", None),
            "structured_payload": self._prepare_json_field(pipeline_result.structured_payload),
            "raw": self._prepare_json_field(updated_raw),
            "missing_fields": self._prepare_json_field(pipeline_result.missing_fields),  # Already a list of strings
            "completion_status": completion_status,
            "source": request.source
            or getattr(objective_record, "source", None)
            or "intake",
            "preferences": self._prepare_json_field(
                pipeline_result.structured_payload.get("preferences") or {}
            ),
            "constraints": self._prepare_json_field(
                pipeline_result.structured_payload.get("constraints") or {}
            ),
            "generic_notes": self._prepare_json_field(pipeline_result.structured_payload.get("generic_notes") or []),
        }

        # Update optional scalar fields where data exists
        investable_amount = pipeline_result.structured_payload.get("investable_amount")
        if investable_amount is not None:
            update_payload["investable_amount"] = Decimal(str(investable_amount))
        horizon_years = _horizon_to_years(
            pipeline_result.structured_payload.get("investment_horizon")
        )
        if horizon_years is not None:
            update_payload["investment_horizon_years"] = horizon_years
        if isinstance(
            pipeline_result.structured_payload.get("investment_horizon"), str
        ):
            update_payload["investment_horizon_label"] = pipeline_result.structured_payload.get(
                "investment_horizon"
            )
        target_return_pct = pipeline_result.structured_payload.get("target_return")
        if target_return_pct is not None:
            update_payload["target_return"] = Decimal(str(target_return_pct))
        update_payload["risk_tolerance"] = _extract_risk_tolerance(
            pipeline_result.structured_payload
        )
        risk_lambda = _extract_risk_lambda(pipeline_result.structured_payload)
        if risk_lambda is not None:
            update_payload["risk_aversion_lambda"] = risk_lambda
        liquidity_needs = pipeline_result.structured_payload.get("liquidity_needs")
        if liquidity_needs:
            update_payload["liquidity_needs"] = liquidity_needs
        rebalancing_frequency = pipeline_result.structured_payload.get("preferences", {}).get(
            "rebalancing_frequency"
        )
        if rebalancing_frequency:
            update_payload["rebalancing_frequency"] = rebalancing_frequency

        objective_record = await self.prisma.objective.update(
            where={"id": objective_record.id},
            data=update_payload,
        )

        response = ObjectiveIntakeResponse(
            objective_id=objective_record.id,
            status=completion_status,
            missing_fields=pipeline_result.missing_fields,
            structured_payload=pipeline_result.structured_payload,
            warnings=pipeline_result.warnings,
            created=created,
        )

        if completion_status == "pending":
            response.message = (
                "Additional information required for fields: "
                + ", ".join(pipeline_result.missing_fields)
            )

        if completion_status == "complete":
            create_request = _build_create_request(
                intake_payload=pipeline_result.structured_payload,
                objective_name=objective_record.name,
                raw_payload=pipeline_result.structured_payload,
            )
            finalize_response = await self._controller.finalize_intake_objective(
                user=user,
                objective_id=objective_record.id,
                payload=create_request,
                structured_payload=pipeline_result.structured_payload,
                source=request.source or "intake",
                metadata=request.metadata,
            )
            response.status = "complete"
            response.message = "Objective finalised and portfolio rebalanced."
            response.completion_timestamp = datetime.utcnow()
            response.structured_payload = pipeline_result.structured_payload
            response.missing_fields = []
            response.warnings = pipeline_result.warnings

            # Augment raw response with allocation summary
            if finalize_response.allocation:
                response.allocation = finalize_response.allocation

        return response

