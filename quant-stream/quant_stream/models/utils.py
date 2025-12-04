"""Utility functions for model training and evaluation."""

from typing import Dict, List, Tuple

import pandas as pd
from scipy import stats


def create_lagged_features(
    df: pd.DataFrame,
    columns: List[str],
    lags: List[int],
    instrument_col: str = "symbol",
) -> pd.DataFrame:
    """Create lagged features for time-series prediction.

    Args:
        df: DataFrame with time-series data
        columns: Columns to create lags for
        lags: List of lag periods (e.g., [1, 5, 10])
        instrument_col: Column identifying different instruments

    Returns:
        DataFrame with original columns and lagged features

    Example:
        >>> df_lagged = create_lagged_features(
        ...     df,
        ...     columns=["close", "volume"],
        ...     lags=[1, 5, 10],
        ...     instrument_col="symbol"
        ... )
    """
    result = df.copy()

    for col in columns:
        for lag in lags:
            lag_col = f"{col}_lag_{lag}"
            result[lag_col] = result.groupby(instrument_col)[col].shift(lag)

    return result


def calculate_ic(predictions: pd.Series, labels: pd.Series) -> Dict[str, float]:
    """Calculate Information Coefficient metrics.

    Args:
        predictions: Model predictions
        labels: True labels

    Returns:
        Dictionary with IC, Rank IC, ICIR, and Rank ICIR

    Example:
        >>> metrics = calculate_ic(pred, actual)
        >>> print(f"IC: {metrics['IC']:.4f}, Rank IC: {metrics['Rank_IC']:.4f}")
    """
    # Ensure inputs are Series (handle potential DataFrames)
    if isinstance(predictions, pd.DataFrame):
        predictions = predictions.iloc[:, 0]
    if isinstance(labels, pd.DataFrame):
        labels = labels.iloc[:, 0]
    
    # Remove NaN values
    mask = ~(predictions.isna() | labels.isna())
    pred = predictions[mask]
    label = labels[mask]

    if len(pred) < 2:
        return {"IC": 0.0, "Rank_IC": 0.0, "ICIR": 0.0, "Rank_ICIR": 0.0}

    # Check for constant values (would cause correlation to be undefined)
    pred_std = pred.std()
    label_std = label.std()
    
    # Use a small threshold for near-constant values (machine precision)
    EPSILON = 1e-10
    if pred_std < EPSILON or label_std < EPSILON:
        # Constant or near-constant input - correlation is undefined
        print(f"[DEBUG] Constant input detected - pred_std: {pred_std:.10f}, label_std: {label_std:.10f}")
        return {"IC": 0.0, "Rank_IC": 0.0, "ICIR": 0.0, "Rank_ICIR": 0.0}

    # Information Coefficient (Pearson correlation)
    ic = pred.corr(label)
    if pd.isna(ic):
        print(f"[DEBUG] IC is NaN - pred_std: {pred_std:.10f}, label_std: {label_std:.10f}")
        ic = 0.0

    # Rank IC (Spearman correlation)
    try:
        rank_ic, p_value = stats.spearmanr(pred, label)
        if pd.isna(rank_ic):
            print(f"[DEBUG] Rank IC is NaN")
            rank_ic = 0.0
        else:
            print(f"[DEBUG] IC calculation - IC: {ic:.6f}, Rank IC: {rank_ic:.6f}, p-value: {p_value:.6f}, n_samples: {len(pred)}")
    except ValueError as e:
        # Handle constant input or other issues
        print(f"[DEBUG] ValueError in spearmanr: {e}")
        rank_ic = 0.0

    # ICIR = IC / std(IC) - approximation using single value
    # For proper ICIR, we'd need multiple periods
    icir = ic  # Simplified for single period

    # Rank ICIR
    rank_icir = rank_ic  # Simplified for single period

    return {
        "IC": float(ic),
        "Rank_IC": float(rank_ic),
        "ICIR": float(icir),
        "Rank_ICIR": float(rank_icir),
    }


def calculate_ic_by_period(
    df: pd.DataFrame,
    pred_col: str = "prediction",
    label_col: str = "label",
    time_col: str = "date",
) -> pd.DataFrame:
    """Calculate IC metrics for each time period.

    Args:
        df: DataFrame with predictions and labels
        pred_col: Column name for predictions
        label_col: Column name for labels
        time_col: Column name for time grouping

    Returns:
        DataFrame with IC and Rank IC for each period

    Example:
        >>> ic_df = calculate_ic_by_period(results_df)
        >>> print(f"Mean IC: {ic_df['IC'].mean():.4f}")
    """
    results = []

    for date, group in df.groupby(time_col):
        ic_metrics = calculate_ic(group[pred_col], group[label_col])
        results.append(
            {
                time_col: date,
                "IC": ic_metrics["IC"],
                "Rank_IC": ic_metrics["Rank_IC"],
                "n_samples": len(group),
            }
        )

    ic_df = pd.DataFrame(results)

    # Calculate ICIR as IC / std(IC)
    if len(ic_df) > 1:
        ic_df["ICIR"] = ic_df["IC"].mean() / ic_df["IC"].std()
        ic_df["Rank_ICIR"] = ic_df["Rank_IC"].mean() / ic_df["Rank_IC"].std()
    else:
        ic_df["ICIR"] = 0.0
        ic_df["Rank_ICIR"] = 0.0

    return ic_df


def rolling_window_split(
    df: pd.DataFrame,
    train_periods: int,
    test_periods: int,
    time_col: str = "date",
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """Create rolling window train/test splits for time-series cross-validation.

    Args:
        df: DataFrame with time-series data
        train_periods: Number of periods in training window
        test_periods: Number of periods in test window
        time_col: Column name for time

    Returns:
        List of (train_df, test_df) tuples

    Example:
        >>> splits = rolling_window_split(df, train_periods=252, test_periods=21)
        >>> for train, test in splits:
        ...     model.fit(train[features], train[target])
        ...     preds = model.predict(test[features])
    """
    # Get unique time periods sorted
    periods = sorted(df[time_col].unique())

    if len(periods) < train_periods + test_periods:
        raise ValueError(
            f"Not enough periods: {len(periods)} < {train_periods + test_periods}"
        )

    splits = []
    for i in range(0, len(periods) - train_periods - test_periods + 1, test_periods):
        train_end = i + train_periods
        test_end = train_end + test_periods

        train_dates = periods[i:train_end]
        test_dates = periods[train_end:test_end]

        train_df = df[df[time_col].isin(train_dates)]
        test_df = df[df[time_col].isin(test_dates)]

        splits.append((train_df, test_df))

    return splits


def normalize_features(
    X_train: pd.DataFrame, X_test: pd.DataFrame, method: str = "zscore"
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize features using training statistics.

    Args:
        X_train: Training features
        X_test: Test features
        method: Normalization method ('zscore', 'minmax', or 'robust')

    Returns:
        Tuple of (normalized_train, normalized_test)

    Example:
        >>> X_train_norm, X_test_norm = normalize_features(X_train, X_test)
    """
    X_train = X_train.copy()
    X_test = X_test.copy()

    if method == "zscore":
        # Z-score normalization
        mean = X_train.mean()
        std = X_train.std()
        std = std.replace(0, 1)  # Avoid division by zero

        X_train = (X_train - mean) / std
        X_test = (X_test - mean) / std

    elif method == "minmax":
        # Min-max normalization
        min_val = X_train.min()
        max_val = X_train.max()
        range_val = max_val - min_val
        range_val = range_val.replace(0, 1)  # Avoid division by zero

        X_train = (X_train - min_val) / range_val
        X_test = (X_test - min_val) / range_val

    elif method == "robust":
        # Robust scaling using median and IQR
        median = X_train.median()
        q75 = X_train.quantile(0.75)
        q25 = X_train.quantile(0.25)
        iqr = q75 - q25
        iqr = iqr.replace(0, 1)  # Avoid division by zero

        X_train = (X_train - median) / iqr
        X_test = (X_test - median) / iqr

    else:
        raise ValueError(f"Unknown normalization method: {method}")

    return X_train, X_test

