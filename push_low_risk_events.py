#!/usr/bin/env python3
import json
import os
import sys
import time
import random
from datetime import datetime, timezone
from typing import Optional, Literal

# -------------------------------------------------------------------
# Minimal deps: Pydantic + shared kafka layer
# -------------------------------------------------------------------
try:
    from pydantic import BaseModel, ConfigDict
except Exception:
    sys.stderr.write("pydantic is required.\n")
    raise

try:
    from shared.py.kafka_service import (
        KafkaEventBus,
        KafkaSettings,
        PublisherAlreadyRegistered,
    )
except Exception:
    sys.stderr.write("Failed to import kafka_service.\n")
    raise

# -------------------------------------------------------------------
# Timing helpers
# -------------------------------------------------------------------
def sleep_min(max_ms=1500, min_ms=400):
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

def sleep_phase(sec):
    time.sleep(sec)

# -------------------------------------------------------------------
# Kafka bootstrap override
# -------------------------------------------------------------------
if "KAFKA_BOOTSTRAP_SERVERS_HOST" in os.environ:
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = os.environ["KAFKA_BOOTSTRAP_SERVERS_HOST"]
elif "KAFKA_BOOTSTRAP_SERVERS" not in os.environ \
     or os.environ.get("KAFKA_BOOTSTRAP_SERVERS") == "kafka:9092":
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
    print(f"\n✓ EVENT: {name}")
    print(json.dumps(payload_dict, indent=2, ensure_ascii=False))
    sleep_min()

# -------------------------------------------------------------------
# MODELS
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
# TOPICS
# -------------------------------------------------------------------
TOPICS = {
    "low_risk_logs": os.getenv("LOW_RISK_AGENT_LOGS_TOPIC", "low_risk_agent_logs"),
}

user_id = "c2163d21-40de-4c58-9758-4e11fcaf11d3"

# -------------------------------------------------------------------
# Pipeline Simulation
# -------------------------------------------------------------------
print("\n=== 🚀 Starting Low-Risk 2-Minute AI Agent Simulation ===\n")
time.sleep(1)

# -------------------------------------------------------
# INFO EVENTS
# -------------------------------------------------------
msgs = [
    "Running macro scan...",
    "PMI processing...",
    "Volatility clustering...",
    "Validating universe...",
    "Detecting inflation regime...",
    "Checking liquidity flows...",
    "Sector rotation logic running...",
]
for i in range(7):
    publish(f"info_{i}", LowRiskInfoEvent(
        user_id=user_id, type="info", content=random.choice(msgs)
    ).model_dump())

sleep_phase(3)

# -------------------------------------------------------
# INDUSTRY PHASE
# -------------------------------------------------------
industries = [
    "Metals & Mining",
    "Oil Gas & Consumable Fuels",
    "Power",
    "Financial Services",
    "Capital Goods",
    "Construction Materials",
]

publish("industry_fetching", LowRiskIndustryFetchingEvent(
    user_id=user_id, type="industry", status="fetching",
    content={"industries": industries},
).model_dump())

sleep_phase(3)

metrics = {
    "Metals & Mining": {
        "pct_above_ema200": 0.82,
        "median_rsi": 44.2,
        "industry_ret_6m": 0.143,
    }
}

publish("industry_fetched", LowRiskIndustryFetchedEvent(
    user_id=user_id, type="industry", status="fetched",
    content={"industries": industries, "metrics": metrics},
).model_dump())

# -------------------------------------------------------
# STOCK PHASE
# -------------------------------------------------------
tickers = ["IGL", "GAIL", "HINDALCO", "NATIONALUM", "PETRONET"]
for t in tickers:
    publish(f"stock_fetching_{t}", LowRiskStockFetchingEvent(
        user_id=user_id, type="stock", status="fetching", content={"ticker": t}
    ).model_dump())
    sleep_phase(1)
    publish(f"stock_fetched_{t}", LowRiskStockFetchedEvent(
        user_id=user_id, type="stock", status="fetched",
        content={
            "ticker": t,
            "price": round(random.uniform(100, 1500), 2),
            "signal": random.choice(["buy", "hold"]),
            "reasoning": f"Quick eval on {t}.",
        }
    ).model_dump())

# -------------------------------------------------------
# REPORT PHASE
# -------------------------------------------------------
for t in ["IGL", "HINDALCO", "NATIONALUM"]:
    publish(f"report_generating_{t}", LowRiskReportGeneratingEvent(
        user_id=user_id, type="report", status="generating", content={"ticker": t}
    ).model_dump())
    sleep_phase(1)
    publish(f"report_generated_{t}", LowRiskReportGeneratedEvent(
        user_id=user_id, type="report", status="generated", content={"ticker": t}
    ).model_dump())

# -------------------------------------------------------
# FINAL SUMMARY — FULL STRUCTURE, SHORTENED TEXT
# -------------------------------------------------------
summary_content = {
    "industry_list": [
        {"name": "Metals & Mining", "percentage": 28.0,
         "reasoning": "Benefits from commodity strength; strong trend and inflation protection."},
        {"name": "Oil Gas & Consumable Fuels", "percentage": 27.0,
         "reasoning": "Supports overheating regimes due to rising energy prices."},
        {"name": "Financial Services", "percentage": 22.0,
         "reasoning": "Rate cycles improve margins; healthy momentum."},
        {"name": "Capital Goods", "percentage": 13.0,
         "reasoning": "Cyclical strength; moderate technical support."},
        {"name": "Construction Materials", "percentage": 5.0,
         "reasoning": "Benefits from inflation and input cost cycles."},
        {"name": "Power", "percentage": 5.0,
         "reasoning": "Energy-linked sector with inflation upside."}
    ],

    "final_portfolio": [
        {"ticker": "NATIONALUM", "percentage": 14.0,
         "reasoning": "Strong PSU balance sheet, low-cost producer, clear growth capex."},
        {"ticker": "GMDCLTD", "percentage": 14.0,
         "reasoning": "Debt-free, government-backed miner with regulatory moat."},
        {"ticker": "IGL", "percentage": 10.8,
         "reasoning": "Monopoly gas distributor, debt-free, steady expansion."},
        {"ticker": "PETRONET", "percentage": 8.1,
         "reasoning": "Critical LNG infra, long-term contracts, stable moat."},
        {"ticker": "GSPL", "percentage": 8.1,
         "reasoning": "Gas transmission utility with strong financial safety."},
        {"ticker": "HDFCBANK", "percentage": 8.8,
         "reasoning": "High CASA moat, proven management, strong execution."},
        {"ticker": "CAMS", "percentage": 6.6,
         "reasoning": "Duopoly with high switching costs; MF industry tailwinds."},
        {"ticker": "CRISIL", "percentage": 6.6,
         "reasoning": "Brand-driven rating moat; diversified analytics growth."},
        {"ticker": "AIAENG", "percentage": 5.2,
         "reasoning": "Specialized metallurgy moat; recurring replacement demand."},
        {"ticker": "TRITURBINE", "percentage": 4.55,
         "reasoning": "Market-share leader; strong balance sheet; niche turbines."},
        {"ticker": "CARBORUN", "percentage": 3.25,
         "reasoning": "Scale-led abrasives moat; diversified demand base."},
        {"ticker": "AMBUJACEM", "percentage": 2.75,
         "reasoning": "Debt-free; aggressive expansion under new management."},
        {"ticker": "ULTRACEM", "percentage": 2.25,
         "reasoning": "Largest cement player; wide scale moat."},
        {"ticker": "POWERGRID", "percentage": 2.0,
         "reasoning": "Near-monopoly transmission utility with cost-plus stability."},
        {"ticker": "NTPC", "percentage": 1.75,
         "reasoning": "Largest power generator; stable earnings; RE expansion."},
        {"ticker": "TATAPOWER", "percentage": 1.25,
         "reasoning": "Renewables + EV infra growth; strong brand advantage."}
    ],

    "trade_list": [
        {"ticker": "NATIONALUM","amount_invested":1399840.0,
         "no_of_shares_bought":5384,"price_bought":260.0,
         "reasoning": "Strong PSU, low-cost profile.","percentage":14.0},

        {"ticker": "GMDCLTD","amount_invested":1399613.25,
         "no_of_shares_bought":2595,"price_bought":539.35,
         "reasoning": "Regulatory mining moat.","percentage":14.0},

        {"ticker": "IGL","amount_invested":1079822.3,
         "no_of_shares_bought":5414,"price_bought":199.45,
         "reasoning": "Monopoly distribution network.","percentage":10.8},

        {"ticker": "PETRONET","amount_invested":809964.0,
         "no_of_shares_bought":2980,"price_bought":271.8,
         "reasoning": "LNG infra essentiality.","percentage":8.1},

        {"ticker": "GSPL","amount_invested":809893.2,
         "no_of_shares_bought":2818,"price_bought":287.4,
         "reasoning": "Stable utility-like profile.","percentage":8.1},

        {"ticker": "HDFCBANK","amount_invested":879111.0,
         "no_of_shares_bought":873,"price_bought":1007.0,
         "reasoning": "High-return bank.","percentage":8.8},

        {"ticker": "CAMS","amount_invested":658563.0,
         "no_of_shares_bought":170,"price_bought":3873.9,
         "reasoning": "High switching costs.","percentage":6.6},

        {"ticker": "CRISIL","amount_invested":659779.45,
         "no_of_shares_bought":149,"price_bought":4428.05,
         "reasoning": "Brand-led rating moat.","percentage":6.6},

        {"ticker": "AIAENG","amount_invested":516744.2,
         "no_of_shares_bought":134,"price_bought":3856.3,
         "reasoning": "Engineering specialization.","percentage":5.2},

        {"ticker": "TRITURBINE","amount_invested":454584.9,
         "no_of_shares_bought":847,"price_bought":536.7,
         "reasoning": "Market leader turbines.","percentage":4.55},

        {"ticker": "AMBUJACEM","amount_invested":274975.0,
         "no_of_shares_bought":500,"price_bought":549.95,
         "reasoning": "Debt-light cement.","percentage":2.75},

        {"ticker": "POWERGRID","amount_invested":199995.9,
         "no_of_shares_bought":741,"price_bought":269.9,
         "reasoning": "Transmission monopoly.","percentage":2.0},

        {"ticker": "NTPC","amount_invested":174731.0,
         "no_of_shares_bought":535,"price_bought":326.6,
         "reasoning": "Stable PSU gen.","percentage":1.75},

        {"ticker": "TATAPOWER","amount_invested":124864.0,
         "no_of_shares_bought":320,"price_bought":390.2,
         "reasoning": "Renewable & EV push.","percentage":1.25}
    ],

    "summary": {
        "total_stocks": 16,
        "total_trades": 14,
        "total_invested": 9442481.2,
        "total_shares": 23460,
        "fund_allocated": 100000.0,
        "utilization_rate": 9442.48
    }
}

summary_event = LowRiskSummaryEvent(
    user_id="c2163d21-40de-4c58-9758-4e11fcaf11d3",
    type="summary",
    content=summary_content
)

sleep_phase(2)
publish("summary_final", summary_event.model_dump())

print("\n=== ✅ Low-Risk Agent Simulation Completed ===")
BUS.stop_all()
print("Kafka publishers stopped.\n")
