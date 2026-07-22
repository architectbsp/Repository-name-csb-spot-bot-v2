"""Dip Hunter -- classic Path A / Path B dip-recovery strategy."""

from __future__ import annotations

from app.core.strategies.base import BaseStrategy, coin_key, strategy_config
from app.core.watch_list import WatchState


class DipHunterStrategy(BaseStrategy):
    """
    Path A: already rising (>= watch_percent) → WATCH_RISING.
    Path B: falling (<= -watch_percent) → WATCH_FALLING → reverse → WATCH_RISING.
    Entry when recovery from lowest >= entry_percent.
    """

    name = "dip_hunter"

    def on_ticker(self, watch_list, ticker) -> None:
        key = coin_key(ticker)
        state = watch_list.get_state(key)
        if state is None:
            return

        if state in (WatchState.POSITION_OPEN, WatchState.BREAK_EVEN):
            self._handle_position_open(watch_list, ticker)
            return

        if self._position_already_open(ticker):
            return

        if state == WatchState.IDLE:
            self._handle_idle(watch_list, ticker)
            return

        if state == WatchState.WATCH_FALLING:
            self._handle_falling_watch(watch_list, ticker)
            return

        if state == WatchState.WATCH_RISING:
            self._handle_rising_watch(watch_list, ticker)

    def _handle_idle(self, watch_list, ticker) -> None:
        key = coin_key(ticker)
        watch_percent = strategy_config(self._config).watch_percent

        if ticker.change_24h <= -watch_percent:
            watch_list.begin_falling_watch(key, ticker.last_price)
            return

        if ticker.change_24h >= watch_percent:
            watch_list.begin_rising_watch(key, ticker.last_price)

    def _handle_falling_watch(self, watch_list, ticker) -> None:
        key = coin_key(ticker)
        watch_list.record_falling_price(key, ticker.last_price)
        coin = watch_list.get(key)
        if ticker.last_price > coin["lowest_price"]:
            watch_list.begin_rising_watch(key, ticker.last_price)

    def _handle_rising_watch(self, watch_list, ticker) -> None:
        key = coin_key(ticker)
        watch_list.record_rising_price(key, ticker.last_price)
        coin = watch_list.get(key)
        recovery = (
            (ticker.last_price - coin["lowest_price"]) / coin["lowest_price"]
        ) * 100
        if recovery < strategy_config(self._config).entry_percent:
            return

        entry_reason = coin.get("entry_path") or "PATH_B_DIP_RECOVERY"
        self._try_open_position(
            watch_list,
            ticker,
            coin=coin,
            entry_reason=entry_reason,
        )
