class MarketScanner:
    def __init__(self) -> None:
        self._running = False

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def scan(self) -> None:
        pass

    def scan_once(self) -> None:
        pass
