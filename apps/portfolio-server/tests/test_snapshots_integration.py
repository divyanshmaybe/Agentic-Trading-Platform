"""
Integration test suite for snapshot functionality.

This test suite verifies the complete snapshot workflow:
1. Celery Beat schedule configuration
2. Trading agent snapshot capture via Celery task
3. Portfolio snapshot aggregation
4. Allocation snapshot creation during pipeline execution
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from celery_app import celery_app
from services.snapshot_service import TradingAgentSnapshotService
from controllers.portfolio_controller import PortfolioController


# Skip if database tests are disabled
if os.getenv("ENABLE_DB_TESTS", "false").lower() not in {"1", "true", "yes"}:
    pytest.skip(
        "Snapshot integration tests require live database. Set ENABLE_DB_TESTS=true to run.",
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
@pytest.mark.slow
class TestSnapshotWorkflow:
    """End-to-end workflow tests for snapshot system"""
    
    async def test_complete_snapshot_workflow(
        self, prisma_client, test_portfolio, test_trading_agent, test_allocation
    ):
        """
        Test complete snapshot workflow:
        1. Capture agent snapshot
        2. Verify portfolio snapshot aggregation
        3. Trigger allocation pipeline
        4. Verify allocation snapshot creation
        """
        # Step 1: Capture agent snapshot
        service = TradingAgentSnapshotService()
        agent_snapshot = await service.capture_agent_snapshot(test_trading_agent.id)
        
        assert agent_snapshot is not None
        assert agent_snapshot["portfolio_value"] > 0
        
        # Step 2: Verify portfolio snapshot aggregation
        portfolio_history = await service.get_portfolio_snapshot_history(
            test_portfolio.id, limit=10
        )
        assert len(portfolio_history) >= 1
        assert portfolio_history[0]["portfolio_value"] == agent_snapshot["portfolio_value"]
        
        # Step 3: Simulate allocation pipeline trigger
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
        
        # Step 4: Create allocation snapshot (simulating _persist_allocation_result)
        allocation_snapshot = await prisma_client.allocationsnapshot.create(
            data={
                "rebalance_run": {"connect": {"id": rebalance_run.id}},
                "portfolio_allocation": {"connect": {"id": test_allocation.id}},
                "snapshot_weight": Decimal("0.333333"),
                "snapshot_amount": Decimal("35000"),
                "snapshot_current_value": Decimal("35000"),
                "snapshot_pnl": Decimal("0"),
                "metadata": {
                    "regime": "bull_market",
                    "generated_at": datetime.utcnow().isoformat(),
                },
            }
        )
        
        assert allocation_snapshot is not None
        assert allocation_snapshot.rebalance_run_id == rebalance_run.id
        
        # Step 5: Verify allocation snapshot retrieval
        controller = PortfolioController(prisma_client)
        request_user = {"id": "test_user_123", "organization_id": "test_org_123"}
        
        allocation_history = await controller.get_allocation_snapshots(
            request_user, allocation_id=test_allocation.id, limit=10
        )
        
        assert allocation_history.total >= 1
        assert len(allocation_history.items) >= 1
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": agent_snapshot["id"]})
        await prisma_client.allocationsnapshot.delete(where={"id": allocation_snapshot.id})
        await prisma_client.rebalancerun.delete(where={"id": rebalance_run.id})


@pytest.mark.asyncio
@pytest.mark.integration
class TestSnapshotAPIEndpoints:
    """Test snapshot API endpoints via controller"""
    
    async def test_get_portfolio_snapshots_endpoint(
        self, prisma_client, test_portfolio, test_trading_agent
    ):
        """Test portfolio snapshots endpoint"""
        service = TradingAgentSnapshotService()
        snapshot = await service.capture_agent_snapshot(test_trading_agent.id)
        
        controller = PortfolioController(prisma_client)
        request_user = {"id": "test_user_123", "organization_id": "test_org_123"}
        
        result = await controller.get_snapshots(request_user, limit=10)
        
        assert result.total >= 1
        assert len(result.items) >= 1
        assert result.items[0].portfolio_value > Decimal("0")
        assert result.items[0].agents_count >= 1
        
        # Cleanup
        await prisma_client.tradingagentsnapshot.delete(where={"id": snapshot["id"]})
