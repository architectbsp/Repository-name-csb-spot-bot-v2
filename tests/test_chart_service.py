"""
Sprint 6 -- Coin charts: ChartService assembles OHLCV candles (via
ExchangeManager) plus Entry/Stop/Take-Profit/Trailing overlay levels from
whichever trade a symbol currently has (an open Position, or -- once
closed -- the most recent Trade Journal entry).
"""

from datetime import UTC, datetime

from app.core.config.settings import AppSettings
from app.core.domain.candle import Candle
from app.core.domain.chart import STATUS_CLOSED, STATUS_OPEN
from app.core.domain.position import Position, PositionState
from app.core.domain.trade_journal import TradeJournalEntry
from app.core.exchange.models import ExchangeType
from app.core.services.chart_service import ChartService


class DummyExchangeManager:
    def __init__(self, candles=None, error=None):
        self._candles = candles or []
        self._error = error
        self.calls = []

    def fetch_ohlcv(self, exchange_type, symbol, timeframe="15m", limit=200):
        self.calls.append((exchange_type, symbol, timeframe, limit))
        if self._error is not None:
            raise self._error
        return self._candles


class DummyPositionManager:
    def __init__(self, positions=None):
        self._positions = positions or {}

    def get(self, symbol, exchange=None):
        return self._positions.get(symbol)


class DummyTradeJournal:
    def __init__(self, closed_entries=None):
        self._closed_entries = closed_entries or {}

    def get_last_closed(self, symbol):
        return self._closed_entries.get(symbol)


def make_candles(count=5):
    return [
        Candle(timestamp=i * 60_000, open=100, high=101, low=99, close=100 + i, volume=1)
        for i in range(count)
    ]


def test_build_chart_data_fetches_candles_from_the_active_exchange_only():
    exchange_manager = DummyExchangeManager(candles=make_candles())
    service = ChartService()
    service.set_exchange_manager(exchange_manager)

    chart = service.build_chart_data("BTCUSDT", ExchangeType.BINANCE)

    assert chart.candles == exchange_manager._candles
    assert exchange_manager.calls == [
        (ExchangeType.BINANCE, "BTCUSDT", "15m", 200)
    ]


def test_build_chart_data_returns_empty_candles_when_exchange_manager_not_wired():
    service = ChartService()

    chart = service.build_chart_data("BTCUSDT", ExchangeType.BINANCE)

    assert chart.candles == []
    assert chart.status is None


def test_build_chart_data_swallows_fetch_failures():
    exchange_manager = DummyExchangeManager(error=RuntimeError("network down"))
    service = ChartService()
    service.set_exchange_manager(exchange_manager)

    chart = service.build_chart_data("BTCUSDT", ExchangeType.BINANCE)

    assert chart.candles == []


def test_build_chart_data_overlays_the_open_position():
    entry_time = datetime(2026, 1, 1, tzinfo=UTC)
    position = Position(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        opened_at=entry_time,
        stop_price=95.0,
        highest_price=110.0,
        stop_stage="TRAILING",
        state=PositionState.OPEN,
    )
    service = ChartService()
    service.set_position_manager(DummyPositionManager({"BTCUSDT": position}))
    service.set_config(AppSettings())

    chart = service.build_chart_data("BTCUSDT", ExchangeType.BINANCE)

    assert chart.status == STATUS_OPEN
    assert chart.entry_price == 100.0
    assert chart.entry_time == entry_time
    assert chart.stop_price == 95.0
    assert chart.stop_stage == "TRAILING"
    assert chart.trailing_reference_price == 110.0
    # Take-profit target derived from entry_price * (1 + trailing_activation_percent / 100).
    config = AppSettings()
    expected_tp = 100.0 * (1 + config.risk.trailing_activation_percent / 100)
    assert chart.take_profit_price == expected_tp


def test_build_chart_data_ignores_a_closed_position_still_in_the_dict():
    position = Position(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        opened_at=datetime.now(UTC),
        state=PositionState.CLOSED,
    )
    service = ChartService()
    service.set_position_manager(DummyPositionManager({"BTCUSDT": position}))

    chart = service.build_chart_data("BTCUSDT", ExchangeType.BINANCE)

    assert chart.status is None
    assert chart.entry_price is None


def test_build_chart_data_falls_back_to_the_last_closed_journal_entry():
    entry = TradeJournalEntry(
        symbol="ETHUSDT",
        entry_time=datetime(2026, 1, 1, tzinfo=UTC),
        entry_price=3000.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        exit_time=datetime(2026, 1, 2, tzinfo=UTC),
        exit_price=3150.0,
        exit_reason="TRAILING_STOP",
    )
    service = ChartService()
    service.set_trade_journal(DummyTradeJournal({"ETHUSDT": entry}))
    service.set_config(AppSettings())

    chart = service.build_chart_data("ETHUSDT", ExchangeType.BINANCE)

    assert chart.status == STATUS_CLOSED
    assert chart.entry_price == 3000.0
    assert chart.exit_price == 3150.0
    assert chart.exit_reason == "TRAILING_STOP"
    # No live position -- stop/trailing fields don't apply to a closed trade.
    assert chart.stop_price is None
    assert chart.trailing_reference_price is None


def test_build_chart_data_prefers_the_open_position_over_journal_history():
    position = Position(
        symbol="BTCUSDT",
        entry_price=200.0,
        quantity=1.0,
        opened_at=datetime.now(UTC),
        state=PositionState.OPEN,
    )
    stale_closed_entry = TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=datetime(2020, 1, 1, tzinfo=UTC),
        entry_price=50.0,
        quantity=1.0,
        entry_reason="PATH_B_DIP_RECOVERY",
    )
    service = ChartService()
    service.set_position_manager(DummyPositionManager({"BTCUSDT": position}))
    service.set_trade_journal(DummyTradeJournal({"BTCUSDT": stale_closed_entry}))

    chart = service.build_chart_data("BTCUSDT", ExchangeType.BINANCE)

    assert chart.status == STATUS_OPEN
    assert chart.entry_price == 200.0


def test_build_chart_data_has_no_overlay_for_a_symbol_with_no_trade_history():
    service = ChartService()
    service.set_position_manager(DummyPositionManager())
    service.set_trade_journal(DummyTradeJournal())

    chart = service.build_chart_data("DOGEUSDT", ExchangeType.BINANCE)

    assert chart.status is None
    assert chart.entry_price is None
    assert chart.stop_price is None
