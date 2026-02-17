"""Performance metrics calculation for backtesting."""

import numpy as np
import pandas as pd
from scipy import stats


def calculate_returns_metrics(returns: pd.Series, periods_per_year: int = 252) -> dict:
    """Calculate comprehensive return metrics.

    Args:
        returns: Series of periodic returns (as fractions, not percentages)
        periods_per_year: Number of periods in a year (252 for daily, 12 for monthly)

    Returns:
        Dictionary with performance metrics:
            - total_return: Cumulative return
            - annual_return: Annualized return
            - annual_volatility: Annualized volatility
            - sharpe_ratio: Sharpe ratio (assuming 0 risk-free rate)
            - sortino_ratio: Sortino ratio
            - max_drawdown: Maximum drawdown
            - calmar_ratio: Calmar ratio (return / max drawdown)
            - win_rate: Percentage of positive returns
            - avg_win: Average winning return
            - avg_loss: Average losing return
            - profit_factor: Sum of wins / sum of losses

    Example:
        >>> metrics = calculate_returns_metrics(portfolio_returns)
        >>> print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    """
    if len(returns) == 0:
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "annual_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown": 0.0,
            "calmar_ratio": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
        }

    # Remove NaN values
    returns = returns.dropna()

    if len(returns) == 0:
        return {k: 0.0 for k in ["total_return", "annual_return", "sharpe_ratio"]}

    # Total return
    total_return = (1 + returns).prod() - 1

    # Annualized return
    n_periods = len(returns)
    years = n_periods / periods_per_year
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0

    # Volatility
    annual_volatility = returns.std() * np.sqrt(periods_per_year)

    # Sharpe ratio (assuming 0 risk-free rate)
    sharpe_ratio = (
        (annual_return / annual_volatility) if annual_volatility > 0 else 0.0
    )

    # Sortino ratio (downside deviation)
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() * np.sqrt(periods_per_year)
    sortino_ratio = (annual_return / downside_std) if downside_std > 0 else 0.0

    # Maximum drawdown
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min()

    # Calmar ratio
    calmar_ratio = (
        (annual_return / abs(max_drawdown)) if max_drawdown != 0 else 0.0
    )

    # Win/loss statistics
    wins = returns[returns > 0]
    losses = returns[returns < 0]

    win_rate = len(wins) / len(returns) if len(returns) > 0 else 0.0
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = losses.mean() if len(losses) > 0 else 0.0

    # Profit factor
    total_wins = wins.sum() if len(wins) > 0 else 0.0
    total_losses = abs(losses.sum()) if len(losses) > 0 else 0.0
    profit_factor = (total_wins / total_losses) if total_losses > 0 else 0.0

    return {
        "total_return": float(total_return),
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_volatility),
        "sharpe_ratio": float(sharpe_ratio),
        "sortino_ratio": float(sortino_ratio),
        "max_drawdown": float(max_drawdown),
        "calmar_ratio": float(calmar_ratio),
        "win_rate": float(win_rate),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
        "profit_factor": float(profit_factor),
    }


def calculate_ic_metrics(predictions: pd.Series, labels: pd.Series) -> dict:
    """Calculate Information Coefficient metrics.

    Args:
        predictions: Model predictions
        labels: True labels

    Returns:
        Dictionary with IC metrics:
            - IC: Pearson correlation between predictions and labels
            - Rank_IC: Spearman rank correlation
            - ICIR: Information Coefficient Information Ratio
            - Rank_ICIR: Rank IC Information Ratio

    Example:
        >>> ic_metrics = calculate_ic_metrics(predictions, actual_returns)
        >>> print(f"IC: {ic_metrics['IC']:.4f}")
    """
    # Ensure inputs are Series (not DataFrames)
    if isinstance(predictions, pd.DataFrame):
        predictions = predictions.iloc[:, 0] if not predictions.empty else pd.Series(dtype=float)
    if isinstance(labels, pd.DataFrame):
        labels = labels.iloc[:, 0] if not labels.empty else pd.Series(dtype=float)
    
    # Remove NaN values
    mask = ~(predictions.isna() | labels.isna())
    pred = predictions[mask]
    label = labels[mask]

    if len(pred) < 2:
        return {"IC": 0.0, "Rank_IC": 0.0, "ICIR": 0.0, "Rank_ICIR": 0.0}

    # Check for constant values (would cause correlation to be undefined)
    pred_std = pred.std()
    label_std = label.std()
    
    if pred_std == 0 or label_std == 0:
        # Constant input - correlation is undefined
        return {"IC": 0.0, "Rank_IC": 0.0, "ICIR": 0.0, "Rank_ICIR": 0.0}

    # Information Coefficient (Pearson correlation)
    ic = pred.corr(label)
    if np.isnan(ic):
        ic = 0.0

    # Rank IC (Spearman correlation)
    try:
        rank_ic, _ = stats.spearmanr(pred, label)
        if np.isnan(rank_ic):
            rank_ic = 0.0
    except ValueError:
        # Handle constant input or other issues
        rank_ic = 0.0

    # ICIR = IC / std(IC) - for single period, just return IC
    icir = ic
    rank_icir = rank_ic

    return {
        "IC": float(ic) if not np.isnan(ic) else 0.0,
        "Rank_IC": float(rank_ic) if not np.isnan(rank_ic) else 0.0,
        "ICIR": float(icir) if not np.isnan(icir) else 0.0,
        "Rank_ICIR": float(rank_icir) if not np.isnan(rank_icir) else 0.0,
    }


def calculate_drawdown(returns: pd.Series) -> pd.Series:
    """Calculate drawdown series.

    Args:
        returns: Series of returns

    Returns:
        Series of drawdown values

    Example:
        >>> dd = calculate_drawdown(returns)
        >>> print(f"Max drawdown: {dd.min():.2%}")
    """
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    return drawdown


def calculate_sharpe_ratio(
    returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252
) -> float:
    """Calculate Sharpe ratio.

    Args:
        returns: Series of returns
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods per year

    Returns:
        Sharpe ratio

    Example:
        >>> sharpe = calculate_sharpe_ratio(returns)
    """
    if len(returns) == 0:
        return 0.0

    excess_returns = returns - (risk_free_rate / periods_per_year)
    std = returns.std()
    
    # Handle zero volatility case  - return 0 to avoid breaking downstream calculations
    if std == 0 or np.isnan(std):
        return 0.0

    return float(excess_returns.mean() / std * np.sqrt(periods_per_year))


def calculate_sortino_ratio(
    returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 252
) -> float:
    """Calculate Sortino ratio (using downside deviation).

    Args:
        returns: Series of returns
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods per year

    Returns:
        Sortino ratio

    Example:
        >>> sortino = calculate_sortino_ratio(returns)
    """
    if len(returns) == 0:
        return 0.0

    excess_returns = returns - (risk_free_rate / periods_per_year)
    downside_returns = returns[returns < 0]

    if len(downside_returns) == 0 or downside_returns.std() == 0:
        return 0.0

    downside_std = downside_returns.std()
    return float(excess_returns.mean() / downside_std * np.sqrt(periods_per_year))


def calculate_max_drawdown(returns: pd.Series) -> float:
    """Calculate maximum drawdown.

    Args:
        returns: Series of returns

    Returns:
        Maximum drawdown (negative value)

    Example:
        >>> max_dd = calculate_max_drawdown(returns)
        >>> print(f"Max drawdown: {max_dd:.2%}")
    """
    if len(returns) == 0:
        return 0.0

    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    return float(drawdown.min())


def calculate_calmar_ratio(
    returns: pd.Series, periods_per_year: int = 252
) -> float:
    """Calculate Calmar ratio (annual return / max drawdown).

    Args:
        returns: Series of returns
        periods_per_year: Number of periods per year

    Returns:
        Calmar ratio

    Example:
        >>> calmar = calculate_calmar_ratio(returns)
    """
    if len(returns) == 0:
        return 0.0

    # Annual return
    total_return = (1 + returns).prod() - 1
    years = len(returns) / periods_per_year
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0

    # Max drawdown
    max_dd = calculate_max_drawdown(returns)

    if max_dd == 0:
        return 0.0

    return float(annual_return / abs(max_dd))


def calculate_turnover(positions: pd.DataFrame, value_col: str = "value") -> float:
    """Calculate portfolio turnover.

    Args:
        positions: DataFrame with position values over time
        value_col: Name of the value column

    Returns:
        Average turnover per period

    Example:
        >>> turnover = calculate_turnover(positions_df)
    """
    if len(positions) < 2:
        return 0.0

    # Calculate absolute changes in positions
    changes = positions[value_col].diff().abs()

    # Average turnover
    avg_turnover = changes.mean()

    return float(avg_turnover)


def calculate_benchmark_metrics(
    returns: pd.Series, benchmark_returns: pd.Series, periods_per_year: int = 252
) -> dict:
    """Calculate metrics relative to a benchmark.

    Args:
        returns: Portfolio returns
        benchmark_returns: Benchmark returns
        periods_per_year: Number of periods per year

    Returns:
        Dictionary with:
            - alpha: Jensen's alpha
            - beta: Portfolio beta
            - tracking_error: Tracking error (volatility of excess returns)
            - information_ratio: Information ratio

    Example:
        >>> bench_metrics = calculate_benchmark_metrics(returns, sp500_returns)
    """
    if len(returns) != len(benchmark_returns) or len(returns) < 2:
        return {
            "alpha": 0.0,
            "beta": 0.0,
            "tracking_error": 0.0,
            "information_ratio": 0.0,
        }

    # Align and remove NaNs
    df = pd.DataFrame({"returns": returns, "benchmark": benchmark_returns}).dropna()

    if len(df) < 2:
        return {
            "alpha": 0.0,
            "beta": 0.0,
            "tracking_error": 0.0,
            "information_ratio": 0.0,
        }

    # Beta (covariance / variance)
    covariance = df["returns"].cov(df["benchmark"])
    variance = df["benchmark"].var()
    beta = covariance / variance if variance > 0 else 0.0

    # Alpha (excess return after adjusting for beta)
    mean_return = df["returns"].mean() * periods_per_year
    mean_benchmark = df["benchmark"].mean() * periods_per_year
    alpha = mean_return - beta * mean_benchmark

    # Tracking error
    excess_returns = df["returns"] - df["benchmark"]
    tracking_error = excess_returns.std() * np.sqrt(periods_per_year)

    # Information ratio
    information_ratio = (
        (excess_returns.mean() * periods_per_year / tracking_error)
        if tracking_error > 0
        else 0.0
    )

    return {
        "alpha": float(alpha),
        "beta": float(beta),
        "tracking_error": float(tracking_error),
        "information_ratio": float(information_ratio),
    }

