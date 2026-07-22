"""
Backtest engine: replay OHLCV through live Strategy + RiskManager with
mock (paper) execution and produce a PerformanceReport.
"""

from app.core.backtest.engine import BacktestEngine, BacktestResult
from app.core.backtest.data import download_binance_klines, load_ohlcv_csv

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "download_binance_klines",
    "load_ohlcv_csv",
]
