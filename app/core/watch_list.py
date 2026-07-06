class WatchList:
    def __init__(self) -> None:
        self._coins: dict[str, dict] = {}
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

        self._coins[symbol] = {}
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
