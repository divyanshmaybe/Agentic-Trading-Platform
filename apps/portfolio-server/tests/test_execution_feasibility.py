import pytest
from unittest.mock import MagicMock, patch
from services.execution_feasibility_service import ExecutionFeasibilityService, FeasibilityResult

@pytest.mark.asyncio
async def test_t2t_intraday_block():
    # Mock MarketDataService
    mock_market_service = MagicMock()
    mock_market_service._get_token_info.return_value = {
        "_matched_key": "PRAXIS-BE",
        "symbol": "PRAXIS-BE",
    }
    mock_market_service._normalize_symbol.return_value = "PRAXIS"

    with patch("services.execution_feasibility_service.get_market_data_service", return_value=mock_market_service):
        service = ExecutionFeasibilityService()
        
        # Test intraday T2T (should be blocked)
        result = await service.check_execution_feasibility(
            symbol="PRAXIS",
            quantity=100,
            side="BUY",
            intended_holding="intraday",
            price=10.0,
        )
        assert not result.is_feasible
        assert result.blocking_reason == "T2T_INTRADAY_RESTRICTED"
        assert len(result.warnings) > 0
        
        # Test delivery T2T (should be allowed)
        result_delivery = await service.check_execution_feasibility(
            symbol="PRAXIS",
            quantity=100,
            side="BUY",
            intended_holding="delivery",
            price=10.0,
        )
        assert result_delivery.is_feasible
        assert any("T2T segment" in w for w in result_delivery.warnings)


@pytest.mark.asyncio
async def test_freeze_quantity_block():
    mock_market_service = MagicMock()
    mock_market_service._get_token_info.return_value = {
        "_matched_key": "RELIANCE-EQ",
        "symbol": "RELIANCE-EQ",
    }
    mock_market_service._normalize_symbol.return_value = "RELIANCE"

    with patch("services.execution_feasibility_service.get_market_data_service", return_value=mock_market_service):
        service = ExecutionFeasibilityService()
        
        # Test normal quantity (under default 100,000 limit)
        result_ok = await service.check_execution_feasibility(
            symbol="RELIANCE",
            quantity=5000,
            side="BUY",
            intended_holding="delivery",
            price=2500.0,
        )
        assert result_ok.is_feasible
        
        # Test quantity exceeding freeze limit
        result_block = await service.check_execution_feasibility(
            symbol="RELIANCE",
            quantity=150000,  # exceeds default limit of 100,000
            side="BUY",
            intended_holding="delivery",
            price=2500.0,
        )
        assert not result_block.is_feasible
        assert result_block.blocking_reason == "EXCEEDS_FREEZE_QUANTITY"


@pytest.mark.asyncio
async def test_liquidity_and_slippage():
    mock_market_service = MagicMock()
    mock_market_service._get_token_info.return_value = {
        "_matched_key": "RELIANCE-EQ",
        "symbol": "RELIANCE-EQ",
    }
    mock_market_service._normalize_symbol.return_value = "RELIANCE"
    
    # Mock 30-day daily volume data to have ADV of 1,000,000 shares
    mock_market_service.get_historical_candles.return_value = [
        {"volume": 1000000} for _ in range(30)
    ]

    with patch("services.execution_feasibility_service.get_market_data_service", return_value=mock_market_service):
        # 1. Test Demo Mode behavior (DEMO_MODE = True)
        with patch("services.execution_feasibility_service.DEMO_MODE", True):
            service = ExecutionFeasibilityService()
            
            # Let's test a trade of 50,000 shares (5% of ADV, above the 2.0% threshold)
            # slippage_bps = base_spread_bps (5.0) + impact_factor (10.0) * sqrt(50,000 / 1,000,000)
            # sqrt(0.05) = 0.2236067977
            # slippage_bps = 5.0 + 10.0 * 0.2236067977 = 7.236 bps
            
            # Check BUY trade
            result_buy = await service.check_execution_feasibility(
                symbol="RELIANCE",
                quantity=50000,
                side="BUY",
                intended_holding="delivery",
                price=100.0,
            )
            assert result_buy.is_feasible
            assert result_buy.simulated_price > 100.0
            assert abs(result_buy.slippage_bps - 7.236) < 0.01
            assert any("Order size" in w for w in result_buy.warnings)
            
            # Check SELL trade
            result_sell = await service.check_execution_feasibility(
                symbol="RELIANCE",
                quantity=50000,
                side="SELL",
                intended_holding="delivery",
                price=100.0,
            )
            assert result_sell.is_feasible
            assert result_sell.simulated_price < 100.0
            assert abs(result_sell.slippage_bps - 7.236) < 0.01

        # 2. Test Live Mode behavior (DEMO_MODE = False, LIVE_LIQUIDITY_BLOCK = True)
        with patch("services.execution_feasibility_service.DEMO_MODE", False), \
             patch("services.execution_feasibility_service.LIVE_LIQUIDITY_BLOCK", True):
            service = ExecutionFeasibilityService()
            result_live_block = await service.check_execution_feasibility(
                symbol="RELIANCE",
                quantity=50000,
                side="BUY",
                intended_holding="delivery",
                price=100.0,
            )
            assert not result_live_block.is_feasible
            assert result_live_block.blocking_reason == "LIQUIDITY_LIMIT_EXCEEDED"

