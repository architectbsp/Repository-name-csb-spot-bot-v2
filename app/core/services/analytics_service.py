"""
AnalyticsService -- prompt-facing name for trade performance analytics.

Computes Win Rate, Avg Profit/Loss, Profit Factor, Sharpe Ratio,
Max Drawdown and Expectancy from closed Trade Journal rows. Implementation
lives in PerformanceAnalytics; this module is the public alias used by
BotEngine / DashboardService.
"""

from app.core.services.performance_analytics import PerformanceAnalytics


class AnalyticsService(PerformanceAnalytics):
    """Identical to PerformanceAnalytics; preferred public name."""

    pass
