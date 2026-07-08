from app.core.watch_list import WatchList, WatchState


def test_full_state_machine_lifecycle():
    watchlist = WatchList()

    assert watchlist.add("BTCUSDT")

    assert watchlist.begin_falling_watch("BTCUSDT", 100)
    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_FALLING

    assert watchlist.begin_rising_watch("BTCUSDT", 101)
    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_RISING

    assert watchlist.promote_to_buy_pending("BTCUSDT", 102)
    assert watchlist.get_state("BTCUSDT") == WatchState.BUY_PENDING

    assert watchlist.promote_to_position_open("BTCUSDT", 102, 98)
    assert watchlist.get_state("BTCUSDT") == WatchState.POSITION_OPEN

    assert watchlist.activate_break_even("BTCUSDT")
    assert watchlist.get_state("BTCUSDT") == WatchState.BREAK_EVEN

    assert watchlist.activate_trailing("BTCUSDT", 110, 107)
    assert watchlist.get_state("BTCUSDT") == WatchState.TRAILING_ACTIVE

    assert watchlist.close_position("BTCUSDT")
    assert watchlist.get_state("BTCUSDT") == WatchState.POSITION_CLOSED

from datetime import datetime, timedelta


def test_cooldown_lifecycle():
    watchlist = WatchList()

    watchlist.add("ETHUSDT")
    watchlist.begin_falling_watch("ETHUSDT", 100)
    watchlist.begin_rising_watch("ETHUSDT", 101)
    watchlist.promote_to_buy_pending("ETHUSDT", 102)
    watchlist.promote_to_position_open("ETHUSDT", 102, 98)
    watchlist.close_position("ETHUSDT")

    until = datetime.utcnow() + timedelta(minutes=5)

    assert watchlist.enter_cooldown("ETHUSDT", until)
    assert watchlist.get_state("ETHUSDT") == WatchState.COOLDOWN
    assert watchlist.is_in_cooldown("ETHUSDT", datetime.utcnow())

    assert watchlist.finish_cooldown("ETHUSDT")
    assert watchlist.get_state("ETHUSDT") == WatchState.IDLE


def test_reset_restores_idle_state():
    watchlist = WatchList()

    watchlist.add("SOLUSDT")
    watchlist.begin_falling_watch("SOLUSDT", 100)
    watchlist.record_falling_price("SOLUSDT", 95)

    assert watchlist.reset("SOLUSDT")

    coin = watchlist.get("SOLUSDT")

    assert coin["state"] == WatchState.IDLE
    assert coin["lowest_price"] is None
    assert coin["highest_price"] is None
    assert coin["entry_price"] is None
    assert coin["stop_price"] is None
    assert coin["trailing_price"] is None
    assert coin["cooldown_until"] is None


def test_duplicate_symbol_is_rejected():
    watchlist = WatchList()

    assert watchlist.add("BTCUSDT") is True
    assert watchlist.add("BTCUSDT") is False


def test_unknown_symbol_operations_return_false():
    watchlist = WatchList()

    assert watchlist.transition("BTCUSDT", WatchState.WATCH_FALLING) is False
    assert watchlist.can_transition("BTCUSDT", WatchState.WATCH_FALLING) is False
    assert watchlist.begin_falling_watch("BTCUSDT", 100) is False
    assert watchlist.promote_to_buy_pending("BTCUSDT", 100) is False


def test_invalid_transition_is_rejected():
    watchlist = WatchList()

    watchlist.add("BTCUSDT")

    assert watchlist.transition(
        "BTCUSDT",
        WatchState.POSITION_OPEN,
    ) is False

    assert watchlist.get_state("BTCUSDT") == WatchState.IDLE


def test_can_transition_follows_state_machine():
    watchlist = WatchList()

    watchlist.add("BTCUSDT")

    assert watchlist.can_transition(
        "BTCUSDT",
        WatchState.WATCH_FALLING,
    )

    assert not watchlist.can_transition(
        "BTCUSDT",
        WatchState.POSITION_OPEN,
    )

    watchlist.begin_falling_watch("BTCUSDT", 100)

    assert watchlist.can_transition(
        "BTCUSDT",
        WatchState.WATCH_RISING,
    )

    assert not watchlist.can_transition(
        "BTCUSDT",
        WatchState.COOLDOWN,
    )
