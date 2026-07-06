from copy import deepcopy
from datetime import datetime
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


_ALLOWED_TRANSITIONS = {
    WatchState.IDLE: {WatchState.WATCH_FALLING, WatchState.WATCH_RISING},
    WatchState.WATCH_FALLING: {WatchState.WATCH_RISING},
    WatchState.WATCH_RISING: {WatchState.BUY_PENDING},
    WatchState.BUY_PENDING: {WatchState.POSITION_OPEN},
    WatchState.POSITION_OPEN: {WatchState.BREAK_EVEN, WatchState.POSITION_CLOSED},
    WatchState.BREAK_EVEN: {WatchState.TRAILING_ACTIVE, WatchState.POSITION_CLOSED},
    WatchState.TRAILING_ACTIVE: {WatchState.POSITION_CLOSED},
    WatchState.POSITION_CLOSED: {WatchState.COOLDOWN},
    WatchState.COOLDOWN: {WatchState.IDLE},
}


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

        now = datetime.utcnow()

        self._coins[symbol] = {
            "state": WatchState.IDLE,
            "lowest_price": None,
            "highest_price": None,
            "entry_price": None,
            "stop_price": None,
            "trailing_price": None,
            "cooldown_until": None,
            "created_at": now,
            "updated_at": now,
        }
        return True

    def get(self, symbol: str):
        coin = self._coins.get(symbol)
        return deepcopy(coin) if coin else None

    def get_state(self, symbol: str):
        if symbol not in self._coins:
            return None
        return self._coins[symbol]["state"]

    def can_transition(self, symbol: str, target: WatchState) -> bool:
        if symbol not in self._coins:
            return False

        current = self._coins[symbol]["state"]
        return target in _ALLOWED_TRANSITIONS[current]

    def transition(self, symbol: str, target: WatchState) -> bool:
        if not self.can_transition(symbol, target):
            return False

        self._coins[symbol]["state"] = target
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def update_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None or price < coin["lowest_price"]:
            coin["lowest_price"] = price

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price

        coin["updated_at"] = datetime.utcnow()
        return True


    def update_lowest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None or price < coin["lowest_price"]:
            coin["lowest_price"] = price
            coin["updated_at"] = datetime.utcnow()

        return True

    def update_highest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price
            coin["updated_at"] = datetime.utcnow()

        return True


    def set_entry_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["entry_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def set_stop_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["stop_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def set_trailing_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["trailing_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def reset(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        created_at = self._coins[symbol]["created_at"]
        now = datetime.utcnow()

        self._coins[symbol] = {
            "state": WatchState.IDLE,
            "lowest_price": None,
            "highest_price": None,
            "entry_price": None,
            "stop_price": None,
            "trailing_price": None,
            "cooldown_until": None,
            "created_at": created_at,
            "updated_at": now,
        }
        return True

    def remove(self, symbol: str) -> bool:
        return self._coins.pop(symbol, None) is not None

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
