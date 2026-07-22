"""
Sprint 7 -- Performance Analytics: measures the bot's own trading
performance (Win Rate, Average Profit/Loss, Profit Factor, Expectancy,
Sharpe, Maximum Drawdown, Recovery Factor) from the Trade Journal's
permanent, closed-trade history (Sprint 5). Read-only: this module never
touches a position, an order, or risk state -- it only summarizes what
already happened.
"""

import math
import statistics
from datetime import UTC, datetime

from app.core.domain.performance import PerformanceReport
from app.core.domain.trade_journal import STATUS_CLOSED


def _empty_report() -> PerformanceReport:
    return PerformanceReport(
        generated_at=datetime.now(UTC),
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        breakeven_trades=0,
        win_rate_percent=0.0,
        average_profit=0.0,
        average_loss=0.0,
        total_pnl=0.0,
        expectancy=0.0,
        profit_factor=None,
        sharpe_ratio=None,
        max_drawdown=0.0,
        max_drawdown_percent=0.0,
        recovery_factor=None,
    )


class PerformanceAnalytics:
    def __init__(self) -> None:
        self._trade_journal = None

    def set_trade_journal(self, trade_journal) -> None:
        self._trade_journal = trade_journal

    def _closed_trades(self) -> list:
        if self._trade_journal is None:
            return []

        return [
            entry
            for entry in self._trade_journal.list_all()
            if entry.status == STATUS_CLOSED and entry.pnl is not None
        ]

    def generate_report(self, trades: list | None = None) -> PerformanceReport:
        """Computes a PerformanceReport from the given closed trades (in
        any order -- they are sorted chronologically internally for the
        drawdown/equity-curve calculation), or from every closed trade in
        the wired TradeJournal if `trades` is omitted."""
        if trades is None:
            trades = self._closed_trades()

        if not trades:
            return _empty_report()

        trades = sorted(
            trades,
            key=lambda entry: entry.exit_time or entry.entry_time,
        )

        pnls = [entry.pnl for entry in trades]

        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        breakeven = [pnl for pnl in pnls if pnl == 0]

        total_trades = len(trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        breakeven_trades = len(breakeven)

        win_rate_percent = (winning_trades / total_trades) * 100

        average_profit = (sum(wins) / winning_trades) if wins else 0.0
        average_loss = (sum(losses) / losing_trades) if losses else 0.0

        total_pnl = sum(pnls)
        expectancy = total_pnl / total_trades

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = _safe_ratio(gross_profit, gross_loss)

        sharpe_ratio = _sharpe_ratio(trades)

        max_drawdown, max_drawdown_percent = _max_drawdown(pnls)
        recovery_factor = _safe_ratio(total_pnl, max_drawdown)

        return PerformanceReport(
            generated_at=datetime.now(UTC),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            breakeven_trades=breakeven_trades,
            win_rate_percent=win_rate_percent,
            average_profit=average_profit,
            average_loss=average_loss,
            total_pnl=total_pnl,
            expectancy=expectancy,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_percent=max_drawdown_percent,
            recovery_factor=recovery_factor,
        )


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    """numerator/denominator, but +inf instead of a ZeroDivisionError when
    the denominator is 0 and there's something to show for it (a
    "perfect" record so far -- no losses / no drawdown), or None when
    both are 0 (nothing to measure yet)."""
    if denominator > 0:
        return numerator / denominator

    if numerator > 0:
        return math.inf

    return None


def _sharpe_ratio(trades: list) -> float | None:
    returns = [
        entry.pnl_percent for entry in trades if entry.pnl_percent is not None
    ]

    if len(returns) < 2:
        return None

    stdev = statistics.pstdev(returns)

    if stdev == 0:
        return None

    mean = statistics.mean(returns)

    return (mean / stdev) * math.sqrt(len(returns))


def _max_drawdown(pnls: list[float]) -> tuple[float, float]:
    """Walks the chronologically-ordered realized-PnL equity curve
    (starting at 0, one step per closed trade) and returns the largest
    peak-to-trough drop, both in absolute PnL terms and as a percentage
    of the peak at which that drop started."""
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    max_drawdown_percent = 0.0

    for pnl in pnls:
        equity += pnl

        if equity > peak:
            peak = equity

        drawdown = peak - equity

        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_percent = (drawdown / peak * 100) if peak > 0 else 0.0

    return max_drawdown, max_drawdown_percent
