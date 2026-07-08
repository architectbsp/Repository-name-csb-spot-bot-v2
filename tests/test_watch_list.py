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


def test_update_price_tracks_low_and_high():
    watchlist = WatchList()

    watchlist.add("BTCUSDT")

    assert watchlist.update_price("BTCUSDT", 100)
    assert watchlist.update_price("BTCUSDT", 95)
    assert watchlist.update_price("BTCUSDT", 110)

    coin = watchlist.get("BTCUSDT")

    assert coin["lowest_price"] == 95
    assert coin["highest_price"] == 110


def test_setters_update_values():
    watchlist = WatchList()

    watchlist.add("BTCUSDT")

    watchlist.set_entry_price("BTCUSDT", 100)
    watchlist.set_stop_price("BTCUSDT", 95)
    watchlist.set_trailing_price("BTCUSDT", 105)
    watchlist.set_lowest_price("BTCUSDT", 90)
    watchlist.set_highest_price("BTCUSDT", 120)

    coin = watchlist.get("BTCUSDT")

    assert coin["entry_price"] == 100
    assert coin["stop_price"] == 95
    assert coin["trailing_price"] == 105
    assert coin["lowest_price"] == 90
    assert coin["highest_price"] == 120


def test_clear_price_tracking():
    watchlist = WatchList()

    watchlist.add("BTCUSDT")
    watchlist.set_lowest_price("BTCUSDT", 90)
    watchlist.set_highest_price("BTCUSDT", 120)

    assert watchlist.clear_price_tracking("BTCUSDT")

    coin = watchlist.get("BTCUSDT")

    assert coin["lowest_price"] is None
    assert coin["highest_price"] is None


def test_cooldown_helpers():
    watchlist = WatchList()

    watchlist.add("BTCUSDT")

    until = datetime.utcnow() + timedelta(minutes=10)

    watchlist.start_cooldown("BTCUSDT", until)

    assert watchlist.is_in_cooldown(
        "BTCUSDT",
        datetime.utcnow(),
    )

    assert not watchlist.cooldown_expired(
        "BTCUSDT",
        datetime.utcnow(),
    )

    assert watchlist.remaining_cooldown(
        "BTCUSDT",
        datetime.utcnow(),
    ) is not None

    watchlist.clear_cooldown("BTCUSDT")

    assert not watchlist.is_in_cooldown(
        "BTCUSDT",
        datetime.utcnow(),
    )


def test_dependency_setters_and_clearers():
    watchlist = WatchList()

    exchange = object()
    scheduler = object()
    event_bus = object()
    rate_limiter = object()
    retry_policy = object()
    timeout = object()
    timer = object()
    stopwatch = object()
    strategy = object()
    config = object()

    watchlist.set_exchange(exchange)
    watchlist.set_scheduler(scheduler)
    watchlist.set_event_bus(event_bus)
    watchlist.set_rate_limiter(rate_limiter)
    watchlist.set_retry_policy(retry_policy)
    watchlist.set_timeout(timeout)
    watchlist.set_timer(timer)
    watchlist.set_stopwatch(stopwatch)
    watchlist.set_strategy(strategy)
    watchlist.set_config(config)

    assert watchlist.has_exchange()
    assert watchlist.has_scheduler()
    assert watchlist.has_event_bus()
    assert watchlist.has_rate_limiter()
    assert watchlist.has_retry_policy()
    assert watchlist.has_timeout()
    assert watchlist.has_timer()
    assert watchlist.has_stopwatch()
    assert watchlist.has_strategy()
    assert watchlist.has_config()

    watchlist.clear_exchange()
    watchlist.clear_scheduler()
    watchlist.clear_event_bus()
    watchlist.clear_rate_limiter()
    watchlist.clear_retry_policy()
    watchlist.clear_timeout()
    watchlist.clear_timer()
    watchlist.clear_stopwatch()
    watchlist.clear_strategy()
    watchlist.clear_config()

    assert not watchlist.has_exchange()
    assert not watchlist.has_scheduler()
    assert not watchlist.has_event_bus()
    assert not watchlist.has_rate_limiter()
    assert not watchlist.has_retry_policy()
    assert not watchlist.has_timeout()
    assert not watchlist.has_timer()
    assert not watchlist.has_stopwatch()
    assert not watchlist.has_strategy()
    assert not watchlist.has_config()
