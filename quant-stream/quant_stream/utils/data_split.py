"""Data splitting utilities for train/test splits."""

from __future__ import annotations
from typing import Optional, Tuple
import pandas as pd


def train_test_split_by_date(
    df: pd.DataFrame,
    timestamp_col: str = "timestamp",
    train_start_date: Optional[str] = None,
    train_end_date: Optional[str] = None,
    test_start_date: Optional[str] = None,
    test_end_date: Optional[str] = None,
    default_split_ratio: float = 0.7,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Split a DataFrame into train and test sets based on dates.
    
    If date parameters are not provided, falls back to a simple ratio-based split.
    
    Args:
        df: DataFrame to split
        timestamp_col: Name of the timestamp column (default: "timestamp")
        train_start_date: Start date for training data (e.g., '2020-01-01', None for all)
        train_end_date: End date for training data (e.g., '2021-12-31', None for all)
        test_start_date: Start date for test data (e.g., '2022-01-01', None for all)
        test_end_date: End date for test data (e.g., '2022-12-31', None for all)
        default_split_ratio: Ratio for train split if dates not provided (default: 0.7)
    
    Returns:
        Tuple of (train_df, test_df)
    
    Examples:
        >>> # Date-based split
        >>> train_df, test_df = train_test_split_by_date(
        ...     df,
        ...     train_start_date='2020-01-01',
        ...     train_end_date='2021-12-31',
        ...     test_start_date='2022-01-01',
        ...     test_end_date='2022-12-31'
        ... )
        
        >>> # Default 70/30 split
        >>> train_df, test_df = train_test_split_by_date(df)
    """
    # Make a copy to avoid modifying the original
    df = df.copy()
    
    # Convert timestamp to datetime if needed
    if not pd.api.types.is_datetime64_any_dtype(df[timestamp_col]):
        df[timestamp_col] = pd.to_datetime(df[timestamp_col])
    
    # Check if date-based splitting is requested
    if train_start_date or train_end_date or test_start_date or test_end_date:
        # Date-based splitting
        train_df = df.copy()
        if train_start_date:
            train_df = train_df[train_df[timestamp_col] >= pd.to_datetime(train_start_date)]
        if train_end_date:
            train_df = train_df[train_df[timestamp_col] <= pd.to_datetime(train_end_date)]
        
        test_df = df.copy()
        if test_start_date:
            test_df = test_df[test_df[timestamp_col] >= pd.to_datetime(test_start_date)]
        if test_end_date:
            test_df = test_df[test_df[timestamp_col] <= pd.to_datetime(test_end_date)]
    else:
        # Default ratio-based split
        split_idx = int(len(df) * default_split_ratio)
        train_df = df.iloc[:split_idx]
        test_df = df.iloc[split_idx:]
    
    return train_df, test_df


def print_split_info(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    timestamp_col: str = "timestamp",
) -> None:
    """Print information about the train/test split.
    
    Args:
        train_df: Training DataFrame
        test_df: Test DataFrame
        timestamp_col: Name of the timestamp column (default: "timestamp")
    """
    print(f"  Train: {len(train_df):,} samples", end="")
    if len(train_df) > 0 and timestamp_col in train_df.columns:
        print(f" (from {train_df[timestamp_col].min()} to {train_df[timestamp_col].max()})")
    else:
        print()
    
    print(f"  Test:  {len(test_df):,} samples", end="")
    if len(test_df) > 0 and timestamp_col in test_df.columns:
        print(f" (from {test_df[timestamp_col].min()} to {test_df[timestamp_col].max()})")
    else:
        print()

