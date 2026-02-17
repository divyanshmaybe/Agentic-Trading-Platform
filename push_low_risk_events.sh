#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"

python <<'PY'
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Literal
import random

# -------------------------------------------------------------------
# Kafka bootstrap server override
# -------------------------------------------------------------------
if "KAFKA_BOOTSTRAP_SERVERS_HOST" in os.environ:
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = os.environ["KAFKA_BOOTSTRAP_SERVERS_HOST"]
elif "KAFKA_BOOTSTRAP_SERVERS" not in os.environ or os.environ.get("KAFKA_BOOTSTRAP_SERVERS") == "kafka:9092":
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "localhost:9092"

# -------------------------------------------------------------------
# Imports
# -------------------------------------------------------------------
try:
    from pydantic import BaseModel, ConfigDict, Field
except Exception as exc:
    sys.stderr.write("pydantic is required to run this script.\n")
    raise

try:
    from shared.py.kafka_service import (
        KafkaEventBus,
        KafkaPublisher,
        KafkaSettings,
        PublisherAlreadyRegistered,
    )
except Exception as exc:
    sys.stderr.write(
        "Failed to import shared Kafka service. Ensure PYTHONPATH includes the repo root.\n"
    )
    raise

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def utc_ts():
    return datetime.now(timezone.utc).isoformat()

def ensure_pub(name, topic):
    try:
        return BUS.register_publisher(
            name,
            topic=topic,
            value_model=None,  # low_risk DOES NOT use model validation in publisher
            default_headers={"source": "low_risk_pipeline"},
            auto_start=True,
        )
    except PublisherAlreadyRegistered:
        p = BUS.get_publisher(name)
        p.start()
        return p

def publish_raw(publisher_name, payload_dict):
    pub = ensure_pub(
        publisher_name,
        TOPICS["low_risk_logs"],
    )
    key = payload_dict.get("user_id") or ""
    try:
        pub.publish(payload_dict, key=key, block=True, timeout=5.0)
    except TypeError:
        # fallback if signature differs
        pub.publish(payload_dict, key=key, block=True)
    print(f"\n\u2713 Published {publisher_name}:")
    print(json.dumps(payload_dict, indent=2, ensure_ascii=False))
    # small pause to simulate streaming
    time.sleep(0.25)


# -------------------------------------------------------------------
# MODELS FOR ALL LOW-RISK EVENTS (used for constructing valid payloads)
# -------------------------------------------------------------------
class LowRiskBase(BaseModel):
    user_id: str
    type: str
    status: Optional[str] = None
    content: Optional[dict] = None
    model_config = ConfigDict(extra="allow")


class LowRiskInfoEvent(LowRiskBase):
    type: Literal["info"]
    message: str


class LowRiskIndustryFetchingEvent(LowRiskBase):
    type: Literal["industry"]
    status: Literal["fetching"]
    content: dict  # { industries: [...] }


class LowRiskIndustryFetchedEvent(LowRiskBase):
    type: Literal["industry"]
    status: Literal["fetched"]
    content: dict  # { industries:[...], metrics:{...} }


class LowRiskStockFetchingEvent(LowRiskBase):
    type: Literal["stock"]
    status: Literal["fetching"]
    content: dict  # { content: "CASTROL" }


class LowRiskStockFetchedEvent(LowRiskBase):
    type: Literal["stock"]
    status: Literal["fetched"]
    content: dict  # MUST include whatever fields pipeline would produce


class LowRiskReportGeneratingEvent(LowRiskBase):
    type: Literal["report"]
    status: Literal["generating"]
    content: dict  # { ticker: "XYZ" }


class LowRiskReportGeneratedEvent(LowRiskBase):
    type: Literal["report"]
    status: Literal["generated"]
    content: dict  # { ticker: "XYZ" }


class LowRiskSummaryEvent(LowRiskBase):
    type: Literal["summary"]
    content: dict  # large object


# -------------------------------------------------------------------
# Kafka Setup
# -------------------------------------------------------------------
TOPICS = {
    "low_risk_logs": os.getenv("LOW_RISK_AGENT_LOGS_TOPIC", "low_risk_agent_logs"),
}
SETTINGS = KafkaSettings()
BUS = KafkaEventBus(SETTINGS)
time.sleep(0.5)

# -------------------------------------------------------------------
# USER ID
# -------------------------------------------------------------------
user_id = "86d157fb-f02b-4d8e-8477-c32bc834bd83"

# -------------------------------------------------------------------
# 1) PUSH 5\u201310 INFO EVENTS
# -------------------------------------------------------------------
info_messages = [
    "Starting low-risk pipeline...",
    "\u2713 PMI value: 57.4",
    "Fetching global macro indicators...",
    "Validating user portfolio state...",
    "Running volatility filters...",
    "Computing inflation regime...",
    "Computing sector EMA signals...",
    "Preparing industry selection...",
    "CPU load normal, pipeline stable",
    "Proceeding to industry scanning phase"
]

for i in range(random.randint(5, 10)):
    msg = random.choice(info_messages)
    evt = LowRiskInfoEvent(
        user_id=user_id,
        type="info",
        message=msg
    )
    publish_raw(f"info_event_{i}", evt.model_dump())

# -------------------------------------------------------------------
# 2) INDUSTRY FETCHING \u2192 FETCHED
# -------------------------------------------------------------------
industries_fetching = [
    "Oil Gas & Consumable Fuels",
    "Metals & Mining",
    "Power",
    "Financial Services",
    "Capital Goods",
    "Construction"
]

evt_fetching = LowRiskIndustryFetchingEvent(
    user_id=user_id,
    type="industry",
    status="fetching",
    content={"industries": industries_fetching}
)
publish_raw("industry_fetching", evt_fetching.model_dump())

# Fetched snapshot (simplified metrics)
sample_metrics = {
    "Metals & Mining": {
        "pct_above_ema50": 0.5294117647058824,
        "pct_above_ema200": 0.8235294117647058,
        "median_rsi": 44.23987375065756,
        "pct_rsi_overbought": 0.0,
        "pct_rsi_oversold": 0.11764705882352941,
        "industry_ret_6m": 0.14371136509370958,
        "benchmark_ret_6m": None,
    },
    "Financial Services": {
        "pct_above_ema50": 0.5789473684210527,
        "pct_above_ema200": 0.7052631578947368,
        "median_rsi": 48.01473598035202,
        "pct_rsi_overbought": 0.08421052631578947,
        "pct_rsi_oversold": 0.11578947368421053,
        "industry_ret_6m": 0.07712797173055844,
        "benchmark_ret_6m": None,
    },
}

evt_fetched = LowRiskIndustryFetchedEvent(
    user_id=user_id,
    type="industry",
    status="fetched",
    content={
        "industries": industries_fetching,
        "metrics": sample_metrics
    }
)
publish_raw("industry_fetched", evt_fetched.model_dump())

# -------------------------------------------------------------------
# 3) STOCK FETCHING \u2192 FETCHED (5\u201310 random stocks), ensure same stock has fetching and fetched
# -------------------------------------------------------------------
tickers = ["IGL", "GAIL", "CASTROL", "GRAVITA", "HINDZINC", "HINDALCO", "NATIONALUM"]

for i in range(random.randint(5, 10)):
    t = random.choice(tickers)

    evt_fetching = LowRiskStockFetchingEvent(
        user_id=user_id,
        type="stock",
        status="fetching",
        content={"content": t}
    )
    publish_raw(f"stock_fetching_{t}_{i}", evt_fetching.model_dump())

    evt_fetched = LowRiskStockFetchedEvent(
        user_id=user_id,
        type="stock",
        status="fetched",
        content={
            "ticker": t,
            "price": round(random.uniform(50, 1200), 2),
            "signal": random.choice(["buy", "hold", "sell"]),
            "rsi": round(random.uniform(20, 80), 2),
            "notes": f"Simulated metrics for {t}"
        }
    )
    publish_raw(f"stock_fetched_{t}_{i}", evt_fetched.model_dump())

# -------------------------------------------------------------------
# 4) REPORT GENERATING \u2192 GENERATED
# -------------------------------------------------------------------
rpt_tickers = ["IGL", "GRAVITA", "HINDZINC", "HINDALCO"]

for t in rpt_tickers:
    evt_gen = LowRiskReportGeneratingEvent(
        user_id=user_id,
        type="report",
        status="generating",
        content={"ticker": t}
    )
    publish_raw(f"report_generating_{t}", evt_gen.model_dump())

    evt_done = LowRiskReportGeneratedEvent(
        user_id=user_id,
        type="report",
        status="generated",
        content={"ticker": t}
    )
    publish_raw(f"report_generated_{t}", evt_done.model_dump())

# -------------------------------------------------------------------
# 5) FINAL SUMMARY (LAST EVENT) \u2014 full reasoning included as requested
# -------------------------------------------------------------------
summary_content = {
    "industry_list": [
        {
            "name": "Metals & Mining",
            "percentage": 28.0,
            "reasoning": "In an overheating regime, Metals & Mining directly benefits from rising commodity prices. The industry shows strong 6-month returns (14.37%) and a high percentage of stocks above their 200-day EMA (82.35%), indicating a robust bullish trend. This sector acts as a strong inflation hedge."
        },
        {
            "name": "Oil Gas & Consumable Fuels",
            "percentage": 27.0,
            "reasoning": "This sector is a primary beneficiary of rising energy prices, which is a key characteristic of an overheating economy. While its 6-month return is modest (0.66%), the overall economic environment supports its growth as crude oil prices are a strong signal of overheating conditions."
        },
        {
            "name": "Financial Services",
            "percentage": 22.0,
            "reasoning": "Financial Services can perform well as interest rates climb during an overheating phase, widening profit margins. The industry's strong 6-month return (7.71%) and a high percentage of stocks above their 200-day EMA (70.52%) indicate a healthy and upward trend, making it an attractive investment."
        },
        {
            "name": "Capital Goods",
            "percentage": 13.0,
            "reasoning": "Capital Goods firms are often tied to government budgets and strategic spending, which can be attractive during periods of strong growth. While its 6-month return is slightly negative (-2.20%), a decent percentage of stocks are above their 200-day EMA (45.31%), indicating underlying strength in a cyclical context."
        },
        {
            "name": "Construction Materials",
            "percentage": 5.0,
            "reasoning": "As a component of the broader materials sector, Construction Materials benefits from rising input costs and inflation. It shows a positive 6-month return (2.60%) and a moderate percentage of stocks above their 200-day EMA (30%), making it a suitable, albeit smaller, allocation for inflation hedging."
        },
        {
            "name": "Power",
            "percentage": 5.0,
            "reasoning": "The Power sector generally outperforms as energy prices climb, providing an inflation hedge. Although its recent 6-month return is negative (-4.41%), its fundamental alignment with rising energy costs in an overheating regime warrants a modest allocation to capture potential upside."
        }
    ],
    "final_portfolio": [
        {
            "ticker": "NATIONALUM",
            "percentage": 14.0,
            "reasoning": "NALCO is an ideal fit for the strategy, excelling across all three analytical pillars. For Safety (Graham), it is a Navratna PSU with a strong balance sheet, low debt, and a history of consistent dividend payments, ensuring a margin of safety. For Structural Advantage (Dorsey), it possesses a wide and durable economic moat as the world's lowest-cost producer of bauxite and alumina, a powerful and sustainable Cost Advantage. For Growth (Fisher), management has demonstrated a clear long-term outlook with a \u20b930,000 crore capex plan for expansion and a strong commitment to R&D, evident from its increased spending and patent filings. This ensures future growth is not just speculative but planned and funded."
        },
        {
            "ticker": "GMDCLTD",
            "percentage": 14.0,
            "reasoning": "GMDCLTD aligns perfectly with the core tenets of safety, structure, and growth. Its Safety profile (Graham) is exceptionally strong; as a state-owned enterprise, it is nearly debt-free and provides healthy dividends, ensuring protection of principal. Its Economic Moat (Dorsey) is a formidable combination of Intangible Asset (regulatory advantage) and Cost Advantage, stemming from its exclusive government mandate to mine minerals across Gujarat, creating a high barrier to entry. Finally, it satisfies the Growth criteria (Fisher) through a clear and determined management strategy to diversify from its core lignite business into high-demand critical minerals like Rare Earth Elements, positioning the company for long-term, sustainable growth."
        },
        {
            "ticker": "IGL",
            "percentage": 10.8,
            "reasoning": "This is the highest conviction selection as it aligns with all three pillars of the investment strategy. For Quantitative Safety (Graham), it is virtually debt-free, providing a strong margin of safety against financial distress. For Structural Analysis (Dorsey), it possesses a wide economic moat through its regulated monopoly in the key Delhi NCR region, creating high barriers to entry. For Qualitative Analysis (Fisher), management shows a long-term outlook by actively expanding its core network while prudently diversifying into renewables, and has maintained a clean record of integrity."
        },
        {
            "ticker": "PETRONET",
            "percentage": 8.1,
            "reasoning": "Petronet LNG strongly aligns with the Structural Analysis (Dorsey) pillar, possessing a wide and durable economic moat as its terminals are critical national infrastructure for energy security, making them nearly impossible to replicate. It passes the Quantitative Safety (Graham) test due to its low debt-to-equity ratio. While recent profit growth has been weak and there are minor regulatory risks, its long-term contracts (e.g., QatarEnergy until 2048) and strategic expansion plans align with the Qualitative (Fisher) focus on a long-range outlook and market potential as India's gas demand grows."
        },
        {
            "ticker": "GSPL",
            "percentage": 8.1,
            "reasoning": "Gujarat State Petronet fits the portfolio as a defensively-positioned company that excels on the Quantitative Safety (Graham) pillar, being debt-free with a history of dividends. Its business of transmitting natural gas via pipelines in a key industrial state gives it a strong Structural Moat (Dorsey) akin to a utility, based on a cost and scale advantage. While it shares the negative of weak sales growth with other picks, its financial prudence and vital role in Gujarat's energy infrastructure make it a solid investment that provides a margin of safety through its robust balance sheet, fulfilling a core tenet of the strategy."
        },
        {
            "ticker": "HDFCBANK",
            "percentage": 8.8,
            "reasoning": "Selection is based on a synthesis of the Graham, Dorsey, and Fisher methodologies. HDFC Bank exhibits a wide economic moat (Dorsey) derived from significant cost advantages due to its large, low-cost CASA deposit base and a powerful intangible asset in its brand, which is synonymous with trust and reliability. This allows for sustained high returns on capital. From a qualitative perspective (Fisher), the bank has a long track record of excellent management, prudent risk management, and a clear strategy for growth through digital innovation and market expansion, as evidenced by the recent merger with HDFC Ltd. While inherent banking risks exist, its consistent growth, market leadership, and strong execution provide a qualitative margin of safety (Graham), justifying its position as a core long-term holding."
        },
        {
            "ticker": "CAMS",
            "percentage": 6.6,
            "reasoning": "CAMS aligns with the strategy as a business with a near-impenetrable economic moat (Dorsey). The moat is built on extremely high switching costs for its asset management clients and a duopolistic market structure, creating a durable competitive advantage. Qualitatively (Fisher), the company has a long runway for growth tied to the under-penetrated Indian mutual fund industry and is proactively diversifying into new areas like AIFs and insurance repositories, showcasing management's long-range outlook. From a safety perspective (Graham), the company's strong balance sheet with zero debt provides a significant buffer against unforeseen risks. While valuation is a concern, the sheer quality and durability of the business model make it a compelling investment as a critical piece of India's financial market infrastructure."
        },
        {
            "ticker": "CRISIL",
            "percentage": 6.6,
            "reasoning": "CRISIL is selected for its powerful and durable economic moat (Dorsey), which stems from its intangible assets\u2014a globally recognized brand synonymous with integrity and analytical rigor\u2014and regulatory barriers to entry in the credit rating industry. This allows for pricing power and sustained profitability. The company's management (Fisher) has demonstrated a forward-looking strategy by diversifying geographically and expanding its high-growth Research and Analytics segment, reducing dependence on the cyclical ratings business. Its majority ownership by S&P Global ensures high standards of governance and integrity. Financially (Graham), the company maintains a healthy profile with low debt. CRISIL represents an investment in a high-quality, knowledge-based enterprise with a global footprint and strong structural advantages."
        },
        {
            "ticker": "AIAENG",
            "percentage": 5.2,
            "reasoning": "AIA Engineering perfectly fits the investment framework. It possesses a wide and durable 'Economic Moat' as per Pat Dorsey's principles, rooted in intangible assets (specialized metallurgy) and high switching costs for its global mining clients who prioritize reliability over cost. This leads to a dominant market position and pricing power. From a Graham perspective, it has a strong balance sheet and a recurring revenue model from replacement parts, providing a 'Margin of Safety'. Qualitatively, its capacity expansion and entry into new markets like Chile align with Philip Fisher's criteria for a company with a long runway for growth and a determined management."
        },
        {
            "ticker": "TRITURBINE",
            "percentage": 4.55,
            "reasoning": "This selection is a prime example of applying Graham's 'Quantitative Safety' filter first. The company is virtually debt-free with strong cash reserves, ensuring safety of principal. Its 'Economic Moat' is evident from its >60% market share in its core segment, built on deep engineering expertise (Intangible Asset) and a robust aftermarket service network creating 'Switching Costs'. It strongly aligns with Fisher's growth principles through its strategic focus on the high-margin 30-100 MW turbine segment and innovative forays into new-age applications like energy storage, demonstrating a long-range outlook for profitable growth."
        },
        {
            "ticker": "CARBORUN",
            "percentage": 3.25,
            "reasoning": "Carborundum Universal, part of the well-governed Murugappa Group, meets the qualitative 'Management Integrity' test from Fisher's checklist. It has a strong 'Economic Moat' derived from its dominant market share and scale in the abrasives and industrial ceramics sector, providing a significant cost advantage. This market leadership and consistent growth satisfy the quantitative requirement for earnings stability. The company's diversified business across multiple industrial sectors provides resilience, and its position as a critical consumable supplier creates a recurring demand base, offering a solid foundation for long-term compounding."
        },
        {
            "ticker": "AMBUJACEM",
            "percentage": 2.75,
            "reasoning": "This selection scores highest on the Quantitative Safety principle from the strategy handbook due to its 'virtually debt-free' balance sheet, providing a significant Margin of Safety. Under its new ownership, the company has a clear and aggressive growth strategy through acquisitions (Penna, Orient Cement) to increase market share, satisfying Fisher's 'Management Determination' criterion. While it has a history of regulatory issues (CCI fines for cartelisation), these pre-date the current management. The strong financial position provides a buffer against industry cyclicality and supports its growth ambitions, making it a compelling investment based on the triangulation of safety, a clear growth path, and a solid brand moat."
        }
    ],
    "trade_list": [
        {
            "ticker": "NATIONALUM",
            "amount_invested": 1399840.0,
            "no_of_shares_bought": 5384,
            "price_bought": 260.0,
            "reasoning": "NALCO is an ideal fit for the strategy, excelling across all three analytical pillars. For Safety (Graham), it is a Navratna PSU with a strong balance sheet, low debt, and a history of consistent dividend payments, ensuring a margin of safety. For Structural Advantage (Dorsey), it possesses a wide and durable economic moat as the world's lowest-cost producer of bauxite and alumina, a powerful and sustainable Cost Advantage. For Growth (Fisher), management has demonstrated a clear long-term outlook with a \u20b930,000 crore capex plan for expansion and a strong commitment to R&D, evident from its increased spending and patent filings. This ensures future growth is not just speculative but planned and funded.",
            "percentage": 14.0
        },
        {
            "ticker": "GMDCLTD",
            "amount_invested": 1399613.25,
            "no_of_shares_bought": 2595,
            "price_bought": 539.35,
            "reasoning": "GMDCLTD aligns perfectly with the core tenets of safety, structure, and growth. Its Safety profile (Graham) is exceptionally strong; as a state-owned enterprise, it is nearly debt-free and provides healthy dividends, ensuring protection of principal. Its Economic Moat (Dorsey) is a formidable combination of Intangible Asset (regulatory advantage) and Cost Advantage, stemming from its exclusive government mandate to mine minerals across Gujarat, creating a high barrier to entry. Finally, it satisfies the Growth criteria (Fisher) through a clear and determined management strategy to diversify from its core lignite business into high-demand critical minerals like Rare Earth Elements, positioning the company for long-term, sustainable growth.",
            "percentage": 14.0
        },
        {
            "ticker": "IGL",
            "amount_invested": 1079822.3,
            "no_of_shares_bought": 5414,
            "price_bought": 199.45,
            "reasoning": "This is the highest conviction selection as it aligns with all three pillars of the investment strategy. For Quantitative Safety (Graham), it is virtually debt-free, providing a strong margin of safety against financial distress. For Structural Analysis (Dorsey), it possesses a wide economic moat through its regulated monopoly in the key Delhi NCR region, creating high barriers to entry. For Qualitative Analysis (Fisher), management shows a long-term outlook by actively expanding its core network while prudently diversifying into renewables, and has maintained a clean record of integrity.",
            "percentage": 10.8
        },
        {
            "ticker": "PETRONET",
            "amount_invested": 809964.0,
            "no_of_shares_bought": 2980,
            "price_bought": 271.8,
            "reasoning": "Petronet LNG strongly aligns with the Structural Analysis (Dorsey) pillar, possessing a wide and durable economic moat as its terminals are critical national infrastructure for energy security, making them nearly impossible to replicate. It passes the Quantitative Safety (Graham) test due to its low debt-to-equity ratio. While recent profit growth has been weak and there are minor regulatory risks, its long-term contracts (e.g., QatarEnergy until 2048) and strategic expansion plans align with the Qualitative (Fisher) focus on a long-range outlook and market potential as India's gas demand grows.",
            "percentage": 8.1
        }
    ],
    "summary": {
        "total_stocks": 16,
        "total_trades": 14,
        "total_invested": 9442481.200000001,
        "total_shares": 23460,
        "fund_allocated": 100000.0,
        "utilization_rate": 9442.481200000002
    }
}

summary_event = LowRiskSummaryEvent(
    user_id=user_id,
    type="summary",
    content=summary_content
)

publish_raw("summary_final", summary_event.model_dump())

print("\n\u2713 All low-risk events published in logical order.")
BUS.stop_all()
print("Kafka publishers stopped.")

PY
