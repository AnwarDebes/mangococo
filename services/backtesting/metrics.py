"""
Performance metrics calculation for backtesting results.

All functions operate on plain Python / NumPy / Pandas structures
so they can be used independently of the rest of the service.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Core risk-adjusted return metrics
# ---------------------------------------------------------------------------

def calculate_sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 60,
) -> float:
    """
    Annualized Sharpe ratio.

    Parameters
    ----------
    returns : array-like
        Per-period simple returns (e.g. per-minute if using 1m candles).
    risk_free_rate : float
        Annualized risk-free rate (default 0).
    periods_per_year : int
        Number of return periods in a year.  Default assumes 1-minute bars
        across a 24/7 crypto market (365 * 24 * 60).
    """
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) < 2:
        return 0.0

    excess = returns - risk_free_rate / periods_per_year
    mean_excess = np.mean(excess)
    std = np.std(excess, ddof=1)

    if std == 0:
        return 0.0

    return float(mean_excess / std * np.sqrt(periods_per_year))


def calculate_sortino_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365 * 24 * 60,
) -> float:
    """
    Annualized Sortino ratio (penalizes only downside volatility).
    """
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) < 2:
        return 0.0

    excess = returns - risk_free_rate / periods_per_year
    mean_excess = np.mean(excess)

    downside = excess[excess < 0]
    if len(downside) == 0:
        return float("inf") if mean_excess > 0 else 0.0

    downside_std = np.std(downside, ddof=1)
    if downside_std == 0:
        return 0.0

    return float(mean_excess / downside_std * np.sqrt(periods_per_year))


# ---------------------------------------------------------------------------
# Drawdown metrics
# ---------------------------------------------------------------------------

def calculate_max_drawdown(equity_curve: np.ndarray) -> float:
    """
    Maximum peak-to-trough decline as a positive fraction (e.g. 0.15 = 15%).

    Parameters
    ----------
    equity_curve : array-like
        Equity values over time.
    """
    equity = np.asarray(equity_curve, dtype=np.float64)
    if len(equity) < 2:
        return 0.0

    running_max = np.maximum.accumulate(equity)
    drawdowns = (running_max - equity) / np.where(running_max > 0, running_max, 1.0)
    return float(np.max(drawdowns))


def calculate_calmar_ratio(
    returns: np.ndarray,
    max_drawdown: float,
    periods_per_year: int = 365 * 24 * 60,
) -> float:
    """
    Calmar ratio = annualized return / max drawdown.
    """
    if max_drawdown <= 0:
        return 0.0

    returns = np.asarray(returns, dtype=np.float64)
    total_return = np.prod(1 + returns) - 1
    n_periods = len(returns)
    if n_periods == 0:
        return 0.0

    annualized = (1 + total_return) ** (periods_per_year / n_periods) - 1
    return float(annualized / max_drawdown)


# ---------------------------------------------------------------------------
# Trade-level metrics
# ---------------------------------------------------------------------------

def calculate_win_rate(trades: List[Dict[str, Any]]) -> float:
    """Fraction of trades with positive PnL."""
    if not trades:
        return 0.0
    winners = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return float(winners / len(trades))


def calculate_profit_factor(trades: List[Dict[str, Any]]) -> float:
    """Gross profit / gross loss.  Returns inf if no losses."""
    gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))

    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def calculate_avg_trade(trades: List[Dict[str, Any]]) -> float:
    """Average PnL per trade."""
    if not trades:
        return 0.0
    return float(np.mean([t.get("pnl", 0) for t in trades]))


def calculate_avg_win_loss_ratio(trades: List[Dict[str, Any]]) -> float:
    """Average winning trade / average losing trade (absolute value)."""
    wins = [t["pnl"] for t in trades if t.get("pnl", 0) > 0]
    losses = [abs(t["pnl"]) for t in trades if t.get("pnl", 0) < 0]

    if not wins or not losses:
        return 0.0
    return float(np.mean(wins) / np.mean(losses))


# ---------------------------------------------------------------------------
# Time-series analysis
# ---------------------------------------------------------------------------

def calculate_monthly_returns(equity_curve: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Break equity curve into monthly returns.

    Parameters
    ----------
    equity_curve : list of dict
        Each dict must have 'timestamp' (datetime) and 'equity' (float).

    Returns
    -------
    dict mapping 'YYYY-MM' -> monthly return as a fraction.
    """
    if not equity_curve:
        return {}

    df = pd.DataFrame(equity_curve)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").set_index("timestamp")

    # Resample to month-end, take last equity value
    monthly = df["equity"].resample("ME").last().dropna()
    if len(monthly) < 2:
        return {}

    returns = monthly.pct_change().dropna()
    return {dt.strftime("%Y-%m"): round(float(v), 6) for dt, v in returns.items()}


# ---------------------------------------------------------------------------
# Full performance report
# ---------------------------------------------------------------------------

def generate_report(
    trades: List[Dict[str, Any]],
    equity_curve: List[Dict[str, Any]],
    initial_capital: float,
) -> Dict[str, Any]:
    """
    Produce a comprehensive performance report dictionary.
    """
    equity_values = np.array(
        [initial_capital] + [p["equity"] for p in equity_curve],
        dtype=np.float64,
    )

    # Per-period returns from equity curve
    if len(equity_values) > 1:
        returns = np.diff(equity_values) / equity_values[:-1]
    else:
        returns = np.array([], dtype=np.float64)

    final_capital = float(equity_values[-1]) if len(equity_values) > 0 else initial_capital
    total_return = (final_capital - initial_capital) / initial_capital if initial_capital > 0 else 0.0
    max_dd = calculate_max_drawdown(equity_values)

    winning_trades = [t for t in trades if t.get("pnl", 0) > 0]
    losing_trades = [t for t in trades if t.get("pnl", 0) < 0]

    report: Dict[str, Any] = {
        # Capital
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2),
        "total_return": round(total_return, 6),
        "total_return_pct": round(total_return * 100, 2),

        # Risk metrics
        "sharpe_ratio": round(calculate_sharpe_ratio(returns), 4),
        "sortino_ratio": round(calculate_sortino_ratio(returns), 4),
        "max_drawdown": round(max_dd, 6),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "calmar_ratio": round(calculate_calmar_ratio(returns, max_dd), 4),

        # Trade stats
        "total_trades": len(trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "win_rate": round(calculate_win_rate(trades), 4),
        "profit_factor": round(calculate_profit_factor(trades), 4),
        "avg_trade_pnl": round(calculate_avg_trade(trades), 4),
        "avg_win_loss_ratio": round(calculate_avg_win_loss_ratio(trades), 4),

        # Total fees and slippage
        "total_fees": round(sum(t.get("fees", 0) for t in trades), 4),
        "total_slippage": round(sum(t.get("slippage", 0) for t in trades), 4),

        # Monthly breakdown
        "monthly_returns": calculate_monthly_returns(equity_curve),
    }

    return report
