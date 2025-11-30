"""Service for generating alpha signals using quant-stream."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

# Add quant-stream to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"
if str(QUANT_STREAM_PATH) not in sys.path:
    sys.path.insert(0, str(QUANT_STREAM_PATH))


class AlphaSignalService:
    """Service for generating trading signals from live alphas."""
    
    def __init__(self, prisma_client, logger: Optional[logging.Logger] = None):
        self.client = prisma_client
        self.logger = logger or logging.getLogger(__name__)
        self._evaluator = None
    
    def _get_evaluator(self):
        """Lazy load the AlphaEvaluator from quant-stream."""
        if self._evaluator is None:
            try:
                from quant_stream.alpha.evaluator import AlphaEvaluator
                self._evaluator = AlphaEvaluator()
            except ImportError as e:
                self.logger.error("Failed to import AlphaEvaluator: %s", e)
                raise
        return self._evaluator
    
    async def generate_signals_for_alpha(self, alpha) -> List[Dict[str, Any]]:
        """
        Generate trading signals for a live alpha.
        
        Args:
            alpha: LiveAlpha Prisma model
            
        Returns:
            List of signal dictionaries
        """
        workflow_config = alpha.workflow_config
        if isinstance(workflow_config, str):
            import json
            workflow_config = json.loads(workflow_config)
        
        if not workflow_config:
            self.logger.warning("Alpha %s has no workflow config", alpha.id)
            return []
        
        # Extract configuration
        features = workflow_config.get("features", [])
        model_config = workflow_config.get("model", {})
        strategy_config = workflow_config.get("strategy", {})
        symbols = alpha.symbols or []
        
        if not symbols:
            # Try to get symbols from workflow config
            data_config = workflow_config.get("data", {})
            symbols = data_config.get("symbols", [])
        
        if not symbols:
            self.logger.warning("Alpha %s has no symbols configured", alpha.id)
            return []
        
        self.logger.info(
            "Generating signals for alpha %s with %d features and %d symbols",
            alpha.name, len(features), len(symbols)
        )
        
        try:
            # Fetch latest market data for symbols
            market_data = await self._fetch_market_data(symbols)
            
            if not market_data:
                self.logger.warning("No market data available for alpha %s", alpha.id)
                return []
            
            # Evaluate factors
            factor_values = self._evaluate_factors(features, market_data)
            
            # Generate signals based on strategy
            signals = self._generate_strategy_signals(
                alpha_id=alpha.id,
                factor_values=factor_values,
                model_config=model_config,
                strategy_config=strategy_config,
                allocated_amount=float(alpha.allocated_amount),
                symbols=symbols,
            )
            
            # Dispatch signals to trade execution
            if signals:
                await self._dispatch_signals(alpha, signals)
            
            return signals
            
        except Exception as exc:
            self.logger.error(
                "Error generating signals for alpha %s: %s",
                alpha.id, exc, exc_info=True
            )
            raise
    
    async def _fetch_market_data(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch latest market data for symbols.
        
        Returns dict mapping symbol -> OHLCV data
        """
        # Try to get from AngelOne service
        try:
            from services.angelone_service import AngelOneService
            service = AngelOneService()
            
            market_data = {}
            for symbol in symbols:
                try:
                    quote = await service.get_quote_async(symbol)
                    if quote:
                        market_data[symbol] = {
                            "symbol": symbol,
                            "open": quote.get("open"),
                            "high": quote.get("high"),
                            "low": quote.get("low"),
                            "close": quote.get("ltp"),
                            "volume": quote.get("volume"),
                            "timestamp": datetime.utcnow(),
                        }
                except Exception as e:
                    self.logger.warning("Failed to fetch quote for %s: %s", symbol, e)
            
            return market_data
            
        except ImportError:
            self.logger.warning("AngelOneService not available, using mock data")
            # Return empty - no real data available
            return {}
    
    def _evaluate_factors(
        self,
        features: List[Dict[str, Any]],
        market_data: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, float]]:
        """
        Evaluate factor expressions on market data.
        
        Args:
            features: List of feature configs with name and expression
            market_data: Dict of symbol -> OHLCV data
            
        Returns:
            Dict mapping symbol -> factor_name -> value
        """
        try:
            evaluator = self._get_evaluator()
            
            factor_values = {}
            
            for symbol, data in market_data.items():
                symbol_factors = {}
                
                for feature in features:
                    name = feature.get("name", "")
                    expression = feature.get("expression", "")
                    
                    if not expression:
                        continue
                    
                    try:
                        # Evaluate factor expression
                        value = evaluator.evaluate(expression, data)
                        symbol_factors[name] = value
                    except Exception as e:
                        self.logger.debug(
                            "Failed to evaluate factor %s for %s: %s",
                            name, symbol, e
                        )
                        symbol_factors[name] = None
                
                factor_values[symbol] = symbol_factors
            
            return factor_values
            
        except Exception as e:
            self.logger.error("Factor evaluation failed: %s", e)
            return {}
    
    def _generate_strategy_signals(
        self,
        alpha_id: str,
        factor_values: Dict[str, Dict[str, float]],
        model_config: Dict[str, Any],
        strategy_config: Dict[str, Any],
        allocated_amount: float,
        symbols: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Generate trading signals based on strategy configuration.
        
        For TopkDropout strategy:
        - Rank symbols by predicted score
        - Buy top K symbols
        - Sell symbols that drop out of top K
        """
        strategy_type = strategy_config.get("type", "TopkDropout")
        params = strategy_config.get("params", {})
        
        topk = params.get("topk", 10)
        n_drop = params.get("n_drop", 2)
        method = params.get("method", "equal")
        
        # Calculate scores for each symbol
        symbol_scores = []
        
        for symbol in symbols:
            factors = factor_values.get(symbol, {})
            if not factors:
                continue
            
            # Simple scoring: average of factor values
            # In production, this would use the trained ML model
            valid_values = [v for v in factors.values() if v is not None]
            if valid_values:
                score = sum(valid_values) / len(valid_values)
                symbol_scores.append((symbol, score))
        
        if not symbol_scores:
            self.logger.info("No valid factor values, no signals generated")
            return []
        
        # Sort by score (descending)
        symbol_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Get top K symbols for buying
        top_symbols = symbol_scores[:topk]
        
        # Calculate allocation per symbol
        if method == "equal":
            amount_per_symbol = allocated_amount / topk if topk > 0 else 0
        else:
            # Score-weighted allocation
            total_score = sum(max(0, s[1]) for s in top_symbols)
            amount_per_symbol = allocated_amount  # Will be weighted per symbol
        
        signals = []
        
        for symbol, score in top_symbols:
            if method == "equal":
                alloc = amount_per_symbol
            else:
                alloc = (max(0, score) / total_score) * allocated_amount if total_score > 0 else 0
            
            signals.append({
                "alpha_id": alpha_id,
                "symbol": symbol,
                "signal_type": "buy",
                "confidence": min(abs(score), 1.0) if score else 0.5,
                "allocated_amount": alloc,
                "score": score,
                "generated_at": datetime.utcnow().isoformat(),
            })
        
        self.logger.info(
            "Generated %d buy signals for alpha %s",
            len(signals), alpha_id
        )
        
        return signals
    
    async def _dispatch_signals(
        self,
        alpha,
        signals: List[Dict[str, Any]],
    ) -> None:
        """
        Dispatch signals to trade execution pipeline.
        
        Creates trades via the portfolio's agent system.
        """
        from workers.alpha_signal_tasks import process_alpha_signal_batch
        
        if not signals:
            return
        
        # Queue for async processing
        process_alpha_signal_batch.delay(signals)
        
        self.logger.info(
            "Dispatched %d signals for alpha %s to trade execution",
            len(signals), alpha.id
        )



