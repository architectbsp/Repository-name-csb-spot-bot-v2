class MarketScanner:
    def __init__(self) -> None:
        self._running = False
        self._exchange = None
        self._scheduler = None

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def set_exchange(self, exchange) -> None:
        self._exchange = exchange

    def get_exchange(self):
        return self._exchange

    def set_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler

    def scan(self) -> None:
        pass

    def scan_once(self) -> None:
        pass
