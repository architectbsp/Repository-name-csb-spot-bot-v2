from copy import deepcopy
from typing import Any


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

    def add(self, symbol: str, data: dict[str, Any] | None = None) -> bool:
        if symbol in self._coins:
            return False

        self._coins[symbol] = deepcopy(data) if data else {}
        return True

    def update(self, symbol: str, data: dict[str, Any]) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol].update(data)
        return True

    def replace(self, symbol: str, data: dict[str, Any]) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol] = deepcopy(data)
        return True

    def get(self, symbol: str) -> dict[str, Any] | None:
        coin = self._coins.get(symbol)
        return deepcopy(coin) if coin is not None else None

    def get_value(self, symbol: str, key: str, default: Any = None) -> Any:
        if symbol not in self._coins:
            return default

        return self._coins[symbol].get(key, default)

    def set_value(self, symbol: str, key: str, value: Any) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol][key] = value
        return True

    def pop(self, symbol: str) -> dict[str, Any] | None:
        coin = self._coins.pop(symbol, None)
        return deepcopy(coin) if coin is not None else None

    def remove(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        del self._coins[symbol]
        return True

    def contains(self, symbol: str) -> bool:
        return symbol in self._coins

    def find_by(self, key: str, value: Any) -> list[str]:
        return sorted(
            symbol
            for symbol, data in self._coins.items()
            if data.get(key) == value
        )

    def clear(self) -> None:
        self._coins.clear()

    def size(self) -> int:
        return len(self._coins)

    def symbols(self) -> list[str]:
        return sorted(self._coins.keys())

    def items(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._coins)

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def is_empty(self) -> bool:
        return len(self._coins) == 0
