"""
AnalyticsService -- prompt-facing name for trade performance analytics.

Computes Win Rate, Avg Profit/Loss ($ and %), Profit Factor, Sharpe Ratio,
Max Drawdown, Expectancy and Recovery Factor from closed Trade Journal
rows, with optional period / strategy / exchange filters.

Implementation lives in PerformanceAnalytics; this module is the public
alias used by BotEngine / DashboardService.
"""

from app.core.services.performance_analytics import (
    PERIOD_ALL_TIME,
    PERIOD_LAST_7_DAYS,
    PERIOD_LAST_30_DAYS,
    PERIOD_TODAY,
    PerformanceAnalytics,
    period_bounds,
)


class AnalyticsService(PerformanceAnalytics):
    """Identical to PerformanceAnalytics; preferred public name."""

    pass


__all__ = [
    "AnalyticsService",
    "PERIOD_ALL_TIME",
    "PERIOD_LAST_7_DAYS",
    "PERIOD_LAST_30_DAYS",
    "PERIOD_TODAY",
    "PerformanceAnalytics",
    "period_bounds",
]
