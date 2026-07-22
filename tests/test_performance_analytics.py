"""
Sprint 7 -- Performance Analytics: Win Rate, Average Profit/Loss, Profit
Factor, Expectancy, Sharpe, Maximum Drawdown, Recovery Factor, all
computed purely from the Trade Journal's closed-trade history.
"""

import math
from datetime import UTC, datetime, timedelta

from app.core.domain.trade_journal import STATUS_CLOSED, STATUS_OPEN, TradeJournalEntry
from app.core.services.performance_analytics import PerformanceAnalytics


def make_closed_trade(pnl, pnl_percent=None, minutes_ago=0):
    now = datetime.now(UTC)
    return TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=now - timedelta(minutes=minutes_ago + 10),
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        status=STATUS_CLOSED,
        exit_time=now - timedelta(minutes=minutes_ago),
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


def test_empty_report_when_there_are_no_closed_trades():
    analytics = PerformanceAnalytics()
    analytics.set_trade_journal(DummyTradeJournal([]))

    report = analytics.generate_report()

    assert report.total_trades == 0
    assert report.win_rate_percent == 0.0
    assert report.profit_factor is None
    assert report.recovery_factor is None
    assert report.sharpe_ratio is None


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
        make_closed_trade(10.0, minutes_ago=40),
        make_closed_trade(20.0, minutes_ago=30),
        make_closed_trade(-5.0, minutes_ago=20),
        make_closed_trade(-15.0, minutes_ago=10),
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.total_trades == 4
    assert report.winning_trades == 2
    assert report.losing_trades == 2
    assert report.win_rate_percent == 50.0
    assert report.average_profit == 15.0  # (10 + 20) / 2
    assert report.average_loss == -10.0  # (-5 + -15) / 2
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


def test_sharpe_ratio_is_positive_for_consistently_profitable_trades():
    trades = [
        make_closed_trade(10.0, pnl_percent=5.0, minutes_ago=40),
        make_closed_trade(20.0, pnl_percent=8.0, minutes_ago=30),
        make_closed_trade(5.0, pnl_percent=2.0, minutes_ago=20),
        make_closed_trade(15.0, pnl_percent=6.0, minutes_ago=10),
    ]

    analytics = PerformanceAnalytics()
    report = analytics.generate_report(trades)

    assert report.sharpe_ratio is not None
    assert report.sharpe_ratio > 0


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
