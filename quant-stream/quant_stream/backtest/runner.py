"""General-purpose workflow runner for factor-based strategies."""

from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Sequence

import pandas as pd
import pathway as pw

from quant_stream.factors.evaluator import AlphaEvaluator
from quant_stream.factors.parser.expression_parser import parse_expression
from quant_stream.data.replayer import replay_market_data
from quant_stream.strategy import (
    TopkDropoutStrategy,
    WeightStrategy,
    BetaNeutralStrategy,
    DollarNeutralStrategy,
    IntradayMomentumStrategy,
)
from quant_stream.backtest.engine import Backtester
from quant_stream.backtest.metrics import calculate_returns_metrics, calculate_ic_metrics
from quant_stream.models import create_model, train_and_evaluate


def _collect_required_date_ranges(
    backtest_segments: Optional[Dict[str, Any]],
) -> List[Tuple[Optional[str], Optional[str]]]:
    ranges: List[Tuple[Optional[str], Optional[str]]] = []

    if backtest_segments:
        for key in ("train", "validation", "test"):
            segment = backtest_segments.get(key)
            if isinstance(segment, list) and len(segment) == 2:
                ranges.append((segment[0], segment[1]))

    deduped: List[Tuple[Optional[str], Optional[str]]] = []
    for range_start, range_end in ranges:
        normalized = (range_start or None, range_end or None)
        if normalized not in deduped:
            deduped.append(normalized)

    return deduped


def load_market_data(
    data_path: Optional[str] = None,
    date_ranges: Optional[List[Tuple[Optional[str], Optional[str]]]] = None,
    symbols: Optional[list[str]] = None,
    mode: str = "full",
    cache_dir: Optional[str | Path] = None,
) -> pw.Table:
    """Load market data, caching filtered slices to parquet for reuse.

    Args:
        data_path: Path to CSV file (uses default if not provided)
        date_ranges: List of inclusive (start, end) date tuples to cover
        symbols: Optional list of symbols to filter
        mode: Loading mode (currently informational only, kept for backwards compatibility)
        cache_dir: Optional override for cache directory

    Returns:
        Pathway table with market data covering the requested ranges
    """
    csv_path = data_path or ".data/indian_stock_market_nifty500.csv"

    print(f"[INFO] Loading market data from: {csv_path}", flush=True)
    table = replay_market_data(
        csv_path=csv_path,
        start_date=None,
        end_date=None,
        # symbols=symbols,
        mode="static",
        date_ranges=date_ranges,
        cache_dir=cache_dir,
    )
    print("[INFO] ✓ Market data loaded successfully", flush=True)
    return table


def calculate_factors(
    table: pw.Table,
    factor_expressions: list[Dict[str, str]],
    model_features: Optional[List[str]] = None,
) -> Tuple[pw.Table, pd.DataFrame, Optional[Dict[str, str]]]:
    """Calculate alpha factors from expressions.
    
    Args:
        table: Input Pathway table with market data
        factor_expressions: List of dicts with 'name' and 'expression' keys
        model_features: Optional list of feature specs (names or expressions) for model
    
    Returns:
        Tuple of (feature table, features DataFrame, feature_map)
        where feature_map maps model feature specs to column names
    """
    import time
    
    print(f"[INFO] Calculating {len(factor_expressions)} factor(s)...", flush=True)
    evaluator = AlphaEvaluator(table)
    
    factor_timings = []
    
    for i, factor_config in enumerate(factor_expressions, 1):
        # Parse the expression first to convert operators to function calls
        raw_expression = factor_config["expression"]
        parsed_expression = parse_expression(raw_expression)
        
        print(f"[INFO] [{i}/{len(factor_expressions)}] {factor_config['name']}: {raw_expression}", flush=True)
        
        # Time the factor evaluation
        factor_start = time.time()
        
        try:
            # Evaluate the parsed expression
            table = evaluator.evaluate(
                parsed_expression,
                factor_name=factor_config["name"]
            )
        except Exception as exc:
            raise RuntimeError(
                "Failed to evaluate factor '{name}' with expression '{expr}': {error}".format(
                    name=factor_config["name"],
                    expr=raw_expression,
                    error=exc,
                )
            ) from exc

        factor_elapsed = time.time() - factor_start
        factor_timings.append((factor_config["name"], factor_elapsed))
        print(f"[PERF] Factor '{factor_config['name']}' took {factor_elapsed:.2f}s", flush=True)

        # CRITICAL: Update evaluator.table BEFORE pruning
        # The evaluate() method returns a NEW table with the factor column added,
        # but prune_intermediate_columns() operates on self.table.
        # We must update self.table first so pruning works on the correct table.
        evaluator.table = table

        # PERFORMANCE OPTIMIZATION: Early column pruning after each factor
        # Remove intermediate columns that aren't needed for future factors
        # This reduces memory and computation overhead
        # Note: i is 1-indexed (from enumerate(..., 1)), so [:i] includes all factors up to and including current
        factor_names_so_far = {f["name"] for f in factor_expressions[:i]}
        table = evaluator.prune_intermediate_columns(keep_factor_columns=factor_names_so_far)
        evaluator.table = table
    
    # Print timing summary
    if len(factor_timings) > 1:
        print("\n[PERF] Factor timing summary:", flush=True)
        total_factor_time = sum(t for _, t in factor_timings)
        for name, elapsed in factor_timings:
            pct = (elapsed / total_factor_time * 100) if total_factor_time > 0 else 0
            print(f"  - {name}: {elapsed:.2f}s ({pct:.1f}%)", flush=True)
        print(f"  Total factor computation time: {total_factor_time:.2f}s", flush=True)
    
    import time
    start_time = time.time()
    
    # Evaluate model feature expressions if provided (BEFORE column selection and pandas conversion)
    feature_map = None
    if model_features:
        print("[INFO] Evaluating model feature expressions...", flush=True)
        evaluator = AlphaEvaluator(table)
        table, feature_map = evaluate_feature_expressions(
            table, model_features, evaluator
        )
        # Update evaluator table reference
        evaluator.table = table
    
    # Get all columns AFTER model features are evaluated
    all_columns = table.column_names()
    print(f"[DEBUG] Table has {len(all_columns)} total columns", flush=True)
    
    # Identify factor result columns (the final factor names)
    factor_names = {f["name"] for f in factor_expressions}  # Use set for O(1) lookup
    
    # Include model feature columns if they exist
    model_feature_cols = [col for col in all_columns if col.startswith("_model_feature_")]
    if model_feature_cols:
        print(f"[DEBUG] Model feature columns: {model_feature_cols}", flush=True)
    
    # DEBUG: Check if factor columns exist in table
    print(f"[DEBUG] Looking for factor columns: {sorted(factor_names)}", flush=True)
    factor_cols_in_table = [col for col in all_columns if col in factor_names]
    print(f"[DEBUG] Factor columns found in table: {sorted(factor_cols_in_table)}", flush=True)
    missing_factors = factor_names - set(factor_cols_in_table)
    if missing_factors:
        print(f"[WARN] Missing factor columns in table: {sorted(missing_factors)}", flush=True)
    
    # Core columns we always need
    core_cols = {"symbol", "date", "timestamp", "open", "high", "low", "close", "volume"}
    
    # PERFORMANCE OPTIMIZATION: Use evaluator's needed_columns tracking if available
    # This gives us a more accurate list of columns that are actually needed
    needed_columns = None
    if hasattr(evaluator, 'get_needed_columns'):
        needed_columns = evaluator.get_needed_columns()
        print(f"[DEBUG] Evaluator tracked {len(needed_columns)} needed columns", flush=True)
    
    # Single pass: collect columns to keep (filter out intermediate columns starting with _)
    # This avoids redundant iterations - O(n) where n = number of columns
    filtered_columns = []
    for col in all_columns:
        # Keep if:
        # 1. It's a core column, factor name, or model feature column (always needed)
        # 2. AND it doesn't start with _ (intermediate columns), except _model_feature_ columns
        is_core_or_factor = col in core_cols or col in factor_names or col in model_feature_cols
        is_not_intermediate = not col.startswith("_") or col.startswith("_model_feature_")
        
        if is_core_or_factor and is_not_intermediate:
            filtered_columns.append(col)
    
    print(f"[DEBUG] Selecting {len(filtered_columns)} columns (removed {len(all_columns) - len(filtered_columns)} intermediate columns)", flush=True)
    print(f"[DEBUG] Columns to keep: {filtered_columns}", flush=True)
    
    # Verify model feature columns are included
    if model_feature_cols:
        missing_model_features = [col for col in model_feature_cols if col not in filtered_columns]
        if missing_model_features:
            print(f"[WARN] Model feature columns not included in selection: {missing_model_features}", flush=True)
        else:
            print(f"[DEBUG] ✓ All {len(model_feature_cols)} model feature columns included", flush=True)
    
    # PERFORMANCE OPTIMIZATION: Use table.select() to reduce serialization overhead
    # Even though Pathway computes all dependencies, selecting before conversion:
    # 1. Reduces data serialization from 35 columns to 11 columns
    # 2. Tells Pathway's dependency tracker which columns are actually needed
    # 3. May allow Pathway to optimize materialization through tree shaking
    # 4. Reduces memory usage during conversion
    
    # IMPORTANT: Use table.select() (not table.without()) to explicitly tell Pathway
    # which columns we need. This helps Pathway's column dependency tracking system
    # potentially skip computing some intermediate values that aren't in the dependency
    # chain of our final outputs. However, Pathway still needs to compute dependencies
    # so intermediate columns that ARE in the chain will still be computed.
    
    # Select only needed columns before conversion - reduces serialization overhead
    if len(filtered_columns) < len(all_columns):
        # Build select dict efficiently - O(k) where k = filtered_columns
        # Only iterate through columns we want to keep
        select_dict = {col: pw.this[col] for col in filtered_columns}
        if select_dict:
            # Use select to explicitly declare needed columns
            # This helps Pathway's dependency tracker understand what to compute
            table_selected = table.select(**select_dict)
            print(f"[DEBUG] Created select operation with {len(select_dict)} columns", flush=True)
            print("[PERF] ⚠️  Pathway still computes all dependencies - intermediate columns used in dependency chain are still materialized", flush=True)
        else:
            table_selected = table
    else:
        table_selected = table
    
    print("[INFO] Running Pathway computation...", flush=True)
    
    features_df = pw.debug.table_to_pandas(table_selected, include_id=False)
    
    elapsed = time.time() - start_time
    # print(f"[INFO] ✓ Conversion complete in {elapsed:.2f}s")
    print(f"[INFO] ✓ Pipeline complete in {elapsed:.2f}s", flush=True)
    print(f"[INFO] ✓ Factors calculated: {len(features_df)} rows, {len(features_df.columns)} columns", flush=True)
    
    return table, features_df, feature_map


def evaluate_feature_expressions(
    table: pw.Table,
    feature_specs: List[str],
    evaluator: Optional[AlphaEvaluator] = None,
) -> Tuple[pw.Table, Dict[str, str]]:
    """Evaluate inline feature expressions on Pathway table.
    
    This function allows specifying features as either:
    1. Existing column names (computed factors or OHLCV)
    2. Inline expressions (e.g., "($close - $open) / $open")
    
    Args:
        table: Pathway table with market data and computed factors
        feature_specs: List of feature specifications (names or expressions)
        evaluator: Optional AlphaEvaluator instance (creates new if None)
    
    Returns:
        Tuple of (updated table, mapping of feature_spec -> column_name)
        where feature_spec is the original spec and column_name is the resulting column
    """
    if evaluator is None:
        evaluator = AlphaEvaluator(table)
    else:
        evaluator.table = table
    
    feature_map = {}  # Maps feature spec -> column name
    
    for i, feature_spec in enumerate(feature_specs):
        # Check if it's a column name (existing factor or OHLCV)
        if feature_spec in table.column_names():
            feature_map[feature_spec] = feature_spec
            continue
        
        # Otherwise, treat as expression
        try:
            # Parse and evaluate the expression
            parsed_expr = parse_expression(feature_spec)
            # Generate a safe column name
            feature_name = f"_model_feature_{i}"
            table = evaluator.evaluate(parsed_expr, factor_name=feature_name)
            evaluator.table = table
            feature_map[feature_spec] = feature_name
            print(f"[INFO] Evaluated feature expression: {feature_spec} -> {feature_name}")
        except Exception as e:
            raise ValueError(
                f"Failed to evaluate feature expression '{feature_spec}': {e}"
            ) from e
    
    return table, feature_map


def prepare_training_data(
    features_df: pd.DataFrame,
    target_name: str = "forward_return",
    symbol_col: str = "symbol",
    timestamp_col: str = "timestamp",
    train_range: Optional[Tuple[str, str]] = None,
    validation_range: Optional[Tuple[str, str]] = None,
    test_range: Optional[Tuple[str, str]] = None,
    feature_names: Optional[List[str]] = None,
    feature_map: Optional[Dict[str, str]] = None,
    include_ohlcv: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list]:
    """Prepare data for model training.
    
    This function:
    1. Sorts by symbol and timestamp
    2. Creates forward returns as target (IMPORTANT: avoids forward bias)
    3. Selects feature columns (excludes metadata)
    4. Removes NaN values
    5. Converts timestamp to datetime
    6. Splits into train/test sets
    
    FORWARD BIAS PREVENTION:
    -----------------------
    The target variable is the return from t+1 to t+2, where:
    - Features at time t use data available at close of period t
    - Target is the return that occurs AFTER we could have acted
    - This ensures we cannot use future information in training
    
    Timeline:
    - t=0 close: Features calculated using data up to t=0
    - t=1 open: Signal generated, trade executed (in backtest)
    - t=1 to t+2: Measure return (this is our target)
    
    Args:
        features_df: Features DataFrame
        target_name: Name for target column (default: "forward_return")
        symbol_col: Symbol column name
        timestamp_col: Timestamp column name
        train_range: Tuple of (start, end) for training period
        validation_range: Optional tuple of (start, end) for validation period
        test_range: Tuple of (start, end) for test period
        feature_names: Optional explicit list of feature names/expressions to use.
                      If None, uses all computed factors (backward compatible).
        feature_map: Optional mapping from feature spec to column name (for inline expressions)
        include_ohlcv: Whether to include OHLCV columns when feature_names=None
        
    Returns:
        Tuple of (train_df, validation_df, test_df, feature_cols)
    """
    if train_range is None or test_range is None:
        raise ValueError("Both train_range and test_range must be provided for training data preparation.")

    # Sort by symbol and timestamp
    print("[INFO] Preparing training data...")
    features_df = features_df.sort_values([symbol_col, timestamp_col])
    
    # Create forward returns as target - CORRECTED to avoid forward bias
    # OLD (forward bias): .shift(-1) means at time t, we know return from t to t+1
    # NEW (correct): .shift(-2) means at time t, we predict return from t+1 to t+2
    # This ensures we can only trade at t+1 open using signal from t
    features_df[target_name] = features_df.groupby(symbol_col)["close"].pct_change(1).shift(-2)
    
    # Get feature columns (exclude metadata, target, and temporary/cached columns)
    # Base exclusions: metadata and target
    exclude_cols = {symbol_col, timestamp_col, "date", target_name}
    
    # NEW: Feature selection logic
    if feature_names is not None:
        # Explicit feature selection
        print(f"[DEBUG] Feature names from config: {feature_names}")
        if feature_map:
            print(f"[DEBUG] Feature map: {feature_map}")
            # Map feature specs to actual column names
            feature_cols = [feature_map.get(spec, spec) for spec in feature_names]
            print(f"[DEBUG] Mapped feature columns: {feature_cols}")
            print(f"[DEBUG] Available DataFrame columns: {list(features_df.columns)}")
            feature_cols = [col for col in feature_cols if col in features_df.columns]
            print(f"[DEBUG] Feature columns found in DataFrame: {feature_cols}")
        else:
            # Simple case: just column names
            feature_cols = [col for col in feature_names if col in features_df.columns]
        
        missing = [spec for spec in feature_names 
                  if (feature_map.get(spec, spec) if feature_map else spec) not in feature_cols]
        if missing:
            print(f"[WARN] Missing features: {missing}")
        
        # Filter out OHLCV columns if include_ohlcv is False
        if not include_ohlcv:
            ohlcv_cols = {"open", "high", "low", "close", "volume"}
            original_count = len(feature_cols)
            feature_cols = [col for col in feature_cols if col not in ohlcv_cols]
            removed_ohlcv = original_count - len(feature_cols)
            if removed_ohlcv > 0:
                print(f"[INFO] Excluded {removed_ohlcv} OHLCV column(s) (include_ohlcv: false)")
        
        print(f"[INFO] Using {len(feature_cols)} explicitly selected features")
    else:
        # Backward compatible: use all computed factors
        feature_cols = [col for col in features_df.columns 
                       if col not in exclude_cols and not col.startswith('_')]
        if not include_ohlcv:
            ohlcv_cols = {"open", "high", "low", "close", "volume"}
            feature_cols = [col for col in feature_cols if col not in ohlcv_cols]
        
        print(f"[INFO] Using all computed factors ({len(feature_cols)} features)")
        if include_ohlcv:
            print("[INFO] Including OHLCV values as features")
    
    print(f"[INFO] Feature columns ({len(feature_cols)}): {feature_cols[:10]}{'...' if len(feature_cols) > 10 else ''}")
    
    # Remove NaN values
    original_len = len(features_df)
    features_df = features_df.dropna(subset=feature_cols + [target_name])
    print(f"[INFO] Removed {original_len - len(features_df)} rows with NaN values")
    
    # Ensure timestamp is datetime
    if timestamp_col in features_df.columns:
        if not pd.api.types.is_datetime64_any_dtype(features_df[timestamp_col]):
            try:
                features_df[timestamp_col] = pd.to_datetime(
                    features_df[timestamp_col], unit="s"
                )
            except Exception:
                features_df[timestamp_col] = pd.to_datetime(
                    features_df[timestamp_col]
                )
    
    # Split train/validation/test
    validation_df = features_df.iloc[0:0].copy()
    print("[INFO] Splitting data by explicit date ranges...")

    train_start_date, train_end_date = train_range
    test_start_date, test_end_date = test_range
    train_df = features_df[
        (features_df[timestamp_col] >= pd.to_datetime(train_start_date))
        & (features_df[timestamp_col] <= pd.to_datetime(train_end_date))
    ]

    if validation_range:
        validation_start_date, validation_end_date = validation_range
        validation_df = features_df[
            (features_df[timestamp_col] >= pd.to_datetime(validation_start_date))
            & (features_df[timestamp_col] <= pd.to_datetime(validation_end_date))
        ]

    test_df = features_df[
        (features_df[timestamp_col] >= pd.to_datetime(test_start_date))
        & (features_df[timestamp_col] <= pd.to_datetime(test_end_date))
    ]
    
    train_df = train_df.copy().reset_index(drop=True)
    validation_df = validation_df.copy().reset_index(drop=True)
    test_df = test_df.copy().reset_index(drop=True)
    
    print(
        "[INFO] Dataset sizes - "
        f"Train: {len(train_df)} rows, "
        f"Validation: {len(validation_df)} rows, "
        f"Test: {len(test_df)} rows"
    )
    return train_df, validation_df, test_df, feature_cols


def build_segments_dict(
    train_segment: Optional[Any] = None,
    validation_segment: Optional[Any] = None,
    test_segment: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Build segments dictionary for backtest runner.
    
    Args:
        train_segment: Train segment config (dates or ratio)
        validation_segment: Validation segment config (dates or ratio)
        test_segment: Test segment config (dates or ratio)
        
    Returns:
        Segments dict or None if no segments
    """
    segments = {}
    if train_segment:
        segments["train"] = train_segment
    if validation_segment:
        segments["validation"] = validation_segment
    if test_segment:
        segments["test"] = test_segment
    return segments if segments else None


def _range_from_segment(segment: Optional[Any], label: str) -> Optional[Tuple[str, str]]:
    """Normalize a date range definition into a (start, end) tuple."""
    if segment is None:
        return None

    if isinstance(segment, (list, tuple, Sequence)) and not isinstance(segment, (str, bytes)):
        # Handle pydantic BaseModel (iterable) separately to avoid unpacking strings
        if len(segment) != 2:
            raise ValueError(f"{label} segment must be [start, end], got: {segment}")
        start, end = segment[0], segment[1]
    elif isinstance(segment, dict):
        start = segment.get("start") or segment.get("begin") or segment.get("from") or segment.get(0)
        end = segment.get("end") or segment.get("until") or segment.get(1)
    else:
        # Support pydantic models / objects with attributes
        start = getattr(segment, "start", None)
        if start is None:
            start = getattr(segment, "train_start", None)
        if start is None and hasattr(segment, "__getitem__"):
            try:
                start = segment[0]
            except Exception:  # pragma: no cover - best effort
                start = None
        end = getattr(segment, "end", None)
        if end is None:
            end = getattr(segment, "train_end", None)
        if end is None and hasattr(segment, "__getitem__"):
            try:
                end = segment[1]
            except Exception:  # pragma: no cover
                end = None

    if not start or not end:
        raise ValueError(f"{label} segment must include both start and end dates, got: {segment}")

    return str(start), str(end)


def _train_test_split_from_segments(backtest_segments: Optional[Dict[str, Any]]) -> Optional[Dict[str, Optional[str]]]:
    """Derive train/test/validation split configuration from backtest segments."""
    if not backtest_segments:
        return None

    def _get_segment(name: str) -> Optional[Any]:
        if backtest_segments is None:
            return None
        if isinstance(backtest_segments, dict):
            return backtest_segments.get(name)
        return getattr(backtest_segments, name, None)

    train_range = _range_from_segment(_get_segment("train"), "train") if _get_segment("train") else None
    test_range = _range_from_segment(_get_segment("test"), "test") if _get_segment("test") else None
    validation_segment = _get_segment("validation")
    validation_range = (
        _range_from_segment(validation_segment, "validation") if validation_segment else None
    )

    if not train_range or not test_range:
        return None

    return {
        "train_start": train_range[0],
        "train_end": train_range[1],
        "test_start": test_range[0],
        "test_end": test_range[1],
        "validation_start": validation_range[0] if validation_range else None,
        "validation_end": validation_range[1] if validation_range else None,
    }


def _ensure_timestamp_column(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with timestamp column converted to datetime."""
    if "timestamp" not in df.columns:
        raise ValueError("Expected a 'timestamp' column for backtesting data.")
    if pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        return df
    copy = df.copy()
    copy["timestamp"] = pd.to_datetime(copy["timestamp"])
    return copy


def _apply_date_range(
    df: pd.DataFrame,
    date_range: Optional[Tuple[str, str]],
) -> pd.DataFrame:
    """Filter dataframe by inclusive [start, end] date range."""
    if date_range is None:
        return df
    start, end = date_range
    result = df
    if start:
        result = result[result["timestamp"] >= pd.to_datetime(start)]
    if end:
        result = result[result["timestamp"] <= pd.to_datetime(end)]
    return result


def _run_single_backtest(
    signals_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    strategy_type: str,
    strategy_params: Dict[str, Any],
    initial_capital: float,
    commission: float,
    slippage: float,
    min_commission: float,
    rebalance_frequency: int,
    recorder: Optional[Any] = None,
    artifact_label: Optional[str] = None,
    allow_short: bool = False,
    intraday_short_only: bool = True,
    short_funding_rate: float = 0.0002,
) -> Tuple[pd.DataFrame, Dict[str, float], pd.DataFrame]:
    """Run a single backtest and return results with IC metrics.
    
    Returns:
        Tuple of (results_df, metrics)
    """
    print(f"[INFO] Running backtest with {strategy_type} strategy...")
    print(f"[INFO] Signals: {len(signals_df)} rows, Prices: {len(prices_df)} rows")
    
    # Create strategy
    if strategy_type == "TopkDropout":
        strategy = TopkDropoutStrategy(**strategy_params)
    elif strategy_type == "Weight":
        strategy = WeightStrategy(**strategy_params)
    elif strategy_type == "BetaNeutral":
        strategy = BetaNeutralStrategy(**strategy_params)
    elif strategy_type == "DollarNeutral":
        strategy = DollarNeutralStrategy(**strategy_params)
    elif strategy_type == "IntradayMomentum":
        strategy = IntradayMomentumStrategy(**strategy_params)
    else:
        raise ValueError(f"Unknown strategy type: {strategy_type}")
    
    # Create backtester
    backtester = Backtester(
        initial_capital=initial_capital,
        commission=commission,
        slippage=slippage,
        min_commission=min_commission,
        rebalance_frequency=rebalance_frequency,
        allow_short=allow_short,
        intraday_short_only=intraday_short_only,
        short_funding_rate=short_funding_rate,
    )
    
    # Merge signals and prices to calculate forward returns for IC
    print("[INFO] Calculating IC metrics...")
    merged = signals_df.merge(prices_df, on=["symbol", "timestamp"], how="inner")
    
    # Calculate forward returns - matches our backtesting execution lag
    # Signal at t predicts return from t+1 to t+2 (when we trade at t+1)
    merged = merged.sort_values(["symbol", "timestamp"])
    merged["forward_return"] = merged.groupby("symbol")["close"].pct_change(1).shift(-2)
    
    # Run backtest
    print("[INFO] Executing backtest...")
    results_df = backtester.run(
        signals_df,
        prices_df,
        strategy,
        recorder=recorder,
        artifact_prefix=artifact_label,
    )
    holdings_df = getattr(backtester, "holdings_history", pd.DataFrame())
    
    # Calculate return-based metrics
    if len(results_df) > 1:
        returns = results_df["returns"].dropna()
        metrics = calculate_returns_metrics(returns)
    else:
        metrics = {}
    
    # Calculate IC metrics (signal vs forward returns)
    if len(merged) > 1:
        # Remove NaN values - handle potential duplicate columns
        signal_col = merged["signal"]
        if isinstance(signal_col, pd.DataFrame):
            signal_col = signal_col.iloc[:, 0]
        
        forward_return_col = merged["forward_return"]
        if isinstance(forward_return_col, pd.DataFrame):
            forward_return_col = forward_return_col.iloc[:, 0]
        
        valid_mask = ~(signal_col.isna() | forward_return_col.isna())
        
        if valid_mask.sum() > 1:
            ic_metrics = calculate_ic_metrics(
                signal_col[valid_mask],
                forward_return_col[valid_mask]
            )
            metrics.update(ic_metrics)
    
    print(f"[INFO] ✓ Backtest complete: {len(results_df)} periods")
    if metrics:
        print(f"[INFO] Sharpe Ratio: {metrics.get('sharpe_ratio', 'N/A'):.3f}")
        print(f"[INFO] IC: {metrics.get('IC', 'N/A'):.3f}")
    
    return results_df, metrics, holdings_df


def _run_backtest(
    signals_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    segments: Optional[Dict[str, Any]] = None,
    strategy_type: str = "TopkDropout",
    strategy_params: Optional[Dict[str, Any]] = None,
    initial_capital: float = 1_000_000,
    commission: float = 0.001,
    slippage: float = 0.001,
    min_commission: float = 0.0,
    rebalance_frequency: int = 1,
    recorder: Optional[Any] = None,
    experiment_name: str = "backtest",
    run_name: Optional[str] = None,
    log_to_mlflow: bool = False,
    allow_short: bool = False,
    intraday_short_only: bool = True,
    short_funding_rate: float = 0.0002,
) -> Dict[str, Any]:
    """Execute a backtest over optional train/test segments."""
    if signals_df is None or prices_df is None:
        raise ValueError("signals_df and prices_df are required for backtesting.")

    strategy_params = strategy_params or {}
    segments = segments or {}

    mlflow_context = None
    if log_to_mlflow:
        from quant_stream.recorder import Recorder, DEFAULT_TRACKING_URI
        if recorder is None:
            recorder = Recorder(experiment_name=experiment_name, tracking_uri=DEFAULT_TRACKING_URI)

        active_run = getattr(recorder, "active_run", None)
        if active_run is None:
            mlflow_context = recorder.start_run(run_name or "backtest_run")

    try:
        if log_to_mlflow and recorder:
            recorder.log_params(
                strategy_type=strategy_type,
                initial_capital=initial_capital,
                commission=commission,
                slippage=slippage,
                rebalance_frequency=rebalance_frequency,
            )

        signals_df = _ensure_timestamp_column(signals_df)
        prices_df = _ensure_timestamp_column(prices_df)

        def _validate_segment(segment: Optional[Any], label: str) -> Optional[Tuple[str, str]]:
            if segment is None:
                return None
            if isinstance(segment, list) and len(segment) == 2:
                return segment[0], segment[1]
            raise NotImplementedError(f"{label} segment must be a [start, end] date range.")

        segment_ranges: Dict[str, Optional[Tuple[str, str]]] = {
            "train": _validate_segment(segments.get("train"), "train"),
            "validation": _validate_segment(segments.get("validation"), "validation"),
            "test": _validate_segment(segments.get("test"), "test"),
        }

        if segment_ranges["validation"] is not None and segment_ranges["train"] is None:
            raise ValueError("Validation segment requires a train segment to be defined.")
        if segment_ranges["test"] is not None and segment_ranges["train"] is None:
            raise ValueError("Both train and test segments must be provided when segmenting backtests.")

        def _execute(range_bounds: Optional[Tuple[str, str]], label: Optional[str]):
            sliced_signals = _apply_date_range(signals_df, range_bounds)
            sliced_prices = _apply_date_range(prices_df, range_bounds)
            return _run_single_backtest(
                sliced_signals,
                sliced_prices,
                strategy_type,
                strategy_params,
                initial_capital,
                commission,
                slippage,
                min_commission,
                rebalance_frequency,
                recorder=recorder if log_to_mlflow else None,
                artifact_label=label,
                allow_short=allow_short,
                intraday_short_only=intraday_short_only,
                short_funding_rate=short_funding_rate,
            )

        segment_outputs: Dict[str, Dict[str, Any]] = {}
        has_segments = any(range_bounds is not None for range_bounds in segment_ranges.values())

        if not has_segments:
            results_df, metrics, holdings_df = _execute(None, "full")
            segment_outputs["full"] = {
                "results_df": results_df,
                "metrics": metrics,
                "holdings_df": holdings_df,
            }
        else:
            for name in ("train", "validation", "test"):
                range_bounds = segment_ranges.get(name)
                if range_bounds is None:
                    continue
                results_df, metrics, holdings_df = _execute(range_bounds, name)
                segment_outputs[name] = {
                    "results_df": results_df,
                    "metrics": metrics,
                    "holdings_df": holdings_df,
                }

        if log_to_mlflow and recorder:
            if "full" in segment_outputs and len(segment_outputs) == 1:
                metrics = segment_outputs["full"]["metrics"]
                recorder.log_metrics(
                    **{
                        f"backtest_{key}": float(value)
                        for key, value in metrics.items()
                        if isinstance(value, (int, float)) and not isinstance(value, bool)
                    }
                )
            else:
                for prefix in ("train", "validation", "test"):
                    if prefix not in segment_outputs:
                        continue
                    metrics = segment_outputs[prefix]["metrics"]
                    recorder.log_metrics(
                        **{
                            f"{prefix}_{k}": v
                            for k, v in metrics.items()
                            if isinstance(v, (int, float)) and not isinstance(v, bool)
                        }
                    )

        primary_segment = next(
            (name for name in ("test", "validation", "train", "full") if name in segment_outputs),
            "full",
        )
        primary = segment_outputs.get(primary_segment, {})

        primary_results_df = primary.get("results_df")
        primary_metrics = primary.get("metrics")
        primary_holdings_df = primary.get("holdings_df")

        result = {
            "success": True,
            "metrics": primary_metrics,
            "num_periods": len(primary_results_df) if primary_results_df is not None else 0,
            "results_df": primary_results_df,
            "holdings_df": primary_holdings_df,
            "train_results_df": segment_outputs.get("train", {}).get("results_df"),
            "train_holdings_df": segment_outputs.get("train", {}).get("holdings_df"),
            "validation_results_df": segment_outputs.get("validation", {}).get("results_df"),
            "validation_holdings_df": segment_outputs.get("validation", {}).get("holdings_df"),
            "test_results_df": segment_outputs.get("test", {}).get("results_df"),
            "test_holdings_df": segment_outputs.get("test", {}).get("holdings_df"),
            "train_metrics": segment_outputs.get("train", {}).get("metrics"),
            "validation_metrics": segment_outputs.get("validation", {}).get("metrics"),
            "test_metrics": segment_outputs.get("test", {}).get("metrics"),
            "error": None,
        }

        if mlflow_context:
            mlflow_context.__exit__(None, None, None)

        return result
    
    except Exception as e:
        # Close MLflow run if we created it
        if mlflow_context:
            mlflow_context.__exit__(None, None, None)
        
        # Return error structure with consistent fields
        return {
            "success": False,
            "metrics": {},
            "num_periods": 0,
            "results_df": None,
            "train_results_df": None,
            "validation_results_df": None,
            "test_results_df": None,
            "train_metrics": None,
            "validation_metrics": None,
            "test_metrics": None,
            "holdings_df": None,
            "train_holdings_df": None,
            "validation_holdings_df": None,
            "test_holdings_df": None,
            "error": str(e),
        }

def run_ml_workflow(
    data_path: str,
    symbols: Optional[list[str]] = None,
    factor_expressions: Optional[list] = None,
    model_config: Optional[Dict[str, Any]] = None,
    strategy_type: str = "TopkDropout",
    strategy_params: Optional[Dict[str, Any]] = None,
    initial_capital: float = 1_000_000,
    commission: float = 0.001,
    slippage: float = 0.001,
    min_commission: float = 0.0,
    rebalance_frequency: int = 1,
    backtest_segments: Optional[Dict[str, Any]] = None,
    symbol_col: str = "symbol",
    timestamp_col: str = "timestamp",
    recorder: Optional[Any] = None,
    experiment_name: str = "ml_workflow",
    run_name: Optional[str] = None,
    log_to_mlflow: bool = True,
    allow_short: bool = False,
    intraday_short_only: bool = True,
    short_funding_rate: float = 0.0002,
) -> Dict[str, Any]:
    """[UNIFIED WORKFLOW] Run complete quantitative workflow with or without ML model.
    
    This is the ONLY entry point for all factor-based trading workflows:
    - model_config=None: Use factor values directly as signals (simple factor backtest)
    - model_config={...}: Train ML model on factors, use predictions as signals
    
    Workflow steps:
    1. Load market data
    2. Calculate alpha factors from expressions
    3. [If model_config] Prepare training data and train ML model
    4. Generate signals (factor values OR model predictions)
    5. Run backtest with strategy
    6. Return comprehensive results with MLflow logging
    
    Args:
        data_path: Path to market data CSV
        factor_expressions: List of factor expressions [{"name": ..., "expression": ...}]
        model_config: Model configuration dict with:
            - type: Model type (lightgbm, xgboost, linear, tree)
            - params: Model parameters dict
            - target: Target column name
        strategy_type: Strategy type (TopkDropout, Weight)
        strategy_params: Strategy parameters dict
        initial_capital: Starting capital
        commission: Commission rate
        slippage: Slippage rate
        min_commission: Minimum commission per trade
        rebalance_frequency: Rebalance frequency
        backtest_segments: Optional train/test segments for backtest.
            Required when model_config is provided. These ranges are reused
            for model training (train/validation/test) to guarantee alignment.
        symbol_col: Symbol column name
        timestamp_col: Timestamp column name
        recorder: Optional Recorder instance for MLflow logging
        experiment_name: Experiment name for MLflow (if recorder not provided)
        run_name: Run name for MLflow (if recorder not provided)
        log_to_mlflow: Whether to log to MLflow (default: True)
        
    Returns:
        Dict with:
            - success: bool
            - results_df: Backtest results DataFrame
            - metrics: Performance metrics dict (or test_metrics if train/test split)
            - train_metrics: Train metrics (if train/test split)
            - test_metrics: Test metrics (if train/test split)
            - model: Trained model (if model_config provided)
            - train_ic: Train IC metrics (if model_config provided)
            - test_ic: Test IC metrics (if model_config provided)
            - feature_cols: List of feature column names
            - error: Error message if failed
    """
    # Initialize MLflow logging if requested
    mlflow_context = None
    if log_to_mlflow:
        from quant_stream.recorder import Recorder, DEFAULT_TRACKING_URI
        if recorder is None:
            recorder = Recorder(experiment_name=experiment_name, tracking_uri=DEFAULT_TRACKING_URI)
        
        # Generate run name if not provided
        if run_name is None and model_config:
            run_name = f"{model_config.get('type', 'model')}_workflow"
        elif run_name is None:
            run_name = "factor_workflow"
        
        active_run = getattr(recorder, "active_run", None)
        mlflow_current = None
        try:
            from mlflow import active_run as mlflow_active_run  # type: ignore
        except Exception:  # pragma: no cover - optional dependency
            pass
        else:
            mlflow_current = mlflow_active_run()
            if active_run is None and mlflow_current is not None:
                # Recorder was handed an existing MLflow run (e.g., CLI-managed); sync state
                try:
                    recorder._active_run = mlflow_current  # type: ignore[attr-defined]
                except AttributeError:  # pragma: no cover
                    pass
                active_run = mlflow_current

        if active_run is None:
            mlflow_context = recorder.start_run(run_name)

    resolved_run_name = run_name
    if not resolved_run_name:
        if model_config:
            resolved_run_name = f"{model_config.get('type', 'model')}_workflow"
        else:
            resolved_run_name = "factor_workflow"

    resolved_run_name = run_name
    if not resolved_run_name:
        if model_config:
            resolved_run_name = f"{model_config.get('type', 'model')}_workflow"
        else:
            resolved_run_name = "factor_workflow"
    
    try:
        print("\n" + "=" * 80, flush=True)
        print("Starting ML Workflow", flush=True)
        print("=" * 80, flush=True)
        
        # Log configuration to MLflow
        if log_to_mlflow and recorder:
            config_params = {
                "data_path": data_path,
                "strategy_type": strategy_type,
                "initial_capital": initial_capital,
                "commission": commission,
                "slippage": slippage,
                "rebalance_frequency": rebalance_frequency,
            }
            
            if model_config:
                config_params["model_type"] = model_config.get("type")
                config_params.update({f"model_{k}": v for k, v in model_config.get("params", {}).items()})
            
            config_params.update({f"strategy_{k}": v for k, v in (strategy_params or {}).items()})
            
            if backtest_segments:
                if backtest_segments.get("train"):
                    config_params["train_segment"] = str(backtest_segments["train"])
                if backtest_segments.get("validation"):
                    config_params["validation_segment"] = str(backtest_segments["validation"])
                if backtest_segments.get("test"):
                    config_params["test_segment"] = str(backtest_segments["test"])
            
            recorder.log_params(**config_params)
        
        # 1. Load market data
        print("[run_ml_workflow] Step 1: Collecting date ranges...", flush=True)
        date_ranges = _collect_required_date_ranges(backtest_segments)
        print(f"[run_ml_workflow] Step 1: Date ranges: {date_ranges}", flush=True)
        print(f"[run_ml_workflow] Step 2: Loading market data from {data_path}...", flush=True)
        print(f"[run_ml_workflow] Step 2: Symbols filter: {len(symbols) if symbols else 'None'} symbols", flush=True)
        table = load_market_data(
            data_path=data_path,
            date_ranges=date_ranges,
            symbols=symbols,
            mode="full",
        )
        print("[run_ml_workflow] Step 2: Market data loaded successfully", flush=True)
        
        # Extract feature selection from model config (before factor calculation)
        feature_names = None
        include_ohlcv = True
        if model_config:
            feature_names = model_config.get("features")
            include_ohlcv = model_config.get("include_ohlcv", True)
        
        # 2. Create features if configured (includes model feature expressions)
        print(f"[run_ml_workflow] Step 3: Calculating factors...", flush=True)
        print(f"[run_ml_workflow] Step 3: {len(factor_expressions) if factor_expressions else 0} factor expressions", flush=True)
        if factor_expressions:
            table, features_df, feature_map = calculate_factors(
                table, 
                factor_expressions,
                model_features=feature_names  # Pass model features to evaluate during factor calculation
            )
        else:
            # No factor expressions - just convert table to pandas
            # But still evaluate model features if specified
            if feature_names:
                print("[INFO] Evaluating model feature expressions...")
                evaluator = AlphaEvaluator(table)
                table, feature_map = evaluate_feature_expressions(
                    table, feature_names, evaluator
                )
                features_df = pw.debug.table_to_pandas(table, include_id=False)
                print(f"[INFO] Features DataFrame: {len(features_df)} rows, {len(features_df.columns)} columns")
            else:
                features_df = pw.debug.table_to_pandas(table, include_id=False)
                feature_map = None
        
        # 3. If model is configured, train it
        if model_config:
            if model_config.get("train_test_split") is not None:
                raise ValueError(
                    "model_config.train_test_split is no longer supported. "
                    "Define train/validation/test windows under backtest_segments instead."
                )

            split_config = _train_test_split_from_segments(backtest_segments)
            if split_config is None:
                raise ValueError(
                    "When model_config is provided, backtest.segments must define train/test date ranges."
                )

            train_range = (split_config["train_start"], split_config["train_end"])
            test_range = (split_config["test_start"], split_config["test_end"])

            validation_range = None
            if split_config.get("validation_start") and split_config.get("validation_end"):
                validation_range = (
                    split_config["validation_start"],
                    split_config["validation_end"],
                )

            print("[INFO] === Training ML Model ===")
            # Prepare training data
            train_df, validation_df, test_df, feature_cols = prepare_training_data(
                features_df,
                target_name=model_config.get("target", "forward_return"),
                symbol_col=symbol_col,
                timestamp_col=timestamp_col,
                train_range=train_range,
                validation_range=validation_range,
                test_range=test_range,
                feature_names=feature_names,
                feature_map=feature_map,
                include_ohlcv=include_ohlcv,
            )
            
            # Train model
            print(f"[INFO] Training {model_config.get('type', 'lightgbm')} model...")
            target_name = model_config.get("target", "forward_return")
            X_train = train_df[feature_cols]
            y_train = train_df[target_name]
            X_val = None
            y_val = None
            if len(validation_df) > 0:
                X_val = validation_df[feature_cols]
                y_val = validation_df[target_name]

            X_test = test_df[feature_cols]
            y_test = test_df[target_name]
            
            model = create_model(
                model_config.get("type", "lightgbm"),
                model_config.get("params", {})
            )
            model, train_ic, test_ic, validation_ic = train_and_evaluate(
                model, X_train, y_train, X_test, y_test, X_val=X_val, y_val=y_val
            )
            val_msg = (
                f", Validation IC: {validation_ic['IC']:.3f}"
                if validation_ic is not None
                else ""
            )
            print(
                f"[INFO] ✓ Model trained - "
                f"Train IC: {train_ic['IC']:.3f}{val_msg}, Test IC: {test_ic['IC']:.3f}"
            )
            
            # Generate predictions for both train and test segments
            train_predictions = model.predict(X_train)
            validation_predictions = None
            if X_val is not None and len(X_val) > 0:
                validation_predictions = model.predict(X_val)
            test_predictions = model.predict(X_test)
            
            # Log model training metrics to MLflow
            if log_to_mlflow and recorder:
                recorder.log_metrics(
                    train_ic=train_ic["IC"],
                    train_rank_ic=train_ic["Rank_IC"],
                    **(
                        {
                            "validation_ic": validation_ic["IC"],
                            "validation_rank_ic": validation_ic["Rank_IC"],
                        }
                        if validation_ic is not None
                        else {}
                    ),
                    test_ic=test_ic["IC"],
                    test_rank_ic=test_ic["Rank_IC"],
                )
            
            # Build signal dataframes for train and test
            train_signals_df = train_df[[symbol_col, timestamp_col]].copy()
            train_signals_df["signal"] = train_predictions
            signal_frames = [train_signals_df]

            if validation_predictions is not None:
                validation_signals_df = validation_df[[symbol_col, timestamp_col]].copy()
                validation_signals_df["signal"] = validation_predictions
                signal_frames.append(validation_signals_df)

            test_signals_df = test_df[[symbol_col, timestamp_col]].copy()
            test_signals_df["signal"] = test_predictions
            signal_frames.append(test_signals_df)
            
            signals_df = pd.concat(signal_frames, ignore_index=True)
            signals_df.columns = ["symbol", "timestamp", "signal"]
            signals_df = signals_df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
            
            # Build price dataframe covering both train and test periods
            price_frames = [
                train_df[[symbol_col, timestamp_col, "close"]].copy(),
            ]
            if len(validation_df) > 0:
                price_frames.append(validation_df[[symbol_col, timestamp_col, "close"]].copy())
            price_frames.append(test_df[[symbol_col, timestamp_col, "close"]].copy())

            prices_df = pd.concat(price_frames, ignore_index=True)
            prices_df.columns = ["symbol", "timestamp", "close"]
            prices_df = prices_df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
            
        else:
            # No model - use factor values directly as signal
            # NOTE: If multiple factors provided, uses FIRST factor as signal
            # To combine multiple factors, either:
            #   1. Provide single combined expression, e.g., "(FACTOR1 + FACTOR2) / 2"
            #   2. Or set model_config to train ML model on all factors
            
            if not factor_expressions:
                raise ValueError("Must provide either factor_expressions or model_config")
            
            signal_col = factor_expressions[0]["name"]  # Use first factor as signal
            signals_df = features_df[[symbol_col, timestamp_col, signal_col]].copy()
            signals_df.columns = ["symbol", "timestamp", "signal"]
            
            prices_df = features_df[[symbol_col, timestamp_col, "close"]].copy()
            prices_df.columns = ["symbol", "timestamp", "close"]
            
            model = None
            train_ic = None
            test_ic = None
            feature_cols = [signal_col]
            
            # Log info about which factor is being used
            if len(factor_expressions) > 1:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Multiple factors provided but model_config=None. "
                    f"Using first factor '{signal_col}' as signal. "
                    f"Other factors: {[f['name'] for f in factor_expressions[1:]]}"
                )
        
        # 4. Run backtest
        segments = (
            build_segments_dict(
                train_segment=backtest_segments.get("train") if backtest_segments else None,
                validation_segment=backtest_segments.get("validation") if backtest_segments else None,
                test_segment=backtest_segments.get("test") if backtest_segments else None,
            )
            if backtest_segments
            else None
        )
        
        backtest_result = _run_backtest(
            signals_df=signals_df,
            prices_df=prices_df,
            segments=segments,
            strategy_type=strategy_type,
            strategy_params=strategy_params or {},
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            min_commission=min_commission,
            rebalance_frequency=rebalance_frequency,
            allow_short=allow_short,
            intraday_short_only=intraday_short_only,
            short_funding_rate=short_funding_rate,
        )
        
        if not backtest_result["success"]:
            return backtest_result
        
        # 5. Build comprehensive result
        # Always include both train and test results (even if None)
        # Use explicit None checks to avoid "truth value of DataFrame is ambiguous" error
        
        # Get results - prefer test, then validation, then aggregate/backward compatible
        results_df = None
        for key in ("test_results_df", "validation_results_df", "results_df"):
            candidate = backtest_result.get(key)
            if candidate is not None:
                results_df = candidate
                break

        metrics = None
        for key in ("test_metrics", "validation_metrics", "metrics"):
            candidate_metrics = backtest_result.get(key)
            if candidate_metrics:
                metrics = candidate_metrics
                break
        
        result = {
            "success": True,
            "results_df": results_df,  # Main results (test if available, otherwise all)
            "metrics": metrics,  # Main metrics (test if available, otherwise all)
            "train_results_df": backtest_result.get("train_results_df"),
            "validation_results_df": backtest_result.get("validation_results_df"),
            "test_results_df": backtest_result.get("test_results_df"),
            "train_metrics": backtest_result.get("train_metrics"),
            "validation_metrics": backtest_result.get("validation_metrics"),
            "test_metrics": backtest_result.get("test_metrics"),
            "holdings_df": backtest_result.get("holdings_df"),
            "train_holdings_df": backtest_result.get("train_holdings_df"),
            "validation_holdings_df": backtest_result.get("validation_holdings_df"),
            "test_holdings_df": backtest_result.get("test_holdings_df"),
            "run_info": {
                "experiment_name": experiment_name,
                "run_name": resolved_run_name,
                "model_type": model_config.get("type") if model_config else None,
                "strategy_type": strategy_type,
            },
            "error": None,
        }
        
        # Add model results if trained
        if model is not None:
            result["model"] = model
            result["train_ic"] = train_ic
            result["test_ic"] = test_ic
            if validation_ic is not None:
                result["validation_ic"] = validation_ic
            result["feature_cols"] = feature_cols
            
            # Save model to MLflow for future inference
            if log_to_mlflow and recorder:
                try:
                    recorder.save_objects(model=model)
                    print("[INFO] ✓ Saved trained model to MLflow artifacts", flush=True)
                except Exception as save_err:
                    print(f"[WARN] Failed to save model to MLflow: {save_err}", flush=True)
        
        # Log backtest metrics to MLflow
        if log_to_mlflow and recorder:
            logged_segment_metrics = False
            for prefix_key, metrics_payload in (
                ("train", result.get("train_metrics")),
                ("validation", result.get("validation_metrics")),
                ("test", result.get("test_metrics")),
            ):
                if metrics_payload is None:
                    continue
                segment_metrics_prefixed = {
                    f"backtest_{prefix_key}_{k}": v for k, v in metrics_payload.items()
                }
                recorder.log_metrics(**segment_metrics_prefixed)
                logged_segment_metrics = True

            if not logged_segment_metrics and result["metrics"] is not None:
                backtest_metrics_prefixed = {f"backtest_{k}": v for k, v in result["metrics"].items()}
                recorder.log_metrics(**backtest_metrics_prefixed)
        
        # Close MLflow run if we created it
        if mlflow_context:
            mlflow_context.__exit__(None, None, None)
        
        print("\n" + "=" * 80, flush=True)
        print("✓ Workflow completed successfully!", flush=True)
        print("=" * 80, flush=True)
        
        return result
        
    except Exception as e:
        # Close MLflow run if we created it
        if mlflow_context:
            mlflow_context.__exit__(None, None, None)
        
        return {
            "success": False,
            "results_df": None,
            "metrics": {},
            "train_results_df": None,
            "validation_results_df": None,
            "test_results_df": None,
            "train_metrics": None,
            "validation_metrics": None,
            "test_metrics": None,
            "holdings_df": None,
            "train_holdings_df": None,
            "validation_holdings_df": None,
            "test_holdings_df": None,
            "error": str(e),
        }

