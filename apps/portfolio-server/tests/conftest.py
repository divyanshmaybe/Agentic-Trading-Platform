import pytest
from unittest.mock import AsyncMock, MagicMock
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

# Add the project root to the path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_SERVER_ROOT = PROJECT_ROOT / "apps" / "portfolio-server"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PORTFOLIO_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(PORTFOLIO_SERVER_ROOT))


@pytest.fixture(autouse=True)
def mock_database_client(monkeypatch):
    """Mock DatabaseClient to prevent real database connections in tests."""

    # Create a mock client
    mock_client = MagicMock()
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()

    # Mock all the database operations to return AsyncMock for async methods
    for table in ['portfolio', 'position', 'trade', 'tradeexecutionlog', 'tradingagent',
                  'portfolioallocation', 'rebalancerun', 'allocationsnapshot', 'objective']:
        table_mock = MagicMock()
        setattr(mock_client, table, table_mock)

        # Make common database operations async
        for method in ['create', 'find_unique', 'find_first', 'find_many', 'update', 'delete']:
            setattr(table_mock, method, AsyncMock())

        # Set up some default return values
        if table == 'portfolio':
            table_mock.find_unique.return_value = MagicMock(
                id="test-portfolio-id",
                available_cash=Decimal("100000"),
                total_realized_pnl=Decimal("0")
            )
            table_mock.create.return_value = MagicMock(
                id="test-portfolio-id",
                available_cash=Decimal("100000"),
                total_realized_pnl=Decimal("0")
            )
        elif table == 'position':
            table_mock.find_first.return_value = MagicMock(
                id="test-position-id",
                quantity=10,
                realized_pnl=Decimal("0")
            )
            table_mock.create.return_value = MagicMock(
                id="test-position-id",
                quantity=10,
                realized_pnl=Decimal("0")
            )
        elif table == 'trade':
            table_mock.create.return_value = MagicMock(
                id="test-trade-id",
                executed_price=Decimal("100"),
                executed_quantity=10
            )
        elif table == 'tradeexecutionlog':
            table_mock.create.return_value = MagicMock(id="test-log-id")
        elif table == 'tradingagent':
            table_mock.create.return_value = MagicMock(id="test-agent-id")
        elif table == 'portfolioallocation':
            table_mock.create.return_value = MagicMock(id="test-allocation-id")

    # Mock the DatabaseClient context manager
    class MockDatabaseClient:
        def __init__(self):
            self._client = mock_client

        async def __aenter__(self):
            return mock_client

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    # Mock the DatabaseClient class
    monkeypatch.setattr("db_client.DatabaseClient", MockDatabaseClient)

    # Also mock get_db_client function
    async def mock_get_db_client():
        return mock_client

    monkeypatch.setattr("db_client.get_db_client", mock_get_db_client)

    return mock_client