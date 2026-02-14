"""
Compute technical-analysis features from OHLCV candle data.

All calculations use numpy / pandas only (no external TA library dependency).
The function returns a flat ``dict[str, float]`` suitable for feeding into
both the XGBoost model (flat vector) and for building the TCN input matrix.
"""

from typing import Dict

import numpy as np
import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def compute_technical_features(df: pd.DataFrame) -> Dict[str, float]:
    """
    Compute technical features from a DataFrame of recent candles.

    Parameters
    ----------
    df : DataFrame
        Must contain columns: ``open``, ``high``, ``low``, ``close``, ``volume``.
        Should have at least 60 rows for full feature coverage.

    Returns
    -------
    dict
        Feature-name -> value mapping with 20 features.
    """
    if df.empty:
        return _empty_features()

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    open_ = df["open"].astype(float)

    features: Dict[str, float] = {}

    # --- RSI (14 and 7) ---
    features["rsi_14"] = _rsi(close, 14)
    features["rsi_7"] = _rsi(close, 7)

    # --- MACD (8, 17, 9) tuned for crypto ---
    ema_fast = _ema(close, 8)
    ema_slow = _ema(close, 17)
    macd_line = ema_fast - ema_slow
    macd_signal = _ema(macd_line, 9)
    macd_hist = macd_line - macd_signal
    features["macd_histogram"] = float(macd_hist.iloc[-1])
    features["macd_signal"] = float(macd_signal.iloc[-1])

    # --- Bollinger Bands (20, 2) ---
    bb_mid = _sma(close, 20)
    bb_std = close.rolling(window=20, min_periods=1).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bandwidth = bb_upper.iloc[-1] - bb_lower.iloc[-1]
    features["bb_percent_b"] = (
        float((close.iloc[-1] - bb_lower.iloc[-1]) / bandwidth) if bandwidth > 0 else 0.5
    )
    features["bb_bandwidth"] = float(bandwidth / bb_mid.iloc[-1]) if bb_mid.iloc[-1] > 0 else 0.0

    # --- ATR percentage ---
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_14 = tr.rolling(window=14, min_periods=1).mean()
    features["atr_pct"] = float(atr_14.iloc[-1] / close.iloc[-1] * 100) if close.iloc[-1] > 0 else 0.0

    # --- OBV trend ---
    obv = (np.sign(close.diff().fillna(0)) * volume).cumsum()
    obv_ema = _ema(obv, 14)
    features["obv_trend"] = 1.0 if obv.iloc[-1] > obv_ema.iloc[-1] else -1.0

    # --- Stochastic RSI ---
    rsi_series = _rsi_series(close, 14)
    stoch_k, stoch_d = _stoch_rsi(rsi_series, 14)
    features["stoch_rsi_k"] = stoch_k
    features["stoch_rsi_d"] = stoch_d

    # --- Williams %R ---
    features["williams_r"] = _williams_r(high, low, close, 14)

    # --- EMA crosses ---
    ema9 = _ema(close, 9)
    ema21 = _ema(close, 21)
    ema25 = _ema(close, 25)
    ema50 = _ema(close, 50)
    features["ema_9_21_cross"] = 1.0 if ema9.iloc[-1] > ema21.iloc[-1] else -1.0
    features["ema_25_50_cross"] = 1.0 if ema25.iloc[-1] > ema50.iloc[-1] else -1.0

    # --- Volume ratio ---
    vol_sma = _sma(volume, 20)
    features["volume_ratio"] = (
        float(volume.iloc[-1] / vol_sma.iloc[-1]) if vol_sma.iloc[-1] > 0 else 1.0
    )

    # --- Momentum at various lookbacks ---
    for label, periods in [("5m", 5), ("15m", 15), ("30m", 30), ("60m", 60)]:
        if len(close) > periods:
            features[f"momentum_{label}"] = float(
                (close.iloc[-1] - close.iloc[-1 - periods]) / close.iloc[-1 - periods] * 100
            )
        else:
            features[f"momentum_{label}"] = 0.0

    # --- Spread pct (approximated from high/low of last candle) ---
    features["spread_pct"] = (
        float((high.iloc[-1] - low.iloc[-1]) / close.iloc[-1] * 100) if close.iloc[-1] > 0 else 0.0
    )

    # --- VWAP deviation ---
    cum_vol = volume.cumsum()
    cum_vp = (close * volume).cumsum()
    vwap = cum_vp / cum_vol.replace(0, np.nan)
    features["vwap_deviation"] = (
        float((close.iloc[-1] - vwap.iloc[-1]) / vwap.iloc[-1] * 100) if vwap.iloc[-1] else 0.0
    )

    return features


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rsi(close: pd.Series, period: int) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0


def _rsi_series(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=period, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _stoch_rsi(rsi: pd.Series, period: int):
    rsi_min = rsi.rolling(window=period, min_periods=1).min()
    rsi_max = rsi.rolling(window=period, min_periods=1).max()
    denom = rsi_max - rsi_min
    stoch_k = ((rsi - rsi_min) / denom.replace(0, np.nan)).fillna(0.5)
    stoch_d = stoch_k.rolling(window=3, min_periods=1).mean()
    return float(stoch_k.iloc[-1]), float(stoch_d.iloc[-1])


def _williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> float:
    hh = high.rolling(window=period, min_periods=1).max()
    ll = low.rolling(window=period, min_periods=1).min()
    denom = hh - ll
    wr = ((hh - close) / denom.replace(0, np.nan) * -100).fillna(-50.0)
    return float(wr.iloc[-1])


def _empty_features() -> Dict[str, float]:
    keys = [
        "rsi_14", "rsi_7", "macd_histogram", "macd_signal",
        "bb_percent_b", "bb_bandwidth", "atr_pct", "obv_trend",
        "stoch_rsi_k", "stoch_rsi_d", "williams_r",
        "ema_9_21_cross", "ema_25_50_cross", "volume_ratio",
        "momentum_5m", "momentum_15m", "momentum_30m", "momentum_60m",
        "spread_pct", "vwap_deviation",
    ]
    return {k: 0.0 for k in keys}
