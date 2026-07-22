"""
Sprint 8 -- Volatility helpers for advanced position sizing.

Pure functions over Candle lists: Average True Range (ATR) and a simple
realized-volatility percent (sample stdev of close-to-close returns).
RiskManager uses these to size trades inversely to how wild the market
is; nothing here places orders or touches exchange state.
"""

from __future__ import annotations

import math

from app.core.domain.candle import Candle


def compute_atr(candles: list[Candle], period: int = 14) -> float | None:
    """
    Wilder-style ATR over the last `period` true ranges. Needs at least
    `period + 1` candles (one prior close for the first true range).
    Returns None when there isn't enough data.
    """
    if period <= 0 or len(candles) < period + 1:
        return None

    window = candles[-(period + 1) :]
    true_ranges: list[float] = []

    for i in range(1, len(window)):
        current = window[i]
        previous_close = window[i - 1].close
        true_range = max(
            current.high - current.low,
            abs(current.high - previous_close),
            abs(current.low - previous_close),
        )
        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    return sum(true_ranges[-period:]) / period


def compute_realized_volatility_percent(
    candles: list[Candle],
    lookback: int = 20,
) -> float | None:
    """
    Sample standard deviation of close-to-close percent returns over the
    last `lookback` returns, expressed in percent (e.g. 2.5 means 2.5%).
    None when fewer than 2 usable returns exist.
    """
    if lookback < 2 or len(candles) < lookback + 1:
        return None

    window = candles[-(lookback + 1) :]
    returns: list[float] = []

    for i in range(1, len(window)):
        previous = window[i - 1].close
        current = window[i].close
        if previous <= 0:
            continue
        returns.append((current - previous) / previous * 100.0)

    if len(returns) < 2:
        return None

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)

    if variance <= 0:
        return None

    return math.sqrt(variance)
