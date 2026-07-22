from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.domain.position import Position
from app.core.strategy import Strategy
from app.core.watch_list import WatchList, WatchState


class DummyConfig:
    watch_percent = 3
    entry_percent = 2
    stop_loss_percent = 5
    take_profit_activation = 10
    trailing_percent = 5


class DummyPositionManager:
    def is_open(self, symbol):
        return False


def make_ticker(price, change):
    return SimpleNamespace(
        exchange="BINANCE",
        symbol="BTCUSDT",
        last_price=price,
        volume_24h=1000,
        change_24h=change,
        timestamp=0,
    )


class DummyRiskManagerAccepts:
    """Fakes a RiskManager that always approves and fills the buy signal."""

    def __init__(self, position: Position):
        self._position = position
        self.calls: list[dict] = []

    def open_position(self, **kwargs):
        self.calls.append(kwargs)
        return self._position


class DummyRiskManagerRejects:
    """Fakes a RiskManager that rejects every buy signal."""

    def __init__(self):
        self.calls: list[dict] = []

    def open_position(self, **kwargs):
        self.calls.append(kwargs)
        return None


def test_idle_starts_falling_watch():
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())

    watchlist = WatchList()
    watchlist.add("BTCUSDT")

    ticker = make_ticker(100, -5)

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_FALLING


def test_idle_ignores_small_drop():
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())

    watchlist = WatchList()
    watchlist.add("BTCUSDT")

    ticker = make_ticker(100, -1)

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.IDLE


def test_rising_watch_delegates_order_execution_to_risk_manager():
    """
    BUSINESS_RULES.md #11: Strategy must never send exchange orders
    directly. A filled buy must flow entirely through
    RiskManager.open_position() and Strategy must only react to its
    result.
    """
    position = Position(
        symbol="BTCUSDT",
        entry_price=106.0,
        quantity=1.0,
        opened_at=datetime.now(UTC),
        stop_price=100.7,
    )

    risk_manager = DummyRiskManagerAccepts(position)

    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())
    strategy.set_risk_manager(risk_manager)

    watchlist = WatchList()
    watchlist.add("BTCUSDT")
    watchlist.begin_falling_watch("BTCUSDT", 100)
    watchlist.begin_rising_watch("BTCUSDT", 100)

    ticker = make_ticker(106, 6)

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.POSITION_OPEN
    assert watchlist.get("BTCUSDT")["entry_price"] == 106.0
    assert watchlist.get("BTCUSDT")["stop_price"] == 100.7

    assert len(risk_manager.calls) == 1
    assert risk_manager.calls[0]["symbol"] == "BTCUSDT"

    # Strategy no longer has any capability to talk to the exchange itself.
    assert not hasattr(strategy, "_exchange_manager")
    assert not hasattr(strategy, "_order_validator")


def test_rising_watch_returns_to_watch_rising_when_risk_manager_rejects():
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())
    strategy.set_risk_manager(DummyRiskManagerRejects())

    watchlist = WatchList()
    watchlist.add("BTCUSDT")
    watchlist.begin_falling_watch("BTCUSDT", 100)
    watchlist.begin_rising_watch("BTCUSDT", 100)

    ticker = make_ticker(106, 6)

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_RISING
    assert watchlist.get("BTCUSDT")["entry_price"] is None


def test_rising_watch_cancels_buy_pending_when_risk_manager_missing():
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())

    watchlist = WatchList()
    watchlist.add("BTCUSDT")
    watchlist.begin_falling_watch("BTCUSDT", 100)
    watchlist.begin_rising_watch("BTCUSDT", 100)

    ticker = make_ticker(106, 6)

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_RISING
