"""Weight-based strategy implementations."""

from typing import Dict

import pathway as pw

from quant_stream.strategy.base import Strategy


class WeightStrategy(Strategy):
    """Allocate capital based on signal weights.

    This strategy converts signals into portfolio weights using
    various allocation methods.

    Example:
        >>> strategy = WeightStrategy(method="proportional")
        >>> positions = strategy.generate_positions(signals)
    """

    def __init__(
        self,
        method: str = "proportional",
        long_only: bool = True,
        normalize: bool = True,
        min_weight: float = 0.0,
        max_weight: float = 1.0,
        **kwargs,
    ):
        """Initialize Weight strategy.

        Args:
            method: Allocation method:
                - "proportional": Weight by signal strength
                - "equal": Equal weight for all non-zero signals
                - "rank": Weight by rank (highest signal = highest weight)
            long_only: If True, only take long positions
            normalize: If True, normalize weights to sum to 1
            min_weight: Minimum position weight
            max_weight: Maximum position weight
            **kwargs: Additional strategy parameters
        """
        super().__init__(**kwargs)

        self.method = method
        self.long_only = long_only
        self.normalize = normalize
        self.min_weight = min_weight
        self.max_weight = max_weight

        self.params.update(
            {
                "method": method,
                "long_only": long_only,
                "normalize": normalize,
                "min_weight": min_weight,
                "max_weight": max_weight,
            }
        )

    def generate_positions(
        self, signals: pw.Table, current_positions: Dict[str, float] = None
    ) -> pw.Table:
        """Generate target positions based on signal weights.

        Args:
            signals: Table with columns [symbol, timestamp, signal]
            current_positions: Optional current holdings (not used)

        Returns:
            Table with columns [symbol, timestamp, target_weight]

        Example:
            >>> positions = strategy.generate_positions(signals)
        """
        if self.method == "proportional":
            # Weight proportional to signal strength - use helper
            positions = self._proportional_weights(signals)

        elif self.method == "equal":
            # Equal weight for all non-zero signals
            if self.long_only:
                positions = signals.select(
                    symbol=pw.this.symbol,
                    timestamp=pw.this.timestamp,
                    signal=pw.this.signal,
                    has_signal=pw.if_else(pw.this.signal > 0, 1, 0),
                )
            else:
                positions = signals.select(
                    symbol=pw.this.symbol,
                    timestamp=pw.this.timestamp,
                    signal=pw.this.signal,
                    has_signal=pw.if_else(pw.this.signal != 0, 1, 0),
                )

            # Count signals per timestamp
            totals = positions.groupby(pw.this.timestamp).reduce(
                pw.this.timestamp,
                total_signals=pw.reducers.sum(pw.this.has_signal),
            )
            
            # Join back to get total for each row
            positions = positions.join(
                totals,
                pw.left.timestamp == pw.right.timestamp
            ).select(
                symbol=pw.left.symbol,
                timestamp=pw.left.timestamp,
                has_signal=pw.left.has_signal,
                total_signals=pw.right.total_signals,
            )

            # Equal weight
            positions = positions.select(
                symbol=pw.this.symbol,
                timestamp=pw.this.timestamp,
                target_weight=pw.if_else(
                    pw.this.has_signal > 0,
                    1.0 / pw.cast(float, pw.this.total_signals),
                    0.0,
                ),
            )

        elif self.method == "rank":
            # Weight by rank (not fully implemented - requires ranking logic)
            # Simplified: use proportional as fallback
            return self._proportional_weights(signals)

        else:
            raise ValueError(f"Unknown allocation method: {self.method}")

        # Apply min/max weight constraints
        positions = positions.select(
            symbol=pw.this.symbol,
            timestamp=pw.this.timestamp,
            target_weight=pw.apply(
                lambda w: max(self.min_weight, min(self.max_weight, w)),
                pw.this.target_weight,
            ),
        )

        return positions

    def _proportional_weights(self, signals: pw.Table) -> pw.Table:
        """Helper for proportional weighting."""
        positions = signals.select(
            symbol=pw.this.symbol,
            timestamp=pw.this.timestamp,
            signal=pw.this.signal,
            positive_signal=pw.if_else(pw.this.signal > 0, pw.this.signal, 0.0)
            if self.long_only
            else pw.this.signal,
        )

        if self.normalize:
            totals = positions.groupby(pw.this.timestamp).reduce(
                pw.this.timestamp,
                total_signal=pw.reducers.sum(
                    pw.cast(float, pw.apply(abs, pw.this.positive_signal))
                ),
            )
            
            # Join back to get total for each row
            positions = positions.join(
                totals,
                pw.left.timestamp == pw.right.timestamp
            ).select(
                symbol=pw.left.symbol,
                timestamp=pw.left.timestamp,
                positive_signal=pw.left.positive_signal,
                total_signal=pw.right.total_signal,
            )

            positions = positions.select(
                symbol=pw.this.symbol,
                timestamp=pw.this.timestamp,
                target_weight=pw.if_else(
                    pw.this.total_signal > 0,
                    pw.this.positive_signal / pw.this.total_signal,
                    0.0,
                ),
            )
        else:
            positions = positions.select(
                symbol=pw.this.symbol,
                timestamp=pw.this.timestamp,
                target_weight=pw.this.positive_signal,
            )

        return positions

