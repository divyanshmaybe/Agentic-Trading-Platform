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
        # Minimum of one semi_annual to avoid division-by-zero in progress metrics.
        self.time_semi_annual: int = max(1, len(self.value_history) - 1)
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
            self.time_semi_annual = max(
                self.time_semi_annual,
                max((len(values) for values in self.history.values()), default=1),
            )

    # ------------------------------------------------------------------ Metrics
    def record_semi_annual(
        self, segment_metrics: Mapping[str, SegmentMetrics], *, new_portfolio_value: float
    ) -> None:
        """Persist a completed semi_annual into rolling histories."""

        for segment, metrics in segment_metrics.items():
            if segment in self.history:
                self.history[segment].append(metrics)

        self.current_value = float(new_portfolio_value)
        self.value_history.append(self.current_value)
        self.time_semi_annual += 1

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

    def get_rolling_metrics(self, *, lookback_semi_annual: int = 4) -> Dict[str, SegmentMetrics]:
        """Return rolling average metrics across the provided lookback window."""

        rolling: Dict[str, SegmentMetrics] = {}
        for segment in self.segments:
            metrics_history = self.history[segment]
            if not metrics_history:
                rolling[segment] = self.get_latest_metrics()[segment]
                continue
            window = (
                metrics_history[-lookback_semi_annual:]
                if len(metrics_history) >= lookback_semi_annual
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
    """
    Manages dynamic portfolio allocation across risk segments with adaptive optimization.

    This manager implements a sophisticated optimization strategy that adapts to:
    - Market regimes (bull, bear, sideways, high volatility)
    - User risk tolerance
    - Progress toward target returns

    Optimization Objective:
        maximize: E[R] - λ_a * σ² - λ_b * MDD

    where:
        - E[R] is expected return
        - σ² is portfolio variance
        - MDD is maximum drawdown (only active in high volatility regime)
        - λ_a, λ_b are adaptive hyperparameters
    """

    def __init__(self, user_inputs: Dict[str, Any], monitor: PortfolioMonitor, segments: Sequence[str] = DEFAULT_SEGMENTS):
        self.segments = tuple(segments)
        self.user_inputs = user_inputs
        self.monitor = monitor
        self.default_weights = {
        'low_risk': 0.6,
        'high_risk': 0.15,
        'alpha': 0.15,
        'liquid': 0.1
        }

        # Initialize current weights from user allocation strategy
        allocation = user_inputs.get('allocation_strategy', {})
        self.current_weights = np.array([
            allocation.get(seg, self.default_weights[seg]) for seg in self.segments
        ], dtype=float)
        # Normalize to ensure sum = 1
        self.current_weights /= self.current_weights.sum()

        # Extract constraints
        self._setup_constraints()

        # Setup hyperparameter configuration
        self._setup_hyperparameters()
        
    def _setup_constraints(self) -> None:
        """Extract and organize constraints from user inputs."""
        constraints = self.user_inputs.get('constraints', {})
        print(f"DEBUG: Raw constraints: {constraints}")

        # Maximum drift per rebalancing
        self.max_drift = constraints.get('max_weight_drift', 0.15)
        print(f"DEBUG: max_drift: {self.max_drift}")

        # Per-segment bounds
        segment_wise = constraints.get('segment_wise', {})
        print(f"DEBUG: segment_wise: {segment_wise}")
        self.weight_bounds = {}
        for segment in self.segments:
            seg_bounds = segment_wise.get(segment, {})
            self.weight_bounds[segment] = (
                seg_bounds.get('min', 0.0),
                seg_bounds.get('max', 1.0)
            )
        print(f"DEBUG: weight_bounds: {self.weight_bounds}")

        # Convert to arrays for optimization
        self.min_weights = np.array([self.weight_bounds[seg][0] for seg in self.segments])
        self.max_weights = np.array([self.weight_bounds[seg][1] for seg in self.segments])
        print(f"DEBUG: min_weights: {self.min_weights}")
        print(f"DEBUG: max_weights: {self.max_weights}")

    def _setup_hyperparameters(self) -> None:
        """Setup base hyperparameters and scaling factors."""
        # Base penalty weights (before scaling)
        self.base_lambda_variance = 2.0
        self.base_lambda_drawdown = 1.5

        # Risk tolerance multipliers (higher tolerance = lower penalty)
        self.risk_tolerance_scales = {
            RiskTolerance.LOW: 2.0,      # Very risk averse
            RiskTolerance.MEDIUM: 1.0,   # Balanced
            RiskTolerance.HIGH: 0.5      # Risk seeking
        }

        # Regime-specific multipliers for penalties
        self.regime_scales = {
            MarketRegime.BULL: {
                'variance': 0.6,    # Less concerned about volatility
                'drawdown': 0.4     # Less concerned about drawdowns
            },
            MarketRegime.BEAR: {
                'variance': 2.5,    # More risk averse
                'drawdown': 1.5     # Highly concerned about drawdowns
            },
            MarketRegime.SIDEWAYS: {
                'variance': 1.0,    # Neutral stance
                'drawdown': 0.8     # Moderate concern
            },
            MarketRegime.HIGH_VOLATILITY: {
                'variance': 2.5,    # Very risk averse
                'drawdown': 3.0     # Maximum drawdown concern
            }
        }

        # Progress adjustment parameters
        self.progress_adjustment = {
            'behind_aggression': 0.6,  # Reduce penalty when behind target
            'ahead_conservation': 0.4   # Increase penalty when ahead of target
        }
    def compute_progress_ratio(self) -> float:
        """
        Calculate progress ratio relative to target return path.

        Progress > 1.0: Ahead of target
        Progress < 1.0: Behind target
        Progress ≈ 1.0: On track

        Returns:
            Progress ratio
        """
        cumulative_return = self.monitor.get_cumulative_return()

        # Calculate expected cumulative return to date
        target = self.user_inputs.get('expected_return_target')
        horizon_years = self.user_inputs.get('investment_horizon_years')
        semi_annual_elapsed = max(1, self.monitor.time_semi_annual)

        # Target cumulative return for this point in time
        fraction_elapsed = semi_annual_elapsed / (2.0 * horizon_years)
        target_cumulative = (1 + target) ** fraction_elapsed - 1

        # Progress ratio
        if target_cumulative <= 0:
            return 1.0

        progress = (1 + cumulative_return) / (1 + target_cumulative)
        return max(0.05, min(3.0, progress)) # clip it between some range

    def compute_adaptive_penalties(self,
                                   regime: MarketRegime,
                                   progress_ratio: float) -> Tuple[float, float]:
        """
        Calculate adaptive penalty weights based on regime, risk tolerance, and progress.

        Args:
            regime: Current market regime
            progress_ratio: Progress toward target return

        Returns:
            Tuple of (lambda_variance, lambda_drawdown)
        """
        # Get risk tolerance
        risk_tol_str = self.user_inputs.get('risk_tolerance').lower()
        risk_tol = RiskTolerance[risk_tol_str.upper()]

        # Base penalties scaled by risk tolerance
        risk_scale = self.risk_tolerance_scales[risk_tol]
        lambda_var = self.base_lambda_variance * risk_scale
        lambda_dd = self.base_lambda_drawdown * risk_scale

        # Apply regime multipliers
        regime_scale = self.regime_scales[regime]
        lambda_var *= regime_scale['variance']
        lambda_dd *= regime_scale['drawdown']

        # Adjust based on progress toward target
        if progress_ratio < 1.0:
            # Behind target: be more aggressive (reduce penalties)
            adjustment = 1.0 - self.progress_adjustment['behind_aggression'] * (1.0 - progress_ratio)
            lambda_var *= max(0.3, adjustment)
            lambda_dd *= max(0.3, adjustment)
        else:
            # Ahead of target: be more conservative (increase penalties)
            adjustment = 1.0 + self.progress_adjustment['ahead_conservation'] * (progress_ratio - 1.0)
            lambda_var *= min(2.0, adjustment)
            lambda_dd *= min(2.0, adjustment)

        return lambda_var, lambda_dd

    def get_variance(self, metrics: Dict[str, SegmentMetrics]) -> np.ndarray:
        """
        Returns volatility of each segment as a variance vector.
        """
        vols = np.array([metrics[seg].volatility for seg in self.segments])
        variance = vols ** 2

        return variance

    def solve_optimization(self,
                          expected_returns: np.ndarray,
                          variance: np.ndarray,
                          drawdowns: np.ndarray,
                          lambda_var: float,
                          lambda_dd: float,
                          activate_dd_penalty: bool) -> Optional[np.ndarray]:
        """
        Solve the portfolio optimization problem using cvxpy.

        Args:
            expected_returns: Expected return vector for each segment
            covariance: Covariance matrix
            drawdowns: Maximum drawdown vector
            lambda_var: Variance penalty weight
            lambda_dd: Drawdown penalty weight
            activate_dd_penalty: Whether to activate drawdown penalty

        Returns:
            Optimal weight vector, or None if optimization fails
        """
        import cvxpy as cp  # Imported lazily to limit worker initialisation costs.

        print(f"DEBUG: solve_optimization called with:")
        print(f"  expected_returns: {expected_returns}")
        print(f"  variance: {variance}")
        print(f"  drawdowns: {drawdowns}")
        print(f"  lambda_var: {lambda_var}, lambda_dd: {lambda_dd}")
        print(f"  activate_dd_penalty: {activate_dd_penalty}")
        print(f"  current_weights: {self.current_weights}")
        print(f"  min_weights: {self.min_weights}")
        print(f"  max_weights: {self.max_weights}")
        print(f"  max_drift: {self.max_drift}")

        n = len(self.segments)
        w = cp.Variable(n)

        # Objective components
        portfolio_return = expected_returns @ w
        portfolio_variance = w @ variance
        drawdown_penalty = drawdowns @ w if activate_dd_penalty else 0

        print(f"DEBUG: portfolio_return: {portfolio_return}")
        print(f"DEBUG: portfolio_variance: {portfolio_variance}")
        print(f"DEBUG: drawdown_penalty: {drawdown_penalty}")

        # Maximize: E[R] - λ_a * σ² - λ_b * MDD
        # cvxpy minimizes, so negate
        objective = cp.Maximize(
            portfolio_return
            - lambda_var * portfolio_variance
            - lambda_dd * drawdown_penalty
        )

        # Constraints
        constraints = [
            cp.sum(w) == 1,                                    # Fully invested
            w >= self.min_weights,                             # Lower bounds
            w <= self.max_weights,                             # Upper bounds
            w - self.current_weights <= self.max_drift,       # Max increase per segment
            self.current_weights - w <= self.max_drift        # Max decrease per segment
        ]

        print(f"DEBUG: Constraints:")
        for i, constraint in enumerate(constraints):
            print(f"  {i}: {constraint}")

        # Solve
        problem = cp.Problem(objective, constraints)

        try:
            problem.solve(solver=cp.OSQP, warm_start=True, eps_abs=1e-6, eps_rel=1e-6)
            print(f"DEBUG: Problem status: {problem.status}")
            print(f"DEBUG: Problem value: {problem.value}")

            if problem.status in [cp.OPTIMAL, cp.OPTIMAL_INACCURATE]:
                result = np.array(w.value).flatten()
                print(f"DEBUG: Optimal weights: {result}")
                return result
            else:
                print(f"DEBUG: Optimization failed with status: {problem.status}")
                return None

        except Exception as e:
            print(f"Optimization failed: {e}")
            return None

    def rebalance(self,
                  current_regime: str,
                  use_rolling_metrics: bool = True,
                  lookback_semi_annual: int = 4) -> OptimizationResult:
        """
        Compute optimal portfolio weights for the next period.

        Args:
            current_regime: Current market regime as string
            use_rolling_metrics: Whether to use rolling average metrics
            lookback_semi_annual: Number of semi_annual for rolling average

        Returns:
            OptimizationResult containing new weights and diagnostic information
        """
        # Parse regime
        try:
            regime = MarketRegime(current_regime.lower())
        except ValueError:
            regime = MarketRegime.SIDEWAYS

        # Check if this is the first run (no historical data)
        # Skip optimization and use user's allocation preferences directly
        has_historical_data = any(len(self.monitor.history[seg]) > 0 for seg in self.segments)
        
        if not has_historical_data:
            # First run: No historical performance data exists
            # Use user's allocation preferences (current_weights) as-is
            print(f"DEBUG: First run detected (no historical data), using user allocation preferences")
            user_weights = self.current_weights.copy()
            
            # Normalize to ensure sum = 1.0
            user_weights = user_weights / user_weights.sum()
            
            return OptimizationResult(
                weights={seg: float(user_weights[i]) for i, seg in enumerate(self.segments)},
                expected_return=0.0,  # Unknown until we have data
                expected_risk=0.0,     # Unknown until we have data
                objective_value=0.0,
                drift_from_previous={seg: 0.0 for seg in self.segments},  # No drift on first run
                success=True,
                message=f"Initial allocation using user preferences (no historical data available)",
                regime=regime.value,
                progress_ratio=0.0
            )

        # Get metrics
        if use_rolling_metrics and self.monitor.time_semi_annual >= 2:
            metrics = self.monitor.get_rolling_metrics(lookback_semi_annual=lookback_semi_annual)
        else:
            metrics = self.monitor.get_latest_metrics()

        # Build optimization inputs
        mu = np.array([metrics[seg].return_rate for seg in self.segments])
        sigma = self.get_variance(metrics)
        mdd = np.array([metrics[seg].max_drawdown for seg in self.segments])

        # Compute adaptive penalties
        progress = self.compute_progress_ratio()
        lambda_var, lambda_dd = self.compute_adaptive_penalties(regime, progress)

        # Activate drawdown penalty only in high volatility regime
        activate_dd = (regime == MarketRegime.HIGH_VOLATILITY)

        # Solve optimization
        optimal_weights = self.solve_optimization(
            mu, sigma, mdd, lambda_var, lambda_dd, activate_dd
        )

        if optimal_weights is None:
            # Fallback: keep current weights
            return OptimizationResult(
                weights={seg: float(self.current_weights[i]) for i, seg in enumerate(self.segments)},
                expected_return=float(mu @ self.current_weights),
                expected_risk=float(np.sqrt(self.current_weights @ sigma)),
                objective_value=0.0,
                drift_from_previous={seg: 0.0 for seg in self.segments},
                success=False,
                message="Optimization failed, keeping current weights",
                regime=regime.value,
                progress_ratio=progress
            )

        # Enforce bounds and normalize (safety check)
        optimal_weights = np.clip(optimal_weights, self.min_weights, self.max_weights)
        optimal_weights = optimal_weights / optimal_weights.sum()

        # Calculate diagnostics
        drift = optimal_weights - self.current_weights
        expected_return = float(mu @ optimal_weights)
        expected_risk = float(np.sqrt(optimal_weights @ sigma))
        objective_value = expected_return - lambda_var * (optimal_weights @ sigma)
        if activate_dd:
            objective_value -= lambda_dd * (mdd @ optimal_weights)

        # Update current weights
        self.current_weights = optimal_weights

        return OptimizationResult(
            weights={seg: float(optimal_weights[i]) for i, seg in enumerate(self.segments)},
            expected_return=expected_return,
            expected_risk=expected_risk,
            objective_value=float(objective_value),
            drift_from_previous={seg: float(drift[i]) for i, seg in enumerate(self.segments)},
            success=True,
            message=f"Optimization successful in {regime.value} regime (progress: {progress:.2f})",
            regime=regime.value,
            progress_ratio=progress
        )



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


async def calculate_segment_metrics_from_db(portfolio_id: str, lookback_semi_annual: int = 4) -> Dict[str, SegmentMetrics]:
    """
    Calculate SegmentMetrics from TradingAgentSnapshots and PortfolioSnapshots for a given portfolio.

    This function computes per-segment performance metrics (return_rate, volatility, 
    max_drawdown, sharpe_ratio) by analyzing historical snapshots.

    Args:
        portfolio_id: The portfolio ID to calculate metrics for
        lookback_semi_annual: Number of recent semi_annual to use for calculation

    Returns:
        Dictionary mapping segment names (agent_type) to their metrics
    """
    from prisma import Prisma
    from datetime import datetime, timedelta
    
    client = Prisma()
    await client.connect()
    
    try:
        # Calculate date range for lookback period
        lookback_days = lookback_semi_annual * 180  # ~180 days per semi_annual
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
        
        # Fetch TradingAgentSnapshots grouped by agent_type (segment)
        agent_snapshots = await client.tradingagentsnapshot.find_many(
            where={
                "portfolio_id": portfolio_id,
                "snapshot_at": {"gte": cutoff_date}
            },
            order={"snapshot_at": "asc"}
        )
        
        # # Fetch PortfolioSnapshots for overall portfolio metrics
        # portfolio_snapshots = await client.portfoliosnapshot.find_many(
        #     where={
        #         "portfolio_id": portfolio_id,
        #         "snapshot_at": {"gte": cutoff_date}
        #     },
        #     order={"created_at": "desc"},
        #     take=lookback_semi_annual * 4  # Assuming ~4 snapshots per semi_annual
        # )
        
        # Group agent snapshots by agent_type (segment)
        segment_snapshots: Dict[str, List[Dict[str, Any]]] = {}
        for snap in agent_snapshots:
            segment = snap.agent_type
            if not segment:
                continue
            if segment not in segment_snapshots:
                segment_snapshots[segment] = []
            segment_snapshots[segment].append({
                "current_value": float(snap.current_value),
                "realized_pnl": float(snap.realized_pnl),
                "unrealized_pnl": float(snap.unrealized_pnl),
                "snapshot_at": snap.snapshot_at,
                "metadata": snap.metadata if snap.metadata else {}
            })
        
        # Calculate metrics for each segment
        metrics: Dict[str, SegmentMetrics] = {}
        
        for segment, snapshots in segment_snapshots.items():
            if len(snapshots) < 2:
                # Not enough data, use defaults
                metrics[segment] = SegmentMetrics(
                    return_rate=0.02,
                    volatility=0.05,
                    max_drawdown=0.03,
                    sharpe_ratio=0.4,
                )
                continue
            
            # Calculate returns from consecutive snapshots
            values = [s["current_value"] for s in snapshots]
            returns: List[float] = []
            for i in range(1, len(values)):
                if values[i - 1] > 0:
                    ret = (values[i] - values[i - 1]) / values[i - 1]
                    returns.append(ret)
            
            if not returns:
                metrics[segment] = SegmentMetrics(
                    return_rate=0.02,
                    volatility=0.05,
                    max_drawdown=0.03,
                    sharpe_ratio=0.4,
                )
                continue
            
            # Calculate return rate (annualized average return)
            avg_return = float(np.mean(returns))
            # Assuming snapshots are roughly daily, annualize
            return_rate = avg_return * 252  # Trading days per year
            
            # Calculate volatility (annualized std dev of returns)
            volatility = float(np.std(returns)) * np.sqrt(252) if len(returns) > 1 else 0.05
            
            # Calculate max drawdown
            peak = values[0]
            max_dd = 0.0
            for val in values:
                if val > peak:
                    peak = val
                if peak > 0:
                    drawdown = (peak - val) / peak
                    max_dd = max(max_dd, drawdown)
            
            # Calculate Sharpe ratio (assuming risk-free rate of 5%)
            risk_free_rate = 0.05
            excess_return = return_rate - risk_free_rate
            sharpe_ratio = excess_return / volatility if volatility > 0 else 0.0
            
            metrics[segment] = SegmentMetrics(
                return_rate=float(np.clip(return_rate, -0.5, 1.0)),  # Clip to reasonable range
                volatility=float(np.clip(volatility, 0.01, 1.0)),
                max_drawdown=float(np.clip(max_dd, 0.0, 1.0)),
                sharpe_ratio=float(np.clip(sharpe_ratio, -3.0, 5.0)),
            )
        
        # Ensure all default segments have metrics
        for segment in DEFAULT_SEGMENTS:
            if segment not in metrics:
                metrics[segment] = SegmentMetrics(
                    return_rate=0.02,
                    volatility=0.05,
                    max_drawdown=0.03,
                    sharpe_ratio=0.4,
                )
        
        return metrics
    
    finally:
        await client.disconnect()


async def get_portfolio_value_history(portfolio_id: str, lookback_semi_annual: int = 4) -> List[float]:
    """
    Get portfolio value history from PortfolioSnapshots.

    Args:
        portfolio_id: The portfolio ID to get history for
        lookback_semi_annual: Number of recent semi_annual to include

    Returns:
        List of portfolio values ordered chronologically
    """
    from prisma import Prisma
    from datetime import datetime, timedelta
    
    client = Prisma()
    await client.connect()
    
    try:
        lookback_days = lookback_semi_annual * 180
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
        
        snapshots = await client.portfoliosnapshot.find_many(
            where={
                "portfolio_id": portfolio_id,
                "snapshot_at": {"gte": cutoff_date}
            },
            order={"snapshot_at": "asc"}
        )
        
        return [float(s.current_value) for s in snapshots]
    
    finally:
        await client.disconnect()


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

