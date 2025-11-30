"""
Regime Classification Service
Singleton service managing HMM model training, Pathway pipeline, and regime predictions
"""

import os
os.environ["PATHWAY_DISABLE_PROGRESS"] = "1"
os.environ.setdefault("PATHWAY_PROGRESS_DISABLE", "1")
os.environ.setdefault("PW_DISABLE_PROGRESS", "1")
os.environ["PATHWAY_LOG_LEVEL"] = "warning"

import sys
import json
import logging
import threading
import time
from collections import deque
from typing import Dict, List, Optional

import pathway as pw

# Ensure service package imports resolve
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from services.regime_model import (
    MarketRegimeClassifier,
    fetch_nse_data,
    update_sensitivity,
)

logger = logging.getLogger(__name__)


class RegimeService:
    """
    Singleton service for real-time market regime classification.
    
    Manages:
    - HMM model training and lifecycle
    - Pathway streaming pipeline with AsyncTransformers
    - In-memory cache of regime predictions
    - API methods for regime queries
    """
    
    _instance: Optional["RegimeService"] = None
    _instance_lock = threading.Lock()
    
    def __init__(self):
        """Initialize regime service with model training and Pathway pipeline"""
        self.logger = logging.getLogger(__name__)
        
        # Configure symbols for training and streaming
        self.training_symbol = os.getenv("REGIME_TRAINING_SYMBOL", "^NSEI")
        provider_default = os.getenv("REGIME_PROVIDER_SYMBOL") or self._resolve_default_provider_symbol(
            self.training_symbol
        )
        self.provider_symbol = provider_default

        self.streaming_symbol = os.getenv("REGIME_STREAM_SYMBOL", self.training_symbol)
        self.streaming_provider_symbol = (
            os.getenv("REGIME_STREAM_PROVIDER_SYMBOL")
            or self._resolve_default_provider_symbol(self.streaming_symbol, fallback=provider_default)
        )
        self.streaming_interval = os.getenv("REGIME_STREAM_INTERVAL", "ONE_MINUTE")

        # In-memory cache
        self._current_regime: Optional[Dict] = None
        self._regime_history = deque(maxlen=1000)
        self._cache_lock = threading.Lock()

        # Train HMM model on historical data
        self.logger.info("🚀 Training HMM model using symbol %s (provider: %s)...", self.training_symbol, self.provider_symbol)
        self.classifier = self._train_model()
        self.logger.info(f"✅ Model trained with {self.classifier.n_regimes} regimes")
        
        # IMPORTANT: Pathway runtime disabled to avoid event loop conflicts with NSE pipeline
        # The trained model is available for on-demand predictions via API
        # Future: Move regime streaming to separate Celery worker if real-time updates needed
        self._started = threading.Event()
        self._runner_thread: Optional[threading.Thread] = None
        
        self.logger.info("⚠️  Pathway streaming disabled (event loop conflict prevention)")
        self.logger.info("✅ RegimeService initialized (model-only mode)")
    
    @classmethod
    def get_instance(cls) -> "RegimeService":
        """Get or create singleton instance"""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def _train_model(self) -> MarketRegimeClassifier:
        """
        Train HMM model on historical data.
        
        IMPORTANT: Uses yfinance for training to avoid Angel One rate limits.
        This is the ONLY place in the codebase where yfinance should be used.
        
        NOTE: NumPy/OpenBLAS threading should be disabled via environment variables
        to prevent SIGSEGV in multiprocessing contexts (Celery workers).
        
        Returns:
            Trained MarketRegimeClassifier instance
        """
        # Ensure single-threaded mode for BLAS operations to prevent SIGSEGV
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        
        try:
            # Fetch 2+ years of historical data using yfinance (avoids Angel One rate limits)
            self.logger.info("📊 Fetching historical data for training using yfinance...")
            from datetime import datetime
            
            data = fetch_nse_data(
                ticker=self.training_symbol,
                start_date=datetime(2020, 1, 1),
                end_date=datetime.now(),
                provider_symbol=self.provider_symbol,
                use_yfinance=True,  # CRITICAL: Use yfinance to avoid Angel One rate limits
            )
            
            if data is None or data.empty:
                self.logger.error("Failed to fetch historical data from yfinance, using fallback")
                # Fallback: try shorter period
                data = fetch_nse_data(
                    ticker=self.training_symbol,
                    start_date=datetime(2023, 1, 1),
                    end_date=datetime.now(),
                    provider_symbol=self.provider_symbol,
                    use_yfinance=True,
                )
            
            if data is None or data.empty:
                raise RuntimeError(
                    "yfinance returned no historical data for regime training. "
                    "Verify ticker mapping or network connectivity."
                )
            
            self.logger.info(f"📈 Training on {len(data)} days of historical data (fetched via yfinance)")
            
            # Train classifier with 4 regimes
            classifier = MarketRegimeClassifier(n_regimes=4, random_state=42)
            classifier.fit(data)
            if classifier.features is None or classifier.features.empty:
                features = classifier.prepare_features(data)
            else:
                features = classifier.features
            features_scaled = classifier.scaler.transform(features)
            hidden_states = classifier.model.predict(features_scaled)
            latest_state = int(hidden_states[-1])
            latest_regime = classifier.regime_names.get(latest_state, f"Regime {latest_state}")
            latest_ts = data.index[-1]
            latest_close = data["Close"].iloc[-1]
            latest_features = features.iloc[-1].to_dict()
            latest_features = {key: float(value) for key, value in latest_features.items()}
            regime_record = {
                "timestamp": latest_ts.timestamp() if hasattr(latest_ts, "timestamp") else time.time(),
                "regime": latest_regime,
                "state_id": latest_state,
                "close": float(latest_close),
                "symbol": self.training_symbol,
                "features": latest_features,
            }
            self._current_regime = regime_record
            self._regime_history.append(regime_record)
            
            self.logger.info("✅ Model training completed")
            self.logger.info(f"   Regimes identified: {list(classifier.regime_names.values())}")
            
            return classifier
            
        except Exception as exc:
            self.logger.error(f"❌ Model training failed: {exc}", exc_info=True)
            raise RuntimeError(f"Failed to train regime classification model: {exc}")
    
    @staticmethod
    def _resolve_default_provider_symbol(symbol: str, *, fallback: Optional[str] = None) -> str:
        """
        Determine the default provider symbol Angel One understands for a given logical ticker.
        """
        overrides = {
            "^NSEI": "NIFTY 50",
            "NSEI": "NIFTY 50",
            "^NSEBANK": "NIFTY BANK",
            "NSEBANK": "NIFTY BANK",
            "^NIFTY50": "NIFTY 50",
            "NIFTY50": "NIFTY 50",
            "^BANKNIFTY": "NIFTY BANK",
            "BANKNIFTY": "NIFTY BANK",
        }
        upper = symbol.upper()
        if upper in overrides:
            return overrides[upper]
        stripped = upper.lstrip("^")
        return fallback or stripped
    
    def _build_and_start_pipeline(self):
        """Build Pathway pipeline with AsyncTransformers and start runtime"""
        try:
            # Start Pathway runtime in background thread
            self._runner_thread = threading.Thread(
                target=self._run_pathway_runtime,
                daemon=True,
                name="pathway-regime-runtime"
            )
            self._runner_thread.start()
            
            # Wait for pipeline to start (with timeout)
            if not self._started.wait(timeout=15):
                self.logger.warning("⚠️ Pathway runtime startup timeout - continuing anyway")
            else:
                self.logger.info("✅ Pathway runtime started")
                
        except Exception as exc:
            self.logger.error(f"❌ Failed to start Pathway pipeline: {exc}", exc_info=True)
            raise RuntimeError(f"Pathway pipeline startup failed: {exc}")
    
    def _run_pathway_runtime(self):
        """
        Run Pathway runtime in background thread.
        Builds the complete AsyncTransformer pipeline.
        """
        try:
            from services.regime_stream import (
                TriggerSchema,
                CandleStreamSubject,
                CandleFetcherTransformer
            )
            from services.regime_features import (
                FeatureComputeTransformer,
                RegimePredictorTransformer
            )
            
            self.logger.info("🔨 Building Pathway pipeline components...")
            
            # 1. Candle streaming subject (emits triggers every 60s)
            candle_subject = CandleStreamSubject(interval_seconds=60)
            trigger_table = pw.io.python.read(
                candle_subject,
                schema=TriggerSchema,
                autocommit_duration_ms=60000,  # Commit every 60 seconds
                name="candle_trigger_stream"
            )
            
            self.logger.info("✓ Trigger stream created")
            
            # 2. AsyncTransformer: Fetch candles
            candle_fetcher = CandleFetcherTransformer(
                input_table=trigger_table,
                symbol=self.streaming_symbol,
                provider_symbol=self.streaming_provider_symbol,
                interval=self.streaming_interval,
            ).with_options(capacity=5)  # Limit concurrent fetches
            
            candles = candle_fetcher.successful
            self.logger.info("✓ Candle fetcher created")
            
            # 3. AsyncTransformer: Compute features
            feature_computer = FeatureComputeTransformer(
                input_table=candles,
                window_size=250  # Keep 250 candles for feature computation
            ).with_options(capacity=10)  # Higher concurrency for CPU-bound ops
            
            features = feature_computer.successful
            self.logger.info("✓ Feature computer created")
            
            # 4. AsyncTransformer: Predict regime
            regime_predictor = RegimePredictorTransformer(
                input_table=features,
                classifier=self.classifier
            ).with_options(capacity=5)
            
            regimes = regime_predictor.successful
            self.logger.info("✓ Regime predictor created")
            
            # Subscribe to regime updates
            pw.io.subscribe(regimes, self._on_regime_update)
            self.logger.info("✓ Subscribed to regime updates")
            
            # Signal that we're ready
            self._started.set()
            
            # Run Pathway runtime
            self.logger.info("🚀 Starting Pathway runtime...")
            
            try:
                monitoring_level = getattr(pw, "MonitoringLevel", None)
                if monitoring_level is not None and hasattr(monitoring_level, "NONE"):
                    pw.run(monitoring_level=monitoring_level.NONE)
                else:
                    pw.run()
            except Exception as run_exc:
                self.logger.error(f"Pathway runtime error: {run_exc}", exc_info=True)
                
        except Exception as exc:
            self.logger.error(f"❌ Pathway pipeline build failed: {exc}", exc_info=True)
            self._started.set()  # Signal even on failure to avoid hanging
        finally:
            self.logger.info("Pathway runtime shut down")
    
    def _on_regime_update(self, key, row, time, is_addition):
        """
        Callback when new regime prediction arrives from Pathway.
        
        Args:
            key: Pathway row key
            row: Row data with regime prediction
            time: Pathway processing time
            is_addition: Whether this is an addition (vs deletion/update)
        """
        if not is_addition:
            return
        
        try:
            # Parse regime data
            regime_data = {
                "timestamp": float(row["timestamp"]),
                "regime": str(row["regime"]),
                "state_id": int(row["state_id"]),
                "symbol": str(row["symbol"]),
                "features": json.loads(row["features_json"])
            }
            
            # Update cache
            with self._cache_lock:
                self._current_regime = regime_data
                self._regime_history.append(regime_data)
            
            self.logger.info(
                f"📊 Regime Update: {regime_data['regime']} "
                f"(state {regime_data['state_id']}) at {regime_data['timestamp']}"
            )
            
        except Exception as exc:
            self.logger.error(f"Error processing regime update: {exc}", exc_info=True)
    
    # ==================== Public API Methods ====================
    
    def get_current_regime(self) -> Optional[Dict]:
        """
        Get current regime classification.
        
        Returns:
            Dictionary with regime, timestamp, state_id, symbol, and features
            None if no regime has been predicted yet
        """
        with self._cache_lock:
            return self._current_regime.copy() if self._current_regime else None
    
    def get_regime_history(self, limit: int = 100) -> List[Dict]:
        """
        Get regime classification history.
        
        Args:
            limit: Maximum number of historical points to return
            
        Returns:
            List of regime data dictionaries, most recent last
        """
        with self._cache_lock:
            history = list(self._regime_history)
        
        # Return up to 'limit' most recent entries
        return history[-limit:] if len(history) > limit else history
    
    def get_regime_statistics(self) -> Dict:
        """
        Get statistics for each regime.
        
        Returns:
            Dictionary with statistics per regime
        """
        with self._cache_lock:
            history = list(self._regime_history)
        
        if not history:
            return {
                "total_observations": 0,
                "statistics": []
            }
        
        # Count observations per regime
        regime_counts = {}
        regime_features = {}
        
        for data in history:
            regime = data["regime"]
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
            
            if regime not in regime_features:
                regime_features[regime] = {
                    "returns": [],
                    "volatility": []
                }
            
            features = data.get("features", {})
            if "returns" in features:
                regime_features[regime]["returns"].append(features["returns"])
            if "volatility_20d" in features:
                regime_features[regime]["volatility"].append(features["volatility_20d"])
        
        # Compute statistics
        total = len(history)
        statistics = []
        
        for regime, count in regime_counts.items():
            avg_return = (
                sum(regime_features[regime]["returns"]) / len(regime_features[regime]["returns"])
                if regime_features[regime]["returns"] else 0.0
            )
            avg_volatility = (
                sum(regime_features[regime]["volatility"]) / len(regime_features[regime]["volatility"])
                if regime_features[regime]["volatility"] else 0.0
            )
            
            statistics.append({
                "regime": regime,
                "percentage_time": round((count / total) * 100, 2),
                "avg_return": round(avg_return, 6),
                "avg_volatility": round(avg_volatility, 6),
                "count": count
            })
        
        # Sort by percentage time (descending)
        statistics.sort(key=lambda x: x["percentage_time"], reverse=True)
        
        return {
            "total_observations": total,
            "statistics": statistics
        }
    
    def retrain_model(self, start_date: str = "2020-01-01", end_date: Optional[str] = None, 
                     n_regimes: int = 4) -> Dict:
        """
        Retrain the HMM model with new parameters.
        Note: This does NOT restart the Pathway pipeline - requires service restart for full effect.
        
        Uses yfinance to avoid Angel One rate limits during training.
        
        Args:
            start_date: Start date for training data (YYYY-MM-DD format)
            end_date: End date for training data (None = today)
            n_regimes: Number of regimes to classify
            
        Returns:
            Dictionary with training results
        """
        try:
            from datetime import datetime
            
            self.logger.info(f"🔄 Retraining model from {start_date} with {n_regimes} regimes using yfinance...")
            
            # Parse dates
            start_dt = datetime.strptime(start_date, "%Y-%m-%d") if isinstance(start_date, str) else start_date
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date and isinstance(end_date, str) else datetime.now()
            
            # Fetch data using yfinance to avoid rate limits
            data = fetch_nse_data(
                ticker=self.training_symbol,
                start_date=start_dt,
                end_date=end_dt,
                provider_symbol=self.provider_symbol,
                use_yfinance=True,  # CRITICAL: Use yfinance to avoid Angel One rate limits
            )
            
            if data is None or data.empty:
                raise ValueError("Failed to fetch training data from yfinance")
            
            # Train new classifier
            new_classifier = MarketRegimeClassifier(n_regimes=n_regimes, random_state=42)
            new_classifier.fit(data)
            
            # Update classifier (note: pipeline AsyncTransformers still use old classifier)
            self.classifier = new_classifier
            
            self.logger.info("✅ Model retrained successfully using yfinance data")
            
            return {
                "success": True,
                "message": "Model retrained (service restart required for pipeline update)",
                "regimes": {k: v for k, v in new_classifier.regime_names.items()},
                "training_samples": len(data)
            }
            
        except Exception as exc:
            self.logger.error(f"❌ Model retraining failed: {exc}", exc_info=True)
            return {
                "success": False,
                "message": f"Retraining failed: {str(exc)}",
                "regimes": {},
                "training_samples": 0
            }
    
    def update_sensitivity(self, alpha_diag: float = 5.0) -> Dict:
        """
        Update regime transition sensitivity (stickiness).
        Note: This updates the classifier but requires service restart for pipeline effect.
        
        Args:
            alpha_diag: Diagonal boost for transition matrix (higher = stickier)
            
        Returns:
            Dictionary with update results
        """
        try:
            self.logger.info(f"🔄 Updating sensitivity with alpha_diag={alpha_diag}...")
            
            # Update classifier
            self.classifier = update_sensitivity(self.classifier, alpha_diag=alpha_diag)
            
            self.logger.info("✅ Sensitivity updated")
            
            return {
                "success": True,
                "message": "Sensitivity updated (service restart required for pipeline update)",
                "alpha_diag": alpha_diag
            }
            
        except Exception as exc:
            self.logger.error(f"❌ Sensitivity update failed: {exc}", exc_info=True)
            return {
                "success": False,
                "message": f"Sensitivity update failed: {str(exc)}",
                "alpha_diag": alpha_diag
            }

