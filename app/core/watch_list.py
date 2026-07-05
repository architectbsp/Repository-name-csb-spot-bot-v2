class WatchList:
    def __init__(self) -> None:
        self._coins = {}
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

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def is_empty(self) -> bool:
        return len(self._coins) == 0
