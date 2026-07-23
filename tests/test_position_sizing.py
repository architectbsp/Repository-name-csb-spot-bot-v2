"""
Sprint 8 -- dedicated position sizing tests (Fixed Risk + ATR).

Broader hybrid / Kelly coverage also lives in test_risk_manager.py and
test_kelly_sizing.py.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.domain.candle import Candle
from app.core.risk_manager import (
    RiskManager,
    resolve_position_sizing_mode,
)
from app.core.exchange.models import OrderResult
from app.core.trading.models import TradeSide


def make_config(**risk_overrides):
    risk = dict(
        max_daily_loss_percent=20.0,
        max_open_positions=10,
        stop_loss_percent=10.0,
        trailing_activation_percent=2.0,
        trailing_percent=2.5,
        max_balance_utilization_percent=99.5,
        max_volume_share_percent=0.1,
        position_sizing_mode=2,
        risk_per_trade_percent=1.0,
        atr_period=14,
        atr_multiplier=2.0,
        volatility_target_percent=0.0,
        volatility_lookback=20,
        kelly_fraction=0.5,
        kelly_min_trades=10,
        dynamic_lookback_trades=0,
        partial_tp_activation_percent=0.0,
        partial_tp_sell_percent=50.0,
    )
    risk.update(risk_overrides)
    return SimpleNamespace(risk=SimpleNamespace(**risk), strategy=SimpleNamespace())


class FakeOhlcvExchangeManager:
    def __init__(self, candles, balance=10_000.0):
        self._candles = candles
        self._balance = balance

    def get_quote_balance(self, exchange_type):
        return self._balance

    def enabled_exchange_types(self):
        return ["BINANCE"]

    def fetch_ohlcv(self, exchange_type, symbol, timeframe="1h", limit=200):
        return list(self._candles)

    def execute_trade(self, exchange_type, trade):
        return OrderResult(
            order_id="x",
            symbol=trade.symbol,
            side=trade.side.value if hasattr(trade.side, "value") else str(trade.side),
            status="CLOSED",
            requested_quantity=float(trade.quantity),
            filled_quantity=float(trade.quantity),
            average_price=100.0,
            cost=float(trade.quantity) * 100.0,
            raw={},
        )


def _candles(count=30, price=100.0, pad=1.0):
    return [
        Candle(
            timestamp=i * 3_600_000,
            open=price,
            high=price + pad,
            low=price - pad,
            close=price,
            volume=1.0,
        )
        for i in range(count)
    ]


def test_resolve_position_sizing_mode_aliases():
    assert resolve_position_sizing_mode("FIXED_RISK") == 2
    assert resolve_position_sizing_mode("ATR_BASED") == 3
    assert resolve_position_sizing_mode("DYNAMIC") == 4
    assert resolve_position_sizing_mode("FIXED_PERCENT") == 5
    assert resolve_position_sizing_mode(2) == 2


def test_fixed_risk_size_scales_inversely_with_stop_distance():
    """
    risk_amount = balance * 1% = 100.
    stop 10% -> size = 100 / 0.10 = 1_000
    stop 5%  -> size = 100 / 0.05 = 2_000
    """
    rm = RiskManager()
    rm.set_config(
        make_config(
            position_sizing_mode="FIXED_RISK",
            stop_loss_percent=10.0,
            risk_per_trade_percent=1.0,
        )
    )
    wide = rm.calculate_position_size(10_000, volume_24h=50_000_000)
    assert wide == 1_000.0

    rm.set_config(
        make_config(
            position_sizing_mode=2,
            stop_loss_percent=5.0,
            risk_per_trade_percent=1.0,
        )
    )
    tight = rm.calculate_position_size(10_000, volume_24h=50_000_000)
    assert tight == 2_000.0
    assert tight > wide


def test_atr_mode_shrinks_position_when_volatility_rises():
    """
    Same risk budget; larger ATR → larger stop distance → smaller size.
    """
    rm = RiskManager()
    rm.set_config(
        make_config(
            position_sizing_mode="ATR_BASED",
            risk_per_trade_percent=1.0,
            atr_period=14,
            atr_multiplier=2.0,
            volatility_target_percent=0.0,
        )
    )

    rm.set_exchange_manager(
        FakeOhlcvExchangeManager(_candles(pad=1.0), balance=10_000.0)
    )
    calm = rm.calculate_position_size(
        10_000,
        volume_24h=50_000_000,
        price=100.0,
        symbol="BTC/USDT",
        exchange_type="BINANCE",
    )

    rm.set_exchange_manager(
        FakeOhlcvExchangeManager(_candles(pad=5.0), balance=10_000.0)
    )
    wild = rm.calculate_position_size(
        10_000,
        volume_24h=50_000_000,
        price=100.0,
        symbol="BTC/USDT",
        exchange_type="BINANCE",
    )

    # pad=1 -> ATR≈2, stop=4, size=100*100/4=2500
    # pad=5 -> ATR≈10, stop=20, size=100*100/20=500
    assert calm == 2_500.0
    assert wild == 500.0
    assert wild < calm


def test_fixed_percent_allocates_risk_per_trade_of_balance():
    rm = RiskManager()
    rm.set_config(
        make_config(
            position_sizing_mode="FIXED_PERCENT",
            risk_per_trade_percent=10.0,
        )
    )
    # min(99.5% of 10k, 10% of 10k, liquidity) = 1_000
    size = rm.calculate_position_size(10_000, volume_24h=50_000_000)
    assert size == 1_000.0
