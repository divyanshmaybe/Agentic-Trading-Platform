#!/usr/bin/env python3
import json
import os
import sys
import time
import random
from datetime import datetime, timezone
from typing import Optional, Literal

# -------------------------------------------------------------------
# Minimal deps: Only pydantic + your shared kafka layer
# -------------------------------------------------------------------
try:
    from pydantic import BaseModel, ConfigDict
except Exception:
    sys.stderr.write("pydantic is required to run this script.\n")
    raise

try:
    from shared.py.kafka_service import (
        KafkaEventBus,
        KafkaSettings,
        PublisherAlreadyRegistered,
    )
except Exception:
    sys.stderr.write("Failed to import shared kafka_service.\n")
    raise

# -------------------------------------------------------------------
# Compressed timing model
# Total runtime \u2248 120 seconds
# -------------------------------------------------------------------
def sleep_min(max_ms=1500, min_ms=400):
    """Short humanlike delay."""
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

def sleep_phase(phase_seconds):
    """
    Scaled delay: 
    Simulate hours \u2192 seconds.
    Example: passing 10 means ~10 seconds.
    """
    time.sleep(phase_seconds)


# -------------------------------------------------------------------
# Kafka bootstrap override (same as before)
# -------------------------------------------------------------------
if "KAFKA_BOOTSTRAP_SERVERS_HOST" in os.environ:
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = os.environ["KAFKA_BOOTSTRAP_SERVERS_HOST"]
elif "KAFKA_BOOTSTRAP_SERVERS" not in os.environ or os.environ.get("KAFKA_BOOTSTRAP_SERVERS") == "kafka:9092":
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "localhost:9092"

SETTINGS = KafkaSettings()
BUS = KafkaEventBus(SETTINGS)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def ensure_publisher(name, topic):
    try:
        return BUS.register_publisher(
            name,
            topic=topic,
            value_model=None,
            default_headers={"source": "low_risk_pipeline"},
            auto_start=True,
        )
    except PublisherAlreadyRegistered:
        pub = BUS.get_publisher(name)
        pub.start()
        return pub

def publish(name, payload_dict):
    pub = ensure_publisher(name, TOPICS["low_risk_logs"])
    key = payload_dict.get("user_id")

    pub.publish(payload_dict, key=key, block=True)
    print(f"\n\u2713 EVENT: {name}")
    print(json.dumps(payload_dict, indent=2, ensure_ascii=False))
    sleep_min()


def utc_ts():
    return datetime.now(timezone.utc).isoformat()


# -------------------------------------------------------------------
# MODELS (same structure you approved earlier)
# -------------------------------------------------------------------
class LowRiskBase(BaseModel):
    user_id: str
    type: str
    status: Optional[str] = None
    content: Optional[dict] = None
    model_config = ConfigDict(extra="allow")

class LowRiskInfoEvent(LowRiskBase):
    type: Literal["info"]
    content: str

class LowRiskIndustryFetchingEvent(LowRiskBase):
    type: Literal["industry"]
    status: Literal["fetching"]
    content: dict

class LowRiskIndustryFetchedEvent(LowRiskBase):
    type: Literal["industry"]
    status: Literal["fetched"]
    content: dict

class LowRiskStockFetchingEvent(LowRiskBase):
    type: Literal["stock"]
    status: Literal["fetching"]
    content: dict

class LowRiskStockFetchedEvent(LowRiskBase):
    type: Literal["stock"]
    status: Literal["fetched"]
    content: dict

class LowRiskReportGeneratingEvent(LowRiskBase):
    type: Literal["report"]
    status: Literal["generating"]
    content: dict

class LowRiskReportGeneratedEvent(LowRiskBase):
    type: Literal["report"]
    status: Literal["generated"]
    content: dict

class LowRiskSummaryEvent(LowRiskBase):
    type: Literal["summary"]
    content: dict


# -------------------------------------------------------------------
# TOPICS + USER
# -------------------------------------------------------------------
TOPICS = {
    "low_risk_logs": os.getenv("LOW_RISK_AGENT_LOGS_TOPIC", "low_risk_agent_logs"),
}

user_id = "86d157fb-f02b-4d8e-8477-c32bc834bd83"

# -------------------------------------------------------------------
# PIPELINE SIMULATION
# Total runtime target: ~120 seconds
# -------------------------------------------------------------------
print("\n=== \U0001f680 Starting Low-Risk 2-Minute AI Agent Simulation ===\n")
time.sleep(1)

# -------------------------------------------------------
# 1) INFO PHASE \u2014 simulate hours of thinking (20\u201330 sec)
# -------------------------------------------------------
info_messages = [
    "Starting macroeconomic scan...",
    "PMI analysis underway...",
    "Fetching volatility clusters...",
    "Validating investment universe...",
    "Inflation regime detection active...",
    "Inspecting global liquidity trends...",
    "Running sector rotation heuristics...",
    "Agent thinking deeply...",
    "Evaluating risk floors...",
]

num_info = random.randint(7, 10)
for i in range(num_info):
    evt = LowRiskInfoEvent(
        user_id=user_id,
        type="info",
        content=random.choice(info_messages),
    )
    publish(f"info_{i}", evt.model_dump())

sleep_phase(4)  # compressed hours


# -------------------------------------------------------
# 2) INDUSTRY FETCHING \u2192 FETCHED (~15 sec)
# -------------------------------------------------------
industries = [
    "Metals & Mining",
    "Oil Gas & Consumable Fuels",
    "Power",
    "Financial Services",
    "Capital Goods",
    "Construction Materials",
]

publish(
    "industry_fetching",
    LowRiskIndustryFetchingEvent(
        user_id=user_id,
        type="industry",
        status="fetching",
        content={"industries": industries},
    ).model_dump(),
)

sleep_phase(5)  # compressed 8\u201312 hours thinking

metrics = {
    "Metals & Mining": {
        "pct_above_ema200": 0.82,
        "median_rsi": 44.2,
        "industry_ret_6m": 0.143,
    },
    "Financial Services": {
        "pct_above_ema200": 0.70,
        "median_rsi": 48.0,
        "industry_ret_6m": 0.077,
    },
}

publish(
    "industry_fetched",
    LowRiskIndustryFetchedEvent(
        user_id=user_id,
        type="industry",
        status="fetched",
        content={"industries": industries, "metrics": metrics},
    ).model_dump(),
)


# -------------------------------------------------------
# 3) STOCK FETCHING \u2192 FETCHED (20\u201330 sec)
# -------------------------------------------------------
tickers = ["IGL", "GAIL", "HINDALCO", "NATIONALUM", "PETRONET"]

for t in tickers:
    publish(
        f"stock_fetching_{t}",
        LowRiskStockFetchingEvent(
            user_id=user_id,
            type="stock",
            status="fetching",
            content={"ticker": t},
        ).model_dump(),
    )

    sleep_phase(2)

    publish(
        f"stock_fetched_{t}",
        LowRiskStockFetchedEvent(
            user_id=user_id,
            type="stock",
            status="fetched",
            content={
                "ticker": t,
                "price": round(random.uniform(100, 1500), 2),
                "signal": random.choice(["buy", "hold"]),
                "reasoning": f"Simulated evaluation for {t}",
            },
        ).model_dump(),
    )


# -------------------------------------------------------
# 4) REPORT GEN (10 sec)
# -------------------------------------------------------
for t in ["IGL", "HINDALCO", "NATIONALUM"]:
    publish(
        f"report_generating_{t}",
        LowRiskReportGeneratingEvent(
            user_id=user_id,
            type="report",
            status="generating",
            content={"ticker": t},
        ).model_dump(),
    )

    sleep_phase(2)

    publish(
        f"report_generated_{t}",
        LowRiskReportGeneratedEvent(
            user_id=user_id,
            type="report",
            status="generated",
            content={"ticker": t},
        ).model_dump(),
    )


# -------------------------------------------------------
# 5) FINAL SUMMARY (last event)
# -------------------------------------------------------
# Generate trade_list based on final_portfolio
final_portfolio_list = [
    {"ticker": "NATIONALUM", "percentage": 14.0, "reasoning": "Best balance of durability + moat."},
    {"ticker": "IGL", "percentage": 10.8, "reasoning": "High conviction long-term pick."},
]

# Create trade_list with calculated values
trade_list = []
total_invested = 0.0
total_shares = 0

for stock in final_portfolio_list:
    # Simulate trade calculations
    amount_invested = round(random.uniform(100000, 1500000), 2)
    price_bought = round(random.uniform(100, 5000), 2)
    no_of_shares_bought = int(amount_invested / price_bought)
    
    trade_list.append({
        "ticker": stock["ticker"],
        "amount_invested": amount_invested,
        "no_of_shares_bought": no_of_shares_bought,
        "price_bought": price_bought,
        "reasoning": stock["reasoning"],
        "percentage": stock["percentage"],
    })
    
    total_invested += amount_invested
    total_shares += no_of_shares_bought

fund_allocated = 100000.0
utilization_rate = (total_invested / fund_allocated) * 100 if fund_allocated > 0 else 0.0

summary_event = LowRiskSummaryEvent(
    user_id=user_id,
    type="summary",
    content={
        "industry_list": [
            {"name": "Metals & Mining", "percentage": 28.0, "reasoning": "Strong inflation hedge."},
            {"name": "Financial Services", "percentage": 22.0, "reasoning": "Benefit from rate cycles."},
        ],
        "final_portfolio": final_portfolio_list,
        "trade_list": trade_list,
        "summary": {
            "total_stocks": len(final_portfolio_list),
            "total_trades": len(trade_list),
            "total_invested": round(total_invested, 2),
            "total_shares": total_shares,
            "fund_allocated": fund_allocated,
            "utilization_rate": round(utilization_rate, 2),
        }
    }
)

sleep_phase(3)
publish("summary_final", summary_event.model_dump())


# -------------------------------------------------------
# END
# -------------------------------------------------------
print("\n=== \u2705 Low-Risk 2-Minute Agent Simulation Completed ===")
BUS.stop_all()
print("Kafka publishers stopped.\n")
