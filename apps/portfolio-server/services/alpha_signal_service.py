"""Service for generating alpha signals using quant-stream.

This service uses the workflow_config from LiveAlpha to:
1. Load historical OHLCV data from quant-stream data files
2. Compute factor expressions using quant-stream functions
3. Load TRAINED ML model from MLflow artifacts (NO retraining)
4. Run ML model inference for signal generation
5. Apply TopkDropout strategy to generate buy/sell signals
6. Dispatch signals to trade execution pipeline

IMPORTANT: The ML model is trained during the AlphaCopilot research run.
The trained model is saved as an MLflow artifact. This service loads that
trained model for inference - it does NOT retrain the model.
"""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import logging
import pickle

import pandas as pd
import numpy as np

# Add quant-stream to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUANT_STREAM_PATH = PROJECT_ROOT / "quant-stream"
QUANT_STREAM_DATA_PATH = QUANT_STREAM_PATH / ".data"
MLRUNS_PATH = QUANT_STREAM_PATH / "mlruns.db"
if str(QUANT_STREAM_PATH) not in sys.path:
    sys.path.insert(0, str(QUANT_STREAM_PATH))


class AlphaSignalService:
    """Service for generating trading signals from live alphas.
    
    Uses quant-stream's factor library and TRAINED ML models for inference.
    
    The workflow:
    1. Research run trains a model and saves it to MLflow
    2. LiveAlpha stores the mlflow_run_id in workflow_config or metadata
    3. This service loads the trained model from MLflow for inference
    4. Model is cached to avoid repeated loading
    """
    
    def __init__(self, prisma_client, logger: Optional[logging.Logger] = None):
        self.client = prisma_client
        self.logger = logger or logging.getLogger(__name__)
        self._factor_registry = None
        self._ohlcv_cache: Dict[str, pd.DataFrame] = {}
        self._model_cache: Dict[str, Any] = {}  # Cache: mlflow_run_id -> trained model
    
    def _get_factor_registry(self):
        """Lazy load the factor registry from quant-stream."""
        if self._factor_registry is None:
            try:
                from quant_stream.functions import FACTOR_REGISTRY
                self._factor_registry = FACTOR_REGISTRY
                self.logger.info("Loaded %d factors from quant-stream registry", len(FACTOR_REGISTRY))
            except ImportError as e:
                self.logger.error("Failed to import FACTOR_REGISTRY: %s", e)
                self._factor_registry = {}
        return self._factor_registry
    
    def _load_ohlcv_data(self, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """Load OHLCV data from quant-stream data files.
        
        Uses indian_stock_market_nifty500.csv which contains historical data.
        """
        cache_key = str(symbols) if symbols else "all"
        if cache_key in self._ohlcv_cache:
            return self._ohlcv_cache[cache_key]
        
        data_file = QUANT_STREAM_DATA_PATH / "indian_stock_market_nifty500.csv"
        
        if not data_file.exists():
            self.logger.error("OHLCV data file not found: %s", data_file)
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(data_file)
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values(['symbol', 'date'])
            
            if symbols:
                df = df[df['symbol'].isin(symbols)]
            
            self._ohlcv_cache[cache_key] = df
            self.logger.info("Loaded %d rows of OHLCV data for %d symbols", 
                           len(df), df['symbol'].nunique())
            return df
            
        except Exception as e:
            self.logger.error("Failed to load OHLCV data: %s", e)
            return pd.DataFrame()
    
    def _load_trained_model_from_mlflow(
        self,
        mlflow_run_id: str,
        tracking_uri: Optional[str] = None,
    ) -> Optional[Any]:
        """Load a TRAINED ML model from MLflow artifacts.
        
        This loads the model that was trained during the AlphaCopilot research run.
        The model is cached to avoid repeated loading.
        
        Args:
            mlflow_run_id: The MLflow run ID where the model was saved
            tracking_uri: MLflow tracking URI (defaults to quant-stream's mlruns.db)
            
        Returns:
            The trained model object, or None if loading fails
        """
        if mlflow_run_id in self._model_cache:
            self.logger.debug("Using cached model for run %s", mlflow_run_id)
            return self._model_cache[mlflow_run_id]
        
        tracking_uri = tracking_uri or f"sqlite:///{MLRUNS_PATH}"
        
        try:
            from quant_stream.recorder.utils import load_mlflow_run_artifacts
            
            # Try to load model artifact (common names: model, trained_model, lgb_model)
            model_names = ["model", "trained_model", "lgb_model", "xgb_model", "rf_model"]
            
            for model_name in model_names:
                try:
                    artifacts = load_mlflow_run_artifacts(
                        run_id=mlflow_run_id,
                        artifact_names=[model_name],
                        tracking_uri=tracking_uri,
                    )
                    
                    if model_name in artifacts and artifacts[model_name] is not None:
                        model = artifacts[model_name]
                        self._model_cache[mlflow_run_id] = model
                        self.logger.info(
                            "✅ Loaded trained model '%s' from MLflow run %s",
                            model_name, mlflow_run_id
                        )
                        return model
                except Exception as e:
                    self.logger.debug("Model '%s' not found in run %s: %s", model_name, mlflow_run_id, e)
            
            # Fallback: try direct MLflow client access
            try:
                import mlflow
                from mlflow.tracking import MlflowClient
                
                mlflow.set_tracking_uri(tracking_uri)
                client = MlflowClient(tracking_uri=tracking_uri)
                
                # List all artifacts in the run
                artifacts_list = client.list_artifacts(mlflow_run_id)
                self.logger.debug("Available artifacts in run %s: %s", 
                                mlflow_run_id, [a.path for a in artifacts_list])
                
                # Try to find any .pkl file
                for artifact in artifacts_list:
                    if artifact.path.endswith('.pkl'):
                        artifact_path = client.download_artifacts(mlflow_run_id, artifact.path)
                        with open(artifact_path, 'rb') as f:
                            model = pickle.load(f)
                        self._model_cache[mlflow_run_id] = model
                        self.logger.info(
                            "✅ Loaded trained model from artifact '%s' in MLflow run %s",
                            artifact.path, mlflow_run_id
                        )
                        return model
                        
            except Exception as e:
                self.logger.warning("Failed to access MLflow directly: %s", e)
            
            self.logger.warning(
                "⚠️ No trained model found in MLflow run %s. "
                "Will use factor-based scoring instead.",
                mlflow_run_id
            )
            return None
            
        except ImportError as e:
            self.logger.error("Failed to import MLflow utilities: %s", e)
            return None
        except Exception as e:
            self.logger.error("Failed to load model from MLflow run %s: %s", mlflow_run_id, e)
            return None
    
    def _get_mlflow_run_id(self, alpha) -> Optional[str]:
        """Extract MLflow run ID from alpha's workflow_config or metadata.
        
        The run ID might be stored in:
        1. workflow_config.experiment.run_id
        2. workflow_config.mlflow_run_id
        3. alpha.metadata.mlflow_run_id
        4. AlphaCopilotResult associated with alpha.run_id
        """
        workflow_config = alpha.workflow_config
        if isinstance(workflow_config, str):
            workflow_config = json.loads(workflow_config)
        
        # Check workflow_config
        if workflow_config:
            # Check experiment.run_id
            experiment = workflow_config.get("experiment", {})
            if experiment.get("run_id"):
                return experiment["run_id"]
            
            # Check direct mlflow_run_id
            if workflow_config.get("mlflow_run_id"):
                return workflow_config["mlflow_run_id"]
        
        # Check metadata
        metadata = alpha.metadata
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}
        
        if metadata and metadata.get("mlflow_run_id"):
            return metadata["mlflow_run_id"]
        
        return None
    
    async def generate_signals_for_alpha(self, alpha) -> List[Dict[str, Any]]:
        """
        Generate trading signals for a live alpha using its workflow config.
        
        Process:
        1. Parse workflow_config to get data, features, model, strategy config
        2. Load recent OHLCV data for configured symbols
        3. Compute factor values using quant-stream factor expressions
        4. Run ML model inference if model is configured
        5. Apply TopkDropout strategy to rank symbols
        6. Generate buy signals for top-k symbols
        7. Generate sell signals for positions dropping out of top-k
        
        Args:
            alpha: LiveAlpha Prisma model
            
        Returns:
            List of signal dictionaries with:
            - alpha_id: str
            - symbol: str
            - signal_type: 'buy' | 'sell'
            - quantity: int (calculated from allocated_amount)
            - confidence: float (0-1)
            - allocated_amount: float
            - score: float (model prediction or factor score)
        """
        workflow_config = alpha.workflow_config
        if isinstance(workflow_config, str):
            workflow_config = json.loads(workflow_config)
        
        if not workflow_config:
            self.logger.warning("Alpha %s has no workflow config", alpha.id)
            return []
        
        # Extract configuration
        data_config = workflow_config.get("data", {})
        features_config = workflow_config.get("features", [])
        model_config = workflow_config.get("model", {})
        strategy_config = workflow_config.get("strategy", {})
        
        # Get symbols from alpha or workflow config
        symbols = list(alpha.symbols) if alpha.symbols else []
        if not symbols:
            symbols = data_config.get("symbols", [])
        if not symbols and data_config.get("symbols_file"):
            # Load symbols from file
            symbols_file = Path(data_config["symbols_file"])
            if not symbols_file.is_absolute():
                symbols_file = QUANT_STREAM_DATA_PATH / symbols_file
            if symbols_file.exists():
                symbols = [s.strip() for s in symbols_file.read_text().splitlines() if s.strip()]
        
        # Apply max_symbols limit if configured
        max_symbols = data_config.get("max_symbols")
        if max_symbols and len(symbols) > max_symbols:
            symbols = symbols[:max_symbols]
        
        if not symbols:
            self.logger.warning("Alpha %s has no symbols configured", alpha.id)
            return []
        
        self.logger.info(
            "Generating signals for alpha %s (%s) with %d features and %d symbols",
            alpha.name, alpha.id, len(features_config), len(symbols)
        )
        
        try:
            # Load OHLCV data
            ohlcv_df = self._load_ohlcv_data(symbols)
            
            if ohlcv_df.empty:
                self.logger.warning("No OHLCV data available for alpha %s", alpha.id)
                return []
            
            # Get latest data point for each symbol
            latest_df = self._get_latest_data(ohlcv_df, lookback_days=60)
            
            if latest_df.empty:
                self.logger.warning("No recent data available for alpha %s", alpha.id)
                return []
            
            # Compute factor values
            factor_df = self._compute_factors(latest_df, features_config)
            
            # Run ML model inference using TRAINED model from MLflow (no retraining!)
            scores_df = self._run_model_inference(alpha, factor_df, model_config)
            
            # Generate signals based on strategy
            signals = self._apply_strategy(
                alpha=alpha,
                scores_df=scores_df,
                strategy_config=strategy_config,
                allocated_amount=float(alpha.allocated_amount),
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
    
    def _get_latest_data(self, df: pd.DataFrame, lookback_days: int = 60) -> pd.DataFrame:
        """Get latest data for each symbol with lookback for factor computation.
        
        Returns DataFrame with most recent `lookback_days` of data per symbol,
        which is needed for computing rolling factors like MA, RSI, etc.
        """
        if df.empty:
            return df
        
        # Get the latest date in the data
        latest_date = df['date'].max()
        cutoff_date = latest_date - timedelta(days=lookback_days)
        
        # Filter to recent data
        recent_df = df[df['date'] >= cutoff_date].copy()
        
        self.logger.debug(
            "Filtered data to %d rows from %s to %s",
            len(recent_df), cutoff_date.strftime("%Y-%m-%d"), latest_date.strftime("%Y-%m-%d")
        )
        
        return recent_df
    
    def _compute_factors(
        self,
        df: pd.DataFrame,
        features_config: List[Dict[str, Any]],
    ) -> pd.DataFrame:
        """Compute factor values for all symbols using quant-stream factor expressions.
        
        Args:
            df: DataFrame with OHLCV data (columns: symbol, date, open, high, low, close, volume)
            features_config: List of feature configs with name and expression
            
        Returns:
            DataFrame with computed factor values (latest row per symbol)
        """
        if df.empty or not features_config:
            return df
        
        try:
            # Import quant-stream factor computation
            from quant_stream.factors import compute_all_factors
            
            # Compute all factors from expressions
            expressions = [f.get("expression", "") for f in features_config if f.get("expression")]
            names = [f.get("name", f"factor_{i}") for i, f in enumerate(features_config)]
            
            # Use quant-stream's factor computation
            factor_df = compute_all_factors(
                df,
                expressions=expressions,
                factor_names=names,
            )
            
            # Get latest row per symbol
            latest_df = factor_df.sort_values('date').groupby('symbol').last().reset_index()
            
            self.logger.info(
                "Computed %d factors for %d symbols",
                len(names), len(latest_df)
            )
            
            return latest_df
            
        except ImportError:
            self.logger.warning("quant_stream.factors not available, using simple factor computation")
            return self._compute_factors_simple(df, features_config)
        except Exception as e:
            self.logger.error("Factor computation failed: %s", e)
            return self._compute_factors_simple(df, features_config)
    
    def _compute_factors_simple(
        self,
        df: pd.DataFrame,
        features_config: List[Dict[str, Any]],
    ) -> pd.DataFrame:
        """Simple factor computation fallback using pandas.
        
        Computes basic factors like returns, momentum, volatility when 
        quant-stream factor engine is not available.
        """
        if df.empty:
            return df
        
        result_dfs = []
        
        for symbol in df['symbol'].unique():
            symbol_df = df[df['symbol'] == symbol].copy().sort_values('date')
            
            if len(symbol_df) < 5:
                continue
            
            # Basic factors
            symbol_df['return_1d'] = symbol_df['close'].pct_change(1)
            symbol_df['return_5d'] = symbol_df['close'].pct_change(5)
            symbol_df['return_20d'] = symbol_df['close'].pct_change(20)
            symbol_df['momentum_10d'] = symbol_df['close'] / symbol_df['close'].shift(10) - 1
            symbol_df['volatility_20d'] = symbol_df['return_1d'].rolling(20).std()
            symbol_df['volume_ma_10'] = symbol_df['volume'].rolling(10).mean()
            symbol_df['volume_ratio'] = symbol_df['volume'] / symbol_df['volume_ma_10']
            
            # Technical indicators
            symbol_df['sma_20'] = symbol_df['close'].rolling(20).mean()
            symbol_df['sma_50'] = symbol_df['close'].rolling(50).mean()
            symbol_df['price_to_sma20'] = symbol_df['close'] / symbol_df['sma_20'] - 1
            
            # RSI
            delta = symbol_df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, np.nan)
            symbol_df['rsi_14'] = 100 - (100 / (1 + rs))
            
            result_dfs.append(symbol_df)
        
        if not result_dfs:
            return pd.DataFrame()
        
        combined_df = pd.concat(result_dfs, ignore_index=True)
        
        # Get latest row per symbol
        latest_df = combined_df.sort_values('date').groupby('symbol').last().reset_index()
        
        return latest_df
    
    def _run_model_inference(
        self,
        alpha,
        factor_df: pd.DataFrame,
        model_config: Dict[str, Any],
    ) -> pd.DataFrame:
        """Run ML model inference using the TRAINED model from MLflow.
        
        This method loads the model that was trained during the research run,
        NOT retraining. The model is retrieved from MLflow artifacts.
        
        If no model is available, uses average of factor values as score.
        
        Args:
            alpha: LiveAlpha object containing workflow_config with mlflow_run_id
            factor_df: DataFrame with computed factors
            model_config: Model configuration from workflow_config
            
        Returns:
            DataFrame with 'score' column added
        """
        if factor_df.empty:
            return factor_df
        
        # Get MLflow run ID from alpha's workflow config
        mlflow_run_id = self._get_mlflow_run_id(alpha)
        
        # Try to load the trained model from MLflow
        model = None
        if mlflow_run_id:
            model = self._load_trained_model_from_mlflow(mlflow_run_id)
            if model is not None:
                self.logger.info(
                    "Loaded trained model from MLflow run %s for alpha %s",
                    mlflow_run_id, alpha.id
                )
        
        if model is not None:
            try:
                # Get feature columns (exclude symbol, date, OHLCV)
                exclude_cols = ['symbol', 'date', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
                feature_cols = [c for c in factor_df.columns if c not in exclude_cols]
                
                if feature_cols:
                    X = factor_df[feature_cols].fillna(0)
                    
                    # Run prediction using the trained model
                    if hasattr(model, 'predict'):
                        factor_df['score'] = model.predict(X)
                        self.logger.info(
                            "Model inference complete for %d symbols using MLflow model",
                            len(factor_df)
                        )
                    else:
                        # Model doesn't have predict method, use factor average
                        self.logger.warning("Loaded model has no predict method, using factor average")
                        factor_df['score'] = X.mean(axis=1)
                else:
                    self.logger.warning("No feature columns found for model inference")
                    factor_df['score'] = 0.0
                    
            except Exception as e:
                self.logger.warning(
                    "Model inference failed for alpha %s: %s, using factor average",
                    alpha.id, e
                )
                factor_df['score'] = self._compute_simple_score(factor_df)
        else:
            # No model available - use simple factor-based scoring
            self.logger.info(
                "No MLflow model found for alpha %s (run_id=%s), using factor-based scoring",
                alpha.id, mlflow_run_id
            )
            factor_df['score'] = self._compute_simple_score(factor_df)
        
        return factor_df
    
    def _compute_simple_score(self, df: pd.DataFrame) -> pd.Series:
        """Compute simple score from factor values (average of normalized factors)."""
        # Get numeric columns excluding OHLCV
        exclude_cols = ['symbol', 'date', 'timestamp', 'open', 'high', 'low', 'close', 'volume', 'score']
        factor_cols = [c for c in df.columns if c not in exclude_cols and pd.api.types.is_numeric_dtype(df[c])]
        
        if not factor_cols:
            return pd.Series([0.5] * len(df), index=df.index)
        
        # Z-score normalization and average
        factor_matrix = df[factor_cols].fillna(0)
        normalized = (factor_matrix - factor_matrix.mean()) / (factor_matrix.std() + 1e-8)
        scores = normalized.mean(axis=1)
        
        # Scale to 0-1 range
        min_score = scores.min()
        max_score = scores.max()
        if max_score > min_score:
            scores = (scores - min_score) / (max_score - min_score)
        else:
            scores = 0.5
        
        return scores
    
    def _apply_strategy(
        self,
        alpha,
        scores_df: pd.DataFrame,
        strategy_config: Dict[str, Any],
        allocated_amount: float,
    ) -> List[Dict[str, Any]]:
        """Apply TopkDropout strategy to generate trading signals.
        
        TopkDropout Strategy:
        1. Rank symbols by score (descending)
        2. Select top-k symbols for buying
        3. Calculate allocation based on method (equal or signal-weighted)
        4. Compare with current positions to generate buy/sell signals
        """
        if scores_df.empty:
            return []
        
        strategy_type = strategy_config.get("type", "TopkDropout")
        params = strategy_config.get("params", {})
        
        topk = params.get("topk", 10)
        n_drop = params.get("n_drop", 2)
        method = params.get("method", "equal")
        
        # Get current positions for this alpha (to determine sells)
        # For now, just generate buy signals
        
        # Sort by score descending
        ranked_df = scores_df.sort_values('score', ascending=False).head(topk)
        
        if ranked_df.empty:
            return []
        
        signals = []
        total_positive_score = max(ranked_df[ranked_df['score'] > 0]['score'].sum(), 1e-8)
        
        for _, row in ranked_df.iterrows():
            symbol = row['symbol']
            score = row.get('score', 0.5)
            try:
                close_price = float(row.get('close'))
            except (TypeError, ValueError):
                continue
            
            # Skip if close price is invalid
            if close_price <= 0:
                continue
            
            # Calculate allocation
            if method == "equal":
                alloc = allocated_amount / topk
            else:
                # Signal-weighted allocation
                alloc = (max(0, score) / total_positive_score) * allocated_amount if score > 0 else 0
            
            # Calculate quantity
            quantity = int(alloc / close_price) if close_price > 0 else 0
            
            if quantity <= 0:
                continue
            
            signals.append({
                "alpha_id": alpha.id,
                "portfolio_id": alpha.portfolio_id,
                "symbol": symbol,
                "signal_type": "buy",
                "quantity": quantity,
                "confidence": min(max(score, 0), 1.0),
                "allocated_amount": alloc,
                "reference_price": float(close_price),
                "score": float(score),
                "generated_at": datetime.utcnow().isoformat(),
                "strategy_type": strategy_type,
                "rank": len(signals) + 1,
            })
        
        self.logger.info(
            "Generated %d buy signals for alpha %s (top %d of %d)",
            len(signals), alpha.name, topk, len(scores_df)
        )
        
        return signals
    
    async def _dispatch_signals(
        self,
        alpha,
        signals: List[Dict[str, Any]],
    ) -> None:
        """
        Dispatch signals to trade execution pipeline.
        
        Creates trades via the portfolio's alpha agent system.
        """
        if not signals:
            return
        
        # Import here to avoid circular imports
        try:
            from celery_app import celery_app
            
            # Queue for async processing using send_task
            celery_app.send_task(
                "alpha.process_signal_batch",
                args=[signals],
                queue="trading",
                routing_key="trading"
            )
            
            self.logger.info(
                "Dispatched %d signals for alpha %s to trade execution",
                len(signals), alpha.id
            )
        except Exception as e:
            self.logger.error("Failed to dispatch signals: %s", e)
            # Fallback: process synchronously
            await self._process_signals_sync(alpha, signals)
    
    async def _process_signals_sync(
        self,
        alpha,
        signals: List[Dict[str, Any]],
    ) -> None:
        """Process signals synchronously when Celery is not available."""
        from services.trade_execution_service import TradeExecutionService
        
        trade_service = TradeExecutionService(logger=self.logger)
        
        for signal in signals:
            try:
                await trade_service.create_alpha_trade(
                    alpha=alpha,
                    symbol=signal["symbol"],
                    signal_type=signal["signal_type"],
                    quantity=signal.get("quantity"),
                    confidence=signal.get("confidence", 1.0),
                    reference_price=signal.get("reference_price"),
                )
            except Exception as e:
                self.logger.error(
                    "Failed to create trade for signal %s: %s",
                    signal, e
                )



