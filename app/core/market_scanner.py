class MarketScanner:
    def __init__(self) -> None:
        self._running = False
        self._exchange = None

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def set_exchange(self, exchange) -> None:
        self._exchange = exchange

    def scan(self) -> None:
        pass

    def scan_once(self) -> None:
        pass
