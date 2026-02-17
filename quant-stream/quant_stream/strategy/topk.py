"""Top-k with dropout strategy implementation."""

from typing import Dict, Optional

import pandas as pd
import pathway as pw

from quant_stream.strategy.base import Strategy


class TopkDropoutStrategy(Strategy):
    """Select top-k instruments by signal, with periodic dropout of worst performers.

    This strategy:
    1. Ranks instruments by signal strength
    2. Selects top-k instruments
    3. Drops bottom n_drop instruments each rebalance period
    4. Allocates capital equally among selected instruments

    Similar to Qlib's TopkDropoutStrategy with enhancements.

    Example:
        >>> strategy = TopkDropoutStrategy(topk=50, n_drop=5, hold_periods=1)
        >>> positions = strategy.generate_positions(signals)
    """

    def __init__(
        self,
        topk: int = 50,
        n_drop: int = 5,
        buffer: int = 0,
        hold_periods: int = 1,
        method: str = "equal",
        **kwargs,
    ):
        """Initialize Top-k Dropout strategy.

        Args:
            topk: Number of instruments to hold
            n_drop: Number of worst performers to drop each period (NOT YET IMPLEMENTED)
            buffer: Buffer zone for ranking (NOT YET IMPLEMENTED)
            hold_periods: Minimum holding periods before allowing dropout (NOT YET IMPLEMENTED)
            method: Weight allocation method ('equal', 'signal')
            **kwargs: Additional strategy parameters
            
        Note:
            The dropout mechanism (n_drop, buffer, hold_periods) is not yet implemented.
            Currently, the strategy performs simple top-k selection at each rebalancing period.
            To implement dropout, we would need stateful tracking of position history,
            which requires additional infrastructure.
        """
        super().__init__(**kwargs)

        self.topk = topk
        self.n_drop = n_drop
        self.buffer = buffer
        self.hold_periods = hold_periods
        self.method = method

        self.params.update(
            {
                "topk": topk,
                "n_drop": n_drop,
                "buffer": buffer,
                "hold_periods": hold_periods,
                "method": method,
            }
        )

    def generate_positions(
        self, signals: pw.Table, current_positions: Dict[str, float] = None
    ) -> pw.Table:
        """Generate target positions based on top-k ranking.

        Args:
            signals: Table with columns [symbol, timestamp, signal]
            current_positions: Optional current holdings (not fully implemented)

        Returns:
            Table with columns [symbol, timestamp, target_weight]

        Example:
            >>> positions = strategy.generate_positions(signals)
            
        Note:
            This uses cross-sectional ranking similar to quant_stream.functions.RANK,
            grouping by timestamp and computing ranks within each time period.
        """
        # Calculate cross-sectional rank using Pathway operations
        # Group by timestamp and collect sorted signals (ascending order)
        grouped = signals.groupby(pw.this.timestamp).reduce(
            pw.this.timestamp,
            sorted_signals=pw.reducers.sorted_tuple(pw.this.signal),
            count=pw.reducers.count(),
        )
        
        # Join back to get sorted list for each row
        signals_with_ranking = signals.join(
            grouped,
            pw.left.timestamp == pw.right.timestamp
        ).select(
            symbol=pw.left.symbol,
            timestamp=pw.left.timestamp,
            signal=pw.left.signal,
            sorted_signals=pw.right.sorted_signals,
            count=pw.right.count,
        )
        
        # Calculate rank and filter to top-k
        def compute_rank_and_topk(signal_value, sorted_vals, count):
            """Compute rank (descending) and check if in top-k.
            
            Similar to the RANK function in crosssectional.py, but for descending order.
            """
            if signal_value is None or count == 0:
                return 0.0, False
            
            # Filter out None values
            valid_vals = [x for x in sorted_vals if x is not None]
            if not valid_vals:
                return 0.0, False
            
            try:
                # sorted_vals is in ascending order, we want descending rank
                # So highest signal gets rank 1
                # Reverse the sorted list for descending order
                descending_vals = sorted(valid_vals, reverse=True)
                
                # Find rank (1-indexed, where 1 is highest signal)
                rank_idx = descending_vals.index(signal_value)
                rank = rank_idx + 1
                
                # Check if in top-k
                is_topk = rank <= self.topk
                return float(rank), is_topk
            except (ValueError, TypeError):
                return 0.0, False
        
        signals_with_ranking = signals_with_ranking.select(
            *pw.this,
            rank_info=pw.apply(
                compute_rank_and_topk,
                pw.this.signal,
                pw.this.sorted_signals,
                pw.this.count,
            ),
        )
        
        # Extract rank and is_topk from tuple
        signals_with_ranking = signals_with_ranking.select(
            symbol=pw.this.symbol,
            timestamp=pw.this.timestamp,
            signal=pw.this.signal,
            rank=pw.apply_with_type(lambda x: x[0], float, pw.this.rank_info),
            is_topk=pw.apply_with_type(lambda x: x[1], bool, pw.this.rank_info),
        )
        
        # Filter to top-k
        topk_signals = signals_with_ranking.filter(pw.this.is_topk)
        
        # Calculate weights based on method
        if self.method == "equal":
            # Equal weight: 1 / topk for each position
            # Group by timestamp to count actual positions
            topk_counts = topk_signals.groupby(pw.this.timestamp).reduce(
                pw.this.timestamp,
                n_positions=pw.reducers.count(),
            )
            
            positions = topk_signals.join(
                topk_counts,
                pw.left.timestamp == pw.right.timestamp
            ).select(
                symbol=pw.left.symbol,
                timestamp=pw.left.timestamp,
                target_weight=pw.if_else(
                    pw.right.n_positions > 0,
                    1.0 / pw.cast(float, pw.right.n_positions),
                    0.0
                ),
            )
            
        elif self.method == "signal":
            # Weight proportional to signal strength
            # Only use positive signals
            topk_signals_positive = topk_signals.select(
                *pw.this,
                positive_signal=pw.if_else(pw.this.signal > 0, pw.this.signal, 0.0),
            )
            
            # Sum signals per timestamp
            signal_sums = topk_signals_positive.groupby(pw.this.timestamp).reduce(
                pw.this.timestamp,
                total_signal=pw.reducers.sum(pw.this.positive_signal),
            )
            
            positions = topk_signals_positive.join(
                signal_sums,
                pw.left.timestamp == pw.right.timestamp
            ).select(
                symbol=pw.left.symbol,
                timestamp=pw.left.timestamp,
                target_weight=pw.if_else(
                    pw.right.total_signal > 0,
                    pw.left.positive_signal / pw.right.total_signal,
                    0.0
                ),
            )
        else:
            raise ValueError(f"Unknown allocation method: {self.method}")
        
        return positions

