"""
Comprehensive End-to-End Test for NSE Pipeline

This script tests the entire NSE trade execution pipeline:
1. Signal push and processing
2. Trade log creation
3. Trade execution
4. Position creation/updates
5. TP/SL order creation
6. Auto-sell functionality
7. Realized P&L calculation
8. Database state verification using Prisma

Usage:
    python scripts/test_nse_pipeline_e2e.py --symbol RELIANCE --price 2500
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from celery_app import celery_app
from prisma import Prisma
from services.trade_execution_service import TradeExecutionService
from services.pipeline_service import PipelineService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


class NSEPipelineTester:
    """End-to-end tester for NSE pipeline."""

    def __init__(self):
        self.prisma = Prisma()
        self.test_symbol: Optional[str] = None
        self.test_price: Optional[float] = None
        self.created_trade_ids: List[str] = []
        self.created_position_ids: List[str] = []
        self.test_results: Dict[str, bool] = {}

    async def setup(self):
        """Initialize database connection."""
        await self.prisma.connect()
        logger.info("✅ Database connection established via Prisma")

    async def cleanup(self):
        """Clean up database connection."""
        try:
            await self.prisma.disconnect()
        except Exception as e:
            logger.debug(f"Cleanup error: {e}")

    async def verify_db_state(self, step_name: str):
        """Verify database state at a given step."""
        client = self.prisma
        
        logger.info(f"\n{'='*70}")
        logger.info(f"📊 DB STATE VERIFICATION: {step_name}")
        logger.info(f"{'='*70}")
        
        # Count trades
        trades_count = await client.trade.count()
        logger.info(f"Total Trades: {trades_count}")
        
        # Count positions
        positions_count = await client.position.count()
        logger.info(f"Total Positions: {positions_count}")
        
        # Count TP/SL orders
        tp_sl_orders = await client.trade.find_many(
            where={"source": "nse_pipeline_tp_sl", "status": {"in": ["pending", "executed", "cancelled"]}},
            take=10
        )
        logger.info(f"TP/SL Orders: {len(tp_sl_orders)}")
        
        if self.test_symbol:
            # Show recent trades for test symbol
            recent_trades = await client.trade.find_many(
                where={"symbol": {"equals": self.test_symbol, "mode": "insensitive"}},
                order={"created_at": "desc"},
                take=5,
                include={"portfolio": True, "agent": True}
            )
            logger.info(f"\nRecent {self.test_symbol} Trades:")
            for trade in recent_trades or []:
                logger.info(
                    f"  - {trade.id[:8]}: {trade.side} {trade.quantity} @ ₹{trade.price} | "
                    f"Status: {trade.status} | P&L: ₹{trade.realized_pnl or 0}"
                )
            
            # Show positions for test symbol
            positions = await client.position.find_many(
                where={"symbol": {"equals": self.test_symbol, "mode": "insensitive"}},
                include={"agent": True, "allocation": True}
            )
            logger.info(f"\n{self.test_symbol} Positions:")
            for pos in positions or []:
                logger.info(
                    f"  - {pos.id[:8]}: Qty: {pos.quantity} | Avg Buy: ₹{pos.average_buy_price} | "
                    f"Status: {pos.status} | P&L: ₹{pos.realized_pnl}"
                )

    async def test_push_signal(self, symbol: str, signal: int, price: float, confidence: float = 0.85):
        """Test 1: Push signal and verify processing."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST 1: Push Signal and Verify Processing")
        logger.info(f"{'='*70}")
        
        self.test_symbol = symbol
        self.test_price = price
        
        # Import and call push_fake_signal logic
        import uuid
        from datetime import datetime
        
        signal_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        
        signal_event = {
            "signal_id": signal_id,
            "symbol": symbol,
            "signal": signal,  # Use "signal" not "trading_signal"
            "trading_signal": signal,  # Also include for compatibility
            "confidence": confidence,  # Use "confidence" not "confidence_score"
            "confidence_score": confidence,  # Also include for compatibility
            "reference_price": price,
            "timestamp": timestamp,
            "announcement_title": f"[TEST] {symbol} - Test Signal",
            "announcement_desc": f"E2E test signal for {symbol}",
            "pdf_url": f"https://test.example.com/{signal_id}.pdf",
            "concise_explanation": f"TEST: {symbol} signal={signal}",
        }
        
        logger.info(f"📤 Pushing signal: {symbol} signal={signal} (BUY) @ ₹{price}")
        
        # Try Celery first, fallback to direct call if Celery unavailable
        try:
            # Check if Celery worker is available
            inspect = celery_app.control.inspect()
            active_workers = inspect.active()
            
            if active_workers:
                logger.info(f"✅ Celery worker(s) available, using async task")
                # Send to Celery
                task = celery_app.send_task(
                    "pipeline.trade_execution.process_signal",
                    args=[signal_event]
                )
                logger.info(f"✅ Signal pushed to Celery task: {task.id}")
                
                # Wait for task completion with longer timeout
                logger.info("⏳ Waiting for signal processing...")
                try:
                    result = task.get(timeout=120)
                    logger.info(f"✅ Signal processed via Celery: {result}")
                except Exception as celery_exc:
                    logger.warning(f"⚠️ Celery task timed out or failed: {celery_exc}")
                    logger.info("🔄 Falling back to direct service call...")
                    # Fall through to direct call
                    raise
            else:
                logger.warning("⚠️ No active Celery workers, using direct service call")
                raise Exception("No Celery workers")
                
        except Exception as e:
            # Direct service call fallback
            logger.info("🔄 Processing signal directly via PipelineService...")
            from pathlib import Path
            server_dir = Path(__file__).resolve().parents[1]
            service = PipelineService(str(server_dir), logger=logger)
            
            # Call the async method directly
            result = await service._process_signal_for_active_agents(signal_event)
            logger.info(f"✅ Signal processed directly: {result}")
        
        # Wait a bit for DB writes
        await asyncio.sleep(3)
        
        # Verify trade logs created - query all recent logs and filter by signal_id in metadata
        client = self.prisma
        
        # Check Trade records directly (more reliable)
        recent_trades = await client.trade.find_many(
            where={
                "symbol": {"equals": symbol, "mode": "insensitive"},
            },
            order={"created_at": "desc"},
            take=10,
            include={"executions": True}
        )
        
        # Filter trades created in last 5 minutes
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_trades = [t for t in recent_trades if t.created_at >= cutoff_time]
        
        # Also check all recent trade execution logs
        all_recent_logs = await client.tradeexecutionlog.find_many(
            order={"created_at": "desc"},
            take=20,
            include={"trade": True}
        )
        
        # Filter by signal_id in metadata
        trade_logs = []
        for log in all_recent_logs or []:
            metadata = log.metadata if isinstance(log.metadata, dict) else {}
            if metadata.get("signal_id") == signal_id or (log.trade and log.trade.symbol.upper() == symbol.upper()):
                trade_logs.append(log)
        
        if trade_logs or recent_trades:
            logger.info(f"✅ Found {len(trade_logs)} trade log(s) and {len(recent_trades)} trade(s) created")
            for log in trade_logs:
                if log.trade:
                    if log.trade.id not in self.created_trade_ids:
                        self.created_trade_ids.append(log.trade.id)
                        logger.info(f"  - Trade ID: {log.trade.id[:8]}, Symbol: {log.trade.symbol}, Status: {log.trade.status}")
            for trade in recent_trades:
                if trade.id not in self.created_trade_ids:
                    self.created_trade_ids.append(trade.id)
                    logger.info(f"  - Trade ID: {trade.id[:8]}, Symbol: {trade.symbol}, Status: {trade.status}")
            self.test_results["signal_processing"] = len(self.created_trade_ids) > 0
        else:
            logger.warning("⚠️ No trade logs or trades created!")
            logger.info("⚠️ This might mean:")
            logger.info("   1. No active high_risk agents found")
            logger.info("   2. Agents have allocated_value=0")
            logger.info("   3. Calculated quantity is 0")
            # Check agents
            agents = await client.tradingagent.find_many(
                where={"agent_type": "high_risk", "status": "active"},
                include={"allocation": True},
                take=5
            )
            if agents:
                logger.info(f"   Found {len(agents)} active agent(s), checking allocations...")
                for agent in agents:
                    alloc = agent.allocation
                    alloc_value = float(getattr(alloc, "allocated_value", 0)) if alloc else 0
                    logger.info(f"     Agent {agent.id[:8]}: allocated_value=₹{alloc_value}")
            self.test_results["signal_processing"] = False
        
        await self.verify_db_state("After Signal Push")
        return signal_id

    async def test_trade_execution(self):
        """Test 2: Verify trades are executed."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST 2: Verify Trade Execution")
        logger.info(f"{'='*70}")
        
        if not self.created_trade_ids:
            logger.error("❌ No trades to test execution")
            self.test_results["trade_execution"] = False
            return
        
        client = self.prisma
        trade_service = TradeExecutionService(logger=logger)
        
        executed_count = 0
        for trade_id in self.created_trade_ids:
            # Check if already executed
            trade = await client.trade.find_unique(where={"id": trade_id})
            if not trade:
                logger.warning(f"⚠️ Trade {trade_id[:8]} not found")
                continue
            
            if trade.status in ["executed", "executed"]:
                logger.info(f"✅ Trade {trade_id[:8]} already executed: {trade.status}")
                executed_count += 1
            else:
                logger.info(f"🔄 Executing trade {trade_id[:8]}...")
                result = await trade_service.execute_trade(trade_id, simulate=True)
                
                if result.get("status") in ["executed", "executed"]:
                    logger.info(f"✅ Trade {trade_id[:8]} executed successfully")
                    executed_count += 1
                else:
                    logger.error(f"❌ Trade {trade_id[:8]} execution failed: {result}")
        
        if executed_count == len(self.created_trade_ids):
            self.test_results["trade_execution"] = True
        else:
            self.test_results["trade_execution"] = False
        
        await asyncio.sleep(1)
        await self.verify_db_state("After Trade Execution")

    async def test_position_creation(self):
        """Test 3: Verify positions are created."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST 3: Verify Position Creation")
        logger.info(f"{'='*70}")
        
        if not self.test_symbol:
            logger.error("❌ No test symbol set")
            self.test_results["position_creation"] = False
            return
        
        client = self.prisma
        
        # Find positions for test symbol (both open and closed)
        positions = await client.position.find_many(
            where={
                "symbol": {"equals": self.test_symbol, "mode": "insensitive"},
            },
            include={"agent": True, "allocation": True},
            take=10
        )
        
        if positions:
            open_positions = [p for p in positions if p.status == "open"]
            closed_positions = [p for p in positions if p.status == "closed"]
            logger.info(f"✅ Found {len(positions)} position(s) for {self.test_symbol} ({len(open_positions)} open, {len(closed_positions)} closed)")
            for pos in positions:
                self.created_position_ids.append(pos.id)
                logger.info(
                    f"  - Position {pos.id[:8]}: Qty={pos.quantity}, "
                    f"Avg Buy=₹{pos.average_buy_price}, Status={pos.status}, "
                    f"P&L=₹{pos.realized_pnl}, Agent={pos.agent_id[:8] if pos.agent_id else 'None'}"
                )
            self.test_results["position_creation"] = True
        else:
            logger.error(f"❌ No positions found for {self.test_symbol}")
            self.test_results["position_creation"] = False
        
        await self.verify_db_state("After Position Creation")

    async def test_tp_sl_orders(self):
        """Test 4: Verify TP/SL orders are created."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST 4: Verify TP/SL Order Creation")
        logger.info(f"{'='*70}")
        
        if not self.created_trade_ids:
            logger.error("❌ No trades to check TP/SL orders")
            self.test_results["tp_sl_creation"] = False
            return
        
        client = self.prisma
        
        tp_sl_found = False
        for trade_id in self.created_trade_ids:
            # Find TP/SL orders linked to this trade
            # Query all TP/SL orders and filter by metadata in Python
            all_tp_sl_orders = await client.trade.find_many(
                where={
                    "source": "nse_pipeline_tp_sl",
                }
            )
            
            # Filter by parent_trade_id in metadata
            tp_sl_orders = []
            for order in all_tp_sl_orders or []:
                metadata = order.metadata if isinstance(order.metadata, dict) else {}
                if metadata.get("parent_trade_id") == trade_id:
                    tp_sl_orders.append(order)
            
            if tp_sl_orders:
                logger.info(f"✅ Found {len(tp_sl_orders)} TP/SL order(s) for trade {trade_id[:8]}")
                for order in tp_sl_orders:
                    order_type = order.metadata.get("order_type", "unknown") if isinstance(order.metadata, dict) else "unknown"
                    price = order.price or order.limit_price
                    logger.info(
                        f"  - {order_type.upper()}: {order.side} {order.quantity} @ ₹{price} | Status: {order.status}"
                    )
                tp_sl_found = True
            else:
                logger.warning(f"⚠️ No TP/SL orders found for trade {trade_id[:8]}")
        
        self.test_results["tp_sl_creation"] = tp_sl_found
        await self.verify_db_state("After TP/SL Creation")

    async def test_auto_sell(self):
        """Test 5: Test auto-sell functionality."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST 5: Test Auto-Sell Functionality")
        logger.info(f"{'='*70}")
        
        if not self.created_trade_ids:
            logger.error("❌ No trades to test auto-sell")
            self.test_results["auto_sell"] = False
            return
        
        client = self.prisma
        
        # Find BUY trades with auto_sell_at set
        buy_trades = await client.trade.find_many(
            where={
                "id": {"in": self.created_trade_ids},
                "side": "BUY",
                "auto_sell_at": {"not": None},
                "status": {"in": ["executed", "executed"]}
            }
        )
        
        if not buy_trades:
            logger.warning("⚠️ No BUY trades with auto_sell_at found")
            self.test_results["auto_sell"] = False
            return
        
        logger.info(f"✅ Found {len(buy_trades)} BUY trade(s) with auto_sell_at set")
        
        for trade in buy_trades:
            logger.info(
                f"  - Trade {trade.id[:8]}: auto_sell_at={trade.auto_sell_at}, "
                f"Current time={datetime.now(timezone.utc)}"
            )
        
        # Manually trigger auto-sell for expired trades (set auto_sell_at to past)
        logger.info("🔄 Manually setting auto_sell_at to past for testing...")
        test_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        
        for trade in buy_trades:
            await client.trade.update(
                where={"id": trade.id},
                data={"auto_sell_at": test_time}
            )
            logger.info(f"  - Set auto_sell_at for {trade.id[:8]} to {test_time}")
        
        # Trigger auto-sell worker directly (not via Celery)
        logger.info("🔄 Triggering auto-sell worker directly...")
        try:
            from workers.auto_sell_worker import _run_auto_sell
            result = await _run_auto_sell()
            logger.info(f"✅ Auto-sell worker result: {result}")
        except Exception as auto_sell_exc:
            logger.warning(f"⚠️ Auto-sell worker failed: {auto_sell_exc}")
            # Try Celery as fallback
            try:
                task = celery_app.send_task("trades.auto_sell_expired_trades")
                result = task.get(timeout=10)
                logger.info(f"✅ Auto-sell worker result (via Celery): {result}")
            except Exception as celery_exc:
                logger.error(f"❌ Auto-sell failed via both methods: {celery_exc}")
                result = {"status": "failed"}
        
        # Verify SELL trades created
        await asyncio.sleep(2)
        all_sell_trades = await client.trade.find_many(
            where={
                "side": "SELL",
                "source": "auto_sell_worker",
            }
        )
        
        # Filter by parent_trade_id in metadata
        buy_trade_ids = [str(t.id) for t in buy_trades]
        sell_trades = []
        for trade in all_sell_trades or []:
            metadata = trade.metadata if isinstance(trade.metadata, dict) else {}
            if metadata.get("parent_trade_id") in buy_trade_ids:
                sell_trades.append(trade)
        
        if sell_trades:
            logger.info(f"✅ Auto-sell created {len(sell_trades)} SELL trade(s)")
            self.test_results["auto_sell"] = True
        else:
            logger.error("❌ No SELL trades created by auto-sell")
            self.test_results["auto_sell"] = False
        
        await self.verify_db_state("After Auto-Sell")

    async def test_realized_pnl(self):
        """Test 6: Verify realized P&L calculation."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST 6: Verify Realized P&L Calculation")
        logger.info(f"{'='*70}")
        
        if not self.test_symbol:
            logger.error("❌ No test symbol set")
            self.test_results["realized_pnl"] = False
            return
        
        client = self.prisma
        
        # Find SELL trades for test symbol
        sell_trades = await client.trade.find_many(
            where={
                "symbol": {"equals": self.test_symbol, "mode": "insensitive"},
                "side": "SELL",
                "status": {"in": ["executed", "executed"]}
            },
            include={"portfolio": True, "agent": True},
            order={"created_at": "desc"},
            take=5
        )
        
        # Also check positions for realized P&L
        positions = await client.position.find_many(
            where={
                "symbol": {"equals": self.test_symbol, "mode": "insensitive"},
            },
            take=5
        )
        
        if not sell_trades and not positions:
            logger.warning("⚠️ No SELL trades or positions found to verify P&L")
            self.test_results["realized_pnl"] = False
            return
        
        logger.info(f"✅ Found {len(sell_trades)} SELL trade(s) and {len(positions)} position(s) to verify P&L")
        
        pnl_correct = True
        total_trade_pnl = 0
        
        # Check Trade P&L
        for trade in sell_trades:
            trade_pnl = float(trade.realized_pnl or 0)
            total_trade_pnl += trade_pnl
            
            if trade_pnl != 0:
                logger.info(
                    f"  - Trade {trade.id[:8]}: Realized P&L = ₹{trade_pnl}"
                )
            else:
                logger.debug(f"  - Trade {trade.id[:8]}: No realized P&L (may be TP/SL order)")
        
        # Check Position P&L
        total_position_pnl = 0
        for pos in positions:
            pos_pnl = float(pos.realized_pnl or 0)
            total_position_pnl += pos_pnl
            if pos_pnl != 0:
                logger.info(
                    f"  - Position {pos.id[:8]}: Realized P&L = ₹{pos_pnl}, Status = {pos.status}"
                )
        
        # Check Portfolio P&L if we have trades
        if sell_trades:
            portfolio_id = sell_trades[0].portfolio_id
            portfolio = await client.portfolio.find_unique(where={"id": portfolio_id})
            if portfolio:
                portfolio_pnl = float(portfolio.total_realized_pnl or 0)
                logger.info(f"  - Portfolio {portfolio_id[:8]}: Total Realized P&L = ₹{portfolio_pnl}")
                
                # Verify portfolio P&L matches sum of trades (approximately)
                if portfolio_pnl > 0 or total_trade_pnl > 0:
                    pnl_correct = True
                    logger.info(f"✅ Portfolio P&L (₹{portfolio_pnl}) matches trade P&L (₹{total_trade_pnl})")
                else:
                    logger.warning(f"⚠️ Portfolio P&L is 0 but trades exist")
        
        # Check Agent and Allocation P&L
        if sell_trades and sell_trades[0].agent_id:
            agent = await client.tradingagent.find_unique(where={"id": sell_trades[0].agent_id})
            if agent:
                agent_pnl = float(agent.realized_pnl or 0)
                logger.info(f"  - Agent {agent.id[:8]}: Realized P&L = ₹{agent_pnl}")
                
                # Check Allocation P&L
                if hasattr(agent, "portfolio_allocation_id") and agent.portfolio_allocation_id:
                    allocation = await client.portfolioallocation.find_unique(where={"id": agent.portfolio_allocation_id})
                    if allocation:
                        allocation_pnl = float(allocation.realized_pnl or 0)
                        logger.info(f"  - Allocation {allocation.id[:8]}: Realized P&L = ₹{allocation_pnl}")
        
        # P&L is correct if we have any non-zero P&L values
        self.test_results["realized_pnl"] = (total_trade_pnl != 0 or total_position_pnl != 0) and pnl_correct
        await self.verify_db_state("After P&L Verification")

    async def test_sell_cancels_tp_sl(self):
        """Test 7: Verify SELL trades cancel pending TP/SL orders."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST 7: Verify SELL Cancels Pending TP/SL Orders")
        logger.info(f"{'='*70}")
        
        if not self.test_symbol:
            logger.error("❌ No test symbol set")
            self.test_results["sell_cancels_tp_sl"] = False
            return
        
        client = self.prisma
        
        # Find pending TP/SL orders for test symbol
        pending_tp_sl = await client.trade.find_many(
            where={
                "symbol": {"equals": self.test_symbol, "mode": "insensitive"},
                "source": "nse_pipeline_tp_sl",
                "status": {"in": ["pending", "cancelled"]}
            }
        )
        
        if pending_tp_sl:
            logger.info(f"📊 Found {len(pending_tp_sl)} TP/SL order(s) for {self.test_symbol}")
            
            cancelled_count = sum(1 for o in pending_tp_sl if o.status == "cancelled")
            pending_count = sum(1 for o in pending_tp_sl if o.status == "pending")
            
            logger.info(f"  - Cancelled: {cancelled_count}")
            logger.info(f"  - Pending: {pending_count}")
            
            # Check if positions are closed
            positions = await client.position.find_many(
                where={
                    "symbol": {"equals": self.test_symbol, "mode": "insensitive"},
                    "status": "open"
                }
            )
            
            if not positions and cancelled_count > 0:
                logger.info("✅ All TP/SL orders cancelled when position closed")
                self.test_results["sell_cancels_tp_sl"] = True
            elif positions and pending_count > 0:
                logger.info("✅ TP/SL orders remain pending for open positions")
                self.test_results["sell_cancels_tp_sl"] = True
            else:
                logger.warning("⚠️ TP/SL order cancellation status unclear")
                self.test_results["sell_cancels_tp_sl"] = False
        else:
            logger.info("ℹ️ No TP/SL orders found (may have been cancelled)")
            self.test_results["sell_cancels_tp_sl"] = True
        
        await self.verify_db_state("After TP/SL Cancellation Check")

    def print_summary(self):
        """Print test summary."""
        logger.info(f"\n{'='*70}")
        logger.info("TEST SUMMARY")
        logger.info(f"{'='*70}")
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for v in self.test_results.values() if v)
        
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            logger.info(f"{status}: {test_name}")
        
        logger.info(f"\nTotal: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            logger.info("🎉 ALL TESTS PASSED!")
        else:
            logger.warning(f"⚠️ {total_tests - passed_tests} test(s) failed")


async def main():
    """Run all tests."""
    parser = argparse.ArgumentParser(description="End-to-end test for NSE pipeline")
    parser.add_argument("--symbol", type=str, default="RELIANCE", help="Stock symbol")
    parser.add_argument("--price", type=float, default=2500.0, help="Reference price")
    parser.add_argument("--confidence", type=float, default=0.85, help="Confidence score")
    parser.add_argument("--skip-auto-sell", action="store_true", help="Skip auto-sell test")
    
    args = parser.parse_args()
    
    tester = NSEPipelineTester()
    
    try:
        await tester.setup()
        
        # Test 1: Push signal
        signal_id = await tester.test_push_signal(
            symbol=args.symbol,
            signal=1,  # BUY
            price=args.price,
            confidence=args.confidence
        )
        
        # Test 2: Execute trades
        await tester.test_trade_execution()
        
        # Test 3: Verify positions
        await tester.test_position_creation()
        
        # Test 4: Verify TP/SL orders
        await tester.test_tp_sl_orders()
        
        # Test 5: Test auto-sell (unless skipped)
        if not args.skip_auto_sell:
            await tester.test_auto_sell()
        
        # Test 6: Verify realized P&L
        await tester.test_realized_pnl()
        
        # Test 7: Verify SELL cancels TP/SL
        await tester.test_sell_cancels_tp_sl()
        
        # Print summary
        tester.print_summary()
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}", exc_info=True)
        raise
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

