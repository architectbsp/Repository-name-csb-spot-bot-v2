from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.domain.position import Position
from app.core.strategy import Strategy
from app.core.watch_list import WatchList, WatchState


class DummyConfig:
    # Strategy no longer carries its own copy of any risk parameter (stop
    # loss %, position sizing, daily loss limit); those all live on
    # RiskManager now. Only FSM-transition thresholds remain here.
    watch_percent = 3
    entry_percent = 2


class DummyPositionManager:
    def is_open(self, symbol):
        return False


def test_dead_code_entry_points_are_removed():
    """
    Regression guard for B19: Strategy previously shipped an
    on_price_tick()/evaluate_live_signal() pair that referenced a
    non-existent self._watch_list attribute and was never wired into the
    event bus. Both must stay removed rather than silently reappearing.
    """
    assert not hasattr(Strategy, "on_price_tick")
    assert not hasattr(Strategy, "evaluate_live_signal")
    assert not hasattr(Strategy(), "_watch_list")


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


def test_idle_starts_rising_watch_directly_on_entry_path_a():
    """
    docs/BUSINESS_RULES.md §2 Entry Path A: a coin that never dropped and
    is already rising must go straight from IDLE to WATCH_RISING (not
    require a prior WATCH_FALLING dip like Entry Path B).
    """
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())

    watchlist = WatchList()
    watchlist.add("BTCUSDT")

    ticker = make_ticker(100, 5)  # +5% with no prior dip

    strategy.on_ticker(watchlist, ticker)

    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_RISING
    assert watchlist.get("BTCUSDT")["lowest_price"] == 100


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
    # Strategy hands RiskManager the coin's 24h volume so it can size the
    # trade dynamically (docs/BUSINESS_RULES.md §8); it never computes or
    # forwards a stop_loss_percent -- that is RiskManager's own config.
    assert risk_manager.calls[0]["volume_24h"] == 1000
    assert "stop_loss_percent" not in risk_manager.calls[0]

    # Strategy no longer has any capability to talk to the exchange itself.
    assert not hasattr(strategy, "_exchange_manager")
    assert not hasattr(strategy, "_order_validator")


class DummyTradeJournal:
    def __init__(self):
        self.entries = []

    def record_entry(self, **kwargs):
        self.entries.append(kwargs)


def test_rising_watch_records_a_trade_journal_entry_on_fill():
    """Sprint 5 -- Trade Journal: Strategy is the only module that knows
    *why* a BUY happened, so it must record the entry itself, right after
    the position is confirmed open."""
    position = Position(
        symbol="BTCUSDT",
        entry_price=106.0,
        quantity=1.0,
        opened_at=datetime.now(UTC),
        stop_price=100.7,
    )

    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())
    strategy.set_risk_manager(DummyRiskManagerAccepts(position))

    journal = DummyTradeJournal()
    strategy.set_trade_journal(journal)

    watchlist = WatchList()
    watchlist.add("BTCUSDT")
    watchlist.begin_falling_watch("BTCUSDT", 100)
    watchlist.begin_rising_watch("BTCUSDT", 100)
    watchlist.record_rising_price("BTCUSDT", 103)

    ticker = make_ticker(106, 6)

    strategy.on_ticker(watchlist, ticker)

    assert len(journal.entries) == 1
    recorded = journal.entries[0]
    assert recorded["symbol"] == "BTCUSDT"
    assert recorded["entry_price"] == 106.0
    assert recorded["entry_reason"] == "PATH_B_DIP_RECOVERY"
    # +1 from the manual record_rising_price(103) above, +1 more from
    # on_ticker() itself recording the fill tick's own new high (106).
    assert recorded["rise_events"] == 2
    assert recorded["watch_started_at"] is not None
    assert recorded["wait_minutes"] is not None


def test_rejected_buy_does_not_record_a_trade_journal_entry():
    strategy = Strategy()
    strategy.set_config(DummyConfig())
    strategy.set_position_manager(DummyPositionManager())
    strategy.set_risk_manager(DummyRiskManagerRejects())

    journal = DummyTradeJournal()
    strategy.set_trade_journal(journal)

    watchlist = WatchList()
    watchlist.add("BTCUSDT")
    watchlist.begin_falling_watch("BTCUSDT", 100)
    watchlist.begin_rising_watch("BTCUSDT", 100)

    ticker = make_ticker(106, 6)

    strategy.on_ticker(watchlist, ticker)

    assert journal.entries == []


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
