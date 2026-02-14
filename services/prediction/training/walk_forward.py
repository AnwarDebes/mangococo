"""
Walk-forward validation framework.

Generates time-based train / validation splits that slide forward in time,
preventing look-ahead bias.  Computes per-split and aggregate metrics.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score


@dataclass
class SplitMetrics:
    """Metrics for a single walk-forward split."""
    split_id: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    sharpe: float = 0.0


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward results."""
    splits: List[SplitMetrics] = field(default_factory=list)
    mean_accuracy: float = 0.0
    mean_f1: float = 0.0
    mean_sharpe: float = 0.0


class WalkForwardValidator:
    """
    Walk-forward validation with configurable train and validation windows.

    Parameters
    ----------
    train_days : int
        Number of days in each training window (default 30).
    val_days : int
        Number of days in each validation window (default 7).
    step_days : int
        Number of days to slide the window forward each split (default 7).
    """

    def __init__(self, train_days: int = 30, val_days: int = 7, step_days: int = 7):
        self.train_days = train_days
        self.val_days = val_days
        self.step_days = step_days

    def generate_splits(
        self,
        df: pd.DataFrame,
        time_col: str = "timestamp",
    ) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Generate (train, validation) DataFrame pairs.

        Parameters
        ----------
        df : DataFrame sorted by *time_col* ascending.
        time_col : column name holding datetime objects.

        Returns
        -------
        List of (train_df, val_df) tuples.
        """
        if time_col not in df.columns:
            raise ValueError(f"Column '{time_col}' not found in DataFrame")

        df = df.sort_values(time_col).reset_index(drop=True)
        ts = pd.to_datetime(df[time_col])
        min_t = ts.min()
        max_t = ts.max()

        train_td = pd.Timedelta(days=self.train_days)
        val_td = pd.Timedelta(days=self.val_days)
        step_td = pd.Timedelta(days=self.step_days)

        splits: List[Tuple[pd.DataFrame, pd.DataFrame]] = []
        cursor = min_t

        while cursor + train_td + val_td <= max_t:
            train_mask = (ts >= cursor) & (ts < cursor + train_td)
            val_mask = (ts >= cursor + train_td) & (ts < cursor + train_td + val_td)

            train_df = df.loc[train_mask]
            val_df = df.loc[val_mask]

            if len(train_df) > 0 and len(val_df) > 0:
                splits.append((train_df, val_df))

            cursor += step_td

        return splits

    @staticmethod
    def compute_metrics(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        returns: np.ndarray | None = None,
        split_id: int = 0,
        train_start: str = "",
        train_end: str = "",
        val_start: str = "",
        val_end: str = "",
    ) -> SplitMetrics:
        """
        Compute classification + trading metrics for a single split.

        Parameters
        ----------
        y_true, y_pred : array-like of class labels.
        returns : optional array of actual forward returns (for Sharpe).
        """
        acc = accuracy_score(y_true, y_pred)
        prec = precision_score(y_true, y_pred, average="weighted", zero_division=0)
        rec = recall_score(y_true, y_pred, average="weighted", zero_division=0)
        f1 = f1_score(y_true, y_pred, average="weighted", zero_division=0)

        sharpe = 0.0
        if returns is not None and len(returns) > 1:
            mean_ret = np.mean(returns)
            std_ret = np.std(returns)
            if std_ret > 0:
                sharpe = float(mean_ret / std_ret * np.sqrt(252))

        return SplitMetrics(
            split_id=split_id,
            train_start=train_start,
            train_end=train_end,
            val_start=val_start,
            val_end=val_end,
            accuracy=round(acc, 4),
            precision=round(prec, 4),
            recall=round(rec, 4),
            f1=round(f1, 4),
            sharpe=round(sharpe, 4),
        )

    @staticmethod
    def aggregate(splits: List[SplitMetrics]) -> WalkForwardResult:
        """Aggregate metrics across all walk-forward splits."""
        if not splits:
            return WalkForwardResult()
        return WalkForwardResult(
            splits=splits,
            mean_accuracy=round(np.mean([s.accuracy for s in splits]), 4),
            mean_f1=round(np.mean([s.f1 for s in splits]), 4),
            mean_sharpe=round(np.mean([s.sharpe for s in splits]), 4),
        )
