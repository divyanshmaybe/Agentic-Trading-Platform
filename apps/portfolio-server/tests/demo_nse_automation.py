#!/usr/bin/env python3
"""
NSE Automated Trading Demo Script

This script demonstrates the complete automation flow:
1. NSE filing signal generation (simulated)
2. Signal processing and trade allocation
3. Trade execution via Pathway pipeline
4. Take-profit and stop-loss order creation
5. Order monitoring and execution

Usage:
    python tests/demo_nse_automation.py --dry-run
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

# Setup paths
REPO_ROOT = Path(__file__).resolve().parents[3]
PORTFOLIO_SERVER_ROOT = Path(__file__).resolve().parents[1]
SHARED_PY_PATH = REPO_ROOT / "shared" / "py"

for path in [str(REPO_ROOT), str(PORTFOLIO_SERVER_ROOT), str(SHARED_PY_PATH)]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
env_file = PORTFOLIO_SERVER_ROOT / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

# Import services
from db import get_db_manager
from services.pipeline_service import PipelineService
from utils.trade_execution import TradeSignal, PortfolioSnapshot


class NSEAutomationDemo:
    """Demonstrates NSE automated trading pipeline."""
    
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.db = None
        self.pipeline_service = None
        self.test_user_id = None
        self.test_portfolio_id = None
        
    async def setup(self):
        """Setup demo environment."""
        logger.info("=" * 80)
        logger.info("🚀 NSE Automated Trading Demo")
        logger.info("=" * 80)
        logger.info("")
        
        # Connect to database
        self.db = get_db_manager()
        if not self.db.is_connected():
            await self.db.connect()
        
        client = self.db.get_client()
        
        # Setup pipeline service
        self.pipeline_service = PipelineService(str(PORTFOLIO_SERVER_ROOT), logger=logger)
        
        # Find or create high-risk user
        await self._setup_test_user(client)
        
    async def _setup_test_user(self, client):
        """Setup test user with high_risk subscription."""
        logger.info("🔧 Setting up test user with high_risk subscription...")
        
        # Find user or create demo user
        user = await client.user.find_first(
            where={"email": "demo_trader@agentinvest.com"}
        )
        
        if not user:
            # Create organization first
            org = await client.organization.create(
                data={
                    "name": "Demo Trading Org",
                    "email": "demo_org@agentinvest.com",
                    "status": "active",
                }
            )
            
            # Create user with high_risk subscription
            user = await client.user.create(
                data={
                    "organization_id": org.id,
                    "email": "demo_trader@agentinvest.com",
                    "password_hash": "demo_hash",
                    "first_name": "Demo",
                    "last_name": "Trader",
                    "role": "admin",
                    "status": "active",
                    "subscriptions": ["high_risk"],  # Enable automated trading
                }
            )
            logger.info("✅ Created demo user with high_risk subscription")
        else:
            # Ensure user has high_risk subscription
            if "high_risk" not in (user.subscriptions or []):
                user = await client.user.update(
                    where={"id": user.id},
                    data={"subscriptions": ["high_risk"]},
                )
            logger.info("✅ Updated demo user with high_risk subscription")
        
        self.test_user_id = user.id
        
        # Find or create customer
        customer = await client.customer.find_first(
            where={
                "organization_id": user.organization_id,
                "user_id": user.id,
            }
        )
        
        if not customer:
            customer = await client.customer.create(
                data={
                    "organization_id": user.organization_id,
                    "user_id": user.id,
                    "customer_type": "individual",
                    "status": "active",
                }
            )
            logger.info("✅ Created demo customer")
        
        # Find or create portfolio
        portfolio = await client.portfolio.find_first(
            where={
                "user_id": user.id,
                "status": "active",
            }
        )
        
        if not portfolio:
            portfolio = await client.portfolio.create(
                data={
                    "user_id": user.id,
                    "organization_id": user.organization_id,
                    "customer_id": customer.id,
                    "portfolio_name": "High-Risk Automated Portfolio",
                    "initial_investment": Decimal("500000"),
                    "investment_amount": Decimal("500000"),
                    "available_cash": Decimal("500000"),
                    "investment_horizon_years": 5,
                    "expected_return_target": Decimal("0.15"),
                    "risk_tolerance": "high",
                    "liquidity_needs": "low",
                    "status": "active",
                    "metadata": {"cash_available": 500000},
                }
            )
            logger.info("✅ Created demo portfolio with ₹500,000 capital")
        
        self.test_portfolio_id = portfolio.id
        
        logger.info(f"   User ID: {user.id}")
        logger.info(f"   Portfolio ID: {portfolio.id}")
        logger.info(f"   Available Capital: ₹{portfolio.current_value:,.2f}")
        logger.info("")
    
    async def simulate_nse_signal(self) -> Dict[str, Any]:
        """Simulate an NSE filing signal."""
        logger.info("📊 Simulating NSE filing signal...")
        
        signal = {
            "symbol": "RELIANCE",
            "filing_time": "2025-11-12 09:15:00",
            "signal": 1,  # BUY signal
            "explanation": "Positive corporate action filing detected",
            "confidence": 0.85,  # High confidence (>0.8) → 40% allocation
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "signal_id": f"nse_demo_{datetime.utcnow().timestamp()}",
            "source": "nse_filings_pipeline",
            "metadata": {
                "filing_type": "board_meeting",
                "sentiment": "bullish",
                "demo": True,
            }
        }
        
        logger.info(f"   Symbol: {signal['symbol']}")
        logger.info(f"   Signal: {'BUY' if signal['signal'] > 0 else 'SELL'}")
        logger.info(f"   Confidence: {signal['confidence']:.1%}")
        logger.info(f"   Explanation: {signal['explanation']}")
        logger.info("")
        
        return signal
    
    async def process_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Process the signal through the automation pipeline."""
        logger.info("⚙️  Processing signal through automation pipeline...")
        
        # Use pipeline service to process the signal
        result = await self.pipeline_service._process_nse_trade_signals_async(
            signals=[signal],
            publish_kafka=not self.dry_run,
        )
        
        logger.info(f"   Processed Signals: {result['processed_signals']}")
        logger.info(f"   Trade Payloads: {result['payloads']}")
        logger.info(f"   Jobs Created: {result['jobs']}")
        logger.info(f"   Celery Tasks Dispatched: {result['dispatched']}")
        logger.info("")
        
        return result
    
    async def verify_execution_logs(self) -> List[Dict[str, Any]]:
        """Verify trade execution logs were created."""
        logger.info("🔍 Verifying trade execution logs...")
        
        client = self.db.get_client()
        
        # Fetch recent trade execution logs
        logs = await client.tradeexecutionlog.find_many(
            where={"user_id": self.test_user_id},
            order={"created_at": "desc"},
            take=5,
        )
        
        if logs:
            logger.info(f"✅ Found {len(logs)} trade execution log(s)")
            for log in logs:
                logger.info(f"   Trade ID: {log.id}")
                logger.info(f"   Symbol: {log.symbol}")
                logger.info(f"   Side: {log.side}")
                logger.info(f"   Quantity: {log.quantity}")
                logger.info(f"   Allocated Capital: ₹{log.allocated_capital:,.2f}")
                logger.info(f"   Confidence: {log.confidence:.1%}")
                logger.info(f"   Status: {log.status}")
                logger.info("")
        else:
            logger.warning("⚠️  No trade execution logs found")
        
        return [log.dict() for log in logs]
    
    async def verify_pending_orders(self) -> List[Dict[str, Any]]:
        """Verify take-profit and stop-loss orders were created."""
        logger.info("🎯 Verifying take-profit and stop-loss orders...")
        
        client = self.db.get_client()
        
        # Fetch pending TP/SL orders
        pending_orders = await client.trade.find_many(
            where={
                "portfolio_id": self.test_portfolio_id,
                "status": "pending",
                "order_type": {"in": ["take_profit", "stop_loss"]},
                "source": "auto_tp_sl",
            },
            order={"created_at": "desc"},
            take=10,
        )
        
        if pending_orders:
            logger.info(f"✅ Found {len(pending_orders)} pending TP/SL order(s)")
            for order in pending_orders:
                metadata = order.metadata or {}
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}
                
                logger.info(f"   Order ID: {order.id}")
                logger.info(f"   Type: {order.order_type.upper()}")
                logger.info(f"   Symbol: {order.symbol}")
                logger.info(f"   Side: {order.side}")
                logger.info(f"   Quantity: {order.quantity}")
                logger.info(f"   Trigger Price: ₹{order.trigger_price:.2f}")
                logger.info(f"   Parent Trade: {metadata.get('parent_trade_id', 'N/A')}")
                logger.info("")
        else:
            logger.warning("⚠️  No pending TP/SL orders found")
        
        return [order.dict() for order in pending_orders]
    
    async def show_allocation_logic(self, signal: Dict[str, Any]):
        """Demonstrate the allocation logic."""
        logger.info("💰 Allocation Logic Demonstration")
        logger.info("-" * 80)
        
        confidence = signal['confidence']
        capital = 500000  # Demo portfolio capital
        
        # Import allocation function
        from utils.trade_execution import get_allocation
        
        allocation = get_allocation(capital, confidence)
        
        logger.info(f"   Available Capital: ₹{capital:,.2f}")
        logger.info(f"   Signal Confidence: {confidence:.1%}")
        logger.info("")
        logger.info("   Allocation Tiers:")
        logger.info("   • Confidence > 80%: 40% allocation")
        logger.info("   • Confidence > 49%: 25% allocation")
        logger.info("   • Confidence ≤ 49%: 0% allocation (no trade)")
        logger.info("")
        logger.info(f"   ✅ Allocated Capital: ₹{allocation:,.2f} ({allocation/capital:.1%})")
        logger.info("")
        
        # Show expected quantity
        price = 2500  # Assumed price for RELIANCE
        quantity = int(allocation // price)
        logger.info(f"   Assumed Price: ₹{price:.2f}")
        logger.info(f"   Expected Quantity: {quantity} shares")
        logger.info("")
        
        # Show TP/SL prices
        tp_pct = 0.03  # 3%
        sl_pct = 0.01  # 1%
        
        tp_price = price * (1 + tp_pct)
        sl_price = price * (1 - sl_pct)
        
        logger.info("   Risk Management:")
        logger.info(f"   • Take Profit: ₹{tp_price:.2f} (+{tp_pct:.1%})")
        logger.info(f"   • Stop Loss: ₹{sl_price:.2f} (-{sl_pct:.1%})")
        logger.info(f"   • Expected Profit: ₹{quantity * (tp_price - price):,.2f}")
        logger.info(f"   • Maximum Loss: ₹{quantity * (price - sl_price):,.2f}")
        logger.info("")
    
    async def run(self):
        """Run the complete demo."""
        try:
            await self.setup()
            
            # Step 1: Simulate NSE signal
            signal = await self.simulate_nse_signal()
            
            # Step 2: Show allocation logic
            await self.show_allocation_logic(signal)
            
            # Step 3: Process signal through pipeline
            result = await self.process_signal(signal)
            
            # Step 4: Verify execution logs
            if result['jobs'] > 0:
                await asyncio.sleep(2)  # Wait for async processing
                logs = await self.verify_execution_logs()
                
                # Step 5: Verify TP/SL orders
                orders = await self.verify_pending_orders()
                
                # Summary
                logger.info("=" * 80)
                logger.info("📈 Demo Summary")
                logger.info("=" * 80)
                logger.info(f"✅ Signals Processed: {result['processed_signals']}")
                logger.info(f"✅ Trades Created: {len(logs)}")
                logger.info(f"✅ TP/SL Orders Created: {len(orders)}")
                logger.info("")
                
                if self.dry_run:
                    logger.info("ℹ️  Running in DRY-RUN mode")
                    logger.info("   - Trades are simulated (not sent to broker)")
                    logger.info("   - Kafka events are not published")
                    logger.info("   - Order monitoring workers need to be started separately")
                    logger.info("")
                
                logger.info("🎯 Next Steps:")
                logger.info("   1. Start Celery workers: celery -A celery_app worker --loglevel=info")
                logger.info("   2. Start Celery beat: celery -A celery_app beat --loglevel=info")
                logger.info("   3. Monitor order execution via order_monitor_worker")
                logger.info("   4. Check database for updated trade statuses")
                logger.info("")
            else:
                logger.warning("⚠️  No trades were created. Check:")
                logger.warning("   - User has 'high_risk' in subscriptions array")
                logger.warning("   - Portfolio has sufficient capital")
                logger.warning("   - Signal confidence is > 0.49")
                logger.warning("")
            
            logger.info("=" * 80)
            logger.info("✅ Demo completed successfully!")
            logger.info("=" * 80)
            
        except Exception as exc:
            logger.exception("❌ Demo failed: %s", exc)
            raise


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="NSE Automated Trading Demo")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in dry-run mode (no Kafka publishing, simulated execution)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live mode (publishes to Kafka, requires workers)",
    )
    
    args = parser.parse_args()
    
    dry_run = not args.live
    
    demo = NSEAutomationDemo(dry_run=dry_run)
    await demo.run()


if __name__ == "__main__":
    asyncio.run(main())
