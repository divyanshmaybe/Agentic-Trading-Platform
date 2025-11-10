from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from prisma import Prisma

from controllers.portfolio_controller import PortfolioController
from schemas import (
    AllocationResultSummary,
    ObjectiveCreateRequest,
    ObjectiveCreateResponse,
    ObjectiveResponse,
)
from services.pipeline_service import PipelineService
from services.regime_service import RegimeService


class ObjectiveController:
    """Business logic for managing user investment objectives."""

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
        self._portfolio_controller = PortfolioController(prisma)

    async def create_objective(
        self,
        user: Dict[str, Any],
        payload: ObjectiveCreateRequest,
    ) -> ObjectiveCreateResponse:
        """Create a new objective for the user and trigger an immediate allocation."""

        user_id = user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authenticated user id is required to create objectives.",
            )

        organization_id = user.get("organization_id")
        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not associated with an organization; cannot create objective.",
            )

        customer_id = user.get("customer_id") or user_id

        # Ensure the portfolio exists (or create it with sensible defaults).
        portfolio_response = await self._portfolio_controller.get_or_create_portfolio(
            {
                "id": user_id,
                "organization_id": organization_id,
                "customer_id": customer_id,
                "role": user.get("role"),
            }
        )
        portfolio_id = portfolio_response.id

        # Resolve current regime from the streaming classifier.
        regime_label = "sideways"
        regime_timestamp = None
        try:
            regime_service = RegimeService.get_instance()
            regime_state = regime_service.get_current_regime()
            if regime_state and regime_state.get("regime"):
                regime_label = str(regime_state["regime"]).lower()
                regime_timestamp = regime_state.get("timestamp")
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.warning(
                "Regime service unavailable while creating objective for user %s: %s",
                user_id,
                exc,
            )

        self.logger.info(
            "Creating objective for user %s (portfolio %s, regime=%s)",
            user_id,
            portfolio_id,
            regime_label,
        )

        # Persist the objective record.
        objective = await self.prisma.objective.create(
            data={
                "user_id": user_id,
                "name": payload.name,
                "raw": payload.raw or {},
                "investable_amount": payload.investable_amount,
                "investment_horizon_years": payload.investment_horizon_years,
                "liquidity_needs": payload.liquidity_needs,
                "rebalancing_frequency": (
                    payload.rebalancing_frequency
                    if isinstance(payload.rebalancing_frequency, str)
                    else json.dumps(payload.rebalancing_frequency)
                    if payload.rebalancing_frequency is not None
                    else None
                ),
                "constraints": payload.constraints or {},
                "target_returns": payload.target_returns or [],
                "status": "active",
            }
        )

        # Update the associated portfolio with objective-driven preferences.
        await self._apply_objective_to_portfolio(
            portfolio_id=portfolio_id,
            objective_id=objective.id,
            payload=payload,
            current_regime=regime_label,
            regime_timestamp=regime_timestamp,
        )

        allocation_summary = None
        allocation_meta: Dict[str, Any] | None = None
        try:
            allocation_meta = await self.pipeline_service.rebalance_portfolio(
                portfolio_id=portfolio_id,
                triggered_by="objective_create",
                regime_override=regime_label,
                trigger_reason="objective_created",
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.exception(
                "Allocation pipeline failed during objective creation for portfolio %s: %s",
                portfolio_id,
                exc,
            )

        last_rebalanced_at: Optional[datetime] = None
        next_rebalance_at: Optional[datetime] = None

        if allocation_meta and allocation_meta.get("processed"):
            allocation_payload = allocation_meta.get("allocation") or {}
            allocation_summary = AllocationResultSummary(
                weights=self._coerce_weight_map(allocation_payload.get("weights", {})),
                expected_return=self._safe_float(allocation_payload.get("expected_return")),
                expected_risk=self._safe_float(allocation_payload.get("expected_risk")),
                objective_value=self._safe_float(allocation_payload.get("objective_value")),
                message=allocation_payload.get("message"),
                regime=allocation_payload.get("regime") or regime_label,
                progress_ratio=self._safe_float(allocation_payload.get("progress_ratio")),
            )

            last_rebalanced_at = allocation_meta.get("last_rebalanced_at")
            next_rebalance_at = allocation_meta.get("next_rebalance_at")

        objective_response = ObjectiveResponse.model_validate(objective)

        return ObjectiveCreateResponse(
            objective=objective_response,
            portfolio_id=portfolio_id,
            allocation=allocation_summary,
            last_rebalanced_at=last_rebalanced_at,
            next_rebalance_at=next_rebalance_at,
        )

    async def _apply_objective_to_portfolio(
        self,
        *,
        portfolio_id: str,
        objective_id: str,
        payload: ObjectiveCreateRequest,
        current_regime: str,
        regime_timestamp: Optional[float],
    ) -> None:
        """Update portfolio properties based on the freshly created objective."""

        portfolio = await self.prisma.portfolio.find_unique(where={"id": portfolio_id})
        if portfolio is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Portfolio {portfolio_id} not found while linking objective.",
            )

        metadata = {}
        if isinstance(portfolio.metadata, dict):
            metadata.update(portfolio.metadata)

        metadata["current_regime"] = current_regime
        if regime_timestamp:
            metadata["regime_timestamp"] = regime_timestamp
        metadata["objective_reference"] = {
            "objective_id": objective_id,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "investable_amount": float(payload.investable_amount),
            "risk_tolerance": payload.risk_tolerance,
            "expected_return_target": self._safe_float(payload.expected_return_target),
        }

        if payload.metadata:
            existing_meta = metadata.get("objective_metadata")
            if isinstance(existing_meta, dict):
                existing_meta.update(payload.metadata)
                metadata["objective_metadata"] = existing_meta
            else:
                metadata["objective_metadata"] = dict(payload.metadata)

        update_data: Dict[str, Any] = {
            "objective_id": objective_id,
            "metadata": metadata,
            "investment_horizon_years": payload.investment_horizon_years,
        }

        if isinstance(payload.investable_amount, Decimal):
            update_data["investment_amount"] = payload.investable_amount
            update_data["initial_investment"] = payload.investable_amount
            update_data["current_value"] = payload.investable_amount

        if payload.expected_return_target is not None:
            update_data["expected_return_target"] = payload.expected_return_target

        if payload.risk_tolerance:
            update_data["risk_tolerance"] = payload.risk_tolerance

        if payload.liquidity_needs:
            update_data["liquidity_needs"] = payload.liquidity_needs

        if payload.rebalancing_frequency is not None:
            update_data["rebalancing_frequency"] = payload.rebalancing_frequency

        if payload.constraints:
            update_data["constraints"] = payload.constraints

        await self.prisma.portfolio.update(
            where={"id": portfolio_id},
            data=update_data,
        )

    @staticmethod
    def _coerce_weight_map(weights: Dict[str, Any]) -> Dict[str, float]:
        return {str(key): float(value) for key, value in weights.items()}

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            if isinstance(value, Decimal):
                return float(value)
            return float(value)
        except (TypeError, ValueError):
            return None

