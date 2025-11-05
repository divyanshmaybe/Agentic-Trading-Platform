"""
Pipeline Service - Business logic for pipeline operations
"""

import sys
import os
import threading
from typing import Optional


class PipelineService:
    """Service for managing pipeline operations"""
    
    def __init__(self, server_dir: str, logger: any):
        self.server_dir = server_dir
        self.logger = logger
        self.pipeline_thread: Optional[threading.Thread] = None
    
    def start_nse_pipeline(self) -> threading.Thread:
        """Start NSE pipeline in background thread"""
        if self.pipeline_thread and self.pipeline_thread.is_alive():
            self.logger.warning("NSE pipeline is already running")
            return self.pipeline_thread
        
        thread = threading.Thread(target=self._run_nse_pipeline, daemon=True)
        thread.start()
        self.pipeline_thread = thread
        self.logger.info("✓ NSE pipeline started in background thread")
        return thread
    
    def _run_nse_pipeline(self):
        """Run NSE pipeline in a separate thread"""
        try:
            nse_dir = os.path.join(self.server_dir, "pipelines/nse")
            original_dir = os.getcwd()
            
            # Load .env from portfolio-server directory ONLY (before changing directory)
            env_file = os.path.join(self.server_dir, ".env")
            if not os.path.exists(env_file):
                raise FileNotFoundError(f".env file not found in portfolio-server directory: {env_file}")
            
            from dotenv import load_dotenv
            load_dotenv(env_file, override=True)
            # Set environment variable so pipeline files know where .env was loaded from
            os.environ["PORTFOLIO_SERVER_ENV_PATH"] = env_file
            self.logger.info(f"✓ Loaded .env from portfolio-server: {env_file}")
            
            try:
                os.chdir(nse_dir)
                sys.path.insert(0, nse_dir)
                
                import pathway as pw
                from nse_live_scraper import create_nse_scraper_input
                from nse_filings_sentiment import create_nse_filings_pipeline
                from nse_backtest import create_backtest_pipeline, compute_backtest_metrics
                
                self.logger.info("=" * 70)
                self.logger.info("NSE Live Trading Pipeline - Real-time Sentiment Analysis")
                self.logger.info("=" * 70)
                
                refresh_interval = 60
                static_data_path = "staticdata.csv"
                signals_output = "trading_signals.jsonl"
                backtest_output = "backtest_results.jsonl"
                metrics_output = "backtest_metrics.jsonl"
                
                if not os.path.exists(static_data_path):
                    self.logger.info("staticdata.csv not found - using default impact scenarios")
                
                self.logger.info(f"Starting live NSE scraper (interval: {refresh_interval}s)...")
                filings_input = create_nse_scraper_input(refresh_interval=refresh_interval)
                
                self.logger.info("Building sentiment analysis pipeline...")
                trading_signals = create_nse_filings_pipeline(
                    filings_source=filings_input,
                    static_data_path=static_data_path,
                    output_path=signals_output,
                )
                
                self.logger.info("Building backtest pipeline...")
                backtest_results = create_backtest_pipeline(trading_signals)
                backtest_metrics = compute_backtest_metrics(backtest_results)
                
                pw.io.jsonlines.write(backtest_results, backtest_output)
                pw.io.jsonlines.write(backtest_metrics, metrics_output)
                
                def on_new_signal(key, row, time, is_addition):
                    if is_addition:
                        symbol = row.get("symbol", "N/A")
                        signal = row.get("signal", "N/A")
                        explanation = row.get("explanation", "")[:50] if row.get("explanation") else ""
                        self.logger.info(f"[PIPELINE] ✓ Signal generated: {symbol} - Signal: {signal} - {explanation}...")
                
                def on_new_backtest(key, row, time, is_addition):
                    if is_addition:
                        symbol = row.get("symbol", "N/A")
                        pnl = row.get("pnl", 0)
                        exit_reason = row.get("exit_reason", "N/A")
                        self.logger.info(f"[PIPELINE] ✓ Backtest result: {symbol} - PnL: {pnl:.4f} - Exit: {exit_reason}")
                
                def on_signal_end():
                    self.logger.info("[PIPELINE] Signal stream ended")
                
                def on_backtest_end():
                    self.logger.info("[PIPELINE] Backtest stream ended")
                
                pw.io.subscribe(trading_signals, on_new_signal, on_signal_end)
                pw.io.subscribe(backtest_results, on_new_backtest, on_backtest_end)
                
                self.logger.info("✓ Pipeline built successfully!")
                self.logger.info("✓ Running pipeline (will scrape continuously)...")
                pw.run(monitoring_level=pw.MonitoringLevel.NONE)
                
            finally:
                os.chdir(original_dir)
                
        except KeyboardInterrupt:
            self.logger.info("Pipeline stopped by user")
        except Exception as e:
            self.logger.error(f"Pipeline failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    def is_pipeline_running(self) -> bool:
        """Check if pipeline is running"""
        return (
            self.pipeline_thread is not None
            and self.pipeline_thread.is_alive()
        )

