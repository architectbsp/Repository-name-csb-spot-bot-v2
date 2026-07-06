class Strategy:
    _DEPENDENCY_NAMES = (
        "risk_manager",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False

        self._risk_manager = None
        self._config = None

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False

    def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("Strategy is not initialized.")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def set_risk_manager(self, risk_manager) -> None:
        self._risk_manager = risk_manager

    def set_config(self, config) -> None:
        self._config = config

    def should_buy(self, price: float) -> bool:
        return price > 42000

    def should_sell(self, price: float) -> bool:
        return price < 42000
