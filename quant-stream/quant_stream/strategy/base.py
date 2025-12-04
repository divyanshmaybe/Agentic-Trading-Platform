"""Base class for portfolio strategies."""

from abc import ABC, abstractmethod
from typing import Dict, Any

import pathway as pw


class Strategy(ABC):
    """Abstract base class for portfolio strategies.

    Strategies convert trading signals (predictions/alphas) into target
    portfolio positions. Users can extend this class to implement custom
    trading logic.

    Example:
        >>> class MyStrategy(Strategy):
        ...     def generate_positions(self, signals, current_positions):
        ...         # Custom logic
        ...         return target_positions
    """

    def __init__(self, **kwargs):
        """Initialize strategy.

        Args:
            **kwargs: Strategy-specific parameters
        """
        self.params = kwargs

    @abstractmethod
    def generate_positions(
        self, signals: pw.Table, current_positions: Dict[str, float] = None
    ) -> pw.Table:
        """Generate target portfolio positions from signals.

        Args:
            signals: Pathway table with columns:
                - symbol: Instrument identifier
                - timestamp: Time of signal
                - signal: Trading signal (higher = more bullish)
            current_positions: Optional dict of current holdings {symbol: weight}

        Returns:
            Pathway table with columns:
                - symbol: Instrument identifier
                - timestamp: Time
                - target_weight: Target portfolio weight (0 to 1)

        Example:
            >>> positions = strategy.generate_positions(signals)
        """
        pass

    def get_config(self) -> Dict[str, Any]:
        """Get strategy configuration parameters.

        Returns:
            Dictionary of strategy parameters

        Example:
            >>> config = strategy.get_config()
        """
        return self.params.copy()

    def set_params(self, **params):
        """Update strategy parameters.

        Args:
            **params: Parameters to update

        Example:
            >>> strategy.set_params(topk=30, n_drop=3)
        """
        self.params.update(params)

    def __repr__(self) -> str:
        """String representation of the strategy."""
        param_str = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.__class__.__name__}({param_str})"

