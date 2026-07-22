"""Breakout -- enter when price clears a tracked range high."""

from __future__ import annotations

from app.core.strategies.base import BaseStrategy, coin_key, strategy_config
from app.core.watch_list import WatchState


class BreakoutStrategy(BaseStrategy):
    """
    While IDLE, track the session high in ``highest_price``.
    When price breaks that high by ``entry_percent``, open.
    ``watch_percent`` is the minimum prior range expansion (high vs low
    reference) required before a breakout is eligible.
    """

    name = "breakout"

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
        coin = watch_list.get(key)
        if coin is None:
            return

        if state == WatchState.IDLE:
            high = coin.get("highest_price")
            low = coin.get("lowest_price")
            if high is None:
                coin["highest_price"] = ticker.last_price
                coin["lowest_price"] = ticker.last_price
                return

            if ticker.last_price > high:
                coin["highest_price"] = ticker.last_price
            if low is None or ticker.last_price < low:
                coin["lowest_price"] = ticker.last_price

            range_pct = 0.0
            if coin["lowest_price"] and coin["lowest_price"] > 0:
                range_pct = (
                    (coin["highest_price"] - coin["lowest_price"])
                    / coin["lowest_price"]
                ) * 100

            if range_pct < cfg.watch_percent:
                return

            breakout_level = coin["highest_price"] * (
                1 + cfg.entry_percent / 100.0
            )
            if ticker.last_price < breakout_level:
                return

            # Promote through WATCH_RISING so the shared FSM stays valid.
            watch_list.begin_rising_watch(key, coin["highest_price"])
            coin = watch_list.get(key)
            if coin is not None:
                coin["entry_path"] = "PATH_BREAKOUT"
                self._try_open_position(
                    watch_list,
                    ticker,
                    coin=coin,
                    entry_reason="PATH_BREAKOUT",
                )
            return

        if state == WatchState.WATCH_RISING:
            watch_list.record_rising_price(key, ticker.last_price)
            coin = watch_list.get(key)
            if coin is None:
                return
            recovery = (
                (ticker.last_price - coin["lowest_price"]) / coin["lowest_price"]
            ) * 100
            if recovery < cfg.entry_percent:
                return
            self._try_open_position(
                watch_list,
                ticker,
                coin=coin,
                entry_reason=coin.get("entry_path") or "PATH_BREAKOUT",
            )
