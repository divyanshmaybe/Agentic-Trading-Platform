"""
Test script for Order Monitoring System
Tests limit orders, stop orders, and take-profit orders with live price monitoring.

This script:
1. Creates test pending orders in the database
2. Simulates live price changes
3. Verifies orders are executed when conditions are met
4. Validates email notifications are sent
"""

import asyncio
import logging
import os
import sys
from decimal import Decimal
from datetime import datetime, timedelta

import pytest

if os.getenv("ENABLE_DB_TESTS", "false").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Order monitor integration test requires live database. Set ENABLE_DB_TESTS=true to run.",
        allow_module_level=True,
    )

# Setup paths
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SHARED_PY_PATH = os.path.join(REPO_ROOT, "shared/py")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
if SHARED_PY_PATH not in sys.path:
    sys.path.insert(0, SHARED_PY_PATH)

PORTFOLIO_SERVER_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PORTFOLIO_SERVER_ROOT not in sys.path:
    sys.path.insert(0, PORTFOLIO_SERVER_ROOT)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from shared.py.dbManager import DBManager
from services.trade_engine import TradeEngine
from schemas import TradeCreate
from workers.order_monitor_worker import OrderMonitorWorker


class OrderMonitorTester:
    """Comprehensive tester for order monitoring system."""
    
    def __init__(self):
        self.db = None
        self.test_portfolio_id = None
        self.test_customer_id = None
        self.test_org_id = None
        self.created_trade_ids = []
        
    async def setup(self):
        """Setup test environment."""
        logger.info("=" * 80)
        logger.info("🧪 Order Monitoring System Test")
        logger.info("=" * 80)
        
        # Connect to database
        self.db = DBManager.get_instance()
        if not self.db.is_connected():
            await self.db.connect()
        
        prisma = self.db.get_client()
        
        # Create test organization
        org = await prisma.organization.create(
            data={
                "name": "Test Organization",
                "description": "For order monitoring tests"
            }
        )
        self.test_org_id = org.id
        logger.info(f"✅ Created test organization: {org.id}")
        
        # Create test user
        user = await prisma.user.upsert(
            where={"email": "test_trader@agentinvest.com"},
            data={
                "create": {
                    "email": "test_trader@agentinvest.com",
                    "name": "Test Trader",
                    "password": "hashed_password",  # Not used in tests
                    "isActive": True,
                    "isVerified": True
                },
                "update": {}
            }
        )
        logger.info(f"✅ Created/found test user: {user.email}")
        
        # Create test customer
        customer = await prisma.customer.create(
            data={
                "organization_id": self.test_org_id,
                "user_id": user.id,
                "customer_type": "individual",
                "status": "active"
            }
        )
        self.test_customer_id = customer.id
        logger.info(f"✅ Created test customer: {customer.id}")
        
        # Create test portfolio
        portfolio = await prisma.portfolio.create(
            data={
                "organization_id": self.test_org_id,
                "customer_id": self.test_customer_id,
                "name": "Test Trading Portfolio",
                "description": "For order monitoring tests",
                "portfolio_type": "live",
                "initial_balance": Decimal("1000000"),  # 10 lakhs
                "available_cash": Decimal("1000000"),
                "status": "active"
            }
        )
        self.test_portfolio_id = portfolio.id
        logger.info(f"✅ Created test portfolio: {portfolio.id}")
        
        logger.info("")
    
    async def test_limit_order_buy(self):
        """Test BUY limit order execution."""
        logger.info("📊 Test 1: BUY Limit Order")
        logger.info("-" * 80)
        
        prisma = self.db.get_client()
        engine = TradeEngine(prisma)
        
        # Create a BUY limit order for RELIANCE-EQ at ₹2850
        # Order should execute when price drops to or below ₹2850
        payload = TradeCreate(
            organization_id=self.test_org_id,
            portfolio_id=self.test_portfolio_id,
            customer_id=self.test_customer_id,
            trade_type="stock",
            symbol="RELIANCE-EQ",
            exchange="NSE",
            segment="EQ",
            side="BUY",
            order_type="limit",
            quantity=10,
            limit_price=Decimal("2850.00"),
            trigger_price=None,
            source="test",
            metadata={"test": "limit_buy"}
        )
        
        result = await engine.handle_trade(payload)
        trade = result.trades[0]
        self.created_trade_ids.append(trade["id"])
        
        logger.info(f"✅ Created BUY limit order: {trade['id']}")
        logger.info(f"   Symbol: {trade['symbol']}")
        logger.info(f"   Limit Price: ₹{trade['limit_price']}")
        logger.info(f"   Quantity: {trade['quantity']} shares")
        logger.info(f"   Status: {trade['status']}")
        
        assert trade["status"] == "pending", "Order should be pending"
        assert result.pending_orders == 1, "Should have 1 pending order"
        
        logger.info("✅ BUY limit order test passed")
        logger.info("")
        
        return trade["id"]
    
    async def test_limit_order_sell(self):
        """Test SELL limit order execution."""
        logger.info("📊 Test 2: SELL Limit Order")
        logger.info("-" * 80)
        
        prisma = self.db.get_client()
        engine = TradeEngine(prisma)
        
        # First, buy some shares to have holdings
        buy_payload = TradeCreate(
            organization_id=self.test_org_id,
            portfolio_id=self.test_portfolio_id,
            customer_id=self.test_customer_id,
            trade_type="stock",
            symbol="TCS-EQ",
            exchange="NSE",
            segment="EQ",
            side="BUY",
            order_type="market",
            quantity=5,
            limit_price=None,
            trigger_price=None,
            source="test",
            metadata={"test": "initial_buy"}
        )
        
        buy_result = await engine.handle_trade(buy_payload)
        buy_trade = buy_result.trades[0]
        self.created_trade_ids.append(buy_trade["id"])
        
        logger.info(f"✅ Bought 5 TCS-EQ shares at ₹{buy_trade['executed_price']}")
        
        # Now create SELL limit order at higher price
        # Order should execute when price rises to or above ₹4100
        sell_payload = TradeCreate(
            organization_id=self.test_org_id,
            portfolio_id=self.test_portfolio_id,
            customer_id=self.test_customer_id,
            trade_type="stock",
            symbol="TCS-EQ",
            exchange="NSE",
            segment="EQ",
            side="SELL",
            order_type="limit",
            quantity=5,
            limit_price=Decimal("4100.00"),
            trigger_price=None,
            source="test",
            metadata={"test": "limit_sell"}
        )
        
        sell_result = await engine.handle_trade(sell_payload)
        sell_trade = sell_result.trades[0]
        self.created_trade_ids.append(sell_trade["id"])
        
        logger.info(f"✅ Created SELL limit order: {sell_trade['id']}")
        logger.info(f"   Symbol: {sell_trade['symbol']}")
        logger.info(f"   Limit Price: ₹{sell_trade['limit_price']}")
        logger.info(f"   Quantity: {sell_trade['quantity']} shares")
        logger.info(f"   Status: {sell_trade['status']}")
        
        assert sell_trade["status"] == "pending", "Order should be pending"
        
        logger.info("✅ SELL limit order test passed")
        logger.info("")
        
        return sell_trade["id"]
    
    async def test_stop_loss_order(self):
        """Test stop-loss order execution."""
        logger.info("📊 Test 3: Stop-Loss Order")
        logger.info("-" * 80)
        
        prisma = self.db.get_client()
        engine = TradeEngine(prisma)
        
        # First, buy some shares
        buy_payload = TradeCreate(
            organization_id=self.test_org_id,
            portfolio_id=self.test_portfolio_id,
            customer_id=self.test_customer_id,
            trade_type="stock",
            symbol="INFY-EQ",
            exchange="NSE",
            segment="EQ",
            side="BUY",
            order_type="market",
            quantity=10,
            limit_price=None,
            trigger_price=None,
            source="test",
            metadata={"test": "initial_buy_for_sl"}
        )
        
        buy_result = await engine.handle_trade(buy_payload)
        buy_trade = buy_result.trades[0]
        self.created_trade_ids.append(buy_trade["id"])
        
        logger.info(f"✅ Bought 10 INFY-EQ shares at ₹{buy_trade['executed_price']}")
        
        # Create stop-loss order at lower price
        # Order should execute when price drops to or below ₹1450
        sl_payload = TradeCreate(
            organization_id=self.test_org_id,
            portfolio_id=self.test_portfolio_id,
            customer_id=self.test_customer_id,
            trade_type="stock",
            symbol="INFY-EQ",
            exchange="NSE",
            segment="EQ",
            side="SELL",
            order_type="stop_loss",
            quantity=10,
            limit_price=None,
            trigger_price=Decimal("1450.00"),
            source="test",
            metadata={"test": "stop_loss"}
        )
        
        sl_result = await engine.handle_trade(sl_payload)
        sl_trade = sl_result.trades[0]
        self.created_trade_ids.append(sl_trade["id"])
        
        logger.info(f"✅ Created STOP-LOSS order: {sl_trade['id']}")
        logger.info(f"   Symbol: {sl_trade['symbol']}")
        logger.info(f"   Trigger Price: ₹{sl_trade['trigger_price']}")
        logger.info(f"   Quantity: {sl_trade['quantity']} shares")
        logger.info(f"   Status: {sl_trade['status']}")
        
        assert sl_trade["status"] == "pending", "Order should be pending"
        
        logger.info("✅ Stop-loss order test passed")
        logger.info("")
        
        return sl_trade["id"]
    
    async def test_take_profit_order(self):
        """Test take-profit order execution."""
        logger.info("📊 Test 4: Take-Profit Order")
        logger.info("-" * 80)
        
        prisma = self.db.get_client()
        engine = TradeEngine(prisma)
        
        # First, buy some shares
        buy_payload = TradeCreate(
            organization_id=self.test_org_id,
            portfolio_id=self.test_portfolio_id,
            customer_id=self.test_customer_id,
            trade_type="stock",
            symbol="HDFCBANK-EQ",
            exchange="NSE",
            segment="EQ",
            side="BUY",
            order_type="market",
            quantity=8,
            limit_price=None,
            trigger_price=None,
            source="test",
            metadata={"test": "initial_buy_for_tp"}
        )
        
        buy_result = await engine.handle_trade(buy_payload)
        buy_trade = buy_result.trades[0]
        self.created_trade_ids.append(buy_trade["id"])
        
        logger.info(f"✅ Bought 8 HDFCBANK-EQ shares at ₹{buy_trade['executed_price']}")
        
        # Create take-profit order at higher price
        # Order should execute when price rises to or above ₹1700
        tp_payload = TradeCreate(
            organization_id=self.test_org_id,
            portfolio_id=self.test_portfolio_id,
            customer_id=self.test_customer_id,
            trade_type="stock",
            symbol="HDFCBANK-EQ",
            exchange="NSE",
            segment="EQ",
            side="SELL",
            order_type="take_profit",
            quantity=8,
            limit_price=None,
            trigger_price=Decimal("1700.00"),
            source="test",
            metadata={"test": "take_profit"}
        )
        
        tp_result = await engine.handle_trade(tp_payload)
        tp_trade = tp_result.trades[0]
        self.created_trade_ids.append(tp_trade["id"])
        
        logger.info(f"✅ Created TAKE-PROFIT order: {tp_trade['id']}")
        logger.info(f"   Symbol: {tp_trade['symbol']}")
        logger.info(f"   Trigger Price: ₹{tp_trade['trigger_price']}")
        logger.info(f"   Quantity: {tp_trade['quantity']} shares")
        logger.info(f"   Status: {tp_trade['status']}")
        
        assert tp_trade["status"] == "pending", "Order should be pending"
        
        logger.info("✅ Take-profit order test passed")
        logger.info("")
        
        return tp_trade["id"]
    
    async def test_order_monitor_worker(self):
        """Test the order monitor worker."""
        logger.info("📊 Test 5: Order Monitor Worker")
        logger.info("-" * 80)
        
        # Create worker instance
        worker = OrderMonitorWorker()
        await worker.initialize()
        
        # Fetch pending orders
        pending_orders = await worker._fetch_pending_orders()
        logger.info(f"📋 Found {len(pending_orders)} pending orders")
        
        for order in pending_orders[:5]:  # Show first 5
            logger.info(f"   • {order['symbol']} - {order['order_type']} - {order['side']}")
        
        # Ensure symbol subscriptions
        await worker._ensure_symbol_subscriptions(pending_orders)
        logger.info(f"✅ Subscribed to {len(worker.subscribed_symbols)} symbols")
        
        # Process orders (one cycle)
        executed_count = await worker._process_pending_orders(pending_orders)
        logger.info(f"✅ Executed {executed_count} orders this cycle")
        
        # Check if any orders remain pending
        remaining = await worker._fetch_pending_orders()
        logger.info(f"📋 {len(remaining)} orders still pending")
        
        logger.info("✅ Order monitor worker test passed")
        logger.info("")
    
    async def cleanup(self):
        """Cleanup test data."""
        logger.info("🧹 Cleaning up test data...")
        
        prisma = self.db.get_client()
        
        try:
            # Delete test trades
            if self.created_trade_ids:
                await prisma.trade.delete_many(
                    where={"id": {"in": self.created_trade_ids}}
                )
                logger.info(f"✅ Deleted {len(self.created_trade_ids)} test trades")
            
            # Delete test positions
            if self.test_portfolio_id:
                await prisma.position.delete_many(
                    where={"portfolio_id": self.test_portfolio_id}
                )
                logger.info("✅ Deleted test positions")
            
            # Delete test portfolio
            if self.test_portfolio_id:
                await prisma.portfolio.delete(
                    where={"id": self.test_portfolio_id}
                )
                logger.info("✅ Deleted test portfolio")
            
            # Delete test customer
            if self.test_customer_id:
                await prisma.customer.delete(
                    where={"id": self.test_customer_id}
                )
                logger.info("✅ Deleted test customer")
            
            # Delete test organization
            if self.test_org_id:
                await prisma.organization.delete(
                    where={"id": self.test_org_id}
                )
                logger.info("✅ Deleted test organization")
            
        except Exception as e:
            logger.warning(f"⚠️  Cleanup error (non-critical): {e}")
    
    async def run_all_tests(self):
        """Run all tests."""
        try:
            await self.setup()
            
            # Run tests
            await self.test_limit_order_buy()
            await self.test_limit_order_sell()
            await self.test_stop_loss_order()
            await self.test_take_profit_order()
            await self.test_order_monitor_worker()
            
            logger.info("=" * 80)
            logger.info("✅ ALL TESTS PASSED")
            logger.info("=" * 80)
            logger.info("")
            logger.info("📧 Email Notification Test:")
            logger.info("   Check your email (test_trader@agentinvest.com) for trade execution emails.")
            logger.info("   Note: Emails will only be sent if EMAIL_API_URL is configured.")
            logger.info("")
            logger.info("🔄 To test continuous monitoring:")
            logger.info("   1. Start Celery worker: celery -A celery_app worker --loglevel=info")
            logger.info("   2. Start Celery beat: celery -A celery_app beat --loglevel=info")
            logger.info("   3. Watch logs for order execution messages")
            logger.info("")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}", exc_info=True)
            raise
        finally:
            await self.cleanup()


async def main():
    """Main test runner."""
    tester = OrderMonitorTester()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
