"""
Sprint 7 -- Performance Analytics: the report PerformanceAnalytics
computes from a set of closed trades.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PerformanceReport:
    generated_at: datetime

    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int

    win_rate_percent: float

    # Average PnL of winning trades (>= 0) and losing trades (<= 0),
    # in the same currency unit as the trade's `pnl`.
    average_profit: float
    average_loss: float

    total_pnl: float
    # Expected PnL per trade -- (win_rate * avg_win) + (loss_rate * avg_loss).
    expectancy: float

    # Gross profit / abs(gross loss). None with zero trades; +inf when
    # there are wins and zero losses (a "perfect" record so far).
    profit_factor: float | None

    # Mean / stdev of per-trade pnl_percent returns, scaled by sqrt(N) --
    # a simplified, non-annualized Sharpe-like ratio appropriate for a
    # trade-by-trade (not time-series) sample. None when fewer than 2
    # trades have a usable pnl_percent, or when returns have zero
    # variance (no way to compute a meaningful ratio).
    sharpe_ratio: float | None

    # Largest peak-to-trough drop of the cumulative realized-PnL equity
    # curve built by walking the trades in chronological order.
    max_drawdown: float
    max_drawdown_percent: float

    # total_pnl / max_drawdown. None with zero trades or zero drawdown
    # and zero profit; +inf when there's profit but no drawdown at all.
    recovery_factor: float | None
