class MarketScanner:
    def __init__(self) -> None:
        self._running = False
        self._exchange = None
        self._scheduler = None
        self._event_bus = None
        self._rate_limiter = None

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

    def get_scheduler(self):
        return self._scheduler

    def set_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus

    def get_event_bus(self):
        return self._event_bus

    def set_rate_limiter(self, rate_limiter) -> None:
        self._rate_limiter = rate_limiter

    def get_rate_limiter(self):
        return self._rate_limiter

    def scan(self) -> None:
        pass

    def scan_once(self) -> None:
        pass
