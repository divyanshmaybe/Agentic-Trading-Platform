"""
Pipeline Service - Business logic for pipeline operations
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


from dotenv import load_dotenv

class PipelineService:
    """Service for managing pipeline operations."""

    def __init__(self, server_dir: str, logger: Optional[logging.Logger]) -> None:
        self.server_dir = server_dir
        self.logger = logger or logging.getLogger(__name__)
        self.status_file = Path(self.server_dir) / "pipeline_status.json"
        self.news_status_file = Path(self.server_dir) / "news_pipeline_status.json"
        self._env_loaded = False

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def run_nse_pipeline_forever(self) -> None:
        """Run the NSE pipeline continuously (intended for Celery worker)."""
        self._load_environment()
        self._update_status("starting")
        try:
            self.logger.info("Starting NSE pipeline in Celery worker")
            self._execute_nse_pipeline()
        finally:
            self._update_status("stopped")

    def run_news_sentiment_pipeline(self, *, top_k: int = 3) -> Dict[str, Any]:
        """Run the News sentiment pipeline once and return metadata."""

        self._load_environment()
        self._update_news_status("starting")
        try:
            self.logger.info("Running news sentiment pipeline (top_k=%s)", top_k)
            metadata = self._execute_news_pipeline(top_k=top_k)
            self._update_news_status("succeeded", metadata=metadata)
            return metadata
        except Exception as exc:  # pragma: no cover - execution failures surfaced to Celery
            self.logger.exception("News sentiment pipeline failed: %s", exc)
            self._update_news_status("failed", error=str(exc))
            raise

    # Backwards compatibility hook (no longer threaded)
    def start_nse_pipeline(self) -> None:  # pragma: no cover - legacy entrypoint
        self.logger.warning(
            "start_nse_pipeline() now runs synchronously; scheduling should be handled by Celery"
        )
        self.run_nse_pipeline_forever()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_nse_pipeline(self) -> None:
        nse_dir = os.path.join(self.server_dir, "pipelines/nse")
        original_dir = os.getcwd()

        try:
            os.chdir(nse_dir)
            sys.path.insert(0, nse_dir)

            import pathway as pw
            from nse_backtest import compute_backtest_metrics, create_backtest_pipeline
            from nse_filings_sentiment import create_nse_filings_pipeline
            from nse_live_scraper import create_nse_scraper_input

            self.logger.info("=" * 70)
            self.logger.info("NSE Live Trading Pipeline - Real-time Sentiment Analysis")
            self.logger.info("=" * 70)

            refresh_interval = 60
            static_data_path = "staticdata.csv"
            signals_output = "trading_signals.jsonl"
            backtest_output = "backtest_results.jsonl"
            metrics_output = "backtest_metrics.jsonl"

            if not os.path.exists(static_data_path):
                self.logger.info(
                    "staticdata.csv not found - using default impact scenarios"
                )

            self.logger.info(
                "Starting live NSE scraper (interval: %ss)...", refresh_interval
            )
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

            def on_new_signal(key, row, time, is_addition, **_):
                if is_addition:
                    symbol = row.get("symbol", "N/A")
                    signal = row.get("signal", "N/A")
                    explanation = (
                        row.get("explanation", "")[:50]
                        if row.get("explanation")
                        else ""
                    )
                    self.logger.info(
                        "[PIPELINE] ✓ Signal generated: %s - Signal: %s - %s...",
                        symbol,
                        signal,
                        explanation,
                    )

            def on_new_backtest(_key, row, _time, is_addition):
                if is_addition:
                    symbol = row.get("symbol", "N/A")
                    pnl = row.get("pnl", 0)
                    exit_reason = row.get("exit_reason", "N/A")
                    self.logger.info(
                        "[PIPELINE] ✓ Backtest result: %s - PnL: %.4f - Exit: %s",
                        symbol,
                        pnl,
                        exit_reason,
                    )

            def on_signal_end():
                self.logger.info("[PIPELINE] Signal stream ended")

            def on_backtest_end():
                self.logger.info("[PIPELINE] Backtest stream ended")

            pw.io.subscribe(trading_signals, on_new_signal, on_signal_end)
            pw.io.subscribe(backtest_results, on_new_backtest, on_backtest_end)

            self.logger.info("✓ Pipeline built successfully!")
            self._update_status("running")
            self.logger.info("✓ Running pipeline (will scrape continuously)...")
            pw.run(monitoring_level=pw.MonitoringLevel.NONE)
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            self.logger.info("Pipeline stopped by user")
        except Exception as exc:
            self.logger.error("Pipeline failed: %s: %s", type(exc).__name__, exc)
            import traceback

            traceback.print_exc()
        finally:
            os.chdir(original_dir)

    def _execute_news_pipeline(self, *, top_k: int) -> Dict[str, Any]:
        pipelines_dir = Path(self.server_dir) / "pipelines"
        news_dir = pipelines_dir / "news"
        sys.path.insert(0, str(pipelines_dir))

        from pipelines.news import execute_news_sentiment_pipeline  # type: ignore  # noqa: E402

        metadata = execute_news_sentiment_pipeline(
            news_dir,
            news_api_key=os.getenv("NEWS_ORG_API_KEY"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            top_k=top_k,
            logger=self.logger,
        )

        return metadata

    def _load_environment(self) -> None:
        if self._env_loaded:
            return

        server_env = Path(self.server_dir) / ".env"
        project_root = Path(self.server_dir).resolve().parents[1]
        root_env = project_root / ".env"

        if root_env.exists():
            load_dotenv(root_env, override=False)
            self.logger.debug("Loaded root .env: %s", root_env)

        if server_env.exists():
            load_dotenv(server_env, override=True)
            os.environ.setdefault("PORTFOLIO_SERVER_ENV_PATH", str(server_env))
            self.logger.debug("Loaded server .env: %s", server_env)
        else:
            raise FileNotFoundError(
                f".env file not found in portfolio-server directory: {server_env}"
            )

        self._env_loaded = True

    def _update_status(self, state: str) -> None:
        payload = {
            "state": state,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            self.status_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - filesystem issues
            self.logger.warning("Failed to write pipeline status: %s", exc)

    def _update_news_status(
        self,
        state: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "state": state,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        if metadata is not None:
            payload["metadata"] = metadata
        if error is not None:
            payload["error"] = error

        try:
            self.news_status_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - filesystem issues
            self.logger.warning("Failed to write news pipeline status: %s", exc)

    # Legacy helper retained for compatibility
    def is_pipeline_running(self) -> bool:  # pragma: no cover - compatibility
        if not self.status_file.exists():
            return False
        try:
            data = json.loads(self.status_file.read_text(encoding="utf-8"))
            return data.get("state") == "running"
        except Exception:
            return False

