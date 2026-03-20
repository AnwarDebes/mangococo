"""
Core backtesting engine.

Replays historical candle data, applies strategy signals, simulates
execution with realistic fees and slippage, and records every trade.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import structlog

from metrics import generate_report

logger = structlog.get_logger()


@dataclass
class Position:
    """Tracks a single open position."""
    symbol: str
    side: str  # "long" or "short"
    entry_time: datetime
    entry_price: float
    quantity: float
    signal_confidence: float = 0.0


@dataclass
class Trade:
    """Completed trade record."""
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees: float
    slippage: float
    signal_confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "pnl": round(self.pnl, 6),
            "pnl_pct": round(self.pnl_pct, 6),
            "fees": round(self.fees, 6),
            "slippage": round(self.slippage, 6),
            "signal_confidence": self.signal_confidence,
        }


@dataclass
class EquityPoint:
    """Snapshot of portfolio equity at a point in time."""
    timestamp: datetime
    equity: float
    drawdown: float = 0.0
    positions_open: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "equity": round(self.equity, 4),
            "drawdown": round(self.drawdown, 6),
            "positions_open": self.positions_open,
        }


@dataclass
class BacktestResult:
    """Container for all backtest outputs."""
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[EquityPoint] = field(default_factory=list)
    report: Dict[str, Any] = field(default_factory=dict)
    initial_capital: float = 10000.0
    final_capital: float = 10000.0


class BacktestEngine:
    """
    Event-driven backtesting engine.

    Iterates through candles chronologically, applies signals at each
    timestamp, tracks positions with realistic execution (slippage + fees),
    and records every trade.
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        maker_fee: float = 0.001,
        taker_fee: float = 0.001,
        slippage_pct: float = 0.0003,
        max_positions: int = 5,
        position_size_pct: float = 0.20,
    ):
        self.initial_capital = initial_capital
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage_pct = slippage_pct
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct

        # State
        self.cash: float = initial_capital
        self.positions: Dict[str, Position] = {}  # symbol -> Position
        self.trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []
        self.peak_equity: float = initial_capital

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage: worse price for the trader."""
        if side == "buy":
            return price * (1 + self.slippage_pct)
        return price * (1 - self.slippage_pct)

    def _calc_fee(self, notional: float, is_maker: bool = False) -> float:
        rate = self.maker_fee if is_maker else self.taker_fee
        return notional * rate

    def _portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """Total portfolio value = cash + mark-to-market positions."""
        mtm = 0.0
        for sym, pos in self.positions.items():
            price = current_prices.get(sym, pos.entry_price)
            if pos.side == "long":
                mtm += pos.quantity * price
            else:  # short
                mtm += pos.quantity * (2 * pos.entry_price - price)
        return self.cash + mtm

    # ------------------------------------------------------------------
    # Order execution
    # ------------------------------------------------------------------

    def _open_position(
        self,
        symbol: str,
        side: str,
        price: float,
        timestamp: datetime,
        confidence: float = 0.0,
    ) -> bool:
        """Open a new position.  Returns True on success."""
        if symbol in self.positions:
            return False  # already have a position in this symbol
        if len(self.positions) >= self.max_positions:
            return False

        # Position sizing
        alloc = self.cash * self.position_size_pct
        exec_price = self._apply_slippage(price, "buy" if side == "long" else "sell")
        quantity = alloc / exec_price
        fee = self._calc_fee(alloc)

        if alloc + fee > self.cash:
            return False

        self.cash -= alloc + fee
        slippage_cost = abs(exec_price - price) * quantity

        self.positions[symbol] = Position(
            symbol=symbol,
            side=side,
            entry_time=timestamp,
            entry_price=exec_price,
            quantity=quantity,
            signal_confidence=confidence,
        )

        logger.debug(
            "Position opened",
            symbol=symbol,
            side=side,
            price=exec_price,
            quantity=quantity,
        )
        return True

    def _close_position(
        self,
        symbol: str,
        price: float,
        timestamp: datetime,
    ) -> Optional[Trade]:
        """Close an existing position and record the trade."""
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None

        close_side = "sell" if pos.side == "long" else "buy"
        exec_price = self._apply_slippage(price, close_side)
        notional = pos.quantity * exec_price
        fee = self._calc_fee(notional)

        if pos.side == "long":
            pnl = (exec_price - pos.entry_price) * pos.quantity - fee
        else:
            pnl = (pos.entry_price - exec_price) * pos.quantity - fee

        pnl_pct = pnl / (pos.entry_price * pos.quantity) if pos.entry_price > 0 else 0.0
        slippage_cost = abs(exec_price - price) * pos.quantity

        self.cash += notional - fee

        trade = Trade(
            symbol=symbol,
            side=pos.side,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            entry_price=pos.entry_price,
            exit_price=exec_price,
            quantity=pos.quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fees=fee + self._calc_fee(pos.entry_price * pos.quantity),  # entry + exit fees
            slippage=slippage_cost,
            signal_confidence=pos.signal_confidence,
        )
        self.trades.append(trade)

        logger.debug(
            "Position closed",
            symbol=symbol,
            pnl=round(pnl, 4),
            pnl_pct=round(pnl_pct * 100, 2),
        )
        return trade

    # ------------------------------------------------------------------
    # Main backtest loop
    # ------------------------------------------------------------------

    def run(
        self,
        candles_df: pd.DataFrame,
        signals_df: pd.DataFrame,
        equity_sample_interval: int = 60,
    ) -> BacktestResult:
        """
        Run the backtest.

        Parameters
        ----------
        candles_df : DataFrame
            Must have: time, symbol, open, high, low, close, volume.
        signals_df : DataFrame
            Must have: time, symbol, action ('buy'|'sell'), confidence.
        equity_sample_interval : int
            Record equity every N candles to keep the curve manageable.

        Returns
        -------
        BacktestResult with trades, equity curve, and performance report.
        """
        if candles_df.empty:
            logger.warning("Empty candles DataFrame, nothing to backtest")
            return BacktestResult(initial_capital=self.initial_capital)

        # Reset state
        self.cash = self.initial_capital
        self.positions.clear()
        self.trades.clear()
        self.equity_curve.clear()
        self.peak_equity = self.initial_capital

        # Index signals by (time, symbol) for O(1) lookup — vectorized construction
        signal_lookup: Dict[tuple, Dict] = {}
        if not signals_df.empty:
            sig_times = signals_df["time"].values
            sig_symbols = signals_df["symbol"].values
            sig_actions = signals_df["action"].values
            sig_confs = signals_df["confidence"].values if "confidence" in signals_df.columns else np.full(len(signals_df), 0.5)
            for i in range(len(signals_df)):
                signal_lookup[(sig_times[i], sig_symbols[i])] = {
                    "action": sig_actions[i],
                    "confidence": float(sig_confs[i]),
                }

        # Sort candles chronologically
        candles_df = candles_df.sort_values("time").reset_index(drop=True)
        timestamps = candles_df["time"].unique()

        candle_count = 0

        # Pre-group candles by timestamp for faster iteration
        grouped = candles_df.groupby("time")

        for ts in timestamps:
            ts_candles = grouped.get_group(ts)
            current_prices: Dict[str, float] = {}

            # Vectorized access — avoid iterrows()
            ts_symbols = ts_candles["symbol"].values
            ts_closes = ts_candles["close"].values.astype(float)

            for j in range(len(ts_symbols)):
                symbol = ts_symbols[j]
                close_price = ts_closes[j]
                current_prices[symbol] = close_price

                # Check for signal at this (time, symbol)
                sig = signal_lookup.get((ts, symbol))
                if sig is None:
                    continue

                action = sig["action"]
                confidence = sig["confidence"]

                if action == "buy":
                    if symbol in self.positions and self.positions[symbol].side == "short":
                        self._close_position(symbol, close_price, ts)
                    self._open_position(symbol, "long", close_price, ts, confidence)

                elif action == "sell":
                    if symbol in self.positions and self.positions[symbol].side == "long":
                        self._close_position(symbol, close_price, ts)
                    self._open_position(symbol, "short", close_price, ts, confidence)

            # Record equity periodically
            candle_count += 1
            if candle_count % equity_sample_interval == 0 or candle_count == 1:
                equity = self._portfolio_value(current_prices)
                self.peak_equity = max(self.peak_equity, equity)
                dd = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0.0
                self.equity_curve.append(EquityPoint(
                    timestamp=ts,
                    equity=equity,
                    drawdown=dd,
                    positions_open=len(self.positions),
                ))

        # Close all remaining positions at last known prices
        last_candles = candles_df.drop_duplicates(subset="symbol", keep="last")
        last_ts = candles_df["time"].max()
        for _, row in last_candles.iterrows():
            sym = row["symbol"]
            if sym in self.positions:
                self._close_position(sym, float(row["close"]), last_ts)

        # Final equity snapshot
        final_equity = self.cash
        self.peak_equity = max(self.peak_equity, final_equity)
        dd = (self.peak_equity - final_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        self.equity_curve.append(EquityPoint(
            timestamp=last_ts if not candles_df.empty else datetime.now(timezone.utc),
            equity=final_equity,
            drawdown=dd,
            positions_open=0,
        ))

        # Generate report
        trade_dicts = [t.to_dict() for t in self.trades]
        equity_dicts = [e.to_dict() for e in self.equity_curve]
        report = generate_report(trade_dicts, equity_dicts, self.initial_capital)

        logger.info(
            "Backtest complete",
            trades=len(self.trades),
            final_capital=round(final_equity, 2),
            total_return_pct=report.get("total_return_pct", 0),
            sharpe=report.get("sharpe_ratio", 0),
            max_drawdown_pct=report.get("max_drawdown_pct", 0),
        )

        return BacktestResult(
            trades=self.trades,
            equity_curve=self.equity_curve,
            report=report,
            initial_capital=self.initial_capital,
            final_capital=final_equity,
        )

    def get_results(self) -> BacktestResult:
        """Return the latest backtest results (call after run())."""
        trade_dicts = [t.to_dict() for t in self.trades]
        equity_dicts = [e.to_dict() for e in self.equity_curve]
        report = generate_report(trade_dicts, equity_dicts, self.initial_capital)

        return BacktestResult(
            trades=self.trades,
            equity_curve=self.equity_curve,
            report=report,
            initial_capital=self.initial_capital,
            final_capital=self.cash,
        )
