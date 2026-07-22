"""
Backtest engine: replay OHLCV through live Strategy + RiskManager with
mock (paper) execution and produce a PerformanceReport.
"""

from app.core.backtest.data import download_binance_klines, load_ohlcv_csv
from app.core.backtest.engine import BacktestEngine, BacktestResult
from app.core.backtest.optimizer import (
    OptimizationResult,
    OptimizationTrial,
    ParameterOptimizer,
    ParamRange,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "OptimizationResult",
    "OptimizationTrial",
    "ParamRange",
    "ParameterOptimizer",
    "download_binance_klines",
    "load_ohlcv_csv",
]
