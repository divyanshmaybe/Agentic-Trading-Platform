"""Beta/Market Neutral strategy implementation."""

from typing import Dict

import pathway as pw

from quant_stream.strategy.base import Strategy


class BetaNeutralStrategy(Strategy):
    """Market-neutral strategy with long and short positions.

    This strategy constructs a dollar-neutral or beta-neutral portfolio by:
    1. Going long on top-ranked instruments by signal
    2. Going short on bottom-ranked instruments by signal
    3. Balancing exposures to minimize market risk

    For Indian markets, shorts are intraday only (must square off before close).

    Example:
        >>> strategy = BetaNeutralStrategy(
        ...     n_long=20,
        ...     n_short=20,
        ...     neutrality="dollar",
        ... )
        >>> positions = strategy.generate_positions(signals)
    """

    def __init__(
        self,
        n_long: int = 20,
        n_short: int = 20,
        long_weight: float = 0.5,
        short_weight: float = 0.5,
        neutrality: str = "dollar",
        method: str = "equal",
        min_signal_threshold: float = 0.0,
        **kwargs,
    ):
        """Initialize Beta Neutral strategy.

        Args:
            n_long: Number of instruments to hold long (top signals)
            n_short: Number of instruments to hold short (bottom signals)
            long_weight: Total portfolio weight for long positions (default: 0.5 = 50%)
            short_weight: Total portfolio weight for short positions (default: 0.5 = 50%)
            neutrality: Type of market neutrality:
                - "dollar": Long $ exposure = Short $ exposure (dollar-neutral)
                - "count": Equal number of longs and shorts
                - "beta": Adjust for beta (requires beta column in signals) - NOT YET IMPLEMENTED
            method: Weight allocation within long/short buckets:
                - "equal": Equal weight for all positions
                - "signal": Weight proportional to signal strength
                - "rank": Weight by rank (strongest signal = highest weight)
            min_signal_threshold: Minimum absolute signal value to consider
            **kwargs: Additional strategy parameters

        Note:
            For Indian markets, use with Backtester(allow_short=True, intraday_short_only=True).
            All short positions will be squared off at end of each trading day.
        """
        super().__init__(**kwargs)

        self.n_long = n_long
        self.n_short = n_short
        self.long_weight = long_weight
        self.short_weight = short_weight
        self.neutrality = neutrality
        self.method = method
        self.min_signal_threshold = min_signal_threshold

        self.params.update(
            {
                "n_long": n_long,
                "n_short": n_short,
                "long_weight": long_weight,
                "short_weight": short_weight,
                "neutrality": neutrality,
                "method": method,
                "min_signal_threshold": min_signal_threshold,
            }
        )

    def generate_positions(
        self, signals: pw.Table, current_positions: Dict[str, float] | None = None
    ) -> pw.Table:
        """Generate target positions for long-short portfolio.

        Args:
            signals: Table with columns [symbol, timestamp, signal]
            current_positions: Optional current holdings (not used)

        Returns:
            Table with columns [symbol, timestamp, target_weight]
            Positive weights = long positions
            Negative weights = short positions

        Example:
            >>> positions = strategy.generate_positions(signals)
        """
        # Group by timestamp and collect sorted signals for ranking
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

        # Calculate ranks and determine long/short classification
        def compute_rank_and_bucket(signal_value, sorted_vals, count, n_long, n_short, min_threshold):
            """Compute rank and determine if in long/short bucket.

            Returns tuple: (rank, is_long, is_short)
            - rank: 1 = highest signal, count = lowest signal
            - is_long: True if in top n_long
            - is_short: True if in bottom n_short
            """
            if signal_value is None or count == 0:
                return (0.0, False, False)

            # Filter out None values
            valid_vals = [x for x in sorted_vals if x is not None]
            if not valid_vals:
                return (0.0, False, False)

            # Apply minimum signal threshold
            if abs(signal_value) < min_threshold:
                return (0.0, False, False)

            try:
                # sorted_vals is in ascending order from Pathway
                # Reverse for descending (highest signal first)
                descending_vals = sorted(valid_vals, reverse=True)
                n = len(descending_vals)

                # Find rank (1-indexed, where 1 is highest signal)
                rank_idx = descending_vals.index(signal_value)
                rank = rank_idx + 1

                # Determine bucket
                is_long = rank <= n_long
                # For shorts, take bottom n_short (highest ranks)
                is_short = rank > (n - n_short)

                return (float(rank), is_long, is_short)
            except (ValueError, TypeError):
                return (0.0, False, False)

        signals_with_ranking = signals_with_ranking.select(
            *pw.this,
            bucket_info=pw.apply(
                compute_rank_and_bucket,
                pw.this.signal,
                pw.this.sorted_signals,
                pw.this.count,
                self.n_long,
                self.n_short,
                self.min_signal_threshold,
            ),
        )

        # Extract rank and bucket flags
        signals_with_ranking = signals_with_ranking.select(
            symbol=pw.this.symbol,
            timestamp=pw.this.timestamp,
            signal=pw.this.signal,
            rank=pw.apply_with_type(lambda x: x[0], float, pw.this.bucket_info),
            is_long=pw.apply_with_type(lambda x: x[1], bool, pw.this.bucket_info),
            is_short=pw.apply_with_type(lambda x: x[2], bool, pw.this.bucket_info),
        )

        # Filter to only long and short positions
        active_positions = signals_with_ranking.filter(
            pw.this.is_long | pw.this.is_short
        )

        # Count actual longs and shorts per timestamp for weight calculation
        counts_per_timestamp = active_positions.groupby(pw.this.timestamp).reduce(
            pw.this.timestamp,
            n_longs=pw.reducers.sum(pw.cast(int, pw.this.is_long)),
            n_shorts=pw.reducers.sum(pw.cast(int, pw.this.is_short)),
        )

        # Join counts back
        active_with_counts = active_positions.join(
            counts_per_timestamp,
            pw.left.timestamp == pw.right.timestamp
        ).select(
            symbol=pw.left.symbol,
            timestamp=pw.left.timestamp,
            signal=pw.left.signal,
            rank=pw.left.rank,
            is_long=pw.left.is_long,
            is_short=pw.left.is_short,
            n_longs=pw.right.n_longs,
            n_shorts=pw.right.n_shorts,
        )

        # Calculate weights based on method
        if self.method == "equal":
            # Equal weight within each bucket
            positions = active_with_counts.select(
                symbol=pw.this.symbol,
                timestamp=pw.this.timestamp,
                target_weight=pw.if_else(
                    pw.this.is_long,
                    # Long: positive weight
                    pw.if_else(
                        pw.this.n_longs > 0,
                        self.long_weight / pw.cast(float, pw.this.n_longs),
                        0.0
                    ),
                    # Short: negative weight
                    pw.if_else(
                        pw.this.n_shorts > 0,
                        -self.short_weight / pw.cast(float, pw.this.n_shorts),
                        0.0
                    ),
                ),
            )

        elif self.method == "signal":
            # Weight proportional to signal strength
            # For longs: higher signal = higher weight
            # For shorts: lower (more negative) signal = higher short weight

            # Calculate signal sums per timestamp for normalization
            signal_sums = active_with_counts.groupby(pw.this.timestamp).reduce(
                pw.this.timestamp,
                long_signal_sum=pw.reducers.sum(
                    pw.if_else(pw.this.is_long, pw.apply(abs, pw.this.signal), 0.0)
                ),
                short_signal_sum=pw.reducers.sum(
                    pw.if_else(pw.this.is_short, pw.apply(abs, pw.this.signal), 0.0)
                ),
            )

            active_with_sums = active_with_counts.join(
                signal_sums,
                pw.left.timestamp == pw.right.timestamp
            ).select(
                symbol=pw.left.symbol,
                timestamp=pw.left.timestamp,
                signal=pw.left.signal,
                is_long=pw.left.is_long,
                is_short=pw.left.is_short,
                long_signal_sum=pw.right.long_signal_sum,
                short_signal_sum=pw.right.short_signal_sum,
            )

            positions = active_with_sums.select(
                symbol=pw.this.symbol,
                timestamp=pw.this.timestamp,
                target_weight=pw.if_else(
                    pw.this.is_long,
                    # Long weight proportional to signal
                    pw.if_else(
                        pw.this.long_signal_sum > 0,
                        self.long_weight * pw.apply(abs, pw.this.signal) / pw.this.long_signal_sum,
                        0.0
                    ),
                    # Short weight proportional to abs(signal)
                    pw.if_else(
                        pw.this.short_signal_sum > 0,
                        -self.short_weight * pw.apply(abs, pw.this.signal) / pw.this.short_signal_sum,
                        0.0
                    ),
                ),
            )

        elif self.method == "rank":
            # Weight by rank (inverse rank weighting)
            # Higher rank position = higher weight

            # Calculate rank sums for normalization
            rank_sums = active_with_counts.groupby(pw.this.timestamp).reduce(
                pw.this.timestamp,
                # For longs: sum of inverse ranks (rank 1 gets highest weight)
                long_rank_sum=pw.reducers.sum(
                    pw.if_else(
                        pw.this.is_long,
                        pw.cast(float, pw.this.n_longs) + 1.0 - pw.this.rank,
                        0.0
                    )
                ),
                # For shorts: similar inverse weighting from bottom
                short_rank_sum=pw.reducers.sum(
                    pw.if_else(pw.this.is_short, pw.this.rank, 0.0)
                ),
            )

            active_with_ranks = active_with_counts.join(
                rank_sums,
                pw.left.timestamp == pw.right.timestamp
            ).select(
                symbol=pw.left.symbol,
                timestamp=pw.left.timestamp,
                rank=pw.left.rank,
                is_long=pw.left.is_long,
                is_short=pw.left.is_short,
                n_longs=pw.left.n_longs,
                long_rank_sum=pw.right.long_rank_sum,
                short_rank_sum=pw.right.short_rank_sum,
            )

            positions = active_with_ranks.select(
                symbol=pw.this.symbol,
                timestamp=pw.this.timestamp,
                target_weight=pw.if_else(
                    pw.this.is_long,
                    pw.if_else(
                        pw.this.long_rank_sum > 0,
                        self.long_weight * (pw.cast(float, pw.this.n_longs) + 1.0 - pw.this.rank) / pw.this.long_rank_sum,
                        0.0
                    ),
                    pw.if_else(
                        pw.this.short_rank_sum > 0,
                        -self.short_weight * pw.this.rank / pw.this.short_rank_sum,
                        0.0
                    ),
                ),
            )

        else:
            raise ValueError(f"Unknown allocation method: {self.method}")

        return positions


class DollarNeutralStrategy(BetaNeutralStrategy):
    """Convenience class for dollar-neutral long-short strategy.

    Ensures equal dollar exposure on long and short sides.

    Example:
        >>> strategy = DollarNeutralStrategy(n_long=20, n_short=20)
        >>> # Long exposure = 50%, Short exposure = -50%
        >>> # Net exposure = 0 (dollar neutral)
    """

    def __init__(
        self,
        n_long: int = 20,
        n_short: int = 20,
        gross_exposure: float = 1.0,
        method: str = "equal",
        **kwargs,
    ):
        """Initialize Dollar Neutral strategy.

        Args:
            n_long: Number of instruments to hold long
            n_short: Number of instruments to hold short
            gross_exposure: Total gross exposure (long + abs(short)) as fraction
            method: Weight allocation method
            **kwargs: Additional strategy parameters
        """
        # Split gross exposure equally between long and short
        half_exposure = gross_exposure / 2.0

        super().__init__(
            n_long=n_long,
            n_short=n_short,
            long_weight=half_exposure,
            short_weight=half_exposure,
            neutrality="dollar",
            method=method,
            **kwargs,
        )


class IntradayMomentumStrategy(BetaNeutralStrategy):
    """Intraday momentum strategy suitable for Indian market constraints.

    Long strong momentum stocks, short weak momentum stocks,
    with automatic square-off at end of day.

    Example:
        >>> strategy = IntradayMomentumStrategy(n_long=10, n_short=10)
    """

    def __init__(
        self,
        n_long: int = 10,
        n_short: int = 10,
        long_weight: float = 0.4,
        short_weight: float = 0.4,
        method: str = "equal",
        **kwargs,
    ):
        """Initialize Intraday Momentum strategy.

        Args:
            n_long: Number of top momentum stocks to go long
            n_short: Number of bottom momentum stocks to go short
            long_weight: Total weight for long positions
            short_weight: Total weight for short positions
            method: Weight allocation method
            **kwargs: Additional strategy parameters
        """
        super().__init__(
            n_long=n_long,
            n_short=n_short,
            long_weight=long_weight,
            short_weight=short_weight,
            neutrality="dollar",
            method=method,
            **kwargs,
        )

        self.params.update({"strategy_type": "intraday_momentum"})
