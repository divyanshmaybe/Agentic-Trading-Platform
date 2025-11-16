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
from pipelines.portfolio.portfolio_manager import DEFAULT_SEGMENTS  # type: ignore  # noqa: E402
from pipelines.risk import (  # type: ignore  # noqa: E402
    prepare_risk_alerts,
    publish_risk_alerts_to_kafka,
    run_risk_monitor_requests,
)
from pipelines.nse.trade_execution_pipeline import (  # type: ignore  # noqa: E402
    run_trade_execution_requests,
)
from utils import allocate_portfolios  # type: ignore  # noqa: E402
from utils.risk_monitor import prepare_risk_monitor_requests  # type: ignore  # noqa: E402
from utils.symbol_based_risk_monitor import prepare_symbol_based_risk_requests  # type: ignore  # noqa: E402
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
        if not manager.is_connected():
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
        if not manager.is_connected():
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
        if not manager.is_connected():
            await manager.connect()
        client = manager.get_client()

        # Get market data service
        market_service = None
        try:
            market_service = get_market_data_service()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.logger.warning("Risk monitor: market data service unavailable (%s)", exc)
            return {"processed": 0, "alerts": 0, "published": 0, "emails_queued": 0}

        # NEW APPROACH: Symbol-based monitoring (more efficient)
        # 1. Get unique symbols across all positions
        # 2. Fetch price ONCE per symbol
        # 3. Query database for affected users (SQL filtering)
        requests, monitoring_metadata = await prepare_symbol_based_risk_requests(
            client,
            market_service,
            logger=self.logger,
        )

        if not requests:
            self.logger.info(
                "Risk monitor: no affected users (symbols=%s, prices=%s)",
                monitoring_metadata.get("unique_symbols", 0),
                monitoring_metadata.get("prices_fetched", 0),
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

        if not allocation_strategy:
            equal_weight = 1.0 / len(DEFAULT_SEGMENTS)
            allocation_strategy = {segment: equal_weight for segment in DEFAULT_SEGMENTS}

        user_inputs = {
            "risk_tolerance": portfolio.risk_tolerance,
            "expected_return_target": self._safe_float(portfolio.expected_return_target),
            "investment_horizon_years": int(getattr(portfolio, "investment_horizon_years", 1) or 1),
            "liquidity_needs": portfolio.liquidity_needs,
            "constraints": constraints,
            "allocation_strategy": allocation_strategy,
        }

        initial_value = self._safe_float(
            portfolio.initial_investment,
            default=self._safe_float(
                portfolio.investment_amount,
                default=self._safe_float(portfolio.current_value),
            ),
        )
        current_value = self._safe_float(portfolio.current_value, default=initial_value)

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
        weights_raw = result.get("weights") or {}
        if not isinstance(weights_raw, Mapping):
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
                default=self._safe_float(portfolio.current_value),
            ),
        )
        current_value = self._safe_float(portfolio.current_value, default=total_investable)
        drift_values = result.get("drift") or {}

        metadata_payload = self._clean_json(dict(portfolio.metadata or {}))
        regime_value = result.get("regime") or metadata_payload.get("current_regime")
        if regime_value:
            metadata_payload["current_regime"] = regime_value

        allocations = getattr(portfolio, "allocations", []) or []
        allocation_lookup = {alloc.allocation_type: alloc for alloc in allocations}
        segments = set(allocation_lookup.keys()) | set(weights.keys())

        for segment in sorted(segments):
            weight = weights.get(segment, 0.0)
            drift = self._safe_float(drift_values.get(segment, 0.0))
            target_weight_dec = self._to_decimal(weight, places=6)
            allocated_amount_dec = self._to_decimal(total_investable * weight, places=4)
            current_value_dec = self._to_decimal(current_value * weight, places=4)
            drift_dec = self._to_decimal(drift, places=6)

            allocation = allocation_lookup.get(segment)
            if allocation:
                allocation_metadata = self._clean_json(dict(allocation.metadata or {}))
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
                        "current_value": current_value_dec,
                        "drift_percentage": drift_dec,
                        "requires_rebalancing": False,
                        "metadata": allocation_metadata,
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
                        "current_value": current_value_dec,
                        "metadata": {
                            "created_at": as_of.isoformat() + "Z",
                            "created_by": triggered_by,
                            "trigger_reason": trigger_reason,
                        },
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
                "allocation_strategy": allocation_strategy_payload,
                "last_rebalanced_at": as_of,
                "next_rebalance_at": next_rebalance_at,
                "metadata": metadata_payload,
            },
        )

        snapshot_value_dec = self._to_decimal(current_value, places=4)
        time_elapsed_days = (
            (as_of - portfolio.last_rebalanced_at).days
            if getattr(portfolio, "last_rebalanced_at", None)
            else None
        )

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
                "expected_progress": {"progress_ratio": result.get("progress_ratio")},
                "metadata": rebalance_metadata,
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
                continue

            snapshot_amount = self._to_decimal(total_investable * weight, places=4)
            snapshot_current_value = self._to_decimal(current_value * weight, places=4)

            await client.allocationsnapshot.create(
                data={
                    "rebalance_run_id": rebalance_run.id,
                    "portfolio_allocation_id": allocation.id,
                    "snapshot_weight": self._to_decimal(weight, places=6),
                    "snapshot_amount": snapshot_amount,
                    "snapshot_current_value": snapshot_current_value,
                    "snapshot_pnl": self._to_decimal(0.0, places=4),
                    "metadata": {
                        "regime": result.get("regime"),
                        "generated_at": as_of.isoformat() + "Z",
                    },
                }
            )

            await client.segmentsnapshot.create(
                data={
                    "rebalance_run_id": rebalance_run.id,
                    "segment_key": segment,
                    "allocated_amount": snapshot_amount,
                    "liquid_amount": self._to_decimal(0.0, places=4),
                    "invested_amount": snapshot_current_value,
                    "return_pct": self._to_decimal(0.0, places=6),
                    "volatility": self._to_decimal(0.0, places=6),
                    "max_drawdown": self._to_decimal(0.0, places=6),
                    "sharpe_ratio": None,
                    "metrics": {
                        "expected_return": result.get("expected_return"),
                        "expected_risk": result.get("expected_risk"),
                    },
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

    def _build_portfolio_snapshot(
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

        return PortfolioSnapshot(
            portfolio_id=str(getattr(portfolio, "id")),
            portfolio_name=str(getattr(portfolio, "portfolio_name", "Portfolio")),
            user_id=str(user_id),
            organization_id=getattr(portfolio, "organization_id", None),
            customer_id=getattr(portfolio, "customer_id", None),
            current_value=self._safe_float(getattr(portfolio, "current_value", 0.0)),
            investment_amount=self._safe_float(getattr(portfolio, "investment_amount", 0.0)),
            cash_available=cash_available,
            metadata=metadata,
            agent_id=agent_id,
            agent_type=agent_type,
            agent_status=agent_status,
            agent_metadata=agent_metadata_dict,
            agent_config=agent_config_dict,
        )

    def _build_trade_signal(self, payload: Mapping[str, Any]) -> Optional[TradeSignal]:
        symbol = payload.get("symbol")
        if not symbol:
            return None

        try:
            signal_value = int(payload.get("signal", 0))
        except (TypeError, ValueError):
            return None

        confidence = self._safe_float(payload.get("confidence"), default=0.0)
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

        manager = get_db_manager()
        if not manager.is_connected():
            await manager.connect()
        client = manager.get_client()

        trade_service = TradeExecutionService(logger=self.logger)

        high_risk_users = await self._fetch_high_risk_user_ids(client)
        if not high_risk_users:
            self.logger.info("No high-risk subscribers available for trade automation")
            return {
                "processed_signals": len(processed_signals),
                "payloads": 0,
                "jobs": 0,
                "dispatched": 0,
            }

        portfolios = await client.portfolio.find_many(
            where={
                "user_id": {"in": high_risk_users},
                "status": "active",
            },
            include={"agents": True},
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

            snapshot = self._build_portfolio_snapshot(
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
        job_rows = run_trade_execution_requests(request_events, logger=self.logger)
        if not job_rows:
            self.logger.info("Trade execution pipeline produced no actionable jobs")
            return {
                "processed_signals": len(processed_signals),
                "payloads": len(payloads),
                "jobs": 0,
                "dispatched": 0,
            }
        
        # Add triggered_by to each job row for tracking
        for job_row in job_rows:
            job_row["triggered_by"] = "high_risk_agent"

        events = await trade_service.persist_and_publish(
            job_rows,
            publish_kafka=publish_kafka,
        )

        dispatched = 0
        if events:
            try:
                from workers.trade_execution_tasks import execute_trade_job  # type: ignore

                for event in events:
                    execute_trade_job.delay(event.trade_id)
                    dispatched += 1
                    self.logger.info(
                        "✅ Enqueued trade execution: Trade %s | Agent %s (%s) | %s %s x %d | Portfolio %s",
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

        return {
            "processed_signals": len(processed_signals),
            "payloads": len(payloads),
            "jobs": len(job_rows),
            "dispatched": dispatched,
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
            from nse_backtest import compute_backtest_metrics, create_backtest_pipeline
            from nse_filings_sentiment import create_nse_filings_pipeline
            from nse_live_scraper import create_nse_scraper_input

            self.logger.info("=" * 70)
            self.logger.info("NSE Live Trading Pipeline - Real-time Sentiment Analysis")
            self.logger.info("=" * 70)

            refresh_interval = int(os.getenv("NSE_REFRESH_INTERVAL", "60"))
            static_data_path = "staticdata.csv"
            signals_output = "trading_signals.jsonl"
            backtest_output = "backtest_results.jsonl"
            metrics_output = "backtest_metrics.jsonl"

            if not os.path.exists(static_data_path):
                self.logger.info(
                    "staticdata.csv not found - using default impact scenarios"
                )

            self.logger.info(
                "Starting live NSE scraper (interval: %ss)...", refresh_interval
            )
            filings_input = create_nse_scraper_input(refresh_interval=refresh_interval)

            self.logger.info("Building sentiment analysis pipeline...")
            trading_signals = create_nse_filings_pipeline(
                filings_source=filings_input,
                static_data_path=static_data_path,
                output_path=signals_output,
            )

            self.logger.info("Building backtest pipeline...")
            backtest_results = create_backtest_pipeline(trading_signals)
            backtest_metrics = compute_backtest_metrics(backtest_results)

            pw.io.jsonlines.write(backtest_results, backtest_output)
            pw.io.jsonlines.write(backtest_metrics, metrics_output)

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

            def on_new_backtest(key, row, time, is_addition, **_):
                del key, time
                if is_addition:
                    symbol = row.get("symbol", "N/A")
                    pnl = row.get("pnl", 0)
                    exit_reason = row.get("exit_reason", "N/A")
                    self.logger.info(
                        "[PIPELINE] ✓ Backtest result: %s - PnL: %.4f - Exit: %s",
                        symbol,
                        pnl,
                        exit_reason,
                    )

            def on_signal_end():
                self.logger.info("[PIPELINE] Signal stream ended")

            def on_backtest_end():
                self.logger.info("[PIPELINE] Backtest stream ended")

            pw.io.subscribe(trading_signals, on_new_signal, on_signal_end)
            pw.io.subscribe(backtest_results, on_new_backtest, on_backtest_end)

            self.logger.info("✓ Pipeline built successfully!")
            self._update_status("running")
            self.logger.info("✓ Running pipeline (will scrape continuously)...")
            pw.run(monitoring_level=pw.MonitoringLevel.NONE)
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

