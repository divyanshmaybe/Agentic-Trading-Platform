"""Single source of truth for the Company Filings Driven Trader strategy."""

from __future__ import annotations

import os


MAX_CONCURRENT_TRADES = int(os.getenv("CFDT_MAX_CONCURRENT_TRADES", "3"))
MAX_POSITION_FRACTION = float(os.getenv("CFDT_MAX_POSITION_FRACTION", "0.33"))
TAKE_PROFIT_PCT = float(os.getenv("CFDT_TAKE_PROFIT_PCT", "0.025"))
STOP_LOSS_PCT = float(os.getenv("CFDT_STOP_LOSS_PCT", "0.01"))
HOLDING_WINDOW_MINUTES = int(os.getenv("CFDT_HOLDING_WINDOW_MINUTES", "30"))

# Virtual execution remains mandatory until a separate live-broker rollout.
PAPER_TRADING_ONLY = os.getenv("CFDT_PAPER_TRADING_ONLY", "true").lower() in {
    "1",
    "true",
    "yes",
}
