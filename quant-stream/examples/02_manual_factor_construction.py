"""Manual alpha factor construction demonstration.

This is the RECOMMENDED approach for production alpha factors.
Shows how to build factors step-by-step using Pathway operations with full control.

This example demonstrates:
1. Loading market data using Pathway
2. Applying technical indicator functions
3. Building composite alpha factors
4. Combining multiple factors
5. Outputting results to CSV

Usage:
    python examples/alpha_demo.py
    
Benefits of manual construction:
- Full control over computation graph
- Better performance optimization
- Explicit intermediate steps
- Easier debugging
- Production-ready code
"""

import pathway as pw
from pathlib import Path

from quant_stream import (
    DELTA,
    SMA,
    TS_STD,
    RANK,
    ZSCORE,
    RSI,
    DIVIDE,
)
from quant_stream.data.replayer import replay_market_data


def main():
    """Run manual alpha factor construction demo."""
    print("=" * 80)
    print("Alpha Factor Demo - Manual Construction (RECOMMENDED)")
    print("=" * 80)
    print()
    
    # Create outputs directory
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    
    # Load market data
    print("Loading market data...")
    table = replay_market_data()
    print("  ✓ Data loaded")
    
    # ========================================================================
    # Example 1: Simple Momentum Factor
    # ========================================================================
    print("\n" + "=" * 80)
    print("Example 1: Simple Momentum (1-day price change)")
    print("=" * 80)
    
    momentum_table = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
    momentum_table = momentum_table.select(
        symbol=pw.this.symbol,
        date=pw.this.date,
        timestamp=pw.this.timestamp,
        close=pw.this.close,
        momentum_1d=pw.this.delta,
    )
    
    pw.io.csv.write(momentum_table, str(output_dir / "alpha_momentum_1d.csv"))
    print("  ✓ Created: momentum_1d = DELTA(close, 1)")
    print("  ✓ Output: outputs/alpha_momentum_1d.csv")
    
    # ========================================================================
    # Example 2: Mean Reversion Factor
    # ========================================================================
    print("\n" + "=" * 80)
    print("Example 2: Mean Reversion (distance from SMA)")
    print("=" * 80)
    
    # Price distance from 20-day SMA, normalized by volatility
    mean_rev_table = SMA(table, pw.this.close, m=20, by_instrument=pw.this.symbol)
    mean_rev_table = TS_STD(mean_rev_table, pw.this.close, p=20, by_instrument=pw.this.symbol)
    mean_rev_table = mean_rev_table.select(
        symbol=pw.this.symbol,
        date=pw.this.date,
        timestamp=pw.this.timestamp,
        close=pw.this.close,
        sma_20=pw.this.sma,
        volatility=pw.this.ts_std,
        mean_reversion=(pw.this.close - pw.this.sma) / pw.this.ts_std,
    )
    
    pw.io.csv.write(mean_rev_table, str(output_dir / "alpha_mean_reversion.csv"))
    print("  ✓ Created: mean_reversion = (close - SMA(close, 20)) / TS_STD(close, 20)")
    print("  ✓ Output: outputs/alpha_mean_reversion.csv")
    
    # ========================================================================
    # Example 3: Cross-Sectional Rank Factor
    # ========================================================================
    print("\n" + "=" * 80)
    print("Example 3: Momentum Rank (cross-sectional ranking)")
    print("=" * 80)
    
    # Rank stocks by momentum at each timestamp
    rank_table = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
    rank_table = RANK(rank_table, pw.this.delta, by_time=pw.this.timestamp)
    rank_table = rank_table.select(
        symbol=pw.this.symbol,
        date=pw.this.date,
        timestamp=pw.this.timestamp,
        close=pw.this.close,
        momentum=pw.this.delta,
        momentum_rank=pw.this.rank,
    )
    
    pw.io.csv.write(rank_table, str(output_dir / "alpha_momentum_rank.csv"))
    print("  ✓ Created: momentum_rank = RANK(DELTA(close, 1))")
    print("  ✓ Output: outputs/alpha_momentum_rank.csv")
    
    # ========================================================================
    # Example 4: Technical Indicator Factor
    # ========================================================================
    print("\n" + "=" * 80)
    print("Example 4: RSI-based Factor")
    print("=" * 80)
    
    rsi_table = RSI(table, pw.this.close, p=14, by_instrument=pw.this.symbol)
    rsi_table = rsi_table.select(
        symbol=pw.this.symbol,
        date=pw.this.date,
        timestamp=pw.this.timestamp,
        close=pw.this.close,
        rsi_14=pw.this.rsi,
        rsi_signal=pw.this.rsi - 50.0,  # Centered at 50
    )
    
    pw.io.csv.write(rsi_table, str(output_dir / "alpha_rsi.csv"))
    print("  ✓ Created: rsi_signal = RSI(close, 14) - 50")
    print("  ✓ Output: outputs/alpha_rsi.csv")
    
    # ========================================================================
    # Example 5: Composite Multi-Factor
    # ========================================================================
    print("\n" + "=" * 80)
    print("Example 5: Composite Factor (momentum + volatility + rank)")
    print("=" * 80)
    
    # Build a composite factor step by step
    composite = DELTA(table, pw.this.close, periods=1, by_instrument=pw.this.symbol)
    composite = TS_STD(composite, pw.this.close, p=20, by_instrument=pw.this.symbol)
    composite = composite.select(
        *pw.this,
        volatility_adj_return=pw.this.delta / pw.this.ts_std,  # Risk-adjusted return
    )
    composite = RANK(composite, pw.this.volatility_adj_return, by_time=pw.this.timestamp)
    composite = composite.select(
        symbol=pw.this.symbol,
        date=pw.this.date,
        timestamp=pw.this.timestamp,
        close=pw.this.close,
        momentum=pw.this.delta,
        volatility=pw.this.ts_std,
        vol_adj_return=pw.this.volatility_adj_return,
        composite_signal=pw.this.rank,  # Final signal
    )
    
    pw.io.csv.write(composite, str(output_dir / "alpha_composite.csv"))
    print("  ✓ Created: composite_signal = RANK(DELTA(close, 1) / TS_STD(close, 20))")
    print("  ✓ Output: outputs/alpha_composite.csv")
    
    # ========================================================================
    # Example 6: Z-Score Normalization
    # ========================================================================
    print("\n" + "=" * 80)
    print("Example 6: Z-Score Normalized Factor")
    print("=" * 80)
    
    zscore_table = DELTA(table, pw.this.close, periods=5, by_instrument=pw.this.symbol)
    zscore_table = ZSCORE(zscore_table, pw.this.delta, by_time=pw.this.timestamp)
    zscore_table = zscore_table.select(
        symbol=pw.this.symbol,
        date=pw.this.date,
        timestamp=pw.this.timestamp,
        close=pw.this.close,
        momentum_5d=pw.this.delta,
        momentum_zscore=pw.this.zscore,  # Cross-sectionally normalized
    )
    
    pw.io.csv.write(zscore_table, str(output_dir / "alpha_zscore.csv"))
    print("  ✓ Created: momentum_zscore = ZSCORE(DELTA(close, 5))")
    print("  ✓ Output: outputs/alpha_zscore.csv")
    
    # Run computation
    print("\n" + "=" * 80)
    print("Computing all factors...")
    print("=" * 80)
    pw.run()
    print("  ✓ All factors computed and written to CSV")
    
    print("\n" + "=" * 80)
    print("Demo Complete!")
    print("=" * 80)
    print("\nOutputs created in outputs/ directory:")
    print("  - alpha_momentum_1d.csv")
    print("  - alpha_mean_reversion.csv")
    print("  - alpha_momentum_rank.csv")
    print("  - alpha_rsi.csv")
    print("  - alpha_composite.csv")
    print("  - alpha_zscore.csv")
    print("\nNext steps:")
    print("  1. Inspect the CSV files to see factor values")
    print("  2. Use these factors in a backtest: examples/simple_backtest.py")
    print("  3. Or configure in YAML: examples/configs/")
    print("=" * 80)


if __name__ == "__main__":
    main()
