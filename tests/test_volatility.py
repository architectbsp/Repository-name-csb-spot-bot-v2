"""Sprint 8 -- ATR and realized-volatility helpers."""

from app.core.domain.candle import Candle
from app.core.services.volatility import (
    compute_atr,
    compute_realized_volatility_percent,
)


def make_candles(closes, *, high_pad=1.0, low_pad=1.0):
    candles = []
    for i, close in enumerate(closes):
        candles.append(
            Candle(
                timestamp=i * 3_600_000,
                open=close,
                high=close + high_pad,
                low=close - low_pad,
                close=close,
                volume=100.0,
            )
        )
    return candles


def test_compute_atr_returns_none_without_enough_candles():
    assert compute_atr(make_candles([10, 11, 12]), period=14) is None


def test_compute_atr_averages_true_ranges():
    # Flat market around 100 with high=101, low=99 -> TR = 2 every bar.
    closes = [100.0] * 20
    atr = compute_atr(make_candles(closes), period=14)

    assert atr is not None
    assert abs(atr - 2.0) < 1e-9


def test_compute_realized_volatility_percent_is_none_for_flat_series():
    # Zero variance returns -> None (no meaningful vol to size against).
    assert (
        compute_realized_volatility_percent(make_candles([100.0] * 30), lookback=20)
        is None
    )


def test_compute_realized_volatility_percent_rises_with_bigger_moves():
    calm = make_candles([100 + (i % 2) * 0.1 for i in range(30)])
    wild = make_candles([100 + (i % 2) * 5.0 for i in range(30)])

    calm_vol = compute_realized_volatility_percent(calm, lookback=20)
    wild_vol = compute_realized_volatility_percent(wild, lookback=20)

    assert calm_vol is not None
    assert wild_vol is not None
    assert wild_vol > calm_vol
