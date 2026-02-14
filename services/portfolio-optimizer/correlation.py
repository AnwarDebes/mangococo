"""
Correlation-aware risk module.

Computes return-based correlation matrices from candle data and
checks whether a new position would breach portfolio concentration
limits relative to existing open positions.
"""
import numpy as np
import structlog

logger = structlog.get_logger()

# Thresholds
HIGH_CORR_THRESHOLD = 0.7   # Reduce size by 50% if above
SKIP_CORR_THRESHOLD = 0.9   # Skip trade entirely if above
MAX_CORRELATED_GROUP_PCT = 0.30  # Max 30% portfolio in highly correlated group


def _close_prices_from_candles(candles: list[dict]) -> np.ndarray:
    """Extract close prices as a numpy array from candle dicts."""
    prices = [c["close"] for c in candles if c.get("close") is not None]
    return np.array(prices, dtype=np.float64)


def _log_returns(prices: np.ndarray) -> np.ndarray:
    """Compute log returns from a price series."""
    if len(prices) < 2:
        return np.array([])
    return np.diff(np.log(prices))


def compute_correlation_matrix(
    symbols: list[str],
    candle_data: dict[str, list[dict]],
) -> dict[str, dict[str, float]]:
    """
    Build a pairwise Pearson correlation matrix from close-price returns.

    Parameters
    ----------
    symbols : list of symbol strings
    candle_data : {symbol: [candle_dict, ...]}  -- from db.fetch_candles_multi

    Returns
    -------
    Nested dict  {sym_a: {sym_b: correlation, ...}, ...}
    Missing / incomputable pairs default to 0.0.
    """
    returns_map: dict[str, np.ndarray] = {}
    for sym in symbols:
        candles = candle_data.get(sym, [])
        prices = _close_prices_from_candles(candles)
        rets = _log_returns(prices)
        if len(rets) > 1:
            returns_map[sym] = rets

    matrix: dict[str, dict[str, float]] = {}
    for a in symbols:
        matrix[a] = {}
        for b in symbols:
            if a == b:
                matrix[a][b] = 1.0
                continue
            ra = returns_map.get(a)
            rb = returns_map.get(b)
            if ra is None or rb is None:
                matrix[a][b] = 0.0
                continue
            # Align to the shorter series
            min_len = min(len(ra), len(rb))
            if min_len < 10:
                matrix[a][b] = 0.0
                continue
            corr = float(np.corrcoef(ra[-min_len:], rb[-min_len:])[0, 1])
            matrix[a][b] = corr if np.isfinite(corr) else 0.0

    return matrix


def check_correlation_risk(
    new_symbol: str,
    open_positions: dict[str, float],
    correlation_matrix: dict[str, dict[str, float]],
    portfolio_value: float = 0.0,
) -> dict:
    """
    Assess correlation risk of adding *new_symbol* to the portfolio.

    Parameters
    ----------
    new_symbol : symbol being considered
    open_positions : {symbol: current_usd_value, ...} of open positions
    correlation_matrix : from compute_correlation_matrix
    portfolio_value : total portfolio value for group-exposure check

    Returns
    -------
    {
        "action": "allow" | "reduce" | "skip",
        "size_multiplier": float,  # 1.0, 0.5, or 0.0
        "max_corr": float,         # highest correlation with any open position
        "correlated_group_exposure": float,  # USD in highly correlated positions
        "reason": str,
    }
    """
    if not open_positions or new_symbol not in correlation_matrix:
        return {
            "action": "allow",
            "size_multiplier": 1.0,
            "max_corr": 0.0,
            "correlated_group_exposure": 0.0,
            "reason": "no_open_positions_or_no_data",
        }

    max_corr = 0.0
    correlated_exposure = 0.0

    for sym, usd_value in open_positions.items():
        corr = correlation_matrix.get(new_symbol, {}).get(sym, 0.0)
        abs_corr = abs(corr)
        max_corr = max(max_corr, abs_corr)
        if abs_corr >= HIGH_CORR_THRESHOLD:
            correlated_exposure += usd_value

    # Check group exposure limit
    if portfolio_value > 0 and correlated_exposure / portfolio_value > MAX_CORRELATED_GROUP_PCT:
        logger.warning(
            "Correlated group exposure exceeded",
            symbol=new_symbol,
            exposure_pct=round(correlated_exposure / portfolio_value, 3),
        )
        return {
            "action": "skip",
            "size_multiplier": 0.0,
            "max_corr": round(max_corr, 4),
            "correlated_group_exposure": round(correlated_exposure, 2),
            "reason": f"correlated_group_exposure_{round(correlated_exposure / portfolio_value * 100, 1)}pct_exceeds_{MAX_CORRELATED_GROUP_PCT * 100}pct",
        }

    # Individual pair checks
    if max_corr >= SKIP_CORR_THRESHOLD:
        logger.warning("Skipping trade due to very high correlation", symbol=new_symbol, max_corr=round(max_corr, 4))
        return {
            "action": "skip",
            "size_multiplier": 0.0,
            "max_corr": round(max_corr, 4),
            "correlated_group_exposure": round(correlated_exposure, 2),
            "reason": f"max_corr_{round(max_corr, 3)}_exceeds_{SKIP_CORR_THRESHOLD}",
        }

    if max_corr >= HIGH_CORR_THRESHOLD:
        logger.info("Reducing size due to high correlation", symbol=new_symbol, max_corr=round(max_corr, 4))
        return {
            "action": "reduce",
            "size_multiplier": 0.5,
            "max_corr": round(max_corr, 4),
            "correlated_group_exposure": round(correlated_exposure, 2),
            "reason": f"max_corr_{round(max_corr, 3)}_above_{HIGH_CORR_THRESHOLD}",
        }

    return {
        "action": "allow",
        "size_multiplier": 1.0,
        "max_corr": round(max_corr, 4),
        "correlated_group_exposure": round(correlated_exposure, 2),
        "reason": "correlation_within_limits",
    }
