class MarketScanner:
    def __init__(self) -> None:
        self._running = False
        self._exchange = None
        self._scheduler = None
        self._event_bus = None
        self._rate_limiter = None
        self._retry_policy = None
        self._timeout = None
        self._timer = None
        self._stopwatch = None
        self._config = None

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

    def set_retry_policy(self, retry_policy) -> None:
        self._retry_policy = retry_policy

    def get_retry_policy(self):
        return self._retry_policy

    def set_timeout(self, timeout) -> None:
        self._timeout = timeout

    def get_timeout(self):
        return self._timeout

    def set_timer(self, timer) -> None:
        self._timer = timer

    def get_timer(self):
        return self._timer

    def set_stopwatch(self, stopwatch) -> None:
        self._stopwatch = stopwatch

    def get_stopwatch(self):
        return self._stopwatch

    def set_config(self, config) -> None:
        self._config = config

    def get_config(self):
        return self._config

    def initialize(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def run(self) -> None:
        pass

    def tick(self) -> None:
        pass

    def scan(self) -> None:
        pass

    def scan_once(self) -> None:
        pass

    def __repr__(self) -> str:
        return "MarketScanner()"

    def __str__(self) -> str:
        return "MarketScanner"

    def __bool__(self) -> bool:
        return self._running

    def __len__(self) -> int:
        return 0

    def __call__(self) -> None:
        self.scan()

    def has_exchange(self) -> bool:
        return self._exchange is not None

    def has_scheduler(self) -> bool:
        return self._scheduler is not None
