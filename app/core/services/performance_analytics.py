"""
Sprint 7 -- Performance Analytics: measures the bot's own trading
performance (Win Rate, Average Profit/Loss, Profit Factor, Expectancy,
Sharpe, Maximum Drawdown, Recovery Factor) from the Trade Journal's
permanent, closed-trade history (Sprint 5). Read-only: this module never
touches a position, an order, or risk state -- it only summarizes what
already happened.

Filters (optional):
  period: today | last_7_days | last_30_days | all_time  (by exit_time UTC)
  strategy: substring match on entry_conditions strategy name
  exchange: venue name
"""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta

from app.core.domain.performance import PerformanceReport
from app.core.domain.trade_journal import STATUS_CLOSED
from app.core.exchange.trading_mode import (
    normalize_trading_mode,
    resolve_trading_mode,
)


PERIOD_TODAY = "today"
PERIOD_LAST_7_DAYS = "last_7_days"
PERIOD_LAST_30_DAYS = "last_30_days"
PERIOD_ALL_TIME = "all_time"

SUPPORTED_PERIODS = frozenset(
    {
        PERIOD_TODAY,
        PERIOD_LAST_7_DAYS,
        PERIOD_LAST_30_DAYS,
        PERIOD_ALL_TIME,
    }
)


def _empty_report(
    *,
    period: str = PERIOD_ALL_TIME,
    strategy: str | None = None,
    exchange: str | None = None,
    trading_mode: str | None = None,
) -> PerformanceReport:
    return PerformanceReport(
        generated_at=datetime.now(UTC),
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        breakeven_trades=0,
        win_rate_percent=0.0,
        average_profit=0.0,
        average_loss=0.0,
        average_profit_percent=0.0,
        average_loss_percent=0.0,
        total_pnl=0.0,
        expectancy=0.0,
        profit_factor=None,
        sharpe_ratio=None,
        max_drawdown=0.0,
        max_drawdown_percent=0.0,
        recovery_factor=None,
        period=period,
        strategy=strategy,
        exchange=exchange,
        trading_mode=trading_mode,
    )


def period_bounds(
    period: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    """
    Returns (date_from, date_to) inclusive window in UTC for ``period``.
    ``all_time`` → (None, None).
    """
    key = (period or PERIOD_ALL_TIME).strip().lower()
    if key not in SUPPORTED_PERIODS:
        raise ValueError(
            f"Unsupported analytics period {period!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_PERIODS))}"
        )
    if key == PERIOD_ALL_TIME:
        return None, None

    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)

    if key == PERIOD_TODAY:
        start = clock.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, None
    if key == PERIOD_LAST_7_DAYS:
        return clock - timedelta(days=7), None
    return clock - timedelta(days=30), None


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

    def _fetch_closed_trades(
        self,
        *,
        strategy: str | None = None,
        exchange: str | None = None,
        trading_mode: str | None = None,
    ) -> list:
        if self._trade_journal is None:
            return []

        if hasattr(self._trade_journal, "query"):
            rows = self._trade_journal.query(
                strategy=strategy,
                exchange=exchange,
                trading_mode=trading_mode,
                status=STATUS_CLOSED,
                limit=50_000,
            )
        else:
            rows = self._closed_trades()
            if strategy:
                rows = [
                    e
                    for e in rows
                    if strategy in str(getattr(e, "entry_conditions", {}))
                ]
            if exchange:
                rows = [
                    e
                    for e in rows
                    if (e.exchange or "").upper() == exchange.upper()
                ]
            if trading_mode:
                mode = normalize_trading_mode(trading_mode).value
                rows = [
                    e
                    for e in rows
                    if (getattr(e, "trading_mode", None) or "") == mode
                ]

        return [e for e in rows if e.status == STATUS_CLOSED and e.pnl is not None]

    @staticmethod
    def _filter_by_exit_period(
        trades: list,
        *,
        period: str,
        now: datetime | None = None,
    ) -> list:
        date_from, date_to = period_bounds(period, now=now)
        if date_from is None and date_to is None:
            return trades

        out = []
        for entry in trades:
            stamp = entry.exit_time or entry.entry_time
            if stamp is None:
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            if date_from is not None and stamp < date_from:
                continue
            if date_to is not None and stamp > date_to:
                continue
            out.append(entry)
        return out

    def generate_report(
        self,
        trades: list | None = None,
        *,
        period: str = PERIOD_ALL_TIME,
        strategy: str | None = None,
        exchange: str | None = None,
        trading_mode: str | None = None,
        now: datetime | None = None,
    ) -> PerformanceReport:
        """
        Computes a PerformanceReport from closed trades.

        If ``trades`` is omitted, loads from the wired TradeJournal and
        applies ``period`` / ``strategy`` / ``exchange`` / ``trading_mode``
        filters (period uses exit_time UTC). When ``trading_mode`` is
        omitted, defaults to the process trading mode so PAPER and REAL
        stats stay isolated.
        """
        period_key = (period or PERIOD_ALL_TIME).strip().lower()
        if period_key not in SUPPORTED_PERIODS:
            raise ValueError(
                f"Unsupported analytics period {period!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_PERIODS))}"
            )

        mode_explicit = trading_mode is not None
        if trades is None:
            mode_key = normalize_trading_mode(
                trading_mode if mode_explicit else resolve_trading_mode()
            ).value
            trades = self._fetch_closed_trades(
                strategy=strategy,
                exchange=exchange,
                trading_mode=mode_key,
            )
            trades = self._filter_by_exit_period(
                trades, period=period_key, now=now
            )
        else:
            # Explicit trade list: only apply mode filter when the caller
            # asked for one (legacy unit tests pass mixed/untagged rows).
            mode_key = (
                normalize_trading_mode(trading_mode).value
                if mode_explicit
                else None
            )
            if strategy:
                trades = [
                    e
                    for e in trades
                    if strategy in str(getattr(e, "entry_conditions", {}))
                ]
            if exchange:
                trades = [
                    e
                    for e in trades
                    if (getattr(e, "exchange", None) or "").upper()
                    == exchange.upper()
                ]
            if mode_key is not None:
                trades = [
                    e
                    for e in trades
                    if (getattr(e, "trading_mode", None) or mode_key) == mode_key
                ]
            if period_key != PERIOD_ALL_TIME:
                trades = self._filter_by_exit_period(
                    trades, period=period_key, now=now
                )

        if not trades:
            return _empty_report(
                period=period_key,
                strategy=strategy,
                exchange=exchange,
                trading_mode=mode_key,
            )

        trades = sorted(
            trades,
            key=lambda entry: entry.exit_time or entry.entry_time,
        )

        pnls = [entry.pnl for entry in trades]

        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl < 0]
        breakeven = [pnl for pnl in pnls if pnl == 0]

        win_pcts = [
            e.pnl_percent
            for e in trades
            if e.pnl is not None and e.pnl > 0 and e.pnl_percent is not None
        ]
        loss_pcts = [
            e.pnl_percent
            for e in trades
            if e.pnl is not None and e.pnl < 0 and e.pnl_percent is not None
        ]

        total_trades = len(trades)
        winning_trades = len(wins)
        losing_trades = len(losses)
        breakeven_trades = len(breakeven)

        win_rate_percent = (winning_trades / total_trades) * 100

        average_profit = (sum(wins) / winning_trades) if wins else 0.0
        average_loss = (sum(losses) / losing_trades) if losses else 0.0
        average_profit_percent = (
            (sum(win_pcts) / len(win_pcts)) if win_pcts else 0.0
        )
        average_loss_percent = (
            (sum(loss_pcts) / len(loss_pcts)) if loss_pcts else 0.0
        )

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
            average_profit_percent=average_profit_percent,
            average_loss_percent=average_loss_percent,
            total_pnl=total_pnl,
            expectancy=expectancy,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            max_drawdown_percent=max_drawdown_percent,
            recovery_factor=recovery_factor,
            period=period_key,
            strategy=strategy,
            exchange=exchange,
            trading_mode=mode_key,
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
