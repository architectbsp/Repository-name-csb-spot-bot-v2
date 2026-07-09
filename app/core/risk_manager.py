class RiskManager:
    _DEPENDENCY_NAMES = (
        "exchange",
        "exchange_manager",
        "scheduler",
        "event_bus",
        "rate_limiter",
        "retry_policy",
        "timeout",
        "timer",
        "stopwatch",
        "position_manager",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False

        self._exchange = None
        self._exchange_manager = None
        self._scheduler = None
        self._event_bus = None
        self._rate_limiter = None
        self._retry_policy = None
        self._timeout = None
        self._timer = None
        self._stopwatch = None
        self._position_manager = None
        self._config = None

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False

    def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("RiskManager is not initialized.")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running

    def set_exchange(self, exchange):
        self._exchange = exchange

    def set_exchange_manager(self, exchange_manager):
        self._exchange_manager = exchange_manager

    def set_scheduler(self, scheduler):
        self._scheduler = scheduler

    def set_event_bus(self, event_bus):
        self._event_bus = event_bus

    def set_rate_limiter(self, rate_limiter):
        self._rate_limiter = rate_limiter

    def set_retry_policy(self, retry_policy):
        self._retry_policy = retry_policy

    def set_timeout(self, timeout):
        self._timeout = timeout

    def set_timer(self, timer):
        self._timer = timer

    def set_stopwatch(self, stopwatch):
        self._stopwatch = stopwatch

    def set_position_manager(self, position_manager):
        self._position_manager = position_manager

    def set_config(self, config):
        self._config = config

    @property
    def _risk(self):
        if self._config is None:
            raise RuntimeError("RiskManager config dependency is not set.")
        return self._config.risk

    def calculate_position_size(self, balance: float) -> float:
        if balance <= 0:
            return 0.0
        return balance * (self._risk.capital_per_trade_percent / 100.0)

    def has_sufficient_balance(self, balance: float) -> bool:
        return self.calculate_position_size(balance) > 0.0

    def is_daily_loss_limit_reached(self, daily_loss_percent: float) -> bool:
        return daily_loss_percent >= self._risk.max_daily_loss_percent

    def can_open_trade(
        self,
        *,
        balance: float,
        daily_loss_percent: float,
        open_positions: int,
    ) -> bool:
        if self.is_daily_loss_limit_reached(daily_loss_percent):
            return False

        if open_positions >= self._risk.max_open_positions:
            return False

        if not self.has_sufficient_balance(balance):
            return False

        return True


    def on_price_tick(
        self,
        ticker: dict,
    ) -> None:
        symbol = ticker["symbol"]

        position = self._position_manager.get(symbol)

        if position is None:
            return

        self.update_position(position, ticker)

    def update_position(
        self,
        position,
        ticker: dict,
    ) -> None:
        self.check_break_even(position, ticker)
        self.check_trailing(position, ticker)
        self.check_stop_loss(position, ticker)

    def check_stop_loss(self, position, ticker) -> None:
        if position.stop_price is None:
            return

        last_price = ticker["last_price"]

        if last_price > position.stop_price:
            return

        from decimal import Decimal

        from app.core.trading.models import (
            TradeRequest,
            TradeSide,
        )

        trade = TradeRequest(
            symbol=position.symbol,
            quantity=Decimal(str(position.quantity)),
            side=TradeSide.SELL,
        )

        result = self._exchange_manager.execute_trade(
            ticker["exchange"],
            trade,
        )

        if not result:
            return

        self._position_manager.close(
            position.symbol,
            exit_price=last_price,
            reason="STOP_LOSS",
        )

        if self._event_bus is not None:
            self._event_bus.publish(
                "position.closed",
                {
                    "symbol": position.symbol,
                    "reason": "STOP_LOSS",
                    "price": last_price,
                },
            )

    def check_break_even(self, position, ticker) -> None:
        activation = self._risk.break_even_activation_percent

        profit = (
            (ticker["last_price"] - position.entry_price)
            / position.entry_price
        ) * 100

        if profit < activation:
            return

        if position.stop_price is None:
            position.stop_price = position.entry_price
            return

        if position.stop_price < position.entry_price:
            position.stop_price = position.entry_price

    def check_trailing(self, position, ticker) -> None:
        activation = self._risk.trailing_activation_percent

        profit = (
            (ticker["last_price"] - position.entry_price)
            / position.entry_price
        ) * 100

        if profit < activation:
            return

        highest_price = max(
            ticker["last_price"],
            getattr(position, "highest_price", ticker["last_price"]),
        )

        position.highest_price = highest_price

        trailing_stop = highest_price * (
            1 - self._risk.trailing_percent / 100
        )

        if (
            position.stop_price is None
            or trailing_stop > position.stop_price
        ):
            position.stop_price = trailing_stop
