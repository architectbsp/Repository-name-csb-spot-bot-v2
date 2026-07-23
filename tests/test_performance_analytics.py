"""
Sprint 7 -- Performance Analytics: Win Rate, Average Profit/Loss, Profit
Factor, Expectancy, Sharpe, Maximum Drawdown, Recovery Factor, all
computed purely from the Trade Journal's closed-trade history.
"""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta

import pytest

from app.core.domain.trade_journal import STATUS_CLOSED, STATUS_OPEN, TradeJournalEntry
from app.core.services.analytics_service import AnalyticsService
from app.core.services.performance_analytics import (
    PERIOD_LAST_7_DAYS,
    PERIOD_TODAY,
    PerformanceAnalytics,
    period_bounds,
)


def make_closed_trade(
    pnl,
    pnl_percent=None,
    minutes_ago=0,
    *,
    strategy: str | None = None,
    exchange: str | None = "BINANCE",
    exit_at: datetime | None = None,
):
    now = datetime.now(UTC)
    exit_time = exit_at or (now - timedelta(minutes=minutes_ago))
    return TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=exit_time - timedelta(minutes=10),
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        exchange=exchange,
        entry_conditions={"strategy": strategy} if strategy else {},
        status=STATUS_CLOSED,
        exit_time=exit_time,
        exit_price=100.0 + pnl,
        exit_reason="TRAILING_STOP",
        pnl=pnl,
        pnl_percent=pnl_percent if pnl_percent is not None else pnl,
    )


class DummyTradeJournal:
    def __init__(self, entries):
        self._entries = entries

    def list_all(self):
        return self._entries

    def query(self, **kwargs):
        status = kwargs.get("status")
        strategy = kwargs.get("strategy")
        exchange = kwargs.get("exchange")
        rows = list(self._entries)
        if status:
            rows = [e for e in rows if e.status == status]
        if strategy:
            rows = [e for e in rows if strategy in str(e.entry_conditions)]
        if exchange:
            rows = [
                e for e in rows if (e.exchange or "").upper() == exchange.upper()
            ]
        return rows


def test_empty_report_when_there_are_no_closed_trades():
    analytics = PerformanceAnalytics()
    analytics.set_trade_journal(DummyTradeJournal([]))

    report = analytics.generate_report()

    assert report.total_trades == 0
    assert report.win_rate_percent == 0.0
    assert report.profit_factor is None
    assert report.recovery_factor is None
    assert report.sharpe_ratio is None
    assert report.average_profit_percent == 0.0
    assert report.average_loss_percent == 0.0


def test_open_trades_are_excluded_from_the_report():
    open_trade = TradeJournalEntry(
        symbol="ETHUSDT",
        entry_time=datetime.now(UTC),
        entry_price=50.0,
        quantity=1.0,
        entry_reason="PATH_B_DIP_RECOVERY",
        status=STATUS_OPEN,
    )
    closed_trade = make_closed_trade(10.0, minutes_ago=5)

    analytics = PerformanceAnalytics()
    analytics.set_trade_journal(DummyTradeJournal([open_trade, closed_trade]))

    report = analytics.generate_report()

    assert report.total_trades == 1


def test_win_rate_and_average_profit_loss():
    trades = [
        make_closed_trade(10.0, pnl_percent=10.0, minutes_ago=40),
        make_closed_trade(20.0, pnl_percent=20.0, minutes_ago=30),
        make_closed_trade(-5.0, pnl_percent=-5.0, minutes_ago=20),
        make_closed_trade(-15.0, pnl_percent=-15.0, minutes_ago=10),
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.total_trades == 4
    assert report.winning_trades == 2
    assert report.losing_trades == 2
    assert report.win_rate_percent == 50.0
    assert report.average_profit == 15.0  # (10 + 20) / 2
    assert report.average_loss == -10.0  # (-5 + -15) / 2
    assert report.average_profit_percent == 15.0
    assert report.average_loss_percent == -10.0
    assert report.total_pnl == 10.0
    assert report.expectancy == 2.5  # 10 / 4


def test_profit_factor_is_gross_profit_over_gross_loss():
    trades = [
        make_closed_trade(30.0, minutes_ago=20),
        make_closed_trade(-10.0, minutes_ago=10),
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.profit_factor == 3.0  # 30 / 10


def test_profit_factor_is_infinite_with_wins_and_no_losses():
    trades = [make_closed_trade(10.0, minutes_ago=10)]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert math.isinf(report.profit_factor)
    assert math.isinf(report.recovery_factor)


def test_all_losing_trades_have_no_profit_factor_upside():
    trades = [
        make_closed_trade(-10.0, minutes_ago=20),
        make_closed_trade(-5.0, minutes_ago=10),
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.profit_factor == 0.0
    assert report.win_rate_percent == 0.0
    assert report.recovery_factor is not None
    assert report.recovery_factor < 0


def test_max_drawdown_from_a_realized_pnl_equity_curve():
    # Equity curve: 0 -> 100 -> 60 -> 80. Peak 100, trough 60 -> DD = 40
    # (40% of the 100 peak).
    trades = [
        make_closed_trade(100.0, minutes_ago=30),
        make_closed_trade(-40.0, minutes_ago=20),
        make_closed_trade(20.0, minutes_ago=10),
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.max_drawdown == 40.0
    assert report.max_drawdown_percent == 40.0
    assert report.total_pnl == 80.0
    assert report.recovery_factor == 2.0  # 80 / 40


def test_sharpe_ratio_is_none_with_a_single_trade():
    trades = [make_closed_trade(10.0, minutes_ago=10)]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.sharpe_ratio is None


def test_sharpe_ratio_is_none_when_returns_have_zero_variance():
    trades = [
        make_closed_trade(10.0, pnl_percent=5.0, minutes_ago=20),
        make_closed_trade(10.0, pnl_percent=5.0, minutes_ago=10),
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.sharpe_ratio is None


def test_sharpe_ratio_matches_closed_form_formula():
    returns = [5.0, 8.0, 2.0, 6.0]
    trades = [
        make_closed_trade(10.0, pnl_percent=r, minutes_ago=40 - i * 10)
        for i, r in enumerate(returns)
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    expected = (statistics.mean(returns) / statistics.pstdev(returns)) * math.sqrt(
        len(returns)
    )
    assert report.sharpe_ratio == pytest.approx(expected)


def test_report_reads_from_the_wired_trade_journal_when_no_trades_given():
    trades = [make_closed_trade(10.0, minutes_ago=10)]

    analytics = PerformanceAnalytics()
    analytics.set_trade_journal(DummyTradeJournal(trades))

    report = analytics.generate_report()

    assert report.total_trades == 1


def test_generate_report_without_a_trade_journal_wired_returns_empty_report():
    analytics = PerformanceAnalytics()

    report = analytics.generate_report()

    assert report.total_trades == 0


def test_period_today_filters_by_exit_time():
    now = datetime(2026, 7, 23, 15, 0, tzinfo=UTC)
    today_trade = make_closed_trade(
        10.0, exit_at=datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    )
    yesterday_trade = make_closed_trade(
        20.0, exit_at=datetime(2026, 7, 22, 10, 0, tzinfo=UTC)
    )

    analytics = AnalyticsService()
    analytics.set_trade_journal(
        DummyTradeJournal([today_trade, yesterday_trade])
    )

    report = analytics.generate_report(period=PERIOD_TODAY, now=now)

    assert report.total_trades == 1
    assert report.total_pnl == 10.0
    assert report.period == PERIOD_TODAY


def test_period_last_7_days_excludes_older_exits():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    recent = make_closed_trade(5.0, exit_at=now - timedelta(days=3))
    old = make_closed_trade(50.0, exit_at=now - timedelta(days=10))

    analytics = AnalyticsService()
    analytics.set_trade_journal(DummyTradeJournal([recent, old]))

    report = analytics.generate_report(period=PERIOD_LAST_7_DAYS, now=now)

    assert report.total_trades == 1
    assert report.total_pnl == 5.0


def test_strategy_and_exchange_filters():
    a = make_closed_trade(
        10.0, minutes_ago=20, strategy="dip_hunter", exchange="BINANCE"
    )
    b = make_closed_trade(
        -5.0, minutes_ago=10, strategy="momentum", exchange="BYBIT"
    )

    analytics = AnalyticsService()
    analytics.set_trade_journal(DummyTradeJournal([a, b]))

    by_strategy = analytics.generate_report(strategy="momentum")
    assert by_strategy.total_trades == 1
    assert by_strategy.total_pnl == -5.0
    assert by_strategy.strategy == "momentum"

    by_exchange = analytics.generate_report(exchange="BINANCE")
    assert by_exchange.total_trades == 1
    assert by_exchange.total_pnl == 10.0
    assert by_exchange.exchange == "BINANCE"


def test_period_bounds_all_time_and_today():
    now = datetime(2026, 7, 23, 15, 30, tzinfo=UTC)
    assert period_bounds("all_time", now=now) == (None, None)
    start, end = period_bounds("today", now=now)
    assert end is None
    assert start == datetime(2026, 7, 23, 0, 0, tzinfo=UTC)


def test_unsupported_period_raises():
    analytics = AnalyticsService()
    with pytest.raises(ValueError, match="Unsupported analytics period"):
        analytics.generate_report(period="last_year")
