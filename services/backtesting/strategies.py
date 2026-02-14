"""
Strategy definitions for backtesting.

Each strategy implements ``generate_signals()`` which takes a features
DataFrame (candles + indicators + sentiment) and returns a signals
DataFrame with columns: time, symbol, action, confidence.

Strategies provided:
- MLEnsembleStrategy  -- replays stored ML prediction scores
- TechnicalStrategy   -- legacy RSI / MACD rules (for comparison)
- SentimentStrategy   -- sentiment-only signals (for comparison)
"""
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()


class BaseStrategy(ABC):
    """Abstract base for all backtest strategies."""

    name: str = "base"

    @abstractmethod
    def generate_signals(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """
        Parameters
        ----------
        features_df : DataFrame
            Must contain at least: time, symbol, open, high, low, close, volume.
            May also contain sentiment_score and arbitrary feature columns.

        Returns
        -------
        DataFrame with columns: time, symbol, action ('buy'|'sell'|'hold'),
        confidence (0-1).
        """
        ...


# ---------------------------------------------------------------------------
# ML Ensemble Strategy
# ---------------------------------------------------------------------------

class MLEnsembleStrategy(BaseStrategy):
    """
    Uses stored ML prediction columns (``ml_direction``, ``ml_confidence``)
    in the features DataFrame.  If those columns are not present, falls
    back to a momentum + sentiment heuristic that approximates the
    ensemble logic.
    """

    name = "ml_ensemble"

    def __init__(
        self,
        confidence_threshold: float = 0.60,
        sentiment_weight: float = 0.15,
    ):
        self.confidence_threshold = confidence_threshold
        self.sentiment_weight = sentiment_weight

    def generate_signals(self, features_df: pd.DataFrame) -> pd.DataFrame:
        signals = []

        for symbol in features_df["symbol"].unique():
            sym_df = features_df[features_df["symbol"] == symbol].copy()
            sym_df = sym_df.sort_values("time").reset_index(drop=True)

            if len(sym_df) < 20:
                continue

            # If ML predictions are pre-computed in the feature store
            if "ml_direction" in sym_df.columns and "ml_confidence" in sym_df.columns:
                for _, row in sym_df.iterrows():
                    action = row["ml_direction"]
                    conf = row["ml_confidence"]
                    if conf >= self.confidence_threshold and action in ("buy", "sell"):
                        signals.append({
                            "time": row["time"],
                            "symbol": symbol,
                            "action": action,
                            "confidence": conf,
                        })
                continue

            # Fallback: momentum + RSI + sentiment heuristic
            closes = sym_df["close"].values
            sentiment = sym_df.get("sentiment_score", pd.Series(0.0, index=sym_df.index)).fillna(0.0).values

            # RSI-14
            rsi = self._compute_rsi(closes, period=14)

            # MACD signal crossover
            macd_hist = self._compute_macd_histogram(closes)

            # Momentum (5-bar percentage change)
            mom = np.zeros(len(closes))
            mom[5:] = (closes[5:] - closes[:-5]) / np.where(closes[:-5] != 0, closes[:-5], 1.0)

            for i in range(20, len(sym_df)):
                score = 0.0

                # RSI component
                if rsi[i] < 30:
                    score += 0.35
                elif rsi[i] > 70:
                    score -= 0.35

                # MACD component
                if i > 0 and macd_hist[i] > 0 and macd_hist[i - 1] <= 0:
                    score += 0.30
                elif i > 0 and macd_hist[i] < 0 and macd_hist[i - 1] >= 0:
                    score -= 0.30

                # Momentum component
                if mom[i] > 0.002:
                    score += 0.20
                elif mom[i] < -0.002:
                    score -= 0.20

                # Sentiment component
                score += sentiment[i] * self.sentiment_weight

                conf = min(abs(score), 1.0)
                if conf >= self.confidence_threshold:
                    action = "buy" if score > 0 else "sell"
                    signals.append({
                        "time": sym_df.iloc[i]["time"],
                        "symbol": symbol,
                        "action": action,
                        "confidence": round(conf, 4),
                    })

        if not signals:
            return pd.DataFrame(columns=["time", "symbol", "action", "confidence"])

        return pd.DataFrame(signals)

    # --- helpers ---

    @staticmethod
    def _compute_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
        deltas = np.diff(prices, prepend=prices[0])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        rsi = np.full(len(prices), 50.0)
        if len(prices) <= period:
            return rsi

        avg_gain = np.mean(gains[1 : period + 1])
        avg_loss = np.mean(losses[1 : period + 1])

        for i in range(period, len(prices)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
            rsi[i] = 100 - 100 / (1 + rs)

        return rsi

    @staticmethod
    def _compute_macd_histogram(
        prices: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> np.ndarray:
        def ema(data, span):
            alpha = 2 / (span + 1)
            out = np.empty_like(data, dtype=np.float64)
            out[0] = data[0]
            for i in range(1, len(data)):
                out[i] = alpha * data[i] + (1 - alpha) * out[i - 1]
            return out

        prices = prices.astype(np.float64)
        ema_fast = ema(prices, fast)
        ema_slow = ema(prices, slow)
        macd_line = ema_fast - ema_slow
        signal_line = ema(macd_line, signal)
        return macd_line - signal_line


# ---------------------------------------------------------------------------
# Technical-only Strategy (RSI + MACD baseline)
# ---------------------------------------------------------------------------

class TechnicalStrategy(BaseStrategy):
    """
    Pure technical analysis strategy using RSI and MACD crossovers.
    Serves as a baseline to compare against the ML ensemble.
    """

    name = "technical"

    def __init__(
        self,
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        confidence_threshold: float = 0.55,
    ):
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.confidence_threshold = confidence_threshold

    def generate_signals(self, features_df: pd.DataFrame) -> pd.DataFrame:
        signals = []

        for symbol in features_df["symbol"].unique():
            sym_df = features_df[features_df["symbol"] == symbol].copy()
            sym_df = sym_df.sort_values("time").reset_index(drop=True)

            if len(sym_df) < 30:
                continue

            closes = sym_df["close"].values
            rsi = MLEnsembleStrategy._compute_rsi(closes, 14)
            macd_hist = MLEnsembleStrategy._compute_macd_histogram(closes)

            for i in range(30, len(sym_df)):
                score = 0.0

                # RSI signals
                if rsi[i] < self.rsi_oversold:
                    score += 0.50
                elif rsi[i] > self.rsi_overbought:
                    score -= 0.50

                # MACD histogram crossover
                if macd_hist[i] > 0 and macd_hist[i - 1] <= 0:
                    score += 0.50
                elif macd_hist[i] < 0 and macd_hist[i - 1] >= 0:
                    score -= 0.50

                conf = min(abs(score), 1.0)
                if conf >= self.confidence_threshold:
                    signals.append({
                        "time": sym_df.iloc[i]["time"],
                        "symbol": symbol,
                        "action": "buy" if score > 0 else "sell",
                        "confidence": round(conf, 4),
                    })

        if not signals:
            return pd.DataFrame(columns=["time", "symbol", "action", "confidence"])

        return pd.DataFrame(signals)


# ---------------------------------------------------------------------------
# Sentiment-only Strategy
# ---------------------------------------------------------------------------

class SentimentStrategy(BaseStrategy):
    """
    Trades purely on sentiment score thresholds.
    Useful as a comparison to prove whether sentiment adds alpha.
    """

    name = "sentiment"

    def __init__(
        self,
        buy_threshold: float = 0.3,
        sell_threshold: float = -0.3,
        min_confidence: float = 0.50,
    ):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.min_confidence = min_confidence

    def generate_signals(self, features_df: pd.DataFrame) -> pd.DataFrame:
        signals = []

        if "sentiment_score" not in features_df.columns:
            logger.warning("No sentiment_score column in features, returning empty signals")
            return pd.DataFrame(columns=["time", "symbol", "action", "confidence"])

        for symbol in features_df["symbol"].unique():
            sym_df = features_df[features_df["symbol"] == symbol].copy()
            sym_df = sym_df.sort_values("time").reset_index(drop=True)

            for _, row in sym_df.iterrows():
                sent = row.get("sentiment_score", 0.0)
                if pd.isna(sent):
                    continue

                if sent >= self.buy_threshold:
                    conf = min(abs(sent), 1.0)
                    if conf >= self.min_confidence:
                        signals.append({
                            "time": row["time"],
                            "symbol": symbol,
                            "action": "buy",
                            "confidence": round(conf, 4),
                        })
                elif sent <= self.sell_threshold:
                    conf = min(abs(sent), 1.0)
                    if conf >= self.min_confidence:
                        signals.append({
                            "time": row["time"],
                            "symbol": symbol,
                            "action": "sell",
                            "confidence": round(conf, 4),
                        })

        if not signals:
            return pd.DataFrame(columns=["time", "symbol", "action", "confidence"])

        return pd.DataFrame(signals)


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

STRATEGY_MAP = {
    "ml_ensemble": MLEnsembleStrategy,
    "technical": TechnicalStrategy,
    "sentiment": SentimentStrategy,
}


def get_strategy(name: str, **kwargs) -> BaseStrategy:
    """Instantiate a strategy by name."""
    cls = STRATEGY_MAP.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy '{name}'. Available: {list(STRATEGY_MAP.keys())}")
    return cls(**kwargs)
