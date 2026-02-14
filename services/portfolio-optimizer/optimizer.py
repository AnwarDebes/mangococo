"""
Portfolio optimization module.

Uses scipy.optimize to compute a mean-variance efficient allocation
across symbols, subject to a cash-reserve constraint and per-position caps.
"""
import os

import numpy as np
from scipy.optimize import minimize
import structlog

logger = structlog.get_logger()

MAX_POSITION_PCT = float(os.getenv("PORTFOLIO_MAX_POSITION_PCT", 0.05))
CASH_RESERVE_PCT = float(os.getenv("PORTFOLIO_CASH_RESERVE_PCT", 0.20))
RISK_AVERSION = 2.0  # Lambda for mean-variance utility:  U = mu - (lambda/2) * sigma^2


def _estimate_returns_and_cov(
    candle_data: dict[str, list[dict]],
    symbols: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Estimate expected returns (annualised from 1-min bars) and covariance
    matrix from close-price log returns.

    Returns (mu, cov) both as numpy arrays of shape (n,) and (n, n).
    Falls back to identity covariance and zero returns for missing data.
    """
    n = len(symbols)
    returns_lists: list[np.ndarray] = []
    min_len = None

    for sym in symbols:
        candles = candle_data.get(sym, [])
        closes = np.array([c["close"] for c in candles if c.get("close")], dtype=np.float64)
        if len(closes) < 20:
            # Not enough data -- use zeros
            returns_lists.append(None)
            continue
        log_ret = np.diff(np.log(closes))
        returns_lists.append(log_ret)
        if min_len is None or len(log_ret) < min_len:
            min_len = len(log_ret)

    if min_len is None or min_len < 10:
        # Insufficient data -- return neutral estimates
        return np.zeros(n), np.eye(n) * 1e-4

    # Trim all return series to the same length
    aligned = []
    for rl in returns_lists:
        if rl is None or len(rl) < min_len:
            aligned.append(np.zeros(min_len))
        else:
            aligned.append(rl[-min_len:])

    matrix = np.column_stack(aligned)  # shape (T, n)
    mu = matrix.mean(axis=0)           # per-bar mean return
    cov = np.cov(matrix, rowvar=False) # per-bar covariance

    # Annualise (approx 525600 1-min bars per year)
    mu_annual = mu * 525600
    cov_annual = cov * 525600

    return mu_annual, cov_annual


def optimize_allocations(
    portfolio_value: float,
    open_positions: dict[str, float],
    pending_signals: list[dict],
    candle_data: dict[str, list[dict]],
) -> dict[str, float]:
    """
    Compute recommended allocation percentages via mean-variance optimization.

    Parameters
    ----------
    portfolio_value : total portfolio value in USD
    open_positions : {symbol: current_usd_value}
    pending_signals : list of signal dicts (each has "symbol")
    candle_data : {symbol: [candle dicts]} for return estimation

    Returns
    -------
    {symbol: allocation_pct}  where sum(values) <= 1 - CASH_RESERVE_PCT
    """
    # Gather all relevant symbols
    symbols = list(
        set(open_positions.keys()) | {s["symbol"] for s in pending_signals if "symbol" in s}
    )
    if not symbols:
        return {}

    n = len(symbols)
    mu, cov = _estimate_returns_and_cov(candle_data, symbols)

    # Regularise covariance to ensure positive-definiteness
    cov += np.eye(n) * 1e-8

    max_invest = 1.0 - CASH_RESERVE_PCT  # e.g. 0.80

    def neg_utility(w):
        """Negative mean-variance utility to minimise."""
        port_return = w @ mu
        port_var = w @ cov @ w
        return -(port_return - (RISK_AVERSION / 2.0) * port_var)

    # Bounds: each weight between 0 and MAX_POSITION_PCT
    bounds = [(0.0, MAX_POSITION_PCT)] * n

    # Constraint: sum of weights <= max_invest
    constraints = [
        {"type": "ineq", "fun": lambda w: max_invest - np.sum(w)},
    ]

    # Initial guess: equal weight, capped
    w0 = np.full(n, min(max_invest / n, MAX_POSITION_PCT))

    result = minimize(
        neg_utility,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-10},
    )

    if not result.success:
        logger.warning("Optimizer did not converge, using equal-weight fallback", message=result.message)
        equal_w = min(max_invest / n, MAX_POSITION_PCT)
        return {sym: round(equal_w, 6) for sym in symbols}

    allocations = {}
    for i, sym in enumerate(symbols):
        w = float(result.x[i])
        if w < 0.001:
            w = 0.0
        allocations[sym] = round(w, 6)

    logger.info(
        "Optimization complete",
        n_symbols=n,
        total_alloc=round(sum(allocations.values()), 4),
        allocations=allocations,
    )
    return allocations
