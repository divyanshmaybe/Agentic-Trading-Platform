from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
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
        self._portfolio_controller = PortfolioController(prisma, logger=self.logger)
        self._json_encoder = {
            Decimal: lambda v: float(v),
        }

    def _encode_json(self, value: Any) -> str:
        """
        Recursively prepare a value for Prisma JSON fields by converting nested
        Decimal values to floats while preserving dict/list structure.
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
            return jsonable_encoder(val, custom_encoder=self._json_encoder)

        return json.dumps(_encode_value(value))

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
        structured_payload = payload.raw or {}
        preferences = payload.preferences or {}
        generic_notes = payload.generic_notes or []

        objective = await self.prisma.objective.create(
            data={
                "user_id": user_id,
                "name": payload.name,
                "raw": self._encode_json(structured_payload),
                "structured_payload": self._encode_json(structured_payload),
                "source": "api:create",
                "investable_amount": payload.investable_amount,
                "investment_horizon_years": payload.investment_horizon_years,
                "investment_horizon_label": payload.investment_horizon_label,
                "target_return": payload.target_return,
                "target_returns": self._encode_json(payload.target_returns or []),
                "risk_tolerance": payload.risk_tolerance,
                "risk_aversion_lambda": payload.risk_aversion_lambda,
                "liquidity_needs": payload.liquidity_needs,
                "rebalancing_frequency": (
                    payload.rebalancing_frequency
                    if isinstance(payload.rebalancing_frequency, str)
                    else json.dumps(payload.rebalancing_frequency)
                    if payload.rebalancing_frequency is not None
                    else None
                ),
                "preferences": self._encode_json(preferences),
                "constraints": self._encode_json(payload.constraints or {}),
                "generic_notes": self._encode_json(generic_notes),
                "missing_fields": self._encode_json([]),
                "completion_status": "complete",
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
        
        # Dispatch allocation to Celery worker instead of running synchronously
        try:
            from workers.allocation_tasks import allocate_for_objective_task
            from utils.user_inputs_helper import extract_user_inputs_from_objective
            
            # Build user inputs from objective (matching transcript.py format)
            user_inputs = extract_user_inputs_from_objective(objective)
            
            # Dispatch to Celery worker
            task = allocate_for_objective_task.apply_async(
                kwargs={
                    "portfolio_id": portfolio_id,
                    "objective_id": objective.id,
                    "user_id": user_id,
                    "user_inputs": user_inputs,
                    "initial_value": float(payload.investable_amount),
                    "available_cash": float(payload.investable_amount),
                    "triggered_by": "objective_created",
                },
                countdown=2,  # Delay by 2 seconds to ensure DB commit
            )
            
            self.logger.info(
                f"✅ Dispatched allocation for portfolio {portfolio_id} to Celery "
                f"(task_id={task.id}, objective={objective.id})"
            )
            
            # Return metadata indicating allocation is pending
            allocation_meta = {
                "processed": False,
                "pending": True,
                "task_id": task.id,
                "message": "Portfolio allocation dispatched to background worker",
            }
            
        except Exception as exc:
            self.logger.exception(
                "Failed to dispatch allocation task for objective %s: %s",
                objective.id,
                exc,
            )

        last_rebalanced_at: Optional[datetime] = None
        next_rebalance_at: Optional[datetime] = None

        # Only process allocation summary if it's already been completed
        # For async allocations, the summary will be None and that's okay
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
        elif allocation_meta and allocation_meta.get("pending"):
            # Allocation is pending in background worker
            self.logger.info(
                f"Allocation for portfolio {portfolio_id} is pending "
                f"(task_id={allocation_meta.get('task_id')})"
            )

        objective_response = ObjectiveResponse.model_validate(objective.model_dump())

        return ObjectiveCreateResponse(
            objective=objective_response,
            portfolio_id=portfolio_id,
            allocation=allocation_summary,
            last_rebalanced_at=last_rebalanced_at,
            next_rebalance_at=next_rebalance_at,
        )

    async def finalize_intake_objective(
        self,
        *,
        user: Dict[str, Any],
        objective_id: str,
        payload: ObjectiveCreateRequest,
        structured_payload: Dict[str, Any],
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ObjectiveCreateResponse:
        """Finalize an intake objective after collecting all mandatory fields."""

        user_id = user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Authenticated user id is required to finalise objectives.",
            )

        objective = await self.prisma.objective.find_unique(where={"id": objective_id})
        if not objective:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Objective {objective_id} not found.",
            )

        if objective.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Objective does not belong to the authenticated user.",
            )

        organization_id = user.get("organization_id")
        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not associated with an organization; cannot finalise objective.",
            )

        customer_id = user.get("customer_id") or user_id

        portfolio_response = await self._portfolio_controller.get_or_create_portfolio(
            {
                "id": user_id,
                "organization_id": organization_id,
                "customer_id": customer_id,
                "role": user.get("role"),
            }
        )
        portfolio_id = portfolio_response.id

        regime_label = "sideways"
        regime_timestamp = None
        try:
            regime_service = RegimeService.get_instance()
            regime_state = regime_service.get_current_regime()
            if regime_state and regime_state.get("regime"):
                regime_label = str(regime_state["regime"]).lower()
                regime_timestamp = regime_state.get("timestamp")
        except Exception as exc:  # pragma: no cover
            self.logger.warning(
                "Regime service unavailable while finalising objective %s: %s",
                objective_id,
                exc,
            )

        preferences = payload.preferences or {}
        generic_notes = payload.generic_notes or []

        combined_raw = dict(structured_payload)
        if metadata:
            combined_raw = {**combined_raw, "metadata": metadata}

        updated_objective = await self.prisma.objective.update(
            where={"id": objective_id},
            data={
                "name": payload.name,
                "raw": self._encode_json(combined_raw),
                "structured_payload": self._encode_json(structured_payload),
                "source": source or objective.source or "intake",
                "investable_amount": payload.investable_amount,
                "investment_horizon_years": payload.investment_horizon_years,
                "investment_horizon_label": payload.investment_horizon_label,
                "target_return": payload.target_return,
                "target_returns": self._encode_json(payload.target_returns or []),
                "risk_tolerance": payload.risk_tolerance,
                "risk_aversion_lambda": payload.risk_aversion_lambda,
                "liquidity_needs": payload.liquidity_needs,
                "rebalancing_frequency": (
                    payload.rebalancing_frequency
                    if isinstance(payload.rebalancing_frequency, str)
                    else json.dumps(payload.rebalancing_frequency)
                    if payload.rebalancing_frequency is not None
                    else None
                ),
                "constraints": self._encode_json(payload.constraints or {}),
                "preferences": self._encode_json(preferences),
                "generic_notes": self._encode_json(generic_notes),
                "missing_fields": self._encode_json([]),
                "completion_status": "complete",
                "status": "active",
            },
        )

        allocation_summary = None
        allocation_meta: Dict[str, Any] | None = None

        await self._apply_objective_to_portfolio(
            portfolio_id=portfolio_id,
            objective_id=objective_id,
            payload=payload,
            current_regime=regime_label,
            regime_timestamp=regime_timestamp,
        )

        # Dispatch allocation to Celery worker instead of running synchronously
        try:
            from workers.allocation_tasks import allocate_for_objective_task
            from utils.user_inputs_helper import extract_user_inputs_from_objective
            
            # Build user inputs from updated objective (matching transcript.py format)
            user_inputs = extract_user_inputs_from_objective(updated_objective)
            
            # Dispatch to Celery worker
            task = allocate_for_objective_task.apply_async(
                kwargs={
                    "portfolio_id": portfolio_id,
                    "objective_id": objective_id,
                    "user_id": user_id,
                    "user_inputs": user_inputs,
                    "initial_value": float(payload.investable_amount),
                    "available_cash": float(payload.investable_amount),
                    "triggered_by": "objective_intake_complete",
                },
                countdown=2,  # Delay by 2 seconds to ensure DB commit
            )
            
            self.logger.info(
                f"✅ Dispatched allocation for portfolio {portfolio_id} to Celery "
                f"(task_id={task.id}, objective={objective_id})"
            )
            
            # Return metadata indicating allocation is pending
            allocation_meta = {
                "processed": False,
                "pending": True,
                "task_id": task.id,
                "message": "Portfolio allocation dispatched to background worker",
            }
            
        except Exception as exc:
            self.logger.exception(
                "Failed to dispatch allocation task for objective %s: %s",
                objective_id,
                exc,
            )

        last_rebalanced_at: Optional[datetime] = None
        next_rebalance_at: Optional[datetime] = None

        # Only process allocation summary if it's already been completed
        # For async allocations, the summary will be None and that's okay
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
        elif allocation_meta and allocation_meta.get("pending"):
            # Allocation is pending in background worker
            self.logger.info(
                f"Allocation for portfolio {portfolio_id} is pending "
                f"(task_id={allocation_meta.get('task_id')})"
            )

        objective_response = ObjectiveResponse.model_validate(updated_objective.model_dump())

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

        metadata: Dict[str, Any] = {}
        if isinstance(portfolio.metadata, dict):
            metadata.update(portfolio.metadata)
        elif isinstance(portfolio.metadata, str):
            try:
                parsed_meta = json.loads(portfolio.metadata)
                if isinstance(parsed_meta, dict):
                    metadata.update(parsed_meta)
            except json.JSONDecodeError:
                self.logger.debug(
                    "Portfolio %s metadata is not valid JSON string: %s",
                    portfolio_id,
                    portfolio.metadata,
                )

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
            "metadata": self._encode_json(metadata),
            "investment_horizon_years": payload.investment_horizon_years,
        }

        update_data["objective"] = {"connect": {"id": objective_id}}

        if isinstance(payload.investable_amount, Decimal):
            update_data["investment_amount"] = payload.investable_amount
            update_data["initial_investment"] = payload.investable_amount
            update_data["available_cash"] = payload.investable_amount

        if payload.expected_return_target is not None:
            update_data["expected_return_target"] = payload.expected_return_target

        if payload.risk_tolerance:
            update_data["risk_tolerance"] = payload.risk_tolerance

        if payload.liquidity_needs:
            update_data["liquidity_needs"] = payload.liquidity_needs

        if payload.rebalancing_frequency is not None:
            if isinstance(payload.rebalancing_frequency, str):
                update_data["rebalancing_frequency"] = self._encode_json(
                    {"frequency": payload.rebalancing_frequency}
                )
            else:
                update_data["rebalancing_frequency"] = self._encode_json(
                    payload.rebalancing_frequency
                )

        if payload.constraints:
            update_data["constraints"] = self._encode_json(payload.constraints)

        await self.prisma.portfolio.update(
            where={"id": portfolio_id},
            data=update_data,
        )

    @staticmethod
    def _coerce_weight_map(weights: Any) -> Dict[str, float]:
        """Coerce weights to a dict of floats, handling Prisma Json objects."""
        if weights is None:
            return {}
        # Handle Prisma Json object
        if hasattr(weights, '__dict__') and not isinstance(weights, dict):
            weights = dict(weights)
        # Handle string JSON
        if isinstance(weights, str):
            try:
                weights = json.loads(weights)
            except (json.JSONDecodeError, TypeError):
                return {}
        # Handle dict
        if isinstance(weights, dict):
            return {str(key): float(value) for key, value in weights.items()}
        return {}

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

    async def trigger_missing_allocations(
        self,
        *,
        max_batch: int = 50,
    ) -> Dict[str, Any]:
        """
        Find active objectives without portfolio allocations and trigger them.
        
        This utility function checks for objectives that:
        1. Have completion_status = 'complete'
        2. Have status = 'active'
        3. Have associated portfolios
        4. Portfolios have no allocations or need rebalancing
        
        Args:
            max_batch: Maximum number of objectives to process in one run
            
        Returns:
            Summary of triggered allocations
        """
        self.logger.info("Checking for active objectives without allocations...")
        
        # Find active, completed objectives with portfolios
        objectives = await self.prisma.objective.find_many(
            where={
                "AND": [
                    {"completion_status": "complete"},
                    {"status": "active"},
                    {"portfolios": {"some": {}}},  # Has at least one portfolio
                ]
            },
            include={
                "portfolios": {
                    "include": {
                        "allocations": True,
                    }
                }
            },
            take=max_batch,
        )
        
        if not objectives:
            self.logger.info("No active objectives found needing allocation")
            return {
                "checked": 0,
                "triggered": 0,
                "failed": 0,
                "portfolio_ids": [],
            }
        
        self.logger.info(f"Found {len(objectives)} active objectives to check")
        
        triggered_count = 0
        failed_count = 0
        processed_portfolios = []
        
        # Get current regime
        regime_label = "sideways"
        try:
            regime_service = RegimeService.get_instance()
            regime_state = regime_service.get_current_regime()
            if regime_state and regime_state.get("regime"):
                regime_label = str(regime_state["regime"]).lower()
        except Exception as exc:
            self.logger.warning(f"Regime service unavailable: {exc}")
        
        for objective in objectives:
            for portfolio in objective.portfolios:
                # Check if portfolio needs allocation
                needs_allocation = (
                    not portfolio.allocations or
                    len(portfolio.allocations) == 0 or
                    portfolio.last_rebalanced_at is None or
                    portfolio.allocation_status == "pending"
                )
                
                if not needs_allocation:
                    continue
                
                self.logger.info(
                    f"Triggering allocation for portfolio {portfolio.id} "
                    f"(objective: {objective.id})"
                )
                
                try:
                    # Trigger rebalance for this portfolio
                    await self.pipeline_service.rebalance_portfolio(
                        portfolio_id=portfolio.id,
                        triggered_by="missing_allocation_sweep",
                        regime_override=regime_label,
                        trigger_reason="Retroactive allocation for active objective",
                    )
                    
                    triggered_count += 1
                    processed_portfolios.append(portfolio.id)
                    
                    self.logger.info(
                        f"✅ Successfully triggered allocation for portfolio {portfolio.id}"
                    )
                    
                except Exception as exc:
                    self.logger.error(
                        f"❌ Failed to trigger allocation for portfolio {portfolio.id}: {exc}",
                        exc_info=True,
                    )
                    failed_count += 1
        
        result = {
            "checked": len(objectives),
            "triggered": triggered_count,
            "failed": failed_count,
            "portfolio_ids": processed_portfolios,
            "regime": regime_label,
        }
        
        self.logger.info(
            f"Missing allocations sweep completed: {result}"
        )
        
        return result


