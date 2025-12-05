import asyncio
import random
import uuid
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from prisma import Prisma

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

# Constants for generating random data
SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK", "LICI"]
FILING_TYPES = ["quarterly_report", "annual_report", "press_release", "news_article", "analyst_rating"]
DECISIONS = ["BUY", "SELL", "HOLD"]
TRIGGERS = ["stop_loss", "take_profit", "signal_strength", "market_volatility", "news_event"]
REASONING_TEMPLATES = [
    "Strong fundamentals and positive quarterly results indicate upside potential.",
    "Technical indicators suggest overbought conditions, recommending caution.",
    "Recent news regarding regulatory changes may impact short-term performance.",
    "Sector rotation favoring defensive stocks, making this a solid hold.",
    "Breakout above resistance level confirmed by high volume."
]
FEEDBACK_TEMPLATES = [
    "Agent correctly identified the trend but entered too late.",
    "Stop loss was too tight, resulting in premature exit.",
    "Good risk management, trade played out as expected.",
    "Failed to account for broader market sentiment.",
    "Excellent execution and timing."
]

async def main():
    prisma = Prisma()
    await prisma.connect()

    print("Connected to database. Generating data...")

    logs_to_create = []
    
    # Generate 600 entries
    for i in range(600):
        # Random date within last 30 days
        days_ago = random.randint(0, 30)
        created_at = datetime.now() - timedelta(days=days_ago, hours=random.randint(0, 23), minutes=random.randint(0, 59))
        
        symbol = random.choice(SYMBOLS)
        decision = random.choice(DECISIONS)
        
        # PnL logic: mostly positive for BUY, mixed for others
        if decision == "BUY":
            realized_pnl = random.uniform(-5000, 15000)
        else:
            realized_pnl = random.uniform(-10000, 10000)
            
        # Extended metadata fields
        model_name = random.choice(["gpt-4", "gpt-3.5-turbo", "claude-3-opus", "claude-3-sonnet"])
        latency_ms = random.randint(500, 5000)
        cost_estimate = random.uniform(0.01, 0.5)
        prompt = "Analyze the following financial data for " + symbol + " and provide a trading recommendation."
        key_findings = [
            "Revenue grew by 15% YoY.",
            "Operating margins improved due to cost cutting.",
            "New product launch showing strong traction."
        ]
        risk_factors = [
            "High debt levels remain a concern.",
            "Regulatory headwinds in the sector.",
            "Increasing competition from new entrants."
        ]

        log = {
            "trade_id": str(uuid.uuid4()),
            "symbol": symbol,
            "filing_type": random.choice(FILING_TYPES),
            "trading_decision": f"Recommendation: {decision}",
            "reasoning_of_nse_agent": random.choice(REASONING_TEMPLATES),
            "loss_incurred": f"{abs(realized_pnl):.2f}",
            "feedback_on_agent_performance": random.choice(FEEDBACK_TEMPLATES),
            "realized_pnl": realized_pnl,
            "confidence_score": random.uniform(0.5, 0.99),
            "triggered_by": random.choice(TRIGGERS),
            "created_at": created_at,
            "analyzed_at": created_at,
            "metadata": json.dumps({
                "model_name": model_name,
                "latency_ms": latency_ms,
                "cost_estimate": cost_estimate,
                "prompt": prompt,
                "key_findings": key_findings,
                "risk_factors": risk_factors,
                "tokens": random.randint(100, 2000)
            })
        }
        logs_to_create.append(log)

    print(f"Generated {len(logs_to_create)} logs. Inserting into database...")

    # Batch insert (Prisma python might not support create_many nicely for all DBs, but let's try or loop)
    # Using loop for safety and simplicity with potential relation constraints (though none here really)
    count = 0
    for log in logs_to_create:
        try:
            await prisma.nseobservabilitylog.create(data=log)
            count += 1
            if count % 50 == 0:
                print(f"Inserted {count} logs...")
        except Exception as e:
            print(f"Error inserting log: {e}")

    print(f"Successfully inserted {count} logs.")
    await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())