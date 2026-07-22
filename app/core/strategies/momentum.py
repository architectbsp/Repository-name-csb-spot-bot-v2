"""Momentum -- enter on sustained positive change_24h continuation."""

from __future__ import annotations

from app.core.strategies.base import BaseStrategy, coin_key, strategy_config
from app.core.watch_list import WatchState


class MomentumStrategy(BaseStrategy):
    """
    IDLE → WATCH_RISING when change_24h >= watch_percent.
    Enter when change_24h strengthens to >= entry_percent while still rising
    above the watch reference price.
    """

    name = "momentum"

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

        cfg = strategy_config(self._config)

        if state == WatchState.IDLE:
            if ticker.change_24h >= cfg.watch_percent:
                watch_list.begin_rising_watch(key, ticker.last_price)
                coin = watch_list.get(key)
                if coin is not None:
                    coin["entry_path"] = "PATH_MOMENTUM"
            return

        if state != WatchState.WATCH_RISING:
            return

        watch_list.record_rising_price(key, ticker.last_price)
        coin = watch_list.get(key)
        if coin is None:
            return

        if ticker.last_price < coin["lowest_price"]:
            # Momentum failed -- reset.
            watch_list.begin_falling_watch(key, ticker.last_price)
            return

        if ticker.change_24h < cfg.entry_percent:
            return

        self._try_open_position(
            watch_list,
            ticker,
            coin=coin,
            entry_reason="PATH_MOMENTUM",
        )
