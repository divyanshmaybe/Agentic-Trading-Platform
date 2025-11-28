"""
Pipeline Service - Business logic for pipeline operations
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db_manager  # type: ignore  # noqa: E402
from market_data import get_market_data_service  # type: ignore  # noqa: E402
from prisma import fields  # type: ignore  # noqa: E402
from pipelines.portfolio.portfolio_manager import DEFAULT_SEGMENTS  # type: ignore  # noqa: E402
from pipelines.risk import (  # type: ignore  # noqa: E402
    prepare_risk_alerts,
    publish_risk_alerts_to_kafka,
    run_risk_monitor_requests,
)
from pipelines.nse.trade_execution_pipeline import (  # type: ignore  # noqa: E402
    run_trade_execution_requests,  # Legacy Pathway implementation (slow)
)
from services.trade_sizing_service import (  # type: ignore  # noqa: E402
    calculate_trade_execution_jobs,  # Direct Python implementation (fast)
)
from utils import allocate_portfolios  # type: ignore  # noqa: E402
from utils.risk_monitor import prepare_risk_monitor_requests  # type: ignore  # noqa: E402
from utils.trade_execution import (  # type: ignore  # noqa: E402
    PortfolioSnapshot,
    TradeSignal,
    prepare_trade_execution_payloads,
)
from workers.risk_alert_tasks import send_risk_alert_email_task  # type: ignore  # noqa: E402
from services.trade_execution_service import TradeExecutionService  # type: ignore  # noqa: E402

class PipelineService:
    """Service for managing pipeline operations."""

    def __init__(self, server_dir: str, logger: Optional[logging.Logger]) -> None:
        self.server_dir = server_dir
        self.logger = logger or logging.getLogger(__name__)
        self.status_file = Path(self.server_dir) / "pipeline_status.json"
        self.news_status_file = Path(self.server_dir) / "news_pipeline_status.json"
        self._env_loaded = False

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def run_nse_pipeline_forever(self) -> None:
        """Run the NSE pipeline continuously (intended for Celery worker)."""
        self._load_environment()
        self._update_status("starting")
        try:
            self.logger.info("Starting NSE pipeline in Celery worker")
            self._execute_nse_pipeline()
        finally:
            self._update_status("stopped")

    def run_news_sentiment_pipeline(self, *, top_k: int = 3) -> Dict[str, Any]:
        """Run the News sentiment pipeline once and return metadata."""

        self._load_environment()
        self._update_news_status("starting")
        try:
            self.logger.info("Running news sentiment pipeline (top_k=%s)", top_k)
            metadata = self._execute_news_pipeline(top_k=top_k)
            self._update_news_status("succeeded", metadata=metadata)
            return metadata
        except Exception as exc:  # pragma: no cover - execution failures surfaced to Celery
            self.logger.exception("News sentiment pipeline failed: %s", exc)
            self._update_news_status("failed", error=str(exc))
            raise

    def run_scheduled_rebalance(
        self,
        *,
        as_of: Optional[datetime] = None,
        max_batch: Optional[int] = None,
        audit_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute the scheduled portfolio rebalancing sweep.

        Args:
            as_of: Optional reference timestamp (defaults to ``datetime.utcnow()``).
            max_batch: Maximum number of portfolios to rebalance in one run.
            audit_path: Optional JSONL path for allocation audit trails.
        """

        self._load_environment()
        reference_time = as_of or datetime.utcnow()
        batch_size = max_batch or int(os.getenv("PORTFOLIO_REBALANCE_BATCH_SIZE", "25"))
        audit_path = audit_path or os.getenv("PORTFOLIO_REBALANCE_AUDIT_PATH")

        coroutine = self._run_scheduled_rebalance_async(
            as_of=reference_time,
            max_batch=batch_size,
            audit_path=audit_path,
        )

        try:
            return asyncio.run(coroutine)
        except RuntimeError:
            # Fallback for environments where an event loop is already active.
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coroutine)
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    def run_risk_monitoring(
        self,
        *,
        emit_kafka: bool = True,
        send_email: bool = True,
        max_positions: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute the risk monitoring sweep across open positions.
        """

        self._load_environment()
        coroutine = self._run_risk_monitoring_async(
            emit_kafka=emit_kafka,
            send_email=send_email,
            max_positions=max_positions,
        )

        try:
            return asyncio.run(coroutine)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coroutine)
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    def process_nse_trade_signals(
        self,
        signals: Sequence[Mapping[str, Any]],
        *,
        publish_kafka: bool = True,
    ) -> Dict[str, Any]:
        """
        Process NSE filing trading signals and queue automated trade jobs.

        Args:
            signals: Sequence of trading signal payloads (dict-like).
            publish_kafka: Whether to forward generated trade jobs to Kafka.
        """

        self._load_environment()
        coroutine = self._process_nse_trade_signals_async(
            signals=signals,
            publish_kafka=publish_kafka,
        )

        try:
            return asyncio.run(coroutine)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coroutine)
            finally:
                asyncio.set_event_loop(None)
                loop.close()

    async def rebalance_portfolio(
        self,
        *,
        portfolio_id: str,
        triggered_by: str = "manual",
        regime_override: Optional[str] = None,
        audit_path: Optional[str] = None,
        trigger_reason: Optional[str] = None,
        as_of: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Execute an immediate rebalance for a single portfolio.

        Args:
            portfolio_id: Target portfolio identifier.
            triggered_by: Source of the rebalance (objective_create, manual, etc.).
            regime_override: Optional regime label to enforce for the optimisation input.
            audit_path: Optional JSONL path for audit trail persistence.
            trigger_reason: Human-readable reason for audit metadata.
            as_of: Optional timestamp indicating the rebalance reference time.
        """

        self._load_environment()
        reference_time = as_of or datetime.utcnow()
        trigger_reason = trigger_reason or triggered_by

        manager = get_db_manager()
        await manager.connect()
        client = manager.get_client()

        portfolio = await client.portfolio.find_unique(
            where={"id": portfolio_id},
            include={
                "objective": True,
                "allocations": True,
            },
        )
        if portfolio is None:
            self.logger.warning("Portfolio %s not found for immediate rebalance", portfolio_id)
            return {"processed": 0, "requested": 1, "portfolio_id": portfolio_id}

        request = self._prepare_allocation_request(
            portfolio,
            default_regime=regime_override or "sideways",
        )
        if regime_override:
            request["current_regime"] = regime_override

        results = allocate_portfolios([request], logger=self.logger, audit_path=audit_path)
        if not results:
            self.logger.warning(
                "Allocation pipeline returned no results for portfolio %s during immediate rebalance",
                portfolio_id,
            )
            return {"processed": 0, "requested": 1, "portfolio_id": portfolio_id}

        result = results[0]

        await self._persist_allocation_result(
            client,
            portfolio,
            result,
            as_of=reference_time,
            triggered_by=triggered_by,
            trigger_reason=trigger_reason,
        )

        updated_portfolio = await client.portfolio.find_unique(
            where={"id": portfolio_id},
        )

        return {
            "processed": 1,
            "requested": 1,
            "portfolio_id": portfolio_id,
            "allocation": result,
            "last_rebalanced_at": getattr(updated_portfolio, "last_rebalanced_at", reference_time)
            if updated_portfolio
            else reference_time,
            "next_rebalance_at": getattr(updated_portfolio, "next_rebalance_at", None)
            if updated_portfolio
            else None,
        }

    # Backwards compatibility hook (no longer threaded)
    def start_nse_pipeline(self) -> None:  # pragma: no cover - legacy entrypoint
        self.logger.warning(
            "start_nse_pipeline() now runs synchronously; scheduling should be handled by Celery"
        )
        self.run_nse_pipeline_forever()

    async def _run_scheduled_rebalance_async(
        self,
        *,
        as_of: datetime,
        max_batch: int,
        audit_path: Optional[str],
    ) -> Dict[str, Any]:
        manager = get_db_manager()
        await manager.connect()
        client = manager.get_client()

        where_clause: Dict[str, Any] = {
            "status": "active",
            "OR": [
                {"next_rebalance_at": {"equals": None}},
                {"next_rebalance_at": {"lte": as_of}},
                {"allocations": {"some": {"requires_rebalancing": True}}},
            ],
        }

        portfolios = await client.portfolio.find_many(
            where=where_clause,
            include={
                "objective": True,
                "allocations": True,
            },
            take=max_batch,
        )

        if not portfolios:
            self.logger.info("No portfolios due for scheduled rebalancing at %s", as_of.isoformat())
            return {"processed": 0, "requested": 0, "portfolio_ids": []}

        requests, portfolio_map = self._build_allocation_requests(portfolios)
        if not requests:
            self.logger.info("No valid allocation requests constructed for scheduled rebalancing")
            return {"processed": 0, "requested": 0, "portfolio_ids": []}

        self.logger.info(
            "Executing allocation pipeline for %s portfolio(s) (batch size=%s)",
            len(requests),
            max_batch,
        )

        results = allocate_portfolios(requests, logger=self.logger, audit_path=audit_path)
        if not results:
            self.logger.warning(
                "Allocation pipeline returned no results for %s scheduled request(s)", len(requests)
            )
            return {"processed": 0, "requested": len(requests), "portfolio_ids": []}

        results_map = {str(item.get("request_id")): item for item in results}

        processed = 0
        processed_ids: List[str] = []

        for portfolio in portfolios:
            portfolio_id = str(portfolio.id)
            result = results_map.get(portfolio_id)
            if not result:
                self.logger.warning("Missing allocation result for portfolio %s", portfolio_id)
                continue

            try:
                await self._persist_allocation_result(
                    client,
                    portfolio,
                    result,
                    as_of=as_of,
                    triggered_by="schedule",
                    trigger_reason="scheduled_rebalance",
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.exception(
                    "Failed to persist allocation result for portfolio %s: %s",
                    portfolio_id,
                    exc,
                )
                continue

            processed += 1
            processed_ids.append(portfolio_id)

        self.logger.info(
            "Scheduled rebalance completed: %s/%s portfolios updated",
            processed,
            len(requests),
        )

        return {"processed": processed, "requested": len(requests), "portfolio_ids": processed_ids}

    async def _run_risk_monitoring_async(
        self,
        *,
        emit_kafka: bool,
        send_email: bool,
        max_positions: Optional[int],
    ) -> Dict[str, Any]:
        manager = get_db_manager()
        await manager.connect()
        client = manager.get_client()

        # Get market data service
        market_service = None
        try:
            market_service = get_market_data_service()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.warning("Risk monitor: market data service unavailable (%s)", exc)
            return {"processed": 0, "alerts": 0, "published": 0, "emails_queued": 0}

        query_kwargs: Dict[str, Any] = {
            "where": {"status": "open"},
            "include": {"portfolio": True},
        }
        if max_positions:
            query_kwargs["take"] = max_positions

        positions = await client.position.find_many(**query_kwargs)

        monitoring_metadata = {
            "positions_examined": len(positions),
            "unique_symbols": len({
                getattr(position, "symbol", None)
                for position in positions
                if getattr(position, "symbol", None)
            }),
        }

        if not positions:
            self.logger.info("Risk monitor: no open positions found")
            return {
                "processed": 0,
                "alerts": 0,
                "published": 0,
                "emails_queued": 0,
                "metadata": monitoring_metadata,
            }

        requests = prepare_risk_monitor_requests(
            positions,
            market_data_service=market_service,
            logger=self.logger,
        )

        if not requests:
            self.logger.info(
                "Risk monitor: no affected users (positions=%s, symbols=%s)",
                monitoring_metadata.get("positions_examined", 0),
                monitoring_metadata.get("unique_symbols", 0),
            )
            return {
                "processed": 0,
                "alerts": 0,
                "published": 0,
                "emails_queued": 0,
                "metadata": monitoring_metadata,
            }

        self.logger.info(
            "Risk monitor: %s user(s) affected across %s unique symbols",
            len(requests),
            monitoring_metadata.get("unique_symbols", 0),
        )

        rows = run_risk_monitor_requests(requests, logger=self.logger)
        generated_at = datetime.utcnow().isoformat() + "Z"
        alerts = prepare_risk_alerts(rows, generated_at=generated_at)

        if not alerts:
            self.logger.info("Risk monitor: no threshold breaches detected")
            return {"processed": len(requests), "alerts": 0, "published": 0, "emails_queued": 0}

        published_count = (
            publish_risk_alerts_to_kafka(alerts, logger=self.logger) if emit_kafka else 0
        )

        emails_dispatched = 0
        if send_email:
            severity_rank = {"worst": 3, "worse": 2, "bad": 1, "info": 0}
            email_batches: Dict[str, Dict[str, Any]] = {}

            for alert in alerts:
                if not alert.contact_emails:
                    continue

                alert_payload = {
                    "symbol": alert.symbol,
                    "severity": alert.severity,
                    "message": alert.message,
                    "drawdown_pct": alert.drawdown_pct,
                    "day_change_pct": alert.day_change_pct,
                    "threshold_pct": alert.threshold_pct,
                    "current_price": alert.current_price,
                    "average_price": alert.average_price,
                    "portfolio_id": alert.portfolio_id,
                    "portfolio_name": alert.portfolio_name,
                    "generated_at": alert.generated_at,
                }

                for recipient in alert.contact_emails:
                    batch = email_batches.setdefault(
                        recipient,
                        {
                            "alerts": [],
                            "portfolios": set(),
                            "severity": "info",
                        },
                    )
                    batch["alerts"].append(alert_payload)
                    batch["portfolios"].add(alert.portfolio_name)
                    if severity_rank.get(alert.severity, 0) > severity_rank.get(batch["severity"], 0):
                        batch["severity"] = alert.severity

            for recipient, data in email_batches.items():
                alerts_payload = data["alerts"]
                if not alerts_payload:
                    continue
                severity = data["severity"].upper()
                portfolios_list = ", ".join(sorted(p for p in data["portfolios"] if p))
                subject = f"[Risk Alert:{severity}] {portfolios_list or 'Portfolio'}"
                send_risk_alert_email_task.delay(recipient, subject, alerts_payload)
                emails_dispatched += 1

        self.logger.info(
            "Risk monitor: alerts=%s published=%s emails=%s",
            len(alerts),
            published_count,
            emails_dispatched,
        )

        return {
            "processed": len(requests),
            "alerts": len(alerts),
            "published": published_count,
            "emails_queued": emails_dispatched,
            "generated_at": generated_at,
        }

    def _build_allocation_requests(
        self,
        portfolios: Sequence[Any],
        *,
        default_regime: str = "sideways",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        requests: List[Dict[str, Any]] = []
        portfolio_map: Dict[str, Any] = {}

        for portfolio in portfolios:
            try:
                request = self._prepare_allocation_request(portfolio, default_regime=default_regime)
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.warning(
                    "Skipping portfolio %s during scheduled rebalance preparation: %s",
                    getattr(portfolio, "id", "<unknown>"),
                    exc,
                )
                continue
            requests.append(request)
            portfolio_map[request["request_id"]] = portfolio

        return requests, portfolio_map

    def _prepare_allocation_request(self, portfolio: Any, *, default_regime: str) -> Dict[str, Any]:
        metadata_obj: Mapping[str, Any] = (
            portfolio.metadata if isinstance(portfolio.metadata, Mapping) else {}
        )
        regime = (
            metadata_obj.get("current_regime")
            or metadata_obj.get("regime")
            or default_regime
        )

        objective = getattr(portfolio, "objective", None)
        constraints = self._clean_json(portfolio.constraints) if portfolio.constraints else {}
        if (not constraints) and objective and getattr(objective, "constraints", None):
            constraints = self._clean_json(objective.constraints)

        allocation_strategy = self._extract_weights_from_allocation_strategy(
            portfolio.allocation_strategy
        )

        allocations = getattr(portfolio, "allocations", []) or []
        if not allocation_strategy and allocations:
            allocation_strategy = {
                alloc.allocation_type: self._safe_float(alloc.target_weight)
                for alloc in allocations
            }

        # Use standardized user_inputs format matching transcript.py
        # Note: If allocation_strategy is None, create_user_inputs() will use defaults from transcript.py:
        # low_risk: 0.6, high_risk: 0.2, alpha: 0.2, liquid: 0.0
        from utils.user_inputs_helper import create_user_inputs
        
        # Get expected_return_target (convert from decimal percentage if needed)
        expected_return = self._safe_float(portfolio.expected_return_target, default=0.18)
        if expected_return > 1.0:
            expected_return = expected_return / 100.0  # Convert percentage to decimal
        
        user_inputs = create_user_inputs(
            investment_horizon_years=int(getattr(portfolio, "investment_horizon_years", 1) or 1),
            expected_return_target=expected_return,
            risk_tolerance=portfolio.risk_tolerance or "medium",
            allocation_strategy=allocation_strategy,
            constraints=constraints,
            investment_amount=self._safe_float(portfolio.investment_amount),
        )

        initial_value = self._safe_float(
            portfolio.initial_investment,
            default=self._safe_float(
                portfolio.investment_amount,
                default=self._safe_float(portfolio.available_cash),
            ),
        )
        current_value = self._safe_float(portfolio.available_cash, default=initial_value)

        value_history = metadata_obj.get("value_history")
        if not isinstance(value_history, list) or not value_history:
            value_history = [initial_value, current_value]

        segment_history = metadata_obj.get("segment_history")
        lookback_quarters = int(metadata_obj.get("lookback_quarters", 4))

        user_identifier = getattr(portfolio, "user_id", None) or portfolio.customer_id or portfolio.organization_id
        if not user_identifier:
            raise ValueError("portfolio missing associated user identifier")

        request = {
            "request_id": str(portfolio.id),
            "user_id": str(user_identifier),
            "current_regime": str(regime),
            "user_inputs": user_inputs,
            "initial_value": initial_value,
            "current_value": current_value,
            "value_history": value_history,
            "segment_history": segment_history,
            "lookback_quarters": lookback_quarters,
            "metadata": {
                "portfolio_id": str(portfolio.id),
                "organization_id": portfolio.organization_id,
                "customer_id": portfolio.customer_id,
            },
        }

        return request

    def _extract_weights_from_allocation_strategy(self, strategy: Any) -> Dict[str, float]:
        if not strategy:
            return {}

        if isinstance(strategy, Mapping):
            weights = strategy.get("weights")
            if isinstance(weights, Mapping):
                return {str(key): self._safe_float(value) for key, value in weights.items()}
            return {
                str(key): self._safe_float(value)
                for key, value in strategy.items()
                if isinstance(value, (int, float, Decimal))
            }

        return {}

    async def _persist_allocation_result(
        self,
        client: Any,
        portfolio: Any,
        result: Mapping[str, Any],
        *,
        as_of: datetime,
        triggered_by: str = "schedule",
        trigger_reason: Optional[str] = None,
    ) -> None:
        weights_raw = self._coerce_mapping(result.get("weights"))
        if not weights_raw:
            weights_raw = self._coerce_mapping(result.get("weights_json"))

        if not weights_raw:
            self.logger.warning("Invalid weights payload for portfolio %s", portfolio.id)
            return

        weights = {str(key): self._safe_float(value) for key, value in weights_raw.items()}
        if not weights:
            self.logger.warning("Empty weight vector returned for portfolio %s", portfolio.id)
            return

        total_investable = self._safe_float(
            portfolio.investment_amount,
            default=self._safe_float(
                portfolio.initial_investment,
                default=self._safe_float(portfolio.available_cash),
            ),
        )
        # If total_investable is still 0, try to get from objective
        if total_investable <= 0:
            objective = getattr(portfolio, "objective", None)
            if objective:
                total_investable = self._safe_float(
                    getattr(objective, "investable_amount", None) or
                    getattr(objective, "total_investment", None) or
                    0.0
        )
        current_value = self._safe_float(portfolio.available_cash, default=total_investable)
        drift_values = result.get("drift") or {}

        metadata_payload = self._parse_metadata(portfolio.metadata)
        regime_value = result.get("regime") or metadata_payload.get("current_regime")
        if regime_value:
            metadata_payload["current_regime"] = regime_value

        allocations = getattr(portfolio, "allocations", []) or []
        allocation_lookup = {alloc.allocation_type: alloc for alloc in allocations}
        segments = set(allocation_lookup.keys()) | set(weights.keys())

        self.logger.info(
            "📊 Allocation processing for portfolio %s: weights=%s, existing_allocations=%s, segments=%s",
            portfolio.id,
            weights,
            [alloc.allocation_type for alloc in allocations],
            sorted(segments)
        )

        for segment in sorted(segments):
            weight = weights.get(segment, 0.0)
            drift = self._safe_float(drift_values.get(segment, 0.0))
            target_weight_dec = self._to_decimal(weight, places=6)
            
            # Use existing allocated_amount if it's already set and non-zero, otherwise calculate
            existing_allocation = allocation_lookup.get(segment)
            if existing_allocation and existing_allocation.allocated_amount and float(existing_allocation.allocated_amount) > 0:
                allocated_amount_dec = self._to_decimal(float(existing_allocation.allocated_amount), places=4)
            else:
                allocated_amount_dec = self._to_decimal(total_investable * weight, places=4)
            
            current_value_dec = self._to_decimal(current_value * weight, places=4)
            drift_dec = self._to_decimal(drift, places=6)

            allocation = allocation_lookup.get(segment)
            if allocation:
                allocation_metadata = self._parse_metadata(allocation.metadata)
                allocation_metadata["last_rebalance"] = {
                    "triggered_at": as_of.isoformat() + "Z",
                    "regime": result.get("regime"),
                    "progress_ratio": result.get("progress_ratio"),
                    "triggered_by": triggered_by,
                    "trigger_reason": trigger_reason,
                }
                await client.portfolioallocation.update(
                    where={"id": allocation.id},
                    data={
                        "target_weight": target_weight_dec,
                        "current_weight": target_weight_dec,
                        "allocated_amount": allocated_amount_dec,
                        "available_cash": allocated_amount_dec,  # Initially same as allocated
                        "drift_percentage": drift_dec,
                        "requires_rebalancing": False,
                        "metadata": fields.Json(allocation_metadata),
                    },
                )
            elif weight > 0:
                created = await client.portfolioallocation.create(
                    data={
                        "portfolio": {"connect": {"id": portfolio.id}},
                        "allocation_type": segment,
                        "target_weight": target_weight_dec,
                        "current_weight": target_weight_dec,
                        "allocated_amount": allocated_amount_dec,
                        "available_cash": allocated_amount_dec,  # Initially same as allocated
                        "metadata": fields.Json({
                            "created_at": as_of.isoformat() + "Z",
                            "created_by": triggered_by,
                            "trigger_reason": trigger_reason,
                        }),
                    }
                )
                allocations.append(created)
                allocation_lookup[segment] = created

        metadata_payload["last_rebalance"] = {
            "triggered_at": as_of.isoformat() + "Z",
            "regime": result.get("regime"),
            "progress_ratio": result.get("progress_ratio"),
            "message": result.get("message"),
            "triggered_by": triggered_by,
            "trigger_reason": trigger_reason,
        }

        next_rebalance_at = self._compute_next_rebalance_at(portfolio, as_of)

        allocation_strategy_payload = {
            "weights": weights,
            "expected_return": result.get("expected_return"),
            "expected_risk": result.get("expected_risk"),
            "objective_value": result.get("objective_value"),
            "regime": result.get("regime"),
            "message": result.get("message"),
            "progress_ratio": result.get("progress_ratio"),
            "updated_at": as_of.isoformat() + "Z",
        }

        await client.portfolio.update(
            where={"id": portfolio.id},
            data={
                "allocation_strategy": fields.Json(allocation_strategy_payload),
                "last_rebalanced_at": as_of,
                "next_rebalance_at": next_rebalance_at,
                "metadata": fields.Json(metadata_payload),
            },
        )

        snapshot_value_dec = self._to_decimal(current_value, places=4)
        # Ensure both datetimes are timezone-aware for comparison
        last_rebalanced = getattr(portfolio, "last_rebalanced_at", None)
        if last_rebalanced:
            # Make sure both are timezone-aware
            if as_of.tzinfo is None:
                from datetime import timezone
                as_of = as_of.replace(tzinfo=timezone.utc)
            if last_rebalanced.tzinfo is None:
                from datetime import timezone
                last_rebalanced = last_rebalanced.replace(tzinfo=timezone.utc)
            time_elapsed_days = (as_of - last_rebalanced).days
        else:
            time_elapsed_days = None

        # Check if a rebalance run was already created recently (within last 5 seconds) for this portfolio
        # This prevents duplicate snapshots if _persist_allocation_result is called multiple times
        from datetime import timedelta
        recent_cutoff = as_of - timedelta(seconds=5)
        existing_run = await client.rebalancerun.find_first(
            where={
                "portfolio_id": portfolio.id,
                "triggered_by": triggered_by,
                "triggered_at": {"gte": recent_cutoff},
            },
            order={"triggered_at": "desc"},
        )
        
        if existing_run:
            self.logger.debug(
                f"Reusing existing rebalance run {existing_run.id} for portfolio {portfolio.id} "
                f"(created {as_of - existing_run.triggered_at} ago)"
            )
            rebalance_run = existing_run
        else:
            rebalance_metadata = {
                "weights": weights,
                "regime": result.get("regime"),
                "expected_return": result.get("expected_return"),
                "expected_risk": result.get("expected_risk"),
                "objective_value": result.get("objective_value"),
                "message": result.get("message"),
                "triggered_by": triggered_by,
                "trigger_reason": trigger_reason,
            }

            rebalance_run = await client.rebalancerun.create(
                data={
                    "portfolio_id": portfolio.id,
                    "triggered_by": triggered_by,
                    "triggered_at": as_of,
                    "snapshot_portfolio_value": snapshot_value_dec,
                    "snapshot_cash": self._to_decimal(0.0, places=4),
                    "snapshot_invested": snapshot_value_dec,
                    "time_elapsed_days": time_elapsed_days,
                    "expected_progress": fields.Json({"progress_ratio": result.get("progress_ratio")}),
                    "metadata": fields.Json(rebalance_metadata),
                }
            )

        for segment, weight in weights.items():
            allocation = allocation_lookup.get(segment)
            if allocation is None:
                allocation = next(
                    (alloc for alloc in allocations if alloc.allocation_type == segment),
                    None,
                )
            if allocation is None:
                self.logger.debug(
                    "Skipping AllocationSnapshot for segment %s: no allocation found (weight=%.6f)",
                    segment,
                    weight
                )
                continue

            # Check if snapshot already exists for this rebalance run and allocation
            existing_snapshot = await client.allocationsnapshot.find_first(
                where={
                    "rebalance_run_id": rebalance_run.id,
                    "portfolio_allocation_id": allocation.id,
                }
            )
            
            if existing_snapshot:
                self.logger.debug(
                    f"Skipping duplicate allocation snapshot for allocation {allocation.id} "
                    f"in rebalance run {rebalance_run.id}"
                )
                continue
            
            snapshot_amount = self._to_decimal(total_investable * weight, places=4)
            snapshot_current_value = self._to_decimal(current_value * weight, places=4)

            await client.allocationsnapshot.create(
                data={
                    "rebalance_run_id": rebalance_run.id,
                    "portfolio_allocation_id": allocation.id,
                    "current_value": snapshot_current_value,
                    "realized_pnl": self._to_decimal(0.0, places=4),
                    "unrealized_pnl": self._to_decimal(0.0, places=4),
                    "metadata": fields.Json({
                        "regime": result.get("regime"),
                        "generated_at": as_of.isoformat() + "Z",
                        "snapshot_weight": float(weight),
                        "snapshot_amount": float(snapshot_amount),
                    }),
                }
            )

    def _compute_next_rebalance_at(self, portfolio: Any, reference: datetime) -> datetime:
        frequency = getattr(portfolio, "rebalancing_frequency", None)
        if not frequency:
            objective = getattr(portfolio, "objective", None)
            frequency = getattr(objective, "rebalancing_frequency", None)

        delta = self._resolve_frequency_delta(frequency)
        if delta is None:
            default_months = int(os.getenv("PORTFOLIO_REBALANCE_DEFAULT_MONTHS", "3"))
            delta = relativedelta(months=default_months)

        return reference + delta

    def _resolve_frequency_delta(self, frequency: Any) -> Optional[relativedelta]:
        if frequency is None:
            return None

        if isinstance(frequency, str):
            freq = frequency.strip().lower()
            if freq in {"daily", "day"}:
                return relativedelta(days=1)
            if freq in {"weekly", "week"}:
                return relativedelta(weeks=1)
            if freq in {"monthly", "month"}:
                return relativedelta(months=1)
            if freq in {"bi-monthly", "bimonthly"}:
                return relativedelta(months=2)
            if freq in {"quarterly", "quarter"}:
                return relativedelta(months=3)
            if freq in {"semiannual", "semi-annual", "half-year"}:
                return relativedelta(months=6)
            if freq in {"annual", "yearly", "year"}:
                return relativedelta(years=1)

        if isinstance(frequency, Mapping):
            unit = str(frequency.get("unit", "month")).lower()
            value = frequency.get("value") or frequency.get("months") or frequency.get("interval")
            if isinstance(value, (int, float)):
                value_int = int(value)
                if unit.startswith("day"):
                    return relativedelta(days=value_int)
                if unit.startswith("week"):
                    return relativedelta(weeks=value_int)
                if unit.startswith("year"):
                    return relativedelta(years=value_int)
                return relativedelta(months=value_int)

        if isinstance(frequency, (int, float)):
            return relativedelta(months=int(frequency))

        return None

    def _to_decimal(self, value: Any, *, places: int = 4) -> Decimal:
        numeric = self._safe_float(value)
        quant = Decimal(f"1e-{places}") if places > 0 else Decimal("1")
        return Decimal(str(numeric)).quantize(quant, rounding=ROUND_HALF_UP)

    def _safe_float(self, value: Any, *, default: float = 0.0) -> float:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _clean_json(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            coerced = float(value)
            if math.isnan(coerced) or math.isinf(coerced):
                return None
            return coerced
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return float(value)
        if isinstance(value, Mapping):
            return {key: self._clean_json(val) for key, val in value.items()}
        if isinstance(value, list):
            return [self._clean_json(item) for item in value]
        return value

    def _coerce_mapping(self, value: Any) -> Dict[str, Any]:
        if not value:
            return {}
        if isinstance(value, Mapping):
            return {str(key): val for key, val in value.items()}

        for attr in ("value", "data"):
            nested = getattr(value, attr, None)
            if isinstance(nested, Mapping):
                return {str(key): val for key, val in nested.items()}
            if isinstance(nested, str):
                try:
                    parsed = json.loads(nested)
                    if isinstance(parsed, Mapping):
                        return {str(key): val for key, val in parsed.items()}
                except json.JSONDecodeError:
                    continue

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, Mapping):
                    return {str(key): val for key, val in parsed.items()}
            except json.JSONDecodeError:
                return {}

        return {}

    def _parse_metadata(self, value: Any) -> Mapping[str, Any]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {str(key): self._clean_json(val) for key, val in value.items()}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, Mapping):
                    return {str(key): self._clean_json(val) for key, val in parsed.items()}
            except json.JSONDecodeError:
                return {"raw": value}
        return {}

    def _parse_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            try:
                return datetime.utcfromtimestamp(float(value))
            except Exception:
                return datetime.utcnow()
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return datetime.utcnow()
        return datetime.utcnow()

    async def _fetch_high_risk_user_ids(self, client: Any) -> List[str]:
        """
        Fetch user IDs with active high_risk trading agents.
        Uses TradingAgent table instead of querying users table.
        """
        try:
            # Query TradingAgent table for active high_risk agents
            agents = await client.tradingagent.find_many(
                where={
                    "agent_type": "high_risk",
                    "status": "active",
                },
                include={
                    "portfolio": True,
                    "allocation": True,
                }
            )
            
            if not agents:
                self.logger.warning("No active high_risk trading agents found")
                return []
            
            user_ids = []
            for agent in agents:
                if agent.portfolio and agent.portfolio.user_id:
                    user_ids.append(str(agent.portfolio.user_id))
            
            # Remove duplicates
            user_ids = list(set(user_ids))
            
            self.logger.info(
                "Found %d active high_risk agent(s) for %d unique user(s)",
                len(agents),
                len(user_ids)
            )
            return user_ids
            
        except Exception as exc:
            self.logger.error("Failed to fetch high-risk agents: %s", exc)
            return []

    async def _build_portfolio_snapshot(
        self,
        portfolio: Any,
        *,
        agent: Optional[Any] = None,
        agent_config: Optional[Mapping[str, Any]] = None,
        agent_metadata: Optional[Mapping[str, Any]] = None,
    ) -> Optional[PortfolioSnapshot]:
        user_id = getattr(portfolio, "user_id", None)
        if not user_id:
            return None

        metadata = self._parse_metadata(getattr(portfolio, "metadata", None))
        cash_available = self._safe_float(metadata.get("cash_available", metadata.get("cash")), default=0.0)
        
        # Get capital from agent's allocation - REFETCH from DB to get latest available_cash
        # Try both 'allocation' and 'portfolioAllocation' relation names
        allocation = None
        if agent:
            allocation = getattr(agent, "allocation", None) or getattr(agent, "portfolioAllocation", None)
            
            # CRITICAL: Refetch allocation from database to get the LATEST available_cash
            # This prevents race conditions where multiple signals use stale allocation data
            if allocation:
                try:
                    manager = get_db_manager()
                    if not manager.is_connected():
                        await manager.connect()
                    client = manager.get_client()
                    
                    fresh_allocation = await client.portfolioallocation.find_unique(
                        where={"id": getattr(allocation, "id")}
                    )
                    if fresh_allocation:
                        allocation = fresh_allocation
                        self.logger.debug(
                            "🔄 Refetched allocation %s: available_cash=%.2f (was using potentially stale data)",
                            getattr(allocation, "id"),
                            self._safe_float(getattr(allocation, "available_cash", 0.0))
                        )
                except Exception as e:
                    self.logger.warning("⚠️ Failed to refetch allocation, using existing data: %s", e)
        
        self.logger.info(
            "🔍 ALLOCATION DEBUG: agent=%s, allocation=%s, has_allocation=%s",
            getattr(agent, "id", "none") if agent else "no_agent",
            allocation,
            allocation is not None
        )
        
        # Use available_cash from allocation (this is the current available capital after trades)
        available_cash_from_allocation = self._safe_float(getattr(allocation, "available_cash", 0.0)) if allocation else 0.0
        allocation_amount = self._safe_float(getattr(allocation, "allocated_amount", 0.0)) if allocation else 0.0
        
        self.logger.info(
            "🔍 ALLOCATION AMOUNT DEBUG: allocated_amount=%.2f, available_cash=%.2f, allocated_amount_raw=%s",
            allocation_amount,
            available_cash_from_allocation,
            getattr(allocation, "allocated_amount", "NO_ATTR") if allocation else "NO_ALLOCATION"
        )
        
        # Use available_cash from allocation as cash_available for trading (this is the current capital after trades)
        if available_cash_from_allocation > 0:
            cash_available = available_cash_from_allocation
            self.logger.info(
                "✅ Using allocation available_cash %.2f as cash_available for portfolio %s (agent %s)",
                available_cash_from_allocation,
                getattr(portfolio, "id", "unknown"),
                getattr(agent, "id", "unknown") if agent else "none",
            )
        elif allocation_amount > 0:
            # Fallback: use allocated_amount if available_cash is not set yet
            cash_available = allocation_amount
            self.logger.info(
                "✅ Using allocation amount %.2f as cash_available for portfolio %s (agent %s) - available_cash not set",
                allocation_amount,
                getattr(portfolio, "id", "unknown"),
                getattr(agent, "id", "unknown") if agent else "none",
            )
        elif cash_available <= 0:
            # Fallback: use a portion of portfolio investment if no allocation
            portfolio_investment = self._safe_float(getattr(portfolio, "investment_amount", 0.0))
            if allocation and hasattr(allocation, "target_weight"):
                target_weight = self._safe_float(getattr(allocation, "target_weight", 0.0))
                if target_weight > 0:
                    cash_available = portfolio_investment * target_weight
                else:
                    cash_available = portfolio_investment
            else:
                cash_available = portfolio_investment
            self.logger.debug(
                "Using fallback cash_available %.2f for portfolio %s",
                cash_available,
                getattr(portfolio, "id", "unknown"),
            )
        
        # effective_investment for portfolio snapshot (used for investment_amount field)
        effective_investment = allocation_amount if allocation_amount > 0 else self._safe_float(getattr(portfolio, "investment_amount", 0.0))

        agent_id = str(getattr(agent, "id", "")) if agent else None
        agent_type = str(getattr(agent, "agent_type", "")) if agent else None
        agent_status = str(getattr(agent, "status", "")) if agent else None
        agent_config_dict = dict(agent_config or {})
        agent_metadata_dict = dict(agent_metadata or {})

        if agent_id:
            metadata = {
                **metadata,
                "trading_agent": {
                    "id": agent_id,
                    "type": agent_type,
                    "status": agent_status,
                    "config": agent_config_dict,
                    "metadata": agent_metadata_dict,
                },
            }

        snapshot = PortfolioSnapshot(
            portfolio_id=str(getattr(portfolio, "id")),
            portfolio_name=str(getattr(portfolio, "portfolio_name", "Portfolio")),
            user_id=str(user_id),
            organization_id=getattr(portfolio, "organization_id", None),
            customer_id=getattr(portfolio, "customer_id", None),
            current_value=self._safe_float(getattr(portfolio, "current_value", 0.0)),
            investment_amount=max(effective_investment, self._safe_float(getattr(portfolio, "investment_amount", 0.0))),
            cash_available=cash_available,
            metadata=metadata,
            agent_id=agent_id,
            agent_type=agent_type,
            agent_status=agent_status,
            agent_metadata=agent_metadata_dict,
            agent_config=agent_config_dict,
        )
        
        self.logger.info(
            "📸 SNAPSHOT CREATED: portfolio=%s, cash_available=%.2f, current_value=%.2f, investment_amount=%.2f, capital_base=%.2f",
            snapshot.portfolio_id,
            snapshot.cash_available,
            snapshot.current_value,
            snapshot.investment_amount,
            snapshot.capital_base
        )
        
        return snapshot

    def _build_trade_signal(self, payload: Mapping[str, Any]) -> Optional[TradeSignal]:
        symbol = payload.get("symbol")
        if not symbol:
            return None

        try:
            # NSE pipeline sends "trading_signal", but also support "signal" for compatibility
            signal_value = int(payload.get("trading_signal") or payload.get("signal", 0))
        except (TypeError, ValueError):
            return None

        # NSE pipeline sends "confidence_score", but also support "confidence" for compatibility
        confidence = self._safe_float(
            payload.get("confidence_score") or payload.get("confidence"),
            default=0.0
        )
        if confidence <= 0:
            confidence = 0.0

        explanation = str(payload.get("explanation", "") or "")
        metadata = payload.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {"raw_metadata": metadata}
        if not isinstance(metadata, Mapping):
            metadata = {}

        signal_id = (
            str(payload.get("signal_id"))
            or str(payload.get("request_id", ""))
            or str(payload.get("seq_id", ""))
            or str(uuid.uuid4())
        )

        filing_time = (
            str(payload.get("filing_time", ""))
            or str(payload.get("sort_date", ""))
            or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        )

        generated_at = self._parse_datetime(payload.get("generated_at"))

        return TradeSignal(
            signal_id=signal_id,
            symbol=str(symbol),
            signal=signal_value,
            confidence=confidence,
            explanation=explanation,
            filing_time=filing_time,
            generated_at=generated_at,
            metadata=metadata,
        )

    async def _process_nse_trade_signals_async(
        self,
        *,
        signals: Sequence[Mapping[str, Any]],
        publish_kafka: bool,
    ) -> Dict[str, Any]:
        processed_signals = list(signals or [])
        if not processed_signals:
            return {
                "processed_signals": 0,
                "payloads": 0,
                "jobs": 0,
                "dispatched": 0,
            }

        # Use DBManager for proper connection handling
        from dbManager import DBManager
        db_manager = DBManager.get_instance()
        await db_manager.connect()
        client = db_manager.get_client()
        
        trade_service = TradeExecutionService(logger=self.logger)

        # DIRECTLY query for active high_risk agents with auto_trade enabled
        # No need for user filtering bullshit
        agents = await client.tradingagent.find_many(
                where={
                    "agent_type": "high_risk",
                    "status": "active",
                },
                include={
                    "portfolio": True,
                    "allocation": True,
                }
            )
        
        if not agents:
            self.logger.warning("⚠️ No active high_risk trading agents found")
            return {
                "processed_signals": len(processed_signals),
                "payloads": 0,
                "jobs": 0,
                "dispatched": 0,
            }
        
        # Filter agents with auto_trade enabled
        auto_trade_agents = []
        for agent in agents:
            config = self._clean_json(getattr(agent, "strategy_config", None)) or {}
            auto_enabled = bool(config.get("auto_trade", True))
            if auto_enabled:
                auto_trade_agents.append(agent)
            else:
                self.logger.debug(
                    "Skipping agent %s for auto-trade (auto_trade flag disabled)",
                    getattr(agent, "id", "unknown"),
                )
        
        if not auto_trade_agents:
            self.logger.warning("⚠️ Found %d high_risk agents but NONE have auto_trade enabled", len(agents))
            return {
                "processed_signals": len(processed_signals),
                "payloads": 0,
                "jobs": 0,
                "dispatched": 0,
            }
        
        self.logger.info("✅ Found %d active high_risk agents with auto_trade enabled", len(auto_trade_agents))
        
        # Get unique portfolio IDs from these agents
        portfolio_ids = list(set([str(agent.portfolio_id) for agent in auto_trade_agents if agent.portfolio_id]))
        
        portfolios = await client.portfolio.find_many(
            where={
                "id": {"in": portfolio_ids},
                "status": "active",
            },
            include={"agents": {"include": {"allocation": True}}},
        )

        snapshots: List[PortfolioSnapshot] = []
        active_agents_count = 0
        skipped_portfolios = 0
        
        for portfolio in portfolios:
            agent_rows = [
                agent
                for agent in getattr(portfolio, "agents", []) or []
                if str(getattr(agent, "agent_type", "")).lower() == "high_risk"
            ]

            active_agent = None
            active_config: Mapping[str, Any] = {}
            active_metadata: Mapping[str, Any] = {}

            for agent in agent_rows:
                status = str(getattr(agent, "status", "") or "active").lower()
                config = self._clean_json(getattr(agent, "strategy_config", None)) or {}
                auto_trade_enabled = bool(config.get("auto_trade", True))
                agent_id = str(getattr(agent, "id", "unknown"))

                if status == "active" and auto_trade_enabled:
                    active_agent = agent
                    active_config = config
                    active_metadata = self._parse_metadata(getattr(agent, "metadata", None))
                    active_agents_count += 1
                    self.logger.info(
                        "✅ Found active trading agent %s (%s) for portfolio %s (auto-trade enabled)",
                        agent_id,
                        getattr(agent, "agent_type", "unknown"),
                        getattr(portfolio, "id", "unknown"),
                    )
                    break

            if not active_agent:
                skipped_portfolios += 1
                self.logger.debug(
                    "Skipping portfolio %s: no active high-risk agent with auto-trade enabled",
                    getattr(portfolio, "id", "unknown"),
                )
                continue

            snapshot = await self._build_portfolio_snapshot(
                portfolio,
                agent=active_agent,
                agent_config=active_config,
                agent_metadata=active_metadata,
            )
            if snapshot:
                snapshots.append(snapshot)
        
        self.logger.info(
            "📊 Trade signal processing summary: %d active trading agents found, %d portfolios skipped, %d eligible snapshots",
            active_agents_count,
            skipped_portfolios,
            len(snapshots),
        )

        if not snapshots:
            self.logger.info("No eligible portfolios for automated trade execution")
            return {
                "processed_signals": len(processed_signals),
                "payloads": 0,
                "jobs": 0,
                "dispatched": 0,
            }

        trade_signals: List[TradeSignal] = []
        for payload in processed_signals:
            signal = self._build_trade_signal(payload)
            if signal:
                trade_signals.append(signal)

        if not trade_signals:
            self.logger.info("No actionable trading signals to process")
            return {
                "processed_signals": len(processed_signals),
                "payloads": 0,
                "jobs": 0,
                "dispatched": 0,
            }

        payloads = prepare_trade_execution_payloads(
            trade_signals,
            snapshots,
            logger=self.logger,
        )
        if not payloads:
            self.logger.info("Trade execution payload preparation returned no entries")
            return {
                "processed_signals": len(processed_signals),
                "payloads": 0,
                "jobs": 0,
                "dispatched": 0,
            }

        request_events = [payload.to_event() for payload in payloads]
        self.logger.info("🔄 Calculating trade execution jobs with %d payload(s)...", len(request_events))
        
        # Use direct Python implementation (50-200x faster than Pathway)
        job_rows = calculate_trade_execution_jobs(request_events, logger=self.logger)
        
        self.logger.info("📊 Trade execution calculation produced %d actionable job(s)", len(job_rows) if job_rows else 0)
        
        if not job_rows:
            self.logger.info("⚠️ Trade execution calculation produced no actionable jobs")
            return {
                "processed_signals": len(processed_signals),
                "payloads": len(payloads),
                "jobs": 0,
                "dispatched": 0,
            }
        
        # Add triggered_by to each job row for tracking
        for job_row in job_rows:
            job_row["triggered_by"] = "high_risk_agent"
            self.logger.debug(
                "📋 Job row: %s %s x %d | Allocation: %.2f | Price: %.2f | Agent: %s",
                job_row.get("symbol", "unknown"),
                job_row.get("side", "unknown"),
                job_row.get("quantity", 0),
                job_row.get("allocated_capital", 0.0),
                job_row.get("reference_price", 0.0),
                job_row.get("agent_id", "unknown"),
            )

        self.logger.info("💾 Persisting %d trade job(s) to database...", len(job_rows))
        
        try:
            # Persist trade jobs and publish to Kafka
            events = await trade_service.persist_and_publish(
                job_rows,
                publish_kafka=False,  # Disable Pathway Kafka to prevent blocking
            )
            
            self.logger.info("✅ Persisted %d trade execution log(s), created %d event(s)", len(job_rows), len(events) if events else 0)
        except Exception as persist_exc:
            self.logger.error("❌ Failed to persist trade jobs: %s", persist_exc, exc_info=True)
            return {
                "processed_signals": len(processed_signals),
                "payloads": len(payloads),
                "jobs": len(job_rows),
                "dispatched": 0,
                "error": str(persist_exc),
            }

        dispatched = 0
        executed = 0
        if not events:
            self.logger.warning("⚠️ persist_and_publish returned no events (expected %d)", len(job_rows))
        else:
            # Check if we should use Celery or execute directly
            use_celery = os.getenv("USE_CELERY_FOR_TRADES", "false").lower() in {"1", "true", "yes"}
            self.logger.info("🚀 Executing %d trade(s) using %s mode...", len(events), "Celery" if use_celery else "direct simulation")
            
            if use_celery:
                # Use Celery for async execution
                try:
                    from workers.trade_execution_tasks import execute_trade_job  # type: ignore

                    for event in events:
                        execute_trade_job.delay(event.trade_id)
                        dispatched += 1
                        self.logger.info(
                            "✅ Enqueued trade execution to Celery: Trade %s | Agent %s (%s) | %s %s x %d | Portfolio %s",
                        event.trade_id,
                        event.agent_id or "unknown",
                        event.agent_type or "unknown",
                        event.side,
                        event.symbol,
                        event.quantity,
                        event.portfolio_id,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.error("Failed to enqueue trade execution workers: %s", exc)
            else:
                # Execute trades immediately in simulation mode (paper trading)
                for event in events:
                    try:
                        result = await trade_service.execute_trade(event.trade_id, simulate=True)
                        executed += 1
                        self.logger.info(
                            "✅ Executed trade immediately (simulation): Trade %s | Agent %s (%s) | %s %s x %d | Status: %s",
                            event.trade_id,
                            event.agent_id or "unknown",
                            event.agent_type or "unknown",
                            event.side,
                            event.symbol,
                            event.quantity,
                            result.get("status", "unknown"),
                        )
                    except Exception as exc:
                        self.logger.error("Failed to execute trade %s: %s", event.trade_id, exc, exc_info=True)

        # Disconnect Prisma client
        try:
            await client.disconnect()
        except:
            pass

        return {
            "processed_signals": len(processed_signals),
            "payloads": len(payloads),
            "jobs": len(job_rows),
            "dispatched": dispatched,
            "executed": executed,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_nse_pipeline(self) -> None:
        nse_dir = os.path.join(self.server_dir, "pipelines/nse")
        original_dir = os.getcwd()

        try:
            os.chdir(nse_dir)
            sys.path.insert(0, nse_dir)

            import pathway as pw
            from nse_filings_sentiment import create_nse_filings_pipeline
            from nse_live_scraper import create_nse_scraper_input

            self.logger.info("=" * 70)
            self.logger.info("NSE Live Trading Pipeline - Real-time Sentiment Analysis")
            self.logger.info("=" * 70)

            refresh_interval = int(os.getenv("NSE_REFRESH_INTERVAL", "60"))
            static_data_path = "staticdata.csv"
            signals_output = "trading_signals.jsonl"

            if not os.path.exists(static_data_path):
                self.logger.info(
                    "staticdata.csv not found - using default impact scenarios"
                )

            self.logger.info(
                "Starting live NSE scraper (interval: %ss)...", refresh_interval
            )
            try:
                filings_input = create_nse_scraper_input(refresh_interval=refresh_interval)
                self.logger.info("✓ NSE scraper input created successfully")
            except Exception as scraper_exc:
                self.logger.error("❌ Failed to create NSE scraper input: %s", scraper_exc, exc_info=True)
                raise

            self.logger.info("Building sentiment analysis pipeline...")
            try:
                trading_signals = create_nse_filings_pipeline(
                    filings_source=filings_input,
                    static_data_path=static_data_path,
                    output_path=signals_output,
                )
                self.logger.info("✓ Sentiment analysis pipeline created successfully")
            except Exception as pipeline_exc:
                self.logger.error("❌ Failed to create sentiment pipeline: %s", pipeline_exc, exc_info=True)
                raise

            def on_new_signal(key, row, time, is_addition, **_):
                if is_addition:
                    symbol = row.get("symbol", "N/A")
                    signal = row.get("signal", "N/A")
                    explanation = (
                        row.get("explanation", "")[:50]
                        if row.get("explanation")
                        else ""
                    )
                    self.logger.info(
                        "[PIPELINE] ✓ Signal generated: %s - Signal: %s - %s...",
                        symbol,
                        signal,
                        explanation,
                    )
                    
                    # Process trade signal immediately for active agents using Celery task
                    if signal in [1, -1]:  # Only process BUY (1) or SELL (-1) signals
                        try:
                            from workers.pipeline_tasks import process_trade_signal
                            from celery_app import celery_app
                            
                            signal_payload = {
                                "symbol": symbol,
                                "signal": signal,
                                "explanation": row.get("explanation", ""),
                                "confidence": row.get("confidence", 0.7),
                                "reference_price": row.get("reference_price"),
                                "timestamp": datetime.utcnow().isoformat(),
                                "source": "nse_pipeline",
                            }
                            
                            # Check if Celery workers are available
                            inspect = celery_app.control.inspect(timeout=2.0)
                            active_queues = inspect.active_queues()
                            
                            if not active_queues:
                                self.logger.error(
                                    "❌ No Celery workers available! Cannot enqueue trade for %s. Start workers with: pnpm celery",
                                    symbol
                                )
                                # Store signal for manual retry
                                self.logger.warning(
                                    "⚠️  Signal stored in trading_signals.jsonl for manual processing: %s %s @ confidence=%.2f",
                                    symbol, "BUY" if signal == 1 else "SELL", row.get("confidence", 0.7)
                                )
                            else:
                                # Enqueue trade signal processing via Celery (async, non-blocking)
                                task = process_trade_signal.apply_async(args=[signal_payload])
                                self.logger.info(
                                    "🚀 Enqueued trade signal processing for %s (signal: %s) - Task ID: %s",
                                    symbol, "BUY" if signal == 1 else "SELL", task.id
                                )
                        except Exception as trade_exc:
                            self.logger.error(
                                "❌ Failed to enqueue trade for signal %s (%s): %s",
                                symbol, signal, trade_exc, exc_info=True
                            )

            def on_signal_end():
                self.logger.info("[PIPELINE] Signal stream ended")

            pw.io.subscribe(trading_signals, on_new_signal, on_signal_end)

            self.logger.info("✓ Pipeline built successfully!")
            self._update_status("running")
            self.logger.info("✓ Running pipeline (will scrape continuously)...")
            self.logger.info("🚀 Pipeline is now running and will process filings in real-time...")
            try:
                pw.run(monitoring_level=pw.MonitoringLevel.NONE)
            except Exception as pipeline_exc:
                self.logger.error("❌ Pathway pipeline crashed: %s", pipeline_exc, exc_info=True)
                raise
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            self.logger.info("Pipeline stopped by user")
        except Exception as exc:
            self.logger.error("Pipeline failed: %s: %s", type(exc).__name__, exc)
            import traceback

            traceback.print_exc()
        finally:
            os.chdir(original_dir)

    def _execute_news_pipeline(self, *, top_k: int) -> Dict[str, Any]:
        pipelines_dir = Path(self.server_dir) / "pipelines"
        news_dir = pipelines_dir / "news"
        sys.path.insert(0, str(pipelines_dir))

        from pipelines.news import execute_news_sentiment_pipeline  # type: ignore  # noqa: E402

        # Load API keys with explicit checking
        news_api_key = os.getenv("NEWS_ORG_API_KEY")
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        self.logger.debug(
            "API keys loaded - NEWS_ORG_API_KEY: %s, GEMINI_API_KEY: %s",
            "present" if news_api_key else "missing",
            "present" if gemini_api_key else "missing",
        )
        
        if gemini_api_key:
            self.logger.info("GEMINI_API_KEY loaded (length: %s)", len(gemini_api_key))

        metadata = execute_news_sentiment_pipeline(
            news_dir,
            news_api_key=news_api_key,
            gemini_api_key=gemini_api_key,
            top_k=top_k,
            logger=self.logger,
        )

        return metadata

    def _load_environment(self) -> None:
        if self._env_loaded:
            return

        server_env = Path(self.server_dir) / ".env"
        project_root = Path(self.server_dir).resolve().parents[1]
        root_env = project_root / ".env"

        if root_env.exists():
            load_dotenv(root_env, override=False)
            self.logger.debug("Loaded root .env: %s", root_env)

        if server_env.exists():
            load_dotenv(server_env, override=True)
            os.environ.setdefault("PORTFOLIO_SERVER_ENV_PATH", str(server_env))
            self.logger.debug("Loaded server .env: %s", server_env)
        else:
            raise FileNotFoundError(
                f".env file not found in portfolio-server directory: {server_env}"
            )

        self._env_loaded = True

    def _update_status(self, state: str) -> None:
        payload = {
            "state": state,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            self.status_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - filesystem issues
            self.logger.warning("Failed to write pipeline status: %s", exc)

    def _update_news_status(
        self,
        state: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "state": state,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        if metadata is not None:
            payload["metadata"] = metadata
        if error is not None:
            payload["error"] = error

        try:
            self.news_status_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - filesystem issues
            self.logger.warning("Failed to write news pipeline status: %s", exc)

    # Legacy helper retained for compatibility
    def is_pipeline_running(self) -> bool:  # pragma: no cover - compatibility
        if not self.status_file.exists():
            return False
        try:
            data = json.loads(self.status_file.read_text(encoding="utf-8"))
            return data.get("state") == "running"
        except Exception:
            return False
    
    async def sell_all_high_risk_positions(self) -> Dict[str, Any]:
        """
        Close all open positions for high_risk trading agents at market close (3:15 PM IST).
        
        PRODUCTION BEHAVIOR:
        - LONG positions (position_type="LONG"): Execute SELL trades
        - SHORT positions (position_type="SHORT"): Execute COVER (BUY) trades
        - All intraday positions MUST be closed before market close (NSE requirement)
        """
        self.logger.info("🔄 Starting to close all high_risk positions before market close (3:15 PM IST)...")
        
        try:
            db_manager = get_db_manager()
            await db_manager.connect()
            
            client = db_manager.get_client()
            
            # Find all high_risk agents
            agents = await client.tradingagent.find_many(
                where={
                    "agent_type": "high_risk",
                    "status": "active",
                },
                include={
                    "portfolio": True,
                }
            )
            
            if not agents:
                self.logger.info("No active high_risk agents found - nothing to close")
                return {
                    "status": "completed",
                    "agents_checked": 0,
                    "long_positions_sold": 0,
                    "short_positions_covered": 0,
                    "errors": 0,
                }
            
            self.logger.info("Found %d active high_risk agent(s)", len(agents))
            
            trade_service = TradeExecutionService(logger=self.logger)
            long_positions_sold = 0
            short_positions_covered = 0
            errors = 0
            
            # For each agent, find all open positions and sell them
            for agent in agents:
                try:
                    portfolio_id = str(getattr(agent, "portfolio_id", ""))
                    if not portfolio_id:
                        continue
                    
                    # Find all open positions for this portfolio
                    positions = await client.position.find_many(
                        where={
                            "portfolio_id": portfolio_id,
                            "status": "open",
                        }
                    )
                    
                    if not positions:
                        continue
                    
                    self.logger.info(
                        "Found %d open position(s) for high_risk agent %s (portfolio %s)",
                        len(positions),
                        getattr(agent, "id", "unknown"),
                        portfolio_id,
                    )
                    
                    # Close each position (SELL for LONG, COVER for SHORT)
                    for position in positions:
                        try:
                            symbol = str(getattr(position, "symbol", ""))
                            quantity = int(getattr(position, "quantity", 0))
                            position_type = str(getattr(position, "position_type", "LONG"))
                            
                            if not symbol or quantity == 0:
                                continue
                            
                            # Get current live price
                            try:
                                from market_data import await_live_price  # type: ignore
                                current_price = await await_live_price(symbol, timeout=5.0)
                                reference_price = float(current_price)
                            except Exception as price_exc:
                                self.logger.warning(
                                    "Could not fetch live price for %s, using average_buy_price: %s",
                                    symbol,
                                    price_exc,
                                )
                                reference_price = float(getattr(position, "average_buy_price", 0))
                            
                            if reference_price == 0:
                                self.logger.warning("Skipping %s: invalid price", symbol)
                                continue
                            
                            # Get portfolio to get user_id
                            portfolio = client.portfolio.find_unique(where={"id": portfolio_id})
                            if not portfolio:
                                continue
                            
                            user_id = str(getattr(portfolio, "customer_id", ""))
                            if not user_id:
                                continue
                            
                            # Determine closing trade side based on position type
                            # LONG position → SELL to close
                            # SHORT position → COVER (BUY) to close
                            import uuid
                            import json
                            from decimal import Decimal
                            
                            if position_type == "SHORT":
                                # SHORT position: Execute COVER (BUY) trade to close
                                trade_side = "COVER"
                                trade_action = "covered"
                                order_type_label = "market_close_cover"
                            else:
                                # LONG position: Execute SELL trade to close
                                trade_side = "SELL"
                                trade_action = "sold"
                                order_type_label = "market_close_sell"

                            closing_trade_data = {
                                "portfolio_id": portfolio_id,
                                "organization_id": getattr(portfolio, "organization_id", None),
                                "customer_id": user_id,
                                "trade_type": "auto",
                                "symbol": symbol,
                                "exchange": "NSE",
                                "segment": "EQUITY",
                                "side": trade_side,
                                "order_type": "market",
                                "quantity": quantity,
                                "price": Decimal(str(reference_price)),
                                "status": "pending",
                                "source": "market_close_worker",
                                "agent_id": str(getattr(agent, "id", "")),
                                "metadata": json.dumps({
                                    "order_type": order_type_label,
                                    "triggered_by": "market_close_worker",
                                    "position_id": str(getattr(position, "id", "")),
                                    "position_type": position_type,
                                    "close_reason": "intraday_market_close_3_15_pm",
                                }),
                            }

                            closing_trade = await client.trade.create(data=closing_trade_data)

                            # Create trade execution log
                            closing_log = await client.tradeexecutionlog.create(
                                data={
                                    "trade_id": closing_trade.id,
                                    "request_id": f"{order_type_label}_{uuid.uuid4().hex[:12]}",
                                    "status": "pending",
                                    "order_type": "market",
                                    "metadata": json.dumps({
                                        "order_type": order_type_label,
                                        "triggered_by": "market_close_worker",
                                        "position_id": str(getattr(position, "id", "")),
                                        "position_type": position_type,
                                    }),
                                },
                            )
                            
                            # Execute the closing trade
                            result = await trade_service.execute_trade(closing_trade.id, simulate=True)
                            
                            if result.get("status") in ["executed", "executed"]:
                                if position_type == "SHORT":
                                    short_positions_covered += 1
                                else:
                                    long_positions_sold += 1
                                    
                                self.logger.info(
                                    "✅ Closed %s position: %s %s x %d @ ₹%.2f (market close 3:15 PM)",
                                    position_type,
                                    trade_side,
                                    symbol,
                                    quantity,
                                    result.get("executed_price", reference_price),
                                )
                            else:
                                errors += 1
                                self.logger.error(
                                    "❌ Failed to sell position %s: %s",
                                    symbol,
                                    result,
                                )
                        
                        except Exception as pos_exc:
                            errors += 1
                            self.logger.error(
                                "❌ Error selling position: %s",
                                pos_exc,
                                exc_info=True,
                            )
                
                except Exception as agent_exc:
                    errors += 1
                    self.logger.error(
                        "❌ Error processing agent %s: %s",
                        getattr(agent, "id", "unknown"),
                        agent_exc,
                        exc_info=True,
                    )
            
            self.logger.info(
                "✅ Market close (3:15 PM IST) completed: %d LONG positions sold, %d SHORT positions covered, %d errors",
                long_positions_sold,
                short_positions_covered,
                errors,
            )
            
            return {
                "status": "completed",
                "agents_checked": len(agents),
                "long_positions_sold": long_positions_sold,
                "short_positions_covered": short_positions_covered,
                "total_positions_closed": long_positions_sold + short_positions_covered,
                "errors": errors,
            }
        
        except Exception as exc:
            self.logger.error("❌ Failed to close high-risk positions at market close: %s", exc, exc_info=True)
            raise

    async def _process_signal_for_active_agents(self, signal_payload: Dict[str, Any]) -> None:
        """Process a trading signal for all active high_risk trading agents."""
        
        try:
            symbol = signal_payload["symbol"]
            signal = signal_payload["signal"]
            confidence = signal_payload.get("confidence", 0.7)
            reference_price = signal_payload.get("reference_price")
            
            self.logger.info(
                "📊 Processing signal for active agents: %s %s (confidence: %.2f)",
                symbol,
                "BUY" if signal == 1 else "SELL",
                confidence,
            )
            
            # Get database connection
            db_manager = get_db_manager()
            await db_manager.connect()
            
            client = db_manager.get_client()
            
            # Fetch all active high_risk trading agents
            agents = await client.tradingagent.find_many(
                where={
                    "agent_type": "high_risk",
                    "status": "active",
                },
                include={"allocation": {"include": {"portfolio": True}}},
            )
            
            if not agents:
                self.logger.warning("⚠️ No active high_risk agents found to process signal %s", symbol)
                return
            
            self.logger.info("Found %d active high_risk agents to process signal", len(agents))
            
            # Initialize trade execution service
            trade_service = TradeExecutionService(logger=self.logger)
            
            trades_created = 0
            errors = 0
            
            for agent in agents:
                try:
                    if not hasattr(agent, "allocation") or not agent.allocation:
                        self.logger.warning("Agent %s has no allocation, skipping", agent.id)
                        continue
                    
                    allocation = agent.allocation
                    portfolio = allocation.portfolio if hasattr(allocation, "portfolio") else None
                    
                    if not portfolio:
                        self.logger.warning("Agent %s allocation has no portfolio, skipping", agent.id)
                        continue
                    
                    # Calculate position size based on allocation value
                    allocated_capital = float(getattr(allocation, "allocated_value", 0))
                    
                    if allocated_capital <= 0:
                        self.logger.debug("Agent %s has no allocated capital, skipping", agent.id)
                        continue
                    
                    # Get current price or use reference price
                    try:
                        from market_data import await_live_price  # type: ignore
                        current_price = await await_live_price(symbol, timeout=5.0)
                        if not current_price or current_price <= 0:
                            current_price = reference_price
                    except:
                        current_price = reference_price
                    
                    if not current_price or current_price <= 0:
                        self.logger.warning("No valid price for %s, skipping agent %s", symbol, agent.id)
                        continue
                    
                    # Calculate quantity based on capital allocation
                    # Use 80% of allocated capital for single position
                    position_capital = allocated_capital * 0.8
                    quantity = int(position_capital / current_price)
                    
                    if quantity <= 0:
                        self.logger.debug("Calculated quantity is 0 for %s (agent %s), skipping", symbol, agent.id)
                        continue
                    
                    # Create trade job payload
                    trade_job = {
                        "request_id": f"nse_{symbol}_{uuid.uuid4().hex[:8]}",
                        "user_id": portfolio.customer_id,
                        "portfolio_id": portfolio.id,
                        "agent_id": agent.id,
                        "agent_type": "high_risk",
                        "agent_status": "active",
                        "symbol": symbol,
                        "side": "BUY" if signal == 1 else "SELL",
                        "quantity": quantity,
                        "reference_price": current_price,
                        "allocated_capital": position_capital,
                        "confidence": confidence,
                        "take_profit_pct": 0.02,  # 2% default TP
                        "stop_loss_pct": 0.01,    # 1% default SL
                        "signal_id": f"nse_{symbol}_{int(datetime.utcnow().timestamp())}",
                        "metadata_json": json.dumps({
                            "source": "nse_pipeline",
                            "signal": signal,
                            "explanation": signal_payload.get("explanation", ""),
                            "triggered_by": "nse_pipeline_auto",
                        }),
                    }
                    
                    self.logger.info(
                        "Creating trade for agent %s: %s %s x %d @ ₹%.2f (capital: ₹%.2f)",
                        agent.id,
                        trade_job["side"],
                        symbol,
                        quantity,
                        current_price,
                        position_capital,
                    )
                    
                    # Persist trade log
                    trade_record = await trade_service.create_trade_log(trade_job)
                    
                    # Execute trade immediately
                    result = await trade_service.execute_trade(trade_record.id, simulate=True)
                    # DEBUG: log raw execution result for troubleshooting
                    self.logger.debug(
                        "DEBUG: execute_trade result for trade log %s: %s",
                        trade_record.id,
                        result,
                    )
                    
                    if result.get("status") in ["executed", "executed"]:
                        trades_created += 1
                        self.logger.info(
                            "✅ Trade executed for agent %s: %s %s x %d @ ₹%.2f",
                            agent.id,
                            trade_job["side"],
                            symbol,
                            quantity,
                            result.get("executed_price", current_price),
                        )
                    else:
                        errors += 1
                        self.logger.error(
                            "❌ Trade execution failed for agent %s: %s",
                            agent.id,
                            result,
                        )
                
                except Exception as agent_exc:
                    errors += 1
                    self.logger.error(
                        "❌ Error creating trade for agent %s: %s",
                        agent.id,
                        agent_exc,
                        exc_info=True,
                    )
            
            self.logger.info(
                "✅ Signal processing completed: %s %s - %d trades created, %d errors",
                symbol,
                "BUY" if signal == 1 else "SELL",
                trades_created,
                errors,
            )
        
        except Exception as exc:
            self.logger.error("❌ Failed to process signal for active agents: %s", exc, exc_info=True)
            raise


