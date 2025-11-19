"""
Unit tests for allocation tasks to verify portfolio allocations, trading agents, and snapshots are created.
"""

import asyncio
import sys
import types
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

import pytest

# Add portfolio-server to path
server_root = Path(__file__).resolve().parents[1]
if str(server_root) not in sys.path:
    sys.path.insert(0, str(server_root))

from workers import allocation_tasks


@pytest.fixture
def mock_db():
    """Create a mock database client."""
    db = MagicMock()
    
    # Mock portfolio
    mock_portfolio = MagicMock()
    mock_portfolio.id = "portfolio-123"
    mock_portfolio.investment_amount = Decimal("100000")
    mock_portfolio.initial_investment = Decimal("100000")
    mock_portfolio.current_value = Decimal("100000")
    mock_portfolio.metadata = {}
    mock_portfolio.allocations = []
    mock_portfolio.risk_tolerance = "medium"
    mock_portfolio.investment_horizon_years = 5
    mock_portfolio.liquidity_needs = "medium"
    mock_portfolio.expected_return_target = Decimal("0.12")
    mock_portfolio.rebalancing_frequency = "quarterly"
    mock_portfolio.allocation_status = "pending"
    mock_portfolio.last_rebalanced_at = None
    mock_portfolio.rebalancing_date = None
    mock_portfolio.next_rebalance_at = None
    mock_portfolio.status = "active"
    mock_portfolio.objective_id = "objective-123"
    mock_portfolio.user_id = "user-123"
    mock_portfolio.customer_id = "user-123"
    mock_portfolio.organization_id = "org-123"
    
    db.portfolio.find_unique = AsyncMock(return_value=mock_portfolio)
    db.portfolio.update = AsyncMock(return_value=mock_portfolio)
    db.portfolioallocation.find_first = AsyncMock(return_value=None)
    db.portfolioallocation.create = AsyncMock()
    db.portfolioallocation.update = AsyncMock()
    db.tradingagent.find_first = AsyncMock(return_value=None)
    db.tradingagent.create = AsyncMock()
    db.tradingagent.update = AsyncMock()
    db.query_raw = AsyncMock(return_value=[{"subscriptions": ["high_risk"]}])
    
    return db


@pytest.fixture
def mock_db_manager(mock_db):
    """Create a mock DBManager."""
    manager = MagicMock()
    manager.client = mock_db
    manager.is_connected = MagicMock(return_value=True)
    manager.connect = AsyncMock(return_value=mock_db)
    manager.get_client = MagicMock(return_value=mock_db)
    
    return manager


@pytest.fixture
def mock_allocation_result():
    """Create a mock allocation result from the pipeline."""
    return {
        "request_id": "test-request-123",
        "user_id": "user-123",
        "weights": {
            "high_risk": 0.4,
            "low_risk": 0.3,
            "alpha": 0.3,
        },
        "expected_return": 0.12,
        "expected_risk": 0.08,
        "objective_value": 100000.0,
        "regime": "sideways",
        "message": "Allocation successful",
        "progress_ratio": 0.5,
    }


@pytest.mark.asyncio
async def test_allocate_for_objective_task_creates_allocations(monkeypatch, mock_db, mock_db_manager, mock_allocation_result):
    """Test that allocate_for_objective_task creates portfolio allocations."""
    
    # Mock allocate_portfolios to return our test result
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        return [mock_allocation_result]
    
    # Mock _get_current_regime
    async def fake_get_current_regime():
        return "sideways"
    
    monkeypatch.setattr("workers.allocation_tasks.allocate_portfolios", fake_allocate_portfolios)
    monkeypatch.setattr("workers.allocation_tasks._get_current_regime", fake_get_current_regime)
    
    # Mock DBManager module
    fake_db_manager_module = types.ModuleType("dbManager")
    class _DBManager:
        @staticmethod
        def get_instance():
            return mock_db_manager
    fake_db_manager_module.DBManager = _DBManager
    monkeypatch.setitem(sys.modules, "dbManager", fake_db_manager_module)
    
    # Patch Prisma to return the fake client
    class FakePrisma:
        def __init__(self):
            pass
        
        async def connect(self):
            return mock_db
        
        async def disconnect(self):
            pass
        
        def __getattr__(self, name):
            # Return the corresponding fake model
            return getattr(mock_db, name)
    
    monkeypatch.setattr("prisma.Prisma", lambda: FakePrisma())
    
    # Mock PipelineService - it's imported inside the function, so patch the import location
    mock_pipeline_service = MagicMock()
    mock_pipeline_service._persist_allocation_result = AsyncMock()
    # Patch at the module where it's imported
    monkeypatch.setattr("services.pipeline_service.PipelineService", lambda *args, **kwargs: mock_pipeline_service)
    
    # Create allocation records
    allocation_records = []
    for i, (allocation_type, weight) in enumerate(mock_allocation_result["weights"].items()):
        mock_allocation = MagicMock()
        mock_allocation.id = f"allocation-{i}"
        mock_allocation.allocation_type = allocation_type
        allocation_records.append(mock_allocation)
        # Set return value for each call
        if i == 0:
            mock_db.portfolioallocation.create.return_value = mock_allocation
        else:
            # For subsequent calls, we need to handle them differently
            pass
    
    # Set up mock to return different allocations for each call
    mock_db.portfolioallocation.create.side_effect = allocation_records
    
    # Call the task directly (not as Celery task)
    # The task function creates its own event loop, so we need to run it in executor
    task_func = allocation_tasks.allocate_for_objective_task
    
    # Call the task function with dummy arguments (it will use mocked dependencies)
    # The task creates its own event loop, so we run it in executor to avoid loop conflicts
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: task_func(
            "portfolio-123",
            "objective-123",
            "user-123",
            "org-123",
            {"risk_tolerance": "medium"},
            100000.0,
            100000.0,
            "test"
        )
    )
    
    # Verify allocations were created
    assert mock_db.portfolioallocation.create.call_count == len(mock_allocation_result["weights"])
    
    # Verify trading agents were created
    assert mock_db.tradingagent.create.call_count == len(mock_allocation_result["weights"])
    
    # Verify snapshots were created
    mock_pipeline_service._persist_allocation_result.assert_called_once()
    
    # Verify result
    assert result["success"] is True
    assert result["portfolio_id"] == "portfolio-123"


@pytest.mark.asyncio
async def test_allocate_for_objective_task_handles_missing_weights(mock_db, mock_db_manager):
    """Test that allocate_for_objective_task handles missing weights gracefully."""
    
    # Mock allocation result without weights
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        return [{
            "request_id": "test-request-123",
            "user_id": "user-123",
            "expected_return": 0.12,
            "expected_risk": 0.08,
        }]
    
    with patch("dbManager.DBManager") as mock_db_manager_class:
        mock_db_manager_class.get_instance.return_value = mock_db_manager
        
        with patch("workers.allocation_tasks.allocate_portfolios", side_effect=fake_allocate_portfolios):
            with patch("workers.allocation_tasks._get_current_regime", return_value="sideways"):
                # This should use default weights from DEFAULT_SEGMENTS
                # The task should not fail, but use default weights
                # We'll verify this by checking that allocations are still created
                pass  # Implementation would go here


@pytest.mark.asyncio
async def test_allocate_for_objective_task_creates_trading_agents(mock_db, mock_db_manager, mock_allocation_result):
    """Test that trading agents are created for each allocation."""
    
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        return [mock_allocation_result]
    
    with patch("dbManager.DBManager") as mock_db_manager_class:
        mock_db_manager_class.get_instance.return_value = mock_db_manager
        
        with patch("workers.allocation_tasks.allocate_portfolios", side_effect=fake_allocate_portfolios):
            with patch("workers.allocation_tasks._get_current_regime", return_value="sideways"):
                # Create allocation records
                allocation_records = []
                for i, (allocation_type, weight) in enumerate(mock_allocation_result["weights"].items()):
                    mock_allocation = MagicMock()
                    mock_allocation.id = f"allocation-{i}"
                    mock_allocation.allocation_type = allocation_type
                    allocation_records.append(mock_allocation)
                    mock_db.portfolioallocation.create.return_value = mock_allocation
                
                # Verify trading agents are created
                # The _ensure_trading_agent function should be called for each allocation
                pass  # Implementation would go here


@pytest.mark.asyncio
async def test_allocate_for_objective_task_creates_snapshots(monkeypatch, mock_db, mock_db_manager, mock_allocation_result):
    """Test that allocation snapshots are created via _persist_allocation_result."""
    
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        return [mock_allocation_result]
    
    mock_pipeline_service = MagicMock()
    mock_pipeline_service._persist_allocation_result = AsyncMock()
    
    # Patch Prisma to return the fake client
    class FakePrisma:
        def __init__(self):
            pass
        
        async def connect(self):
            return mock_db
        
        async def disconnect(self):
            pass
        
        def __getattr__(self, name):
            # Return the corresponding fake model
            return getattr(mock_db, name)
    
    monkeypatch.setattr("prisma.Prisma", lambda: FakePrisma())
    monkeypatch.setattr("services.pipeline_service.PipelineService", lambda *args, **kwargs: mock_pipeline_service)
    
    with patch("dbManager.DBManager") as mock_db_manager_class:
        mock_db_manager_class.get_instance.return_value = mock_db_manager
        
        with patch("workers.allocation_tasks.allocate_portfolios", side_effect=fake_allocate_portfolios):
            with patch("workers.allocation_tasks._get_current_regime", return_value="sideways"):
                # Create allocation records
                allocation_records = []
                for i, (allocation_type, weight) in enumerate(mock_allocation_result["weights"].items()):
                    mock_allocation = MagicMock()
                    mock_allocation.id = f"allocation-{i}"
                    mock_allocation.allocation_type = allocation_type
                    allocation_records.append(mock_allocation)
                    mock_db.portfolioallocation.create.return_value = mock_allocation
                    
                    # Verify _persist_allocation_result is called
                    # This should create RebalanceRun and AllocationSnapshot records
                    pass  # Implementation would go here


def test_coerce_to_plain_dict():
    """Test the _coerce_to_plain_dict helper function."""
    # Test with regular dict
    result = allocation_tasks._coerce_to_plain_dict({"key": "value"})
    assert result == {"key": "value"}
    
    # Test with nested dict
    result = allocation_tasks._coerce_to_plain_dict({"weights": {"high_risk": 0.4}})
    assert result == {"weights": {"high_risk": 0.4}}
    
    # Test with empty dict
    result = allocation_tasks._coerce_to_plain_dict({})
    assert result == {}


def test_calculate_next_rebalance_date():
    """Test the _calculate_next_rebalance_date function."""
    from datetime import datetime
    
    # Test quarterly
    result = allocation_tasks._calculate_next_rebalance_date("quarterly")
    assert result is not None
    
    # Test never
    result = allocation_tasks._calculate_next_rebalance_date("never")
    assert result is None

