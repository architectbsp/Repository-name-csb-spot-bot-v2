from copy import deepcopy
from enum import StrEnum
from typing import Any


class WatchState(StrEnum):
    IDLE = "IDLE"
    WATCH_FALLING = "WATCH_FALLING"
    WATCH_RISING = "WATCH_RISING"
    BUY_PENDING = "BUY_PENDING"
    POSITION_OPEN = "POSITION_OPEN"
    BREAK_EVEN = "BREAK_EVEN"
    TRAILING_ACTIVE = "TRAILING_ACTIVE"
    POSITION_CLOSED = "POSITION_CLOSED"
    COOLDOWN = "COOLDOWN"


class WatchList:
    def __init__(self) -> None:
        self._coins: dict[str, dict[str, Any]] = {}
        self._initialized = False
        self._running = False

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False
        self._coins.clear()

    def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("WatchList is not initialized.")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def add(self, symbol: str) -> bool:
        if symbol in self._coins:
            return False

        self._coins[symbol] = {
            "state": WatchState.IDLE,
            "lowest_price": None,
            "highest_price": None,
            "entry_price": None,
            "stop_price": None,
            "trailing_price": None,
            "cooldown_until": None,
        }
        return True

    def get(self, symbol: str) -> dict[str, Any] | None:
        coin = self._coins.get(symbol)
        return deepcopy(coin) if coin else None

    def get_state(self, symbol: str) -> WatchState | None:
        if symbol not in self._coins:
            return None
        return self._coins[symbol]["state"]

    def set_state(self, symbol: str, state: WatchState) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["state"] = state
        return True

    def remove(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        del self._coins[symbol]
        return True

    def contains(self, symbol: str) -> bool:
        return symbol in self._coins

    def clear(self) -> None:
        self._coins.clear()

    def size(self) -> int:
        return len(self._coins)

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def is_empty(self) -> bool:
        return len(self._coins) == 0
