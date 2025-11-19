"""
Portfolio allocation engine driven by adaptive optimisation.

This module encapsulates the portfolio monitoring and optimisation logic used by
the Pathway portfolio allocation pipeline. The implementation is inspired by
the original optimisation notebook and has been adapted to operate in a
production setting with three allocation segments: ``low_risk``, ``high_risk``
and ``alpha``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import numpy.typing as npt


class MarketRegime(Enum):
    """Enumeration of supported market regimes."""

    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"


class RiskTolerance(Enum):
    """Enumeration of client risk tolerance levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class SegmentMetrics:
    """Per-segment performance snapshot."""

    return_rate: float
    volatility: float
    max_drawdown: float
    sharpe_ratio: float


@dataclass
class OptimizationResult:
    """Result container conveyed back to calling layers."""

    weights: Dict[str, float]
    expected_return: float
    expected_risk: float
    objective_value: float
    drift_from_previous: Dict[str, float]
    success: bool
    message: str
    regime: str
    progress_ratio: float


DEFAULT_SEGMENTS: Tuple[str, ...] = ("low_risk", "high_risk", "alpha", "liquid")


class PortfolioMonitor:
    """
    Tracks portfolio valuation and segment metric history.

    The monitor maintains rolling histories used by the optimisation layer to
    derive expected returns, risk metrics and drawdown profiles.
    """

    def __init__(
        self,
        *,
        initial_value: float,
        current_value: Optional[float] = None,
        value_history: Optional[Sequence[float]] = None,
        segment_history: Optional[Mapping[str, Sequence[Mapping[str, float]]]] = None,
        segments: Sequence[str] = DEFAULT_SEGMENTS,
    ) -> None:
        self.segments: Tuple[str, ...] = tuple(segments)
        self.initial_value: float = float(initial_value)
        self.current_value: float = (
            float(current_value) if current_value is not None else float(initial_value)
        )
        self.value_history: List[float] = (
            list(map(float, value_history)) if value_history else [float(initial_value), float(self.current_value)]
        )
        # Minimum of one quarter to avoid division-by-zero in progress metrics.
        self.time_quarters: int = max(1, len(self.value_history) - 1)
        self.history: Dict[str, List[SegmentMetrics]] = {
            segment: [] for segment in self.segments
        }
        if segment_history:
            for segment, metrics_list in segment_history.items():
                if segment not in self.history:
                    continue
                for metrics in metrics_list:
                    self.history[segment].append(
                        SegmentMetrics(
                            return_rate=float(metrics.get("return_rate", 0.0)),
                            volatility=float(metrics.get("volatility", 0.0)),
                            max_drawdown=float(metrics.get("max_drawdown", 0.0)),
                            sharpe_ratio=float(metrics.get("sharpe_ratio", 0.0)),
                        )
                    )
            self.time_quarters = max(
                self.time_quarters,
                max((len(values) for values in self.history.values()), default=1),
            )

    # ------------------------------------------------------------------ Metrics
    def record_quarter(
        self, segment_metrics: Mapping[str, SegmentMetrics], *, new_portfolio_value: float
    ) -> None:
        """Persist a completed quarter into rolling histories."""

        for segment, metrics in segment_metrics.items():
            if segment in self.history:
                self.history[segment].append(metrics)

        self.current_value = float(new_portfolio_value)
        self.value_history.append(self.current_value)
        self.time_quarters += 1

    def get_latest_metrics(self) -> Dict[str, SegmentMetrics]:
        """Return most recently observed metrics, or cold-start defaults."""

        defaults = SegmentMetrics(
            return_rate=0.02,
            volatility=0.05,
            max_drawdown=0.03,
            sharpe_ratio=0.4,
        )
        latest: Dict[str, SegmentMetrics] = {}
        for segment in self.segments:
            latest[segment] = self.history[segment][-1] if self.history[segment] else defaults
        return latest

    def get_rolling_metrics(self, *, lookback_quarters: int = 4) -> Dict[str, SegmentMetrics]:
        """Return rolling average metrics across the provided lookback window."""

        rolling: Dict[str, SegmentMetrics] = {}
        for segment in self.segments:
            metrics_history = self.history[segment]
            if not metrics_history:
                rolling[segment] = self.get_latest_metrics()[segment]
                continue
            window = (
                metrics_history[-lookback_quarters:]
                if len(metrics_history) >= lookback_quarters
                else metrics_history
            )
            rolling[segment] = SegmentMetrics(
                return_rate=float(np.mean([m.return_rate for m in window])),
                volatility=float(np.mean([m.volatility for m in window])),
                max_drawdown=float(np.mean([m.max_drawdown for m in window])),
                sharpe_ratio=float(np.mean([m.sharpe_ratio for m in window])),
            )
        return rolling

    def get_cumulative_return(self) -> float:
        """Compute cumulative return since inception."""

        if self.initial_value <= 0:
            return 0.0
        return (self.current_value - self.initial_value) / self.initial_value


class PortfolioManager:
    """Dynamic allocator orchestrating segment weights based on adaptive factors."""

    def __init__(
        self,
        *,
        user_inputs: Mapping[str, Any],
        monitor: PortfolioMonitor,
        segments: Sequence[str] = DEFAULT_SEGMENTS,
    ) -> None:
        self.user_inputs = dict(user_inputs)
        self.monitor = monitor
        self.segments: Tuple[str, ...] = tuple(segments)
        allocation = self.user_inputs.get("allocation_strategy", {})
        weights = np.array(
            [float(allocation.get(segment, 1.0 / len(self.segments))) for segment in self.segments],
            dtype=float,
        )
        if weights.sum() <= 0:
            weights = np.full_like(weights, 1.0 / len(weights))
        self.current_weights: npt.NDArray[np.float_] = weights / weights.sum()

        self._setup_constraints()
        self._setup_hyperparameters()

    # ------------------------------------------------------------- Configuration
    def _setup_constraints(self) -> None:
        """Extract risk-wise constraints and drift tolerances from user preferences."""

        constraints = self.user_inputs.get("constraints", {})
        self.max_drift: float = float(constraints.get("max_weight_drift", 0.15))
        segment_wise = constraints.get("segment_wise", {})
        self.weight_bounds: Dict[str, Tuple[float, float]] = {}
        for segment in self.segments:
            bounds = segment_wise.get(segment, {})
            self.weight_bounds[segment] = (
                float(bounds.get("min", 0.0)),
                float(bounds.get("max", 1.0)),
            )
        self.min_weights = np.array([self.weight_bounds[segment][0] for segment in self.segments], dtype=float)
        self.max_weights = np.array([self.weight_bounds[segment][1] for segment in self.segments], dtype=float)

    def _setup_hyperparameters(self) -> None:
        """Define optimisation hyperparameters and adaptive scaling rules."""

        self.base_lambda_variance: float = 2.0
        self.base_lambda_drawdown: float = 1.5

        self.risk_tolerance_scales: Dict[RiskTolerance, float] = {
            RiskTolerance.LOW: 2.0,
            RiskTolerance.MEDIUM: 1.0,
            RiskTolerance.HIGH: 0.5,
        }
        self.regime_scales: Dict[MarketRegime, Dict[str, float]] = {
            MarketRegime.BULL: {"variance": 0.6, "drawdown": 0.4},
            MarketRegime.BEAR: {"variance": 1.8, "drawdown": 1.5},
            MarketRegime.SIDEWAYS: {"variance": 1.0, "drawdown": 0.8},
            MarketRegime.HIGH_VOLATILITY: {"variance": 2.5, "drawdown": 3.0},
        }
        self.progress_adjustment = {
            "behind_aggression": 0.6,
            "ahead_conservation": 0.4,
        }

    # ----------------------------------------------------------------- Utilities
    def compute_progress_ratio(self) -> float:
        """Progress ratio relative to the client's target return trajectory."""

        cumulative_return = self.monitor.get_cumulative_return()
        annual_target = float(self.user_inputs.get("expected_return_target", 0.08))
        horizon_years = float(self.user_inputs.get("investment_horizon_years", 1.0))
        quarters_elapsed = max(1, self.monitor.time_quarters)
        fraction_elapsed = quarters_elapsed / (4.0 * max(horizon_years, 1e-6))
        target_cumulative = (1.0 + annual_target) ** fraction_elapsed - 1.0
        if target_cumulative <= 0:
            return 1.0
        progress = (1.0 + cumulative_return) / (1.0 + target_cumulative)
        return float(max(0.05, min(3.0, progress)))

    def compute_adaptive_penalties(
        self,
        *,
        regime: MarketRegime,
        progress_ratio: float,
        risk_tolerance: RiskTolerance,
    ) -> Tuple[float, float]:
        """Combine risk tolerance, market regime and progress into penalty weights."""

        base_scale = self.risk_tolerance_scales[risk_tolerance]
        lambda_var = self.base_lambda_variance * base_scale
        lambda_dd = self.base_lambda_drawdown * base_scale

        regime_scale = self.regime_scales.get(regime, self.regime_scales[MarketRegime.SIDEWAYS])
        lambda_var *= regime_scale["variance"]
        lambda_dd *= regime_scale["drawdown"]

        if progress_ratio < 1.0:
            adjustment = 1.0 - self.progress_adjustment["behind_aggression"] * (1.0 - progress_ratio)
            scaling = max(0.3, adjustment)
            lambda_var *= scaling
            lambda_dd *= scaling
        else:
            adjustment = 1.0 + self.progress_adjustment["ahead_conservation"] * (progress_ratio - 1.0)
            scaling = min(2.0, adjustment)
            lambda_var *= scaling
            lambda_dd *= scaling

        return lambda_var, lambda_dd

    # ---------------------------------------------------------------- Optimiser
    def get_variance(self, metrics: Mapping[str, SegmentMetrics]) -> npt.NDArray[np.float_]:
        """
        Construct covariance matrix from segment volatilities and correlations.

        Args:
            metrics: Dictionary of segment metrics

        Returns:
            4x4 covariance matrix
        """
        vols = np.array([metrics[segment].volatility for segment in self.segments], dtype=float)
        variance = vols ** 2

        return variance

    def _solve_optimisation(
        self,
        *,
        expected_returns: npt.NDArray[np.float_],
        covariance: npt.NDArray[np.float_],
        drawdowns: npt.NDArray[np.float_],
        lambda_var: float,
        lambda_dd: float,
        activate_drawdown_penalty: bool,
    ) -> Optional[npt.NDArray[np.float_]]:
        """Solve the convex optimisation problem using cvxpy."""

        import cvxpy as cp  # Imported lazily to limit worker initialisation costs.

        n = len(self.segments)
        w = cp.Variable(n)

        portfolio_return = expected_returns @ w
        portfolio_variance = cp.quad_form(w, covariance)
        drawdown_penalty = drawdowns @ w if activate_drawdown_penalty else 0

        objective = cp.Maximize(
            portfolio_return - lambda_var * portfolio_variance - lambda_dd * drawdown_penalty
        )

        constraints = [
            cp.sum(w) == 1.0,
            w >= self.min_weights,
            w <= self.max_weights,
            w - self.current_weights <= self.max_drift,
            self.current_weights - w <= self.max_drift,
        ]

        problem = cp.Problem(objective, constraints)
        try:
            problem.solve(solver=cp.OSQP, warm_start=True, eps_abs=1e-6, eps_rel=1e-6)
        except Exception:
            return None

        if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
            return None
        if w.value is None:
            return None
        return np.asarray(w.value, dtype=float).flatten()

    def rebalance(
        self,
        *,
        current_regime: str,
        use_rolling_metrics: bool = True,
        lookback_quarters: int = 4,
    ) -> OptimizationResult:
        """Compute the next allocation vector."""

        try:
            regime = MarketRegime(current_regime.lower())
        except ValueError:
            regime = MarketRegime.SIDEWAYS

        metrics = (
            self.monitor.get_rolling_metrics(lookback_quarters=lookback_quarters)
            if use_rolling_metrics and self.monitor.time_quarters >= 2
            else self.monitor.get_latest_metrics()
        )

        mu = np.array([metrics[segment].return_rate for segment in self.segments], dtype=float)
        covariance = self.get_variance(metrics)
        drawdowns = np.array([metrics[segment].max_drawdown for segment in self.segments], dtype=float)

        risk_tol_raw = str(self.user_inputs.get("risk_tolerance", "medium")).upper()
        risk_tolerance = RiskTolerance[risk_tol_raw] if risk_tol_raw in RiskTolerance.__members__ else RiskTolerance.MEDIUM
        progress_ratio = self.compute_progress_ratio()
        lambda_var, lambda_dd = self.compute_adaptive_penalties(
            regime=regime,
            progress_ratio=progress_ratio,
            risk_tolerance=risk_tolerance,
        )
        activate_dd = regime == MarketRegime.HIGH_VOLATILITY

        optimal_weights = self._solve_optimisation(
            expected_returns=mu,
            covariance=covariance,
            drawdowns=drawdowns,
            lambda_var=lambda_var,
            lambda_dd=lambda_dd,
            activate_drawdown_penalty=activate_dd,
        )

        if optimal_weights is None:
            expected_return = float(mu @ self.current_weights)
            current_risk = float(math.sqrt(self.current_weights @ covariance @ self.current_weights))
            return OptimizationResult(
                weights={segment: float(self.current_weights[i]) for i, segment in enumerate(self.segments)},
                expected_return=expected_return,
                expected_risk=current_risk,
                objective_value=expected_return - lambda_var * (self.current_weights @ covariance @ self.current_weights),
                drift_from_previous={segment: 0.0 for segment in self.segments},
                success=False,
                message="Optimisation failed; retaining existing weights",
                regime=regime.value,
                progress_ratio=progress_ratio,
            )

        optimal_weights = np.clip(optimal_weights, self.min_weights, self.max_weights)
        if optimal_weights.sum() <= 0:
            optimal_weights = np.full_like(optimal_weights, 1.0 / len(optimal_weights))
        optimal_weights = optimal_weights / optimal_weights.sum()

        drift = optimal_weights - self.current_weights
        expected_return = float(mu @ optimal_weights)
        portfolio_variance = float(optimal_weights @ covariance @ optimal_weights)
        expected_risk = float(math.sqrt(max(portfolio_variance, 0.0)))
        objective_value = expected_return - lambda_var * portfolio_variance
        if activate_dd:
            objective_value -= lambda_dd * float(drawdowns @ optimal_weights)

        self.current_weights = optimal_weights

        return OptimizationResult(
            weights={segment: float(optimal_weights[i]) for i, segment in enumerate(self.segments)},
            expected_return=expected_return,
            expected_risk=expected_risk,
            objective_value=objective_value,
            drift_from_previous={segment: float(drift[i]) for i, segment in enumerate(self.segments)},
            success=True,
            message=f"Optimisation successful in {regime.value} regime (progress={progress_ratio:.2f})",
            regime=regime.value,
            progress_ratio=progress_ratio,
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def ensure_segment_metrics(
    data: Optional[Mapping[str, Sequence[Mapping[str, Any]]]],
    segments: Sequence[str] = DEFAULT_SEGMENTS,
) -> Dict[str, List[SegmentMetrics]]:
    """Transform a raw mapping into structured ``SegmentMetrics`` entries."""

    segment_metrics: Dict[str, List[SegmentMetrics]] = {segment: [] for segment in segments}
    if not data:
        return segment_metrics

    for segment, metrics_list in data.items():
        if segment not in segment_metrics:
            continue
        for raw in metrics_list:
            segment_metrics[segment].append(
                SegmentMetrics(
                    return_rate=float(raw.get("return_rate", 0.0)),
                    volatility=float(raw.get("volatility", 0.0)),
                    max_drawdown=float(raw.get("max_drawdown", 0.0)),
                    sharpe_ratio=float(raw.get("sharpe_ratio", 0.0)),
                )
            )
    return segment_metrics


def initial_weight_vector(segments: Sequence[str], allocation: Optional[Mapping[str, Any]] = None) -> Dict[str, float]:
    """Produce a default even-split weight vector honouring any overrides."""

    allocation = allocation or {}
    weights = np.array(
        [float(allocation.get(segment, 1.0 / len(segments))) for segment in segments],
        dtype=float,
    )
    if weights.sum() <= 0:
        weights = np.full_like(weights, 1.0 / len(weights))
    weights = weights / weights.sum()
    return {segment: float(weights[i]) for i, segment in enumerate(segments)}

