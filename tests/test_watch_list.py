from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.core.scheduler.scheduler import Scheduler
from app.core.watch_list import WatchList, WatchState


class DummyExchangeManagerNoActive:
    def active_exchange_type(self):
        raise RuntimeError("No enabled exchange is registered.")


class DummyExchangeManagerWithActive:
    def __init__(self, active_type):
        self._active_type = active_type
        self.update_price_stream_calls = []

    def active_exchange_type(self):
        return self._active_type

    def update_price_stream(self, exchange_type, symbols):
        self.update_price_stream_calls.append((exchange_type, list(symbols)))


def test_sync_price_stream_noop_without_exchange():
    watchlist = WatchList()
    # No exchange configured at all -- must not raise.
    watchlist.add("BTCUSDT")


def test_sync_price_stream_noop_when_no_exchange_enabled():
    watchlist = WatchList()
    watchlist.set_exchange(DummyExchangeManagerNoActive())

    # Must not raise even though active_exchange_type() raises.
    watchlist.add("BTCUSDT")


def test_sync_price_stream_uses_the_single_active_exchange():
    watchlist = WatchList()
    exchange_manager = DummyExchangeManagerWithActive("BYBIT")
    watchlist.set_exchange(exchange_manager)

    watchlist.add("BTCUSDT")

    assert exchange_manager.update_price_stream_calls == [
        ("BYBIT", ["BTCUSDT"]),
    ]


def test_handle_scan_result_logs_instead_of_printing(capsys, caplog):
    """
    Regression guard for B31: handle_scan_result() used to print() its
    summary directly to stdout; it must go through the module logger
    instead so it respects log level/handlers configuration.
    """
    watchlist = WatchList()

    ticker = SimpleNamespace(symbol="BTCUSDT")

    with caplog.at_level("INFO", logger="app.core.watch_list"):
        added = watchlist.handle_scan_result([ticker])

    assert added == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert any(
        "added=1" in record.getMessage() for record in caplog.records
    )


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


def test_cooldown_lifecycle():
    watchlist = WatchList()

    watchlist.add("ETHUSDT")
    watchlist.begin_falling_watch("ETHUSDT", 100)
    watchlist.begin_rising_watch("ETHUSDT", 101)
    watchlist.promote_to_buy_pending("ETHUSDT", 102)
    watchlist.promote_to_position_open("ETHUSDT", 102, 98)
    watchlist.close_position("ETHUSDT")

    until = datetime.now(UTC) + timedelta(minutes=5)

    assert watchlist.enter_cooldown("ETHUSDT", until)
    assert watchlist.get_state("ETHUSDT") == WatchState.COOLDOWN
    assert watchlist.is_in_cooldown("ETHUSDT", datetime.now(UTC))

    assert watchlist.finish_cooldown("ETHUSDT")
    assert watchlist.get_state("ETHUSDT") == WatchState.IDLE


def _open_position(watchlist: WatchList, symbol: str) -> None:
    watchlist.add(symbol)
    watchlist.begin_falling_watch(symbol, 100)
    watchlist.begin_rising_watch(symbol, 101)
    watchlist.promote_to_buy_pending(symbol, 102)
    watchlist.promote_to_position_open(symbol, 102, 98)


def test_handle_position_closed_starts_cooldown_automatically():
    """
    B2 fix: closing a position must not leave the coin stuck in
    POSITION_CLOSED forever. It must automatically enter COOLDOWN using
    the configured cooldown duration (docs/BUSINESS_RULES.md: 4 hours).
    """
    watchlist = WatchList()
    watchlist.set_config(
        SimpleNamespace(risk=SimpleNamespace(cooldown_hours=4)),
    )

    _open_position(watchlist, "BTCUSDT")

    watchlist.handle_position_closed({"symbol": "BTCUSDT"})

    assert watchlist.get_state("BTCUSDT") == WatchState.COOLDOWN

    coin = watchlist.get("BTCUSDT")
    remaining = coin["cooldown_until"] - datetime.now(UTC)

    assert timedelta(hours=3, minutes=59) < remaining <= timedelta(hours=4)


def test_handle_position_closed_uses_default_cooldown_without_config():
    watchlist = WatchList()

    _open_position(watchlist, "BTCUSDT")

    watchlist.handle_position_closed({"symbol": "BTCUSDT"})

    assert watchlist.get_state("BTCUSDT") == WatchState.COOLDOWN


def test_process_cooldowns_returns_expired_coins_to_idle():
    """
    B2 fix: an expired cooldown must actively transition the coin back to
    IDLE, independent of the next market scan.
    """
    watchlist = WatchList()

    _open_position(watchlist, "BTCUSDT")
    watchlist.close_position("BTCUSDT")

    already_expired = datetime.now(UTC) - timedelta(seconds=1)
    watchlist.enter_cooldown("BTCUSDT", already_expired)

    finished = watchlist.process_cooldowns()

    assert finished == 1
    assert watchlist.get_state("BTCUSDT") == WatchState.IDLE


def test_process_cooldowns_keeps_active_cooldowns_untouched():
    watchlist = WatchList()

    _open_position(watchlist, "ETHUSDT")
    watchlist.close_position("ETHUSDT")

    still_active = datetime.now(UTC) + timedelta(hours=1)
    watchlist.enter_cooldown("ETHUSDT", still_active)

    finished = watchlist.process_cooldowns()

    assert finished == 0
    assert watchlist.get_state("ETHUSDT") == WatchState.COOLDOWN


def test_initialize_registers_cooldown_job_with_scheduler():
    watchlist = WatchList()
    scheduler = Scheduler()

    watchlist.set_scheduler(scheduler)
    watchlist.initialize()

    assert scheduler.has_job(WatchList._COOLDOWN_JOB_NAME)

    job = scheduler.get(WatchList._COOLDOWN_JOB_NAME)
    assert job.callback == watchlist.process_cooldowns


def test_cancel_buy_pending_returns_to_rising_watch():
    watchlist = WatchList()

    watchlist.add("BTCUSDT")
    watchlist.begin_falling_watch("BTCUSDT", 100)
    watchlist.begin_rising_watch("BTCUSDT", 101)
    watchlist.promote_to_buy_pending("BTCUSDT", 102)

    assert watchlist.cancel_buy_pending("BTCUSDT")
    assert watchlist.get_state("BTCUSDT") == WatchState.WATCH_RISING
    assert watchlist.get("BTCUSDT")["entry_price"] is None


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

    until = datetime.now(UTC) + timedelta(minutes=10)

    watchlist.start_cooldown("BTCUSDT", until)

    assert watchlist.is_in_cooldown(
        "BTCUSDT",
        datetime.now(UTC),
    )

    assert not watchlist.cooldown_expired(
        "BTCUSDT",
        datetime.now(UTC),
    )

    assert watchlist.remaining_cooldown(
        "BTCUSDT",
        datetime.now(UTC),
    ) is not None

    watchlist.clear_cooldown("BTCUSDT")

    assert not watchlist.is_in_cooldown(
        "BTCUSDT",
        datetime.now(UTC),
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
