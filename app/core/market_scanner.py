class MarketScanner:
    _DEPENDENCY_NAMES = (
        "exchange",
        "scheduler",
        "event_bus",
        "rate_limiter",
        "retry_policy",
        "timeout",
        "timer",
        "stopwatch",
        "config",
    )

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
        self._last_scan_result = []
        self._initialized = False

    def start(self) -> None:
        if not self.is_initialized():
            raise RuntimeError("MarketScanner is not initialized.")

        self._running = True

        if self.has_event_bus():
            self._event_bus.emit("market_scanner.started")

    def stop(self) -> None:
        was_running = self._running
        self._running = False

        if was_running and self.has_event_bus():
            self._event_bus.emit("market_scanner.stopped")

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
        if self.is_initialized():
            return

        self.stop()
        self._initialized = True

    def shutdown(self) -> None:
        if not self.is_initialized():
            return

        self.stop()
        self._initialized = False

    def reset(self) -> None:
        if self.is_running():
            self.stop()

        if self.is_initialized():
            self.shutdown()

        self.clear_all()

    def run(self) -> None:
        if not self.is_ready():
            raise RuntimeError("MarketScanner is not ready.")

        self.start()

        while self.is_running():
            self.tick()

    def tick(self) -> None:
        if not self.is_ready():
            raise RuntimeError("MarketScanner is not ready.")

        elapsed = None

        if self.has_stopwatch():
            self._stopwatch.start()

        try:
            self.scan_once()
        finally:
            if self.has_stopwatch():
                elapsed = self._stopwatch.stop()

        if self.has_event_bus():
            self._event_bus.emit(
                "market_scanner.tick_completed",
                {"elapsed": elapsed},
            )

    def scan(self) -> None:
        if not self.is_ready():
            raise RuntimeError("MarketScanner is not ready.")

        self.scan_once()

    def scan_once(self) -> None:
        if not self.is_running():
            return

        symbols = self.fetch_symbols()
        eligible_symbols = self.filter_symbols(symbols)
        self._last_scan_result = eligible_symbols
        self.publish_scan_result(eligible_symbols)
        return eligible_symbols

    def publish_scan_result(self, symbols):
        if not self.has_event_bus():
            return

        self._event_bus.emit(
            "market_scanner.scan_completed",
            symbols,
        )


    def last_scan_result(self):
        return list(self._last_scan_result)

    def fetch_symbols(self):
        if self.has_retry_policy():
            return self._retry_policy.execute(
                self._exchange.fetch_symbols
            )

        return self._exchange.fetch_symbols()

    def filter_symbols(self, symbols):
        minimum_volume = self._config.minimum_volume_usd

        return [
            symbol
            for symbol in symbols
            if symbol["volume_24h"] >= minimum_volume
        ]

    def __repr__(self) -> str:
        return (
            f"MarketScanner("
            f"running={self._running}, "
            f"initialized={self._initialized}, "
            f"dependencies={self.configured_dependency_count()}"
            f")"
        )

    def __str__(self) -> str:
        state = "running" if self.is_running() else "stopped"
        return f"MarketScanner[{state}]"

    def __bool__(self) -> bool:
        return self._running

    def __len__(self) -> int:
        return self.configured_dependency_count()

    def __call__(self) -> None:
        self.tick()

    def has_exchange(self) -> bool:
        return self._exchange is not None

    def has_scheduler(self) -> bool:
        return self._scheduler is not None

    def has_event_bus(self) -> bool:
        return self._event_bus is not None

    def has_rate_limiter(self) -> bool:
        return self._rate_limiter is not None

    def has_retry_policy(self) -> bool:
        return self._retry_policy is not None

    def has_timeout(self) -> bool:
        return self._timeout is not None

    def has_timer(self) -> bool:
        return self._timer is not None

    def has_stopwatch(self) -> bool:
        return self._stopwatch is not None

    def has_config(self) -> bool:
        return self._config is not None

    def is_initialized(self) -> bool:
        return self._initialized

    def is_scanning(self) -> bool:
        return self._running

    def is_ready(self) -> bool:
        return (
            self.is_initialized()
            and self.has_exchange()
            and self.has_config()
        )

    def clear_exchange(self) -> None:
        self._exchange = None

    def clear_scheduler(self) -> None:
        self._scheduler = None

    def clear_event_bus(self) -> None:
        self._event_bus = None

    def clear_rate_limiter(self) -> None:
        self._rate_limiter = None

    def clear_retry_policy(self) -> None:
        self._retry_policy = None

    def clear_timeout(self) -> None:
        self._timeout = None

    def clear_timer(self) -> None:
        self._timer = None

    def clear_stopwatch(self) -> None:
        self._stopwatch = None

    def clear_config(self) -> None:
        self._config = None

    def clear_all(self) -> None:
        self.stop()
        self._initialized = False

        for name in self._DEPENDENCY_NAMES:
            setattr(self, f"_{name}", None)

    def is_empty(self) -> bool:
        return (
            not self.has_exchange()
            and not self.has_scheduler()
            and not self.has_event_bus()
            and not self.has_rate_limiter()
            and not self.has_retry_policy()
            and not self.has_timeout()
            and not self.has_timer()
            and not self.has_stopwatch()
            and not self.has_config()
        )

    def dependencies(self) -> dict:
        return {
            name: getattr(self, f"_{name}")
            for name in self._DEPENDENCY_NAMES
        }

    def _validate_dependency_name(self, name: str) -> None:
        if name not in self._DEPENDENCY_NAMES:
            raise KeyError(name)

    def dependency_count(self) -> int:
        return sum(value is not None for value in self.dependencies().values())

    def has_dependencies(self) -> bool:
        return self.dependency_count() > 0

    def missing_dependencies(self) -> list[str]:
        return [
            name
            for name, value in self.dependencies().items()
            if value is None
        ]

    def is_fully_configured(self) -> bool:
        return not self.missing_dependencies()

    def configured_dependencies(self) -> list[str]:
        return [
            name
            for name, value in self.dependencies().items()
            if value is not None
        ]

    def dependency_names(self) -> list[str]:
        return list(self.dependencies().keys())

    def get_dependency(self, name: str):
        self._validate_dependency_name(name)
        return getattr(self, f"_{name}")

    def set_dependency(self, name: str, value) -> None:
        self._validate_dependency_name(name)
        setattr(self, f"_{name}", value)

    def clear_dependency(self, name: str) -> None:
        self._validate_dependency_name(name)
        setattr(self, f"_{name}", None)

    def has_dependency(self, name: str) -> bool:
        self._validate_dependency_name(name)
        return getattr(self, f"_{name}") is not None

    def dependency_items(self):
        return self.dependencies().items()

    def dependency_values(self):
        return self.dependencies().values()

    def iter_dependencies(self):
        yield from self.dependencies().items()

    def configured_dependency_count(self) -> int:
        return len(self.configured_dependencies())
