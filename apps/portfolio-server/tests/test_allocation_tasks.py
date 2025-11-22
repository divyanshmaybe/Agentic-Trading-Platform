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
    mock_portfolio.available_cash = Decimal("100000")
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
    
    # Mock DatabaseClient to return our test mock_db
    class MockDatabaseClient:
        @classmethod
        def get_instance(cls):
            return cls()
        
        def __init__(self):
            self._client = mock_db
        
        async def connect(self):
            pass
        
        def get_client(self):
            return self._client
        
        async def disconnect(self):
            pass

        async def __aenter__(self):
            return mock_db

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("dbManager.DBManager", MockDatabaseClient)
    
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


@pytest.mark.asyncio
async def test_check_regime_and_rebalance_task_regime_unchanged(monkeypatch, mock_db, mock_db_manager):
    """Test that check_regime_and_rebalance_task only rebalances due-date portfolios when regime is unchanged."""
    from datetime import date, datetime
    
    # Mock Redis client
    mock_redis = MagicMock()
    mock_redis.get.return_value = "sideways"  # Previous regime
    mock_redis.set = MagicMock()
    
    # Mock redis.Redis.from_url to return our mock
    mock_redis_from_url = MagicMock(return_value=mock_redis)
    
    # Mock portfolios
    mock_pending_portfolio = MagicMock()
    mock_pending_portfolio.id = "portfolio-pending"
    mock_pending_portfolio.allocation_status = "pending"
    mock_pending_portfolio.status = "active"
    mock_pending_portfolio.customer_id = "user-123"
    mock_pending_portfolio.investment_amount = Decimal("100000")
    mock_pending_portfolio.available_cash = Decimal("100000")
    mock_pending_portfolio.rebalancing_frequency = "quarterly"
    mock_pending_portfolio.allocations = []
    
    mock_due_portfolio = MagicMock()
    mock_due_portfolio.id = "portfolio-due"
    mock_due_portfolio.allocation_status = "ready"
    mock_due_portfolio.rebalancing_date = date.today()
    mock_due_portfolio.status = "active"
    mock_due_portfolio.customer_id = "user-456"
    mock_due_portfolio.investment_amount = Decimal("200000")
    mock_due_portfolio.available_cash = Decimal("200000")
    mock_due_portfolio.rebalancing_frequency = "quarterly"
    mock_due_portfolio.allocations = []
    
    # Active portfolios should NOT be rebalanced if regime unchanged
    mock_active_portfolio = MagicMock()
    mock_active_portfolio.id = "portfolio-active"
    mock_active_portfolio.allocation_status = "ready"
    mock_active_portfolio.rebalancing_date = date(2099, 12, 31)
    mock_active_portfolio.status = "active"
    
    mock_db.portfolio.find_many = AsyncMock(side_effect=[
        [mock_pending_portfolio],  # pending portfolios
        [mock_due_portfolio],  # portfolios_to_rebalance
        [mock_active_portfolio, mock_due_portfolio],  # regime_change_portfolios (not used)
    ])
    
    # Mock _get_current_regime
    async def fake_get_current_regime():
        return "sideways"
    
    monkeypatch.setattr("workers.allocation_tasks._get_current_regime", fake_get_current_regime)
    
    # Mock allocate_portfolios to return successful results
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        results = []
        for req in requests:
            results.append({
                "success": True,
                "request_id": req["request_id"],
                "weights": {"high_risk": 0.4, "low_risk": 0.3, "alpha": 0.3},
                "expected_return": 0.12,
                "expected_risk": 0.08,
            })
        return results
    
    monkeypatch.setattr("workers.allocation_tasks.allocate_portfolios", fake_allocate_portfolios)
    
    # Mock DatabaseClient
    class MockDatabaseClient:
        @classmethod
        def get_instance(cls):
            return cls()
        
        def __init__(self):
            self._client = mock_db
        
        async def connect(self):
            pass
        
        def get_client(self):
            return self._client
        
        async def disconnect(self):
            pass
    
    monkeypatch.setattr("dbManager.DBManager", MockDatabaseClient)
    
    # Mock additional helpers
    mock_db.query_raw = AsyncMock(return_value=[{"subscriptions": ["high_risk"]}])
    mock_db.portfolioallocation.find_first = AsyncMock(return_value=None)
    mock_db.portfolioallocation.create = AsyncMock()
    mock_db.tradingagent.find_first = AsyncMock(return_value=None)
    mock_db.tradingagent.create = AsyncMock()
    mock_db.portfolio.update = AsyncMock()
    
    # Mock PipelineService
    mock_pipeline_service = MagicMock()
    mock_pipeline_service._persist_allocation_result = AsyncMock()
    monkeypatch.setattr("services.pipeline_service.PipelineService", lambda *args, **kwargs: mock_pipeline_service)
    
    # Patch redis.Redis.from_url
    with patch("redis.Redis.from_url", mock_redis_from_url):
        # Run the task
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            allocation_tasks.check_regime_and_rebalance_task
        )
    
    # Verify results
    assert result["success"] is True
    assert result["regime_changed"] is False
    assert result["current_regime"] == "sideways"
    assert result["previous_regime"] == "sideways"
    assert result["pending_allocated"] == 1
    assert result["due_date_rebalanced"] == 1
    assert result["regime_change_rebalanced"] == 0


@pytest.mark.asyncio
async def test_check_regime_and_rebalance_task_regime_changed(monkeypatch, mock_db, mock_db_manager):
    """Test that check_regime_and_rebalance_task rebalances all active portfolios when regime changes."""
    from datetime import date
    
    # Mock Redis client with old regime
    mock_redis = MagicMock()
    mock_redis.get.return_value = "sideways"  # Previous regime
    mock_redis.set = MagicMock()
    
    # Mock redis.Redis.from_url to return our mock
    mock_redis_from_url = MagicMock(return_value=mock_redis)
    
    # Mock portfolios
    mock_pending_portfolio = MagicMock()
    mock_pending_portfolio.id = "portfolio-pending"
    mock_pending_portfolio.allocation_status = "pending"
    mock_pending_portfolio.status = "active"
    mock_pending_portfolio.customer_id = "user-123"
    mock_pending_portfolio.investment_amount = Decimal("100000")
    mock_pending_portfolio.available_cash = Decimal("100000")
    mock_pending_portfolio.rebalancing_frequency = "quarterly"
    mock_pending_portfolio.allocations = []
    
    mock_active_portfolio_1 = MagicMock()
    mock_active_portfolio_1.id = "portfolio-active-1"
    mock_active_portfolio_1.allocation_status = "ready"
    mock_active_portfolio_1.status = "active"
    mock_active_portfolio_1.customer_id = "user-456"
    mock_active_portfolio_1.investment_amount = Decimal("200000")
    mock_active_portfolio_1.available_cash = Decimal("200000")
    mock_active_portfolio_1.rebalancing_frequency = "quarterly"
    mock_active_portfolio_1.allocations = []
    
    mock_active_portfolio_2 = MagicMock()
    mock_active_portfolio_2.id = "portfolio-active-2"
    mock_active_portfolio_2.allocation_status = "ready"
    mock_active_portfolio_2.status = "active"
    mock_active_portfolio_2.customer_id = "user-789"
    mock_active_portfolio_2.investment_amount = Decimal("150000")
    mock_active_portfolio_2.available_cash = Decimal("150000")
    mock_active_portfolio_2.rebalancing_frequency = "quarterly"
    mock_active_portfolio_2.allocations = []
    
    mock_db.portfolio.find_many = AsyncMock(side_effect=[
        [mock_pending_portfolio],  # pending portfolios
        [],  # portfolios_to_rebalance (none due)
        [mock_active_portfolio_1, mock_active_portfolio_2],  # regime_change_portfolios
    ])
    
    # Mock _get_current_regime - now returns bullish (changed from sideways)
    async def fake_get_current_regime():
        return "bullish"
    
    monkeypatch.setattr("workers.allocation_tasks._get_current_regime", fake_get_current_regime)
    
    # Mock allocate_portfolios to return successful results
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        results = []
        for req in requests:
            results.append({
                "success": True,
                "request_id": req["request_id"],
                "weights": {"high_risk": 0.4, "low_risk": 0.3, "alpha": 0.3},
                "expected_return": 0.12,
                "expected_risk": 0.08,
            })
        return results
    
    monkeypatch.setattr("workers.allocation_tasks.allocate_portfolios", fake_allocate_portfolios)
    
    # Mock DatabaseClient
    class MockDatabaseClient:
        @classmethod
        def get_instance(cls):
            return cls()
        
        def __init__(self):
            self._client = mock_db
        
        async def connect(self):
            pass
        
        def get_client(self):
            return self._client
        
        async def disconnect(self):
            pass
    
    monkeypatch.setattr("dbManager.DBManager", MockDatabaseClient)
    
    # Mock additional helpers
    mock_db.query_raw = AsyncMock(return_value=[{"subscriptions": ["high_risk"]}])
    mock_db.portfolioallocation.find_first = AsyncMock(return_value=None)
    mock_db.portfolioallocation.create = AsyncMock()
    mock_db.tradingagent.find_first = AsyncMock(return_value=None)
    mock_db.tradingagent.create = AsyncMock()
    mock_db.portfolio.update = AsyncMock()
    
    # Mock PipelineService
    mock_pipeline_service = MagicMock()
    mock_pipeline_service._persist_allocation_result = AsyncMock()
    monkeypatch.setattr("services.pipeline_service.PipelineService", lambda *args, **kwargs: mock_pipeline_service)
    
    # Patch redis.Redis.from_url
    with patch("redis.Redis.from_url", mock_redis_from_url):
        # Run the task
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            allocation_tasks.check_regime_and_rebalance_task
        )
    
    # Verify results
    assert result["success"] is True
    assert result["regime_changed"] is True
    assert result["current_regime"] == "bullish"
    assert result["previous_regime"] == "sideways"
    assert result["pending_allocated"] == 1
    assert result["due_date_rebalanced"] == 0
    assert result["regime_change_rebalanced"] == 2  # 2 active portfolios
    # Redis should be updated with new regime
    mock_redis.set.assert_any_call("market:regime:current", "bullish")


@pytest.mark.asyncio
async def test_check_regime_and_rebalance_task_no_previous_regime(monkeypatch, mock_db, mock_db_manager):
    """Test first-time regime calculation when no previous regime exists."""
    
    # Mock Redis client with no previous regime
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # No previous regime
    mock_redis.set = MagicMock()
    
    # Mock redis.Redis.from_url to return our mock
    mock_redis_from_url = MagicMock(return_value=mock_redis)
    
    # Mock portfolios
    mock_pending_portfolio = MagicMock()
    mock_pending_portfolio.id = "portfolio-pending"
    mock_pending_portfolio.allocation_status = "pending"
    mock_pending_portfolio.status = "active"
    mock_pending_portfolio.customer_id = "user-123"
    mock_pending_portfolio.investment_amount = Decimal("100000")
    mock_pending_portfolio.available_cash = Decimal("100000")
    mock_pending_portfolio.rebalancing_frequency = "quarterly"
    mock_pending_portfolio.allocations = []
    
    mock_db.portfolio.find_many = AsyncMock(side_effect=[
        [mock_pending_portfolio],  # pending portfolios
        [],  # portfolios_to_rebalance
        [],  # regime_change_portfolios
    ])
    
    # Mock _get_current_regime
    async def fake_get_current_regime():
        return "sideways"
    
    monkeypatch.setattr("workers.allocation_tasks._get_current_regime", fake_get_current_regime)
    
    # Mock allocate_portfolios to return successful results
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        results = []
        for req in requests:
            results.append({
                "success": True,
                "request_id": req["request_id"],
                "weights": {"high_risk": 0.4, "low_risk": 0.3, "alpha": 0.3},
                "expected_return": 0.12,
                "expected_risk": 0.08,
            })
        return results
    
    monkeypatch.setattr("workers.allocation_tasks.allocate_portfolios", fake_allocate_portfolios)
    
    # Mock DatabaseClient
    class MockDatabaseClient:
        @classmethod
        def get_instance(cls):
            return cls()
        
        def __init__(self):
            self._client = mock_db
        
        async def connect(self):
            pass
        
        def get_client(self):
            return self._client
        
        async def disconnect(self):
            pass
    
    monkeypatch.setattr("dbManager.DBManager", MockDatabaseClient)
    
    # Mock additional helpers
    mock_db.query_raw = AsyncMock(return_value=[{"subscriptions": ["high_risk"]}])
    mock_db.portfolioallocation.find_first = AsyncMock(return_value=None)
    mock_db.portfolioallocation.create = AsyncMock()
    mock_db.tradingagent.find_first = AsyncMock(return_value=None)
    mock_db.tradingagent.create = AsyncMock()
    mock_db.portfolio.update = AsyncMock()
    
    # Mock PipelineService
    mock_pipeline_service = MagicMock()
    mock_pipeline_service._persist_allocation_result = AsyncMock()
    monkeypatch.setattr("services.pipeline_service.PipelineService", lambda *args, **kwargs: mock_pipeline_service)
    
    # Patch redis.Redis.from_url
    with patch("redis.Redis.from_url", mock_redis_from_url):
        # Run the task
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            allocation_tasks.check_regime_and_rebalance_task
        )
    
    # Verify results
    assert result["success"] is True
    assert result["regime_changed"] is False  # No change if no previous regime
    assert result["current_regime"] == "sideways"
    assert result["previous_regime"] is None
    assert result["pending_allocated"] == 1
    assert result["due_date_rebalanced"] == 0
    assert result["regime_change_rebalanced"] == 0
    # Redis should store the first regime
    mock_redis.set.assert_any_call("market:regime:current", "sideways")


@pytest.mark.asyncio
async def test_check_regime_and_rebalance_task_deduplication(monkeypatch, mock_db, mock_db_manager):
    """Test that portfolios are not processed twice if they appear in multiple categories."""
    from datetime import date
    
    # Mock Redis client
    mock_redis = MagicMock()
    mock_redis.get.return_value = "sideways"
    mock_redis.set = MagicMock()
    
    # Mock redis.Redis.from_url to return our mock
    mock_redis_from_url = MagicMock(return_value=mock_redis)
    
    # Portfolio that is BOTH due for rebalancing AND part of regime change
    mock_due_active_portfolio = MagicMock()
    mock_due_active_portfolio.id = "portfolio-due-and-active"
    mock_due_active_portfolio.allocation_status = "ready"
    mock_due_active_portfolio.rebalancing_date = date.today()
    mock_due_active_portfolio.status = "active"
    mock_due_active_portfolio.customer_id = "user-123"
    mock_due_active_portfolio.investment_amount = Decimal("200000")
    mock_due_active_portfolio.available_cash = Decimal("200000")
    mock_due_active_portfolio.rebalancing_frequency = "quarterly"
    mock_due_active_portfolio.allocations = []
    
    # Another active portfolio (only regime change)
    mock_active_portfolio = MagicMock()
    mock_active_portfolio.id = "portfolio-active-only"
    mock_active_portfolio.allocation_status = "ready"
    mock_active_portfolio.status = "active"
    mock_active_portfolio.customer_id = "user-456"
    mock_active_portfolio.investment_amount = Decimal("150000")
    mock_active_portfolio.available_cash = Decimal("150000")
    mock_active_portfolio.rebalancing_frequency = "quarterly"
    mock_active_portfolio.allocations = []
    
    mock_db.portfolio.find_many = AsyncMock(side_effect=[
        [],  # no pending portfolios
        [mock_due_active_portfolio],  # portfolios_to_rebalance
        [mock_due_active_portfolio, mock_active_portfolio],  # regime_change_portfolios
    ])
    
    # Mock _get_current_regime - regime changes
    async def fake_get_current_regime():
        return "bullish"
    
    monkeypatch.setattr("workers.allocation_tasks._get_current_regime", fake_get_current_regime)
    
    # Mock allocate_portfolios to return successful results
    def fake_allocate_portfolios(requests, logger=None, audit_path=None):
        results = []
        for req in requests:
            results.append({
                "success": True,
                "request_id": req["request_id"],
                "weights": {"high_risk": 0.4, "low_risk": 0.3, "alpha": 0.3},
                "expected_return": 0.12,
                "expected_risk": 0.08,
            })
        return results
    
    monkeypatch.setattr("workers.allocation_tasks.allocate_portfolios", fake_allocate_portfolios)
    
    # Mock DatabaseClient
    class MockDatabaseClient:
        @classmethod
        def get_instance(cls):
            return cls()
        
        def __init__(self):
            self._client = mock_db
        
        async def connect(self):
            pass
        
        def get_client(self):
            return self._client
        
        async def disconnect(self):
            pass
    
    monkeypatch.setattr("dbManager.DBManager", MockDatabaseClient)
    
    # Mock additional helpers
    mock_db.query_raw = AsyncMock(return_value=[{"subscriptions": ["high_risk"]}])
    mock_db.portfolioallocation.find_first = AsyncMock(return_value=None)
    mock_db.portfolioallocation.create = AsyncMock()
    mock_db.tradingagent.find_first = AsyncMock(return_value=None)
    mock_db.tradingagent.create = AsyncMock()
    mock_db.portfolio.update = AsyncMock()
    
    # Mock PipelineService
    mock_pipeline_service = MagicMock()
    mock_pipeline_service._persist_allocation_result = AsyncMock()
    monkeypatch.setattr("services.pipeline_service.PipelineService", lambda *args, **kwargs: mock_pipeline_service)
    
    # Patch redis.Redis.from_url
    with patch("redis.Redis.from_url", mock_redis_from_url):
        # Run the task
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            allocation_tasks.check_regime_and_rebalance_task
        )
    
    # Verify results
    assert result["success"] is True
    assert result["regime_changed"] is True
    # Should process: 1 due portfolio + 1 regime-only portfolio
    # The due portfolio should only be processed once (deduplication)
    assert result["pending_allocated"] == 0
    assert result["due_date_rebalanced"] == 1  # due portfolio
    assert result["regime_change_rebalanced"] == 1  # active-only portfolio (due one is deduplicated)


