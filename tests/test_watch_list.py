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
