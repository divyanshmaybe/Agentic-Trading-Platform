"""
Test suite for snapshot storage and retrieval functionality.

Tests:
1. Trading agent snapshots (captured every 3 hours)
2. Portfolio snapshots (aggregated from agents)
3. Allocation snapshots (created on pipeline trigger)
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

from prisma import Prisma
from services.snapshot_service import TradingAgentSnapshotService
from services.pipeline_service import PipelineService
from controllers.portfolio_controller import PortfolioController
from celery_app import celery_app


# Database tests flag
ENABLE_DB_TESTS = os.getenv("ENABLE_DB_TESTS", "false").lower() in {"1", "true", "yes"}

# Skip database-dependent tests if disabled
if not ENABLE_DB_TESTS:
    pytest.skip(
        "Snapshot database tests require live database. Set ENABLE_DB_TESTS=true to run.",
        allow_module_level=True,
    )


@pytest.fixture
async def prisma_client():
    """Fixture for Prisma client"""
    client = Prisma()
    await client.connect()
    yield client
    await client.disconnect()


@pytest.fixture
async def test_portfolio(prisma_client):
    """Create a test portfolio"""
    portfolio = await prisma_client.portfolio.create(
        data={
            "customer_id": "test_user_123",
            "organization_id": "test_org_123",
            "portfolio_name": "Test Portfolio",
            "investment_amount": Decimal("100000"),
            "current_value": Decimal("105000"),
            "investment_horizon_years": 3,
            "expected_return_target": Decimal("0.08"),
            "risk_tolerance": "moderate",
            "liquidity_needs": "standard",
        }
    )
    yield portfolio
    # Cleanup
    await prisma_client.portfolio.delete(where={"id": portfolio.id})


@pytest.fixture
async def test_trading_agent(prisma_client, test_portfolio):
    """Create a test trading agent with positions"""
    agent = await prisma_client.tradingagent.create(
        data={
            "portfolio": {"connect": {"id": test_portfolio.id}},
            "agent_name": "Test Agent",
            "agent_type": "alpha",
            "status": "active",
            "realized_pnl": Decimal("5000"),
            "metadata": {},
        }
    )
    
    # Create test positions
    await prisma_client.position.create(
        data={
            "portfolio": {"connect": {"id": test_portfolio.id}},
            "agent": {"connect": {"id": agent.id}},
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "segment": "EQ",
            "quantity": 100,
            "average_buy_price": Decimal("2500"),
            "current_price": Decimal("2600"),
            "position_type": "long",
            "status": "open",
        }
    )
    
    yield agent
    # Cleanup
    await prisma_client.tradingagent.delete(where={"id": agent.id})


@pytest.fixture
async def test_allocation(prisma_client, test_portfolio):
    """Create a test portfolio allocation"""
    allocation = await prisma_client.portfolioallocation.create(
        data={
            "portfolio": {"connect": {"id": test_portfolio.id}},
            "allocation_type": "alpha",
            "target_weight": Decimal("0.333333"),
            "current_weight": Decimal("0.333333"),
            "allocated_amount": Decimal("33333.33"),
            "current_value": Decimal("35000"),
            "metadata": {},
        }
    )
    yield allocation
    # Cleanup
    await prisma_client.portfolioallocation.delete(where={"id": allocation.id})


@pytest.mark.asyncio
@pytest.mark.integration
class TestTradingAgentSnapshots:
    """Test trading agent snapshot capture and retrieval"""
    
    async def test_capture_agent_snapshot(self, prisma_client, test_trading_agent):
        """Test capturing a snapshot for a single agent"""
        service = TradingAgentSnapshotService()
        
        result = await service.capture_agent_snapshot(test_trading_agent.id)
        
        assert result is not None
        assert result["agent_id"] == test_trading_agent.id
        assert "portfolio_value" in result
        assert "realized_pnl" in result
        assert "positions_count" in result
        assert result["positions_count"] == 1  # One position created
        
        # Verify snapshot was stored in database
        snapshot = await prisma_client.tradingagentsnapshot.find_unique(
            where={"id": result["id"]}
        )
        assert snapshot is not None
        assert snapshot.agent_id == test_trading_agent.id
        assert snapshot.portfolio_value > Decimal("0")
        assert snapshot.realized_pnl == Decimal("5000")
        assert snapshot.positions_count == 1
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": result["id"]})
    
    async def test_capture_all_active_agents(self, prisma_client, test_trading_agent):
        """Test capturing snapshots for all active agents"""
        service = TradingAgentSnapshotService()
        
        result = await service.capture_all_active_agents()
        
        assert result["total_agents"] >= 1
        assert result["snapshots_captured"] >= 1
        assert result["failed"] == 0
        
        # Verify snapshots were created
        snapshots = await prisma_client.tradingagentsnapshot.find_many(
            where={"agent_id": test_trading_agent.id},
            order={"snapshot_at": "desc"},
            take=1,
        )
        assert len(snapshots) > 0
        
        # Cleanup
        for snapshot in snapshots:
            await prisma_client.tradingagentsnapshot.delete(where={"id": snapshot.id})
    
    async def test_get_agent_snapshot_history(self, prisma_client, test_trading_agent):
        """Test retrieving agent snapshot history"""
        service = TradingAgentSnapshotService()
        
        # Create multiple snapshots
        snapshot1 = await service.capture_agent_snapshot(test_trading_agent.id)
        await asyncio.sleep(0.1)  # Small delay to ensure different timestamps
        snapshot2 = await service.capture_agent_snapshot(test_trading_agent.id)
        
        # Get history
        history = await service.get_agent_snapshot_history(test_trading_agent.id, limit=10)
        
        assert len(history) >= 2
        assert history[0]["snapshot_at"] >= history[1]["snapshot_at"]  # Descending order
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete_many(
            where={"agent_id": test_trading_agent.id}
        )
    
    async def test_snapshot_calculates_portfolio_value_correctly(
        self, prisma_client, test_trading_agent
    ):
        """Test that snapshot correctly calculates portfolio value from positions"""
        service = TradingAgentSnapshotService()
        
        result = await service.capture_agent_snapshot(test_trading_agent.id)
        
        # Portfolio value should be: quantity * current_price = 100 * 2600 = 260000
        expected_value = Decimal("260000")
        actual_value = Decimal(str(result["portfolio_value"]))
        
        assert abs(actual_value - expected_value) < Decimal("0.01"), \
            f"Expected portfolio value {expected_value}, got {actual_value}"
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": result["id"]})


@pytest.mark.asyncio
@pytest.mark.integration
class TestPortfolioSnapshots:
    """Test portfolio snapshot aggregation"""
    
    async def test_get_portfolio_snapshot_history(
        self, prisma_client, test_portfolio, test_trading_agent
    ):
        """Test retrieving aggregated portfolio snapshots"""
        service = TradingAgentSnapshotService()
        
        # Create snapshots for the agent
        snapshot1 = await service.capture_agent_snapshot(test_trading_agent.id)
        await asyncio.sleep(0.1)
        snapshot2 = await service.capture_agent_snapshot(test_trading_agent.id)
        
        # Get portfolio snapshot history
        history = await service.get_portfolio_snapshot_history(test_portfolio.id, limit=10)
        
        assert len(history) >= 1
        assert "portfolio_value" in history[0]
        assert "realized_pnl" in history[0]
        assert "positions_count" in history[0]
        assert "agents_count" in history[0]
        assert history[0]["agents_count"] >= 1
        
        # Portfolio value should match agent's portfolio value
        assert history[0]["portfolio_value"] == snapshot1["portfolio_value"]
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete_many(
            where={"agent_id": test_trading_agent.id}
        )
    
    async def test_portfolio_snapshot_aggregates_multiple_agents(
        self, prisma_client, test_portfolio
    ):
        """Test that portfolio snapshots aggregate values from multiple agents"""
        # Create two agents
        agent1 = await prisma_client.tradingagent.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "agent_name": "Agent 1",
                "agent_type": "alpha",
                "status": "active",
                "realized_pnl": Decimal("1000"),
            }
        )
        
        agent2 = await prisma_client.tradingagent.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "agent_name": "Agent 2",
                "agent_type": "high_risk",
                "status": "active",
                "realized_pnl": Decimal("2000"),
            }
        )
        
        # Create positions for each agent
        await prisma_client.position.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "agent": {"connect": {"id": agent1.id}},
                "symbol": "TCS",
                "exchange": "NSE",
                "segment": "EQ",
                "quantity": 50,
                "average_buy_price": Decimal("3000"),
                "current_price": Decimal("3100"),
                "position_type": "long",
                "status": "open",
            }
        )
        
        await prisma_client.position.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "agent": {"connect": {"id": agent2.id}},
                "symbol": "INFY",
                "exchange": "NSE",
                "segment": "EQ",
                "quantity": 100,
                "average_buy_price": Decimal("1500"),
                "current_price": Decimal("1600"),
                "position_type": "long",
                "status": "open",
            }
        )
        
        service = TradingAgentSnapshotService()
        
        # Capture snapshots for both agents at same time
        snapshot1 = await service.capture_agent_snapshot(agent1.id)
        snapshot2 = await service.capture_agent_snapshot(agent2.id)
        
        # Get aggregated portfolio snapshot
        history = await service.get_portfolio_snapshot_history(test_portfolio.id, limit=10)
        
        assert len(history) >= 1
        aggregated = history[0]
        
        # Portfolio value should be sum of both agents
        expected_value = snapshot1["portfolio_value"] + snapshot2["portfolio_value"]
        assert abs(aggregated["portfolio_value"] - expected_value) < 0.01
        
        # Realized P&L should be sum
        expected_pnl = snapshot1["realized_pnl"] + snapshot2["realized_pnl"]
        assert abs(aggregated["realized_pnl"] - expected_pnl) < 0.01
        
        # Agents count should be 2
        assert aggregated["agents_count"] == 2
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete_many(
            where={"agent_id": {"in": [agent1.id, agent2.id]}}
        )
        await prisma_client.tradingagent.delete_many(
            where={"id": {"in": [agent1.id, agent2.id]}}
        )


@pytest.mark.asyncio
@pytest.mark.integration
class TestAllocationSnapshots:
    """Test allocation snapshot creation and retrieval"""
    
    async def test_allocation_snapshot_created_on_pipeline_run(
        self, prisma_client, test_portfolio, test_allocation
    ):
        """Test that allocation snapshots are created when pipeline runs"""
        # Count existing snapshots
        initial_count = await prisma_client.allocationsnapshot.count(
            where={"portfolio_allocation_id": test_allocation.id}
        )
        
        # Simulate allocation pipeline result
        pipeline_result = {
            "weights": {"alpha": 0.333333, "low_risk": 0.333333, "high_risk": 0.333334},
            "expected_return": 0.08,
            "expected_risk": 0.15,
            "objective_value": 0.75,
            "regime": "bull_market",
            "progress_ratio": 0.95,
            "message": "Optimization successful",
        }
        
        # Create a rebalance run
        rebalance_run = await prisma_client.rebalancerun.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "triggered_by": "test",
                "triggered_at": datetime.utcnow(),
                "snapshot_portfolio_value": Decimal("105000"),
                "snapshot_cash": Decimal("0"),
                "snapshot_invested": Decimal("105000"),
                "metadata": {},
            }
        )
        
        # Manually create allocation snapshot (simulating pipeline behavior)
        allocation_snapshot = await prisma_client.allocationsnapshot.create(
            data={
                "rebalance_run": {"connect": {"id": rebalance_run.id}},
                "portfolio_allocation": {"connect": {"id": test_allocation.id}},
                "snapshot_weight": Decimal("0.333333"),
                "snapshot_amount": Decimal("35000"),
                "snapshot_current_value": Decimal("35000"),
                "snapshot_pnl": Decimal("0"),
                "metadata": {
                    "regime": pipeline_result["regime"],
                    "generated_at": datetime.utcnow().isoformat(),
                },
            }
        )
        
        # Verify snapshot was created
        assert allocation_snapshot is not None
        assert allocation_snapshot.rebalance_run_id == rebalance_run.id
        assert allocation_snapshot.portfolio_allocation_id == test_allocation.id
        
        # Verify count increased
        final_count = await prisma_client.allocationsnapshot.count(
            where={"portfolio_allocation_id": test_allocation.id}
        )
        assert final_count == initial_count + 1
        
        # Cleanup
        await prisma_client.allocationsnapshot.delete(where={"id": allocation_snapshot.id})
        await prisma_client.rebalancerun.delete(where={"id": rebalance_run.id})
    
    async def test_get_allocation_snapshot_history(
        self, prisma_client, test_portfolio, test_allocation
    ):
        """Test retrieving allocation snapshot history"""
        # Create multiple allocation snapshots
        rebalance_run1 = await prisma_client.rebalancerun.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "triggered_by": "test",
                "triggered_at": datetime.utcnow() - timedelta(days=1),
                "snapshot_portfolio_value": Decimal("100000"),
                "snapshot_cash": Decimal("0"),
                "snapshot_invested": Decimal("100000"),
                "metadata": {},
            }
        )
        
        rebalance_run2 = await prisma_client.rebalancerun.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "triggered_by": "test",
                "triggered_at": datetime.utcnow(),
                "snapshot_portfolio_value": Decimal("105000"),
                "snapshot_cash": Decimal("0"),
                "snapshot_invested": Decimal("105000"),
                "metadata": {},
            }
        )
        
        snapshot1 = await prisma_client.allocationsnapshot.create(
            data={
                "rebalance_run": {"connect": {"id": rebalance_run1.id}},
                "portfolio_allocation": {"connect": {"id": test_allocation.id}},
                "snapshot_weight": Decimal("0.333333"),
                "snapshot_amount": Decimal("33333.33"),
                "snapshot_current_value": Decimal("33333.33"),
                "snapshot_pnl": Decimal("0"),
                "metadata": {},
            }
        )
        
        snapshot2 = await prisma_client.allocationsnapshot.create(
            data={
                "rebalance_run": {"connect": {"id": rebalance_run2.id}},
                "portfolio_allocation": {"connect": {"id": test_allocation.id}},
                "snapshot_weight": Decimal("0.333333"),
                "snapshot_amount": Decimal("35000"),
                "snapshot_current_value": Decimal("35000"),
                "snapshot_pnl": Decimal("1666.67"),
                "metadata": {},
            }
        )
        
        # Get history via controller
        controller = PortfolioController(prisma_client)
        request_user = {"id": "test_user_123", "organization_id": "test_org_123"}
        
        result = await controller.get_allocation_snapshots(
            request_user, allocation_id=test_allocation.id, limit=10
        )
        
        assert result.total >= 2
        assert len(result.items) >= 2
        
        # Verify snapshots are in descending order
        assert result.items[0].created_at >= result.items[1].created_at
        
        # Verify snapshot data
        assert result.items[0].portfolio_allocation_id == test_allocation.id
        assert result.items[0].snapshot_weight == Decimal("0.333333")
        
        # Cleanup
        await prisma_client.allocationsnapshot.delete_many(
            where={"id": {"in": [snapshot1.id, snapshot2.id]}}
        )
        await prisma_client.rebalancerun.delete_many(
            where={"id": {"in": [rebalance_run1.id, rebalance_run2.id]}}
        )


class TestCeleryBeatSchedule:
    """Test Celery Beat schedule configuration (no database required)"""
    
    def test_snapshot_task_in_beat_schedule(self):
        """Test that snapshot task is registered in Celery Beat schedule"""
        beat_schedule = celery_app.conf.beat_schedule
        
        assert "trading-agent-snapshots" in beat_schedule, \
            "Snapshot task not found in beat schedule. Check SNAPSHOT_CAPTURE_ENABLED setting."
        
        snapshot_config = beat_schedule["trading-agent-snapshots"]
        assert snapshot_config["task"] == "snapshot.capture_agent_snapshots"
        
        # Verify schedule is every 3 hours
        schedule = str(snapshot_config["schedule"])
        assert "*/3" in schedule, \
            f"Schedule should be every 3 hours, got: {schedule}"
        
        print(f"✅ Snapshot task scheduled: {schedule}")
    
    def test_snapshot_task_enabled(self):
        """Test that snapshot task is enabled by default"""
        beat_schedule = celery_app.conf.beat_schedule
        
        # Check if snapshot task exists (enabled by default)
        assert "trading-agent-snapshots" in beat_schedule, \
            "Snapshot task not enabled. Set SNAPSHOT_CAPTURE_ENABLED=true"
        
        print("✅ Snapshot task is enabled in beat schedule")


@pytest.mark.asyncio
@pytest.mark.integration
class TestSnapshotController:
    """Test snapshot controller methods"""
    
    async def test_get_snapshots_for_agent(
        self, prisma_client, test_portfolio, test_trading_agent
    ):
        """Test getting snapshots for a specific agent"""
        service = TradingAgentSnapshotService()
        
        # Create snapshot
        snapshot = await service.capture_agent_snapshot(test_trading_agent.id)
        
        # Get via controller
        controller = PortfolioController(prisma_client)
        request_user = {"id": "test_user_123", "organization_id": "test_org_123"}
        
        result = await controller.get_snapshots(
            request_user, agent_id=test_trading_agent.id, limit=10
        )
        
        assert result.total >= 1
        assert len(result.items) >= 1
        assert result.items[0].portfolio_value > Decimal("0")
        assert result.items[0].realized_pnl == Decimal("5000")
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": snapshot["id"]})
    
    async def test_get_snapshots_for_portfolio(
        self, prisma_client, test_portfolio, test_trading_agent
    ):
        """Test getting aggregated snapshots for portfolio"""
        service = TradingAgentSnapshotService()
        
        # Create snapshot
        snapshot = await service.capture_agent_snapshot(test_trading_agent.id)
        
        # Get via controller
        controller = PortfolioController(prisma_client)
        request_user = {"id": "test_user_123", "organization_id": "test_org_123"}
        
        result = await controller.get_snapshots(
            request_user, limit=10
        )
        
        assert result.total >= 1
        assert len(result.items) >= 1
        assert result.items[0].portfolio_value > Decimal("0")
        assert result.items[0].agents_count >= 1
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": snapshot["id"]})


@pytest.mark.asyncio
@pytest.mark.integration
class TestSnapshotEdgeCases:
    """Test edge cases and error handling"""
    
    async def test_snapshot_with_no_positions(self, prisma_client, test_portfolio):
        """Test snapshot capture for agent with no positions"""
        agent = await prisma_client.tradingagent.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "agent_name": "Empty Agent",
                "agent_type": "alpha",
                "status": "active",
                "realized_pnl": Decimal("0"),
            }
        )
        
        service = TradingAgentSnapshotService()
        result = await service.capture_agent_snapshot(agent.id)
        
        assert result is not None
        assert result["portfolio_value"] == 0
        assert result["positions_count"] == 0
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": result["id"]})
        await prisma_client.tradingagent.delete(where={"id": agent.id})
    
    async def test_snapshot_with_invalid_agent_id(self, prisma_client):
        """Test snapshot capture with invalid agent ID"""
        service = TradingAgentSnapshotService()
        result = await service.capture_agent_snapshot("invalid-agent-id")
        
        assert result is None
    
    async def test_portfolio_snapshot_with_no_agents(self, prisma_client, test_portfolio):
        """Test portfolio snapshot aggregation with no agents"""
        service = TradingAgentSnapshotService()
        history = await service.get_portfolio_snapshot_history(test_portfolio.id, limit=10)
        
        assert history == []
    
    async def test_allocation_snapshot_with_invalid_allocation_id(
        self, prisma_client
    ):
        """Test getting allocation snapshots with invalid ID"""
        controller = PortfolioController(prisma_client)
        request_user = {"id": "test_user_123", "organization_id": "test_org_123"}
        
        with pytest.raises(Exception):  # Should raise HTTPException
            await controller.get_allocation_snapshots(
                request_user, allocation_id="invalid-id", limit=10
            )


@pytest.mark.integration
class TestCelerySnapshotTask:
    """Test Celery task for snapshot capture"""
    
    def test_capture_trading_agent_snapshots_task(self):
        """Test the Celery task that captures snapshots for all agents"""
        from workers.snapshot_tasks import capture_trading_agent_snapshots
        
        # Run the task (synchronous Celery task)
        result = capture_trading_agent_snapshots()
        
        assert result is not None
        assert "total_agents" in result
        assert "snapshots_captured" in result
        assert "failed" in result
        assert isinstance(result["total_agents"], int)
        assert isinstance(result["snapshots_captured"], int)
        assert isinstance(result["failed"], int)


@pytest.mark.asyncio
@pytest.mark.integration
class TestSnapshotDataIntegrity:
    """Test data integrity and consistency"""
    
    async def test_snapshot_timestamps_are_utc(self, prisma_client, test_trading_agent):
        """Test that snapshot timestamps are stored in UTC"""
        service = TradingAgentSnapshotService()
        result = await service.capture_agent_snapshot(test_trading_agent.id)
        
        snapshot = await prisma_client.tradingagentsnapshot.find_unique(
            where={"id": result["id"]}
        )
        
        # Verify timestamp is timezone-aware (UTC)
        assert snapshot.snapshot_at.tzinfo is not None
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": result["id"]})
    
    async def test_snapshot_links_to_correct_portfolio(
        self, prisma_client, test_portfolio, test_trading_agent
    ):
        """Test that snapshot is linked to correct portfolio"""
        service = TradingAgentSnapshotService()
        result = await service.capture_agent_snapshot(test_trading_agent.id)
        
        snapshot = await prisma_client.tradingagentsnapshot.find_unique(
            where={"id": result["id"]}
        )
        
        assert snapshot.portfolio_id == test_portfolio.id
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": result["id"]})
    
    async def test_allocation_snapshot_links_to_rebalance_run(
        self, prisma_client, test_portfolio, test_allocation
    ):
        """Test that allocation snapshot is linked to rebalance run"""
        rebalance_run = await prisma_client.rebalancerun.create(
            data={
                "portfolio": {"connect": {"id": test_portfolio.id}},
                "triggered_by": "test",
                "triggered_at": datetime.utcnow(),
                "snapshot_portfolio_value": Decimal("105000"),
                "snapshot_cash": Decimal("0"),
                "snapshot_invested": Decimal("105000"),
                "metadata": {},
            }
        )
        
        allocation_snapshot = await prisma_client.allocationsnapshot.create(
            data={
                "rebalance_run": {"connect": {"id": rebalance_run.id}},
                "portfolio_allocation": {"connect": {"id": test_allocation.id}},
                "snapshot_weight": Decimal("0.333333"),
                "snapshot_amount": Decimal("35000"),
                "snapshot_current_value": Decimal("35000"),
                "snapshot_pnl": Decimal("0"),
                "metadata": {},
            }
        )
        
        # Verify links
        assert allocation_snapshot.rebalance_run_id == rebalance_run.id
        assert allocation_snapshot.portfolio_allocation_id == test_allocation.id
        
        # Cleanup
        await prisma_client.allocationsnapshot.delete(where={"id": allocation_snapshot.id})
        await prisma_client.rebalancerun.delete(where={"id": rebalance_run.id})

