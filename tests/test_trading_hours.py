"""
Sprint 10 -- Trading Hours / Time Constraints.

Default OFF = 7/24. When enabled, only new BUY entries are gated;
stop / trailing / emergency sells keep running.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.domain.position import CloseReason
from app.core.exchange.models import OrderResult
from app.core.risk_manager import RiskManager
from app.core.services.trading_hours import (
    TimeConstraintService,
    TradingHoursManager,
    block_reason,
    is_entry_allowed,
)


def test_trading_hours_manager_alias():
    assert TradingHoursManager is TimeConstraintService


def test_disabled_hours_always_allow_247():
    """trading_hours_enabled=False iken bot 7/24 her saatte alım yapabilir."""
    saturday_night = datetime(2026, 7, 25, 3, 0, tzinfo=UTC)
    assert is_entry_allowed(
        enabled=False,
        disable_weekend_trading=True,
        trading_start_time="08:00",
        trading_end_time="23:00",
        now=saturday_night,
    )
    assert is_entry_allowed(
        enabled=False,
        weekend_closed=True,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=saturday_night,
    )


def test_active_window_blocks_buy_outside_hours():
    """Kısıt aktifken tanımlı pencere dışında yeni BUY engellenir."""
    outside = datetime(2026, 7, 23, 3, 30, tzinfo=UTC)  # Thursday 03:30
    assert not is_entry_allowed(
        enabled=True,
        disable_weekend_trading=False,
        trading_start_time="08:00",
        trading_end_time="23:00",
        now=outside,
    )
    assert (
        block_reason(
            enabled=True,
            disable_weekend_trading=False,
            trading_start_time="08:00",
            trading_end_time="23:00",
            now=outside,
        )
        == "outside_trading_hours"
    )

    inside = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    assert is_entry_allowed(
        enabled=True,
        disable_weekend_trading=False,
        trading_start_time="08:00",
        trading_end_time="23:00",
        now=inside,
    )


def test_disable_weekend_trading_blocks_saturday():
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)  # Saturday noon
    assert not is_entry_allowed(
        enabled=True,
        disable_weekend_trading=True,
        trading_start_time="08:00",
        trading_end_time="23:00",
        now=now,
    )
    assert (
        block_reason(
            enabled=True,
            disable_weekend_trading=True,
            trading_start_time="08:00",
            trading_end_time="23:00",
            now=now,
        )
        == "weekend_closed"
    )

    # Default disable_weekend_trading=False allows weekend entries.
    assert is_entry_allowed(
        enabled=True,
        disable_weekend_trading=False,
        trading_start_time="08:00",
        trading_end_time="23:00",
        now=now,
    )


def test_active_window_wraps_midnight():
    assert is_entry_allowed(
        enabled=True,
        disable_weekend_trading=False,
        trading_start_time="22:00",
        trading_end_time="06:00",
        now=datetime(2026, 7, 23, 23, 0, tzinfo=UTC),
    )
    assert not is_entry_allowed(
        enabled=True,
        disable_weekend_trading=False,
        trading_start_time="22:00",
        trading_end_time="06:00",
        now=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
    )


def test_legacy_quiet_hours_still_supported():
    now = datetime(2026, 7, 23, 3, 30, tzinfo=UTC)
    assert not is_entry_allowed(
        enabled=True,
        weekend_closed=False,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        now=now,
    )
    assert (
        block_reason(
            enabled=True,
            weekend_closed=False,
            quiet_start_hour_utc=2,
            quiet_end_hour_utc=5,
            now=now,
        )
        == "quiet_hours"
    )


def test_time_constraint_service_reads_settings():
    config = SimpleNamespace(
        strategy=SimpleNamespace(
            trading_hours_enabled=1,
            disable_weekend_trading=0,
            trading_start_time="08:00",
            trading_end_time="23:00",
        )
    )
    gate = TimeConstraintService(config)
    assert gate.is_entry_allowed(now=datetime(2026, 7, 23, 10, 0, tzinfo=UTC))
    assert not gate.is_entry_allowed(now=datetime(2026, 7, 23, 3, 0, tzinfo=UTC))


def _hours_config(*, enabled: int = 1):
    return SimpleNamespace(
        risk=SimpleNamespace(
            max_daily_loss_percent=20.0,
            max_open_positions=10,
            stop_loss_percent=10.0,
            trailing_activation_percent=2.0,
            trailing_percent=2.5,
            max_balance_utilization_percent=99.5,
            max_volume_share_percent=0.1,
            position_sizing_mode=0,
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
        ),
        strategy=SimpleNamespace(
            trading_hours_enabled=enabled,
            disable_weekend_trading=0,
            trading_start_time="08:00",
            trading_end_time="23:00",
            max_position_hours=24,
        ),
    )


def test_risk_manager_blocks_buy_outside_trading_hours(monkeypatch):
    frozen = datetime(2026, 7, 23, 3, 0, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(
        "app.core.services.trading_hours.datetime",
        FrozenDateTime,
    )

    rm = RiskManager()
    rm.set_config(_hours_config(enabled=1))

    assert not rm.can_open_trade(
        balance=10_000.0,
        daily_loss_percent=0.0,
        open_positions=0,
    )

    # With constraints disabled, same frozen "night" still allows BUY.
    rm.set_config(_hours_config(enabled=0))
    assert rm.can_open_trade(
        balance=10_000.0,
        daily_loss_percent=0.0,
        open_positions=0,
    )


def test_stop_loss_still_runs_outside_trading_hours(monkeypatch):
    """Yasaklı saatlerde açık pozisyonlar Stop Loss ile satılabilir."""
    frozen = datetime(2026, 7, 25, 3, 0, tzinfo=UTC)  # Saturday 03:00

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(
        "app.core.services.trading_hours.datetime",
        FrozenDateTime,
    )

    rm = RiskManager()
    rm.set_config(_hours_config(enabled=1))
    rm._running = True

    class DummyExchangeManager:
        def __init__(self):
            self.executed_trades = []

        def execute_trade(self, exchange_type, trade):
            self.executed_trades.append((exchange_type, trade))
            return OrderResult(
                order_id="order-1",
                symbol=trade.symbol,
                side="SELL",
                status="CLOSED",
                requested_quantity=float(trade.quantity),
                filled_quantity=float(trade.quantity),
                average_price=90.0,
                cost=float(trade.quantity) * 90.0,
                raw={},
            )

    class DummyPositions:
        def __init__(self, position):
            self._position = position
            self.closed = []

        def get(self, symbol, exchange=None):
            return self._position

        def get_open_positions(self):
            return [self._position]

        def close(self, symbol, *, exit_price, reason, exchange=None):
            self.closed.append((symbol, exit_price, reason))

    exchange = DummyExchangeManager()
    rm.set_exchange_manager(exchange)

    position = SimpleNamespace(
        symbol="BTCUSDT",
        quantity=1.0,
        stop_price=95.0,
        exchange="BYBIT",
        state=SimpleNamespace(name="OPEN"),
        entry_price=100.0,
        highest_price=100.0,
        stop_stage="HARD",
        pnl=None,
    )
    positions = DummyPositions(position)
    rm.set_position_manager(positions)

    # BUY would be blocked at this frozen time, but SELL must proceed.
    assert not is_entry_allowed(
        enabled=True,
        disable_weekend_trading=True,
        trading_start_time="08:00",
        trading_end_time="23:00",
        now=frozen,
    )

    ticker = SimpleNamespace(symbol="BTCUSDT", last_price=90.0, exchange="BYBIT")
    rm.on_price_tick(ticker)

    assert len(exchange.executed_trades) == 1
    assert positions.closed
    assert positions.closed[0][2] == CloseReason.STOP_LOSS
