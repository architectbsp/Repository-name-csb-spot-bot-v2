"""Scalper -- tighter dip-recovery with faster confirmation."""

from __future__ import annotations

from app.core.strategies.base import BaseStrategy, coin_key, strategy_config
from app.core.watch_list import WatchState


class ScalperStrategy(BaseStrategy):
    """
    Same FSM skeleton as Dip Hunter, but Path A is preferred and a
    smaller recovery (entry_percent) triggers the entry. Typical presets
    use watch≈1% / entry≈0.8% / stop≈1.5%.
    """

    name = "scalper"

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
            # Prefer quick Path A; also arm on shallow dips.
            if ticker.change_24h >= cfg.watch_percent:
                watch_list.begin_rising_watch(key, ticker.last_price)
                coin = watch_list.get(key)
                if coin is not None:
                    coin["entry_path"] = "PATH_SCALPER_MOMENTUM"
                return
            if ticker.change_24h <= -cfg.watch_percent:
                watch_list.begin_falling_watch(key, ticker.last_price)
            return

        if state == WatchState.WATCH_FALLING:
            watch_list.record_falling_price(key, ticker.last_price)
            coin = watch_list.get(key)
            if ticker.last_price > coin["lowest_price"]:
                watch_list.begin_rising_watch(key, ticker.last_price)
                coin = watch_list.get(key)
                if coin is not None:
                    coin["entry_path"] = "PATH_SCALPER_RECOVERY"
            return

        if state != WatchState.WATCH_RISING:
            return

        watch_list.record_rising_price(key, ticker.last_price)
        coin = watch_list.get(key)
        recovery = (
            (ticker.last_price - coin["lowest_price"]) / coin["lowest_price"]
        ) * 100
        if recovery < cfg.entry_percent:
            return

        self._try_open_position(
            watch_list,
            ticker,
            coin=coin,
            entry_reason=coin.get("entry_path") or "PATH_SCALPER",
        )
