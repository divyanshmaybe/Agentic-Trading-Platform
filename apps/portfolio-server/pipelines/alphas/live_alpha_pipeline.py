"""
Live Alpha Pipeline - Generates trading signals from deployed alpha strategies.

This pipeline:
1. Loads active LiveAlpha configurations from database
2. Fetches latest market data for configured symbols
3. Evaluates factor expressions using quant-stream's AlphaEvaluator
4. Runs ML model inference (if configured)
5. Generates buy/sell signals based on strategy (TopK dropout, etc.)
6. Publishes signals to Kafka for trade execution
"""

from __future__ import annotations

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from decimal import Decimal

# Add quant-stream to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"
if str(QUANT_STREAM_PATH) not in sys.path:
    sys.path.insert(0, str(QUANT_STREAM_PATH))


class LiveAlphaPipeline:
    """
    Pipeline for generating live alpha trading signals.
    
    Uses quant-stream for factor evaluation and signal generation.
    """
    
    def __init__(self, prisma_client, logger: Optional[logging.Logger] = None):
        self.client = prisma_client
        self.logger = logger or logging.getLogger(__name__)
        self._evaluator = None
        self._market_data_service = None
    
    async def run(self) -> Dict[str, Any]:
        """
        Run the live alpha pipeline for all active alphas.
        
        Returns:
            Summary of pipeline execution
        """
        self.logger.info("Starting live alpha pipeline...")
        
        # Get all running live alphas
        live_alphas = await self.client.livealpha.find_many(
            where={"status": "running"}
        )
        
        if not live_alphas:
            self.logger.info("No active live alphas found")
            return {"status": "success", "alphas_processed": 0, "signals_generated": 0}
        
        self.logger.info("Found %d active live alphas", len(live_alphas))
        
        total_signals = 0
        processed = 0
        errors = []
        
        for alpha in live_alphas:
            try:
                signals = await self._process_alpha(alpha)
                total_signals += len(signals)
                processed += 1
            except Exception as exc:
                self.logger.error(
                    "Failed to process alpha %s: %s",
                    alpha.id, exc, exc_info=True
                )
                errors.append({"alpha_id": alpha.id, "error": str(exc)})
        
        return {
            "status": "success",
            "alphas_processed": processed,
            "signals_generated": total_signals,
            "errors": errors if errors else None,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    async def run_for_alpha(self, alpha_id: str) -> Dict[str, Any]:
        """
        Run the pipeline for a specific alpha.
        
        Args:
            alpha_id: ID of the live alpha
            
        Returns:
            Summary of signal generation
        """
        alpha = await self.client.livealpha.find_unique(where={"id": alpha_id})
        if not alpha:
            return {"status": "error", "error": "Alpha not found"}
        
        if alpha.status != "running":
            return {"status": "skipped", "reason": f"Alpha status is {alpha.status}"}
        
        try:
            signals = await self._process_alpha(alpha)
            return {
                "status": "success",
                "alpha_id": alpha_id,
                "signals_generated": len(signals),
                "signals": signals,
            }
        except Exception as exc:
            self.logger.error("Failed to process alpha %s: %s", alpha_id, exc)
            return {"status": "error", "error": str(exc)}
    
    async def _process_alpha(self, alpha) -> List[Dict[str, Any]]:
        """
        Process a single live alpha and generate signals.
        
        Args:
            alpha: LiveAlpha Prisma model
            
        Returns:
            List of generated signals
        """
        self.logger.info("Processing alpha: %s (%s)", alpha.name, alpha.id)
        
        workflow_config = alpha.workflow_config
        if isinstance(workflow_config, str):
            workflow_config = json.loads(workflow_config)
        
        if not workflow_config:
            self.logger.warning("Alpha %s has no workflow config", alpha.id)
            return []
        
        # Extract configuration
        features = workflow_config.get("features", [])
        model_config = workflow_config.get("model", {})
        strategy_config = workflow_config.get("strategy", {})
        symbols = alpha.symbols or []
        
        # Get symbols from config if not set
        if not symbols:
            data_config = workflow_config.get("data", {})
            symbols = data_config.get("symbols", [])
        
        if not symbols:
            self.logger.warning("Alpha %s has no symbols", alpha.id)
            return []
        
        # Fetch market data
        market_data = await self._fetch_market_data(symbols)
        
        if not market_data:
            self.logger.warning("No market data for alpha %s", alpha.id)
            return []
        
        # Evaluate factors
        factor_values = self._evaluate_factors(features, market_data)
        
        # Generate signals using strategy
        signals = self._generate_signals(
            alpha=alpha,
            factor_values=factor_values,
            model_config=model_config,
            strategy_config=strategy_config,
        )
        
        # Update alpha tracking
        if signals:
            await self.client.livealpha.update(
                where={"id": alpha.id},
                data={
                    "last_signal_at": datetime.utcnow(),
                    "total_signals": alpha.total_signals + len(signals),
                }
            )
            
            # Publish to Kafka for trade execution
            await self._publish_signals(alpha, signals)
        
        self.logger.info(
            "Alpha %s generated %d signals",
            alpha.name, len(signals)
        )
        
        return signals
    
    async def _fetch_market_data(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Fetch latest OHLCV data for symbols."""
        # Try AngelOne first
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
                            "open": float(quote.get("open", 0)),
                            "high": float(quote.get("high", 0)),
                            "low": float(quote.get("low", 0)),
                            "close": float(quote.get("ltp", 0)),
                            "volume": int(quote.get("volume", 0)),
                            "timestamp": datetime.utcnow(),
                        }
                except Exception as e:
                    self.logger.debug("Quote fetch failed for %s: %s", symbol, e)
            
            return market_data
            
        except ImportError:
            self.logger.warning("AngelOneService not available")
            return {}
    
    def _evaluate_factors(
        self,
        features: List[Dict[str, Any]],
        market_data: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, float]]:
        """Evaluate factor expressions on market data."""
        try:
            from quant_stream.alpha.evaluator import AlphaEvaluator
            evaluator = AlphaEvaluator()
            
            results = {}
            
            for symbol, data in market_data.items():
                symbol_factors = {}
                
                for feature in features:
                    name = feature.get("name", "")
                    expression = feature.get("expression", "")
                    
                    if not expression:
                        continue
                    
                    try:
                        value = evaluator.evaluate(expression, data)
                        symbol_factors[name] = float(value) if value is not None else None
                    except Exception:
                        symbol_factors[name] = None
                
                results[symbol] = symbol_factors
            
            return results
            
        except ImportError:
            self.logger.error("quant_stream not available for factor evaluation")
            return {}
    
    def _generate_signals(
        self,
        alpha,
        factor_values: Dict[str, Dict[str, float]],
        model_config: Dict[str, Any],
        strategy_config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Generate trading signals based on strategy."""
        strategy_type = strategy_config.get("type", "TopkDropout")
        params = strategy_config.get("params", {})
        
        topk = params.get("topk", 10)
        n_drop = params.get("n_drop", 2)
        method = params.get("method", "equal")
        
        # Calculate scores
        symbol_scores = []
        for symbol, factors in factor_values.items():
            valid_values = [v for v in factors.values() if v is not None]
            if valid_values:
                score = sum(valid_values) / len(valid_values)
                symbol_scores.append((symbol, score))
        
        if not symbol_scores:
            return []
        
        # Sort by score descending
        symbol_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Select top K
        top_symbols = symbol_scores[:topk]
        
        # Calculate allocations
        allocated_amount = float(alpha.allocated_amount)
        
        if method == "equal":
            amount_per_symbol = allocated_amount / len(top_symbols) if top_symbols else 0
        else:
            total_score = sum(max(0, s[1]) for s in top_symbols)
            amount_per_symbol = None  # Will calculate per symbol
        
        signals = []
        for symbol, score in top_symbols:
            if method == "equal":
                alloc = amount_per_symbol
            else:
                total_score = sum(max(0, s[1]) for s in top_symbols)
                alloc = (max(0, score) / total_score) * allocated_amount if total_score > 0 else 0
            
            signals.append({
                "alpha_id": alpha.id,
                "alpha_name": alpha.name,
                "portfolio_id": alpha.portfolio_id,
                "symbol": symbol,
                "signal_type": "buy",
                "confidence": min(abs(score), 1.0) if score else 0.5,
                "allocated_amount": alloc,
                "score": score,
                "strategy_type": strategy_type,
                "generated_at": datetime.utcnow().isoformat(),
            })
        
        return signals
    
    async def _publish_signals(
        self,
        alpha,
        signals: List[Dict[str, Any]],
    ) -> None:
        """Publish signals to Kafka for trade execution."""
        try:
            from kafka import KafkaProducer
            
            kafka_bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
            topic = "alpha_signals"
            
            producer = KafkaProducer(
                bootstrap_servers=kafka_bootstrap,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            
            for signal in signals:
                producer.send(topic, value=signal)
            
            producer.flush()
            producer.close()
            
            self.logger.info(
                "Published %d signals to Kafka topic %s",
                len(signals), topic
            )
            
        except Exception as exc:
            self.logger.warning(
                "Failed to publish to Kafka, falling back to direct execution: %s",
                exc
            )
            # Fall back to direct task dispatch using send_task
            from celery_app import celery_app
            celery_app.send_task(
                "alpha.process_signal_batch",
                args=[signals],
                queue="trading",
                routing_key="trading"
            )



