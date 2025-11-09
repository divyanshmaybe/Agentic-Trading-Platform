from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

import pathway as pw

from utils.backtesting import (
    BacktestConfig,
    BacktestSummary,
    BacktestTradeResult,
    run_backtest,
    serialise_results,
)


class BacktestSignalSchema(pw.Schema):
    symbol: str
    desc: str
    filing_time: str
    signal: int
    confidence: float


class _SignalCollector:
    """Pathway subscriber that collects rows for batch backtesting."""

    def __init__(self) -> None:
        self._rows: list[Mapping[str, object]] = []

    def __call__(self, _key, row, _time, is_addition) -> None:
        if not is_addition:
            return
        self._rows.append(dict(row))

    @property
    def rows(self) -> Sequence[Mapping[str, object]]:
        return self._rows


def run_backtest_pipeline(
    signals_path: Path | str,
    *,
    output_dir: Optional[Path | str] = None,
    config: Optional[BacktestConfig] = None,
) -> dict:
    """
    Execute NSE filings backtest pipeline using Pathway for ingestion.

    Args:
        signals_path: Path to JSON Lines file containing filings/signals.
        output_dir: Optional directory to persist results and summary.
        config: Optional BacktestConfig override.

    Returns:
        Dictionary with serialised trade results and summary statistics.
    """
    signals_path = Path(signals_path)
    if not signals_path.exists():
        raise FileNotFoundError(f"Signals file not found: {signals_path}")

    table = pw.io.jsonlines.read(
        str(signals_path),
        schema=BacktestSignalSchema,
        mode="static",
    )

    collector = _SignalCollector()
    pw.io.subscribe(table, collector)
    pw.run()

    results, summary = run_backtest(collector.rows, config=config)
    payload = {
        "results": serialise_results(results),
        "summary": asdict(summary),
        "config": asdict(config or BacktestConfig()),
    }

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        results_path = output_dir / "backtest_results.jsonl"
        summary_path = output_dir / "backtest_summary.json"

        with results_path.open("w", encoding="utf-8") as fh:
            for row in payload["results"]:
                fh.write(json.dumps(row))
                fh.write("\n")

        with summary_path.open("w", encoding="utf-8") as fh:
            json.dump(payload["summary"], fh, indent=2)

    return payload


__all__ = [
    "BacktestConfig",
    "BacktestSummary",
    "BacktestTradeResult",
    "run_backtest_pipeline",
]

