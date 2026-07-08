from copy import deepcopy
from datetime import datetime
from enum import StrEnum
from typing import Any


class WatchState(StrEnum):
    IDLE = "IDLE"
    WATCH_FALLING = "WATCH_FALLING"
    WATCH_RISING = "WATCH_RISING"
    BUY_PENDING = "BUY_PENDING"
    POSITION_OPEN = "POSITION_OPEN"
    BREAK_EVEN = "BREAK_EVEN"
    TRAILING_ACTIVE = "TRAILING_ACTIVE"
    POSITION_CLOSED = "POSITION_CLOSED"
    COOLDOWN = "COOLDOWN"


_ALLOWED_TRANSITIONS = {
    WatchState.IDLE: {WatchState.WATCH_FALLING, WatchState.WATCH_RISING},
    WatchState.WATCH_FALLING: {WatchState.WATCH_RISING},
    WatchState.WATCH_RISING: {WatchState.BUY_PENDING},
    WatchState.BUY_PENDING: {WatchState.POSITION_OPEN},
    WatchState.POSITION_OPEN: {WatchState.BREAK_EVEN, WatchState.POSITION_CLOSED},
    WatchState.BREAK_EVEN: {WatchState.TRAILING_ACTIVE, WatchState.POSITION_CLOSED},
    WatchState.TRAILING_ACTIVE: {WatchState.POSITION_CLOSED},
    WatchState.POSITION_CLOSED: {WatchState.COOLDOWN},
    WatchState.COOLDOWN: {WatchState.IDLE},
}


class WatchList:
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
        "strategy",
    )

    def __init__(self) -> None:
        self._coins: dict[str, dict[str, Any]] = {}
        self._initialized = False
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
        self._strategy = None

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

        now = datetime.utcnow()

        self._coins[symbol] = {
            "state": WatchState.IDLE,
            "lowest_price": None,
            "highest_price": None,
            "entry_price": None,
            "stop_price": None,
            "trailing_price": None,
            "cooldown_until": None,
            "created_at": now,
            "updated_at": now,
        }
        return True

    def get(self, symbol: str):
        coin = self._coins.get(symbol)
        return deepcopy(coin) if coin else None

    def get_state(self, symbol: str):
        if symbol not in self._coins:
            return None
        return self._coins[symbol]["state"]

    def can_transition(self, symbol: str, target: WatchState) -> bool:
        if symbol not in self._coins:
            return False

        current = self._coins[symbol]["state"]
        return target in _ALLOWED_TRANSITIONS[current]

    def transition(self, symbol: str, target: WatchState) -> bool:
        if not self.can_transition(symbol, target):
            return False

        self._coins[symbol]["state"] = target
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True


    def begin_falling_watch(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        if not self.transition(symbol, WatchState.WATCH_FALLING):
            return False

        coin = self._coins[symbol]
        coin["lowest_price"] = price
        coin["highest_price"] = price
        coin["updated_at"] = datetime.utcnow()

        return True

    def begin_rising_watch(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        if not self.transition(symbol, WatchState.WATCH_RISING):
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None:
            coin["lowest_price"] = price

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price

        coin["updated_at"] = datetime.utcnow()

        return True


    def record_falling_price(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        if self.get_state(symbol) != WatchState.WATCH_FALLING:
            return False

        coin = self._coins[symbol]

        if price < coin["lowest_price"]:
            coin["lowest_price"] = price

        coin["updated_at"] = datetime.utcnow()
        return True

    def record_rising_price(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        if self.get_state(symbol) != WatchState.WATCH_RISING:
            return False

        coin = self._coins[symbol]

        if price > coin["highest_price"]:
            coin["highest_price"] = price

        coin["updated_at"] = datetime.utcnow()
        return True


    def promote_to_buy_pending(
        self,
        symbol: str,
        entry_price: float,
    ) -> bool:
        if not self.transition(symbol, WatchState.BUY_PENDING):
            return False

        coin = self._coins[symbol]
        coin["entry_price"] = entry_price
        coin["updated_at"] = datetime.utcnow()

        return True


    def promote_to_position_open(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
    ) -> bool:
        if not self.transition(symbol, WatchState.POSITION_OPEN):
            return False

        coin = self._coins[symbol]
        coin["entry_price"] = entry_price
        coin["stop_price"] = stop_price
        coin["updated_at"] = datetime.utcnow()

        return True


    def activate_break_even(
        self,
        symbol: str,
    ) -> bool:
        if not self.transition(symbol, WatchState.BREAK_EVEN):
            return False

        coin = self._coins[symbol]
        coin["stop_price"] = coin["entry_price"]
        coin["updated_at"] = datetime.utcnow()

        return True


    def activate_trailing(
        self,
        symbol: str,
        highest_price: float,
        trailing_price: float,
    ) -> bool:
        if not self.transition(symbol, WatchState.TRAILING_ACTIVE):
            return False

        coin = self._coins[symbol]

        if (
            coin["highest_price"] is None
            or highest_price > coin["highest_price"]
        ):
            coin["highest_price"] = highest_price

        coin["trailing_price"] = trailing_price
        coin["updated_at"] = datetime.utcnow()

        return True


    def close_position(
        self,
        symbol: str,
    ) -> bool:
        if not self.transition(symbol, WatchState.POSITION_CLOSED):
            return False

        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True


    def enter_cooldown(
        self,
        symbol: str,
        cooldown_until: datetime,
    ) -> bool:
        if not self.transition(symbol, WatchState.COOLDOWN):
            return False

        coin = self._coins[symbol]
        coin["cooldown_until"] = cooldown_until
        coin["updated_at"] = datetime.utcnow()

        return True

    def finish_cooldown(
        self,
        symbol: str,
    ) -> bool:
        if not self.transition(symbol, WatchState.IDLE):
            return False

        coin = self._coins[symbol]
        coin["lowest_price"] = None
        coin["highest_price"] = None
        coin["entry_price"] = None
        coin["stop_price"] = None
        coin["trailing_price"] = None
        coin["cooldown_until"] = None
        coin["updated_at"] = datetime.utcnow()

        return True

    def update_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None or price < coin["lowest_price"]:
            coin["lowest_price"] = price

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price

        coin["updated_at"] = datetime.utcnow()
        return True


    def update_lowest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None or price < coin["lowest_price"]:
            coin["lowest_price"] = price
            coin["updated_at"] = datetime.utcnow()

        return True

    def update_highest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price
            coin["updated_at"] = datetime.utcnow()

        return True


    def set_entry_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["entry_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def set_stop_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["stop_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def set_trailing_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["trailing_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True


    def start_cooldown(
        self,
        symbol: str,
        cooldown_until: datetime,
    ) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]
        coin["cooldown_until"] = cooldown_until
        coin["updated_at"] = datetime.utcnow()

        return True

    def clear_cooldown(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]
        coin["cooldown_until"] = None
        coin["updated_at"] = datetime.utcnow()

        return True

    def is_in_cooldown(
        self,
        symbol: str,
        now: datetime,
    ) -> bool:
        if symbol not in self._coins:
            return False

        cooldown_until = self._coins[symbol]["cooldown_until"]

        if cooldown_until is None:
            return False

        return now < cooldown_until


    def cooldown_expired(
        self,
        symbol: str,
        now: datetime,
    ) -> bool:
        if symbol not in self._coins:
            return False

        cooldown_until = self._coins[symbol]["cooldown_until"]

        if cooldown_until is None:
            return True

        return now >= cooldown_until

    def remaining_cooldown(
        self,
        symbol: str,
        now: datetime,
    ):
        if symbol not in self._coins:
            return None

        cooldown_until = self._coins[symbol]["cooldown_until"]

        if cooldown_until is None:
            return None

        remaining = cooldown_until - now

        if remaining.total_seconds() <= 0:
            return None

        return remaining


    def set_lowest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["lowest_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def set_highest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["highest_price"] = price
        self._coins[symbol]["updated_at"] = datetime.utcnow()
        return True

    def clear_price_tracking(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]
        coin["lowest_price"] = None
        coin["highest_price"] = None
        coin["updated_at"] = datetime.utcnow()

        return True

    def reset(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        created_at = self._coins[symbol]["created_at"]
        now = datetime.utcnow()

        self._coins[symbol] = {
            "state": WatchState.IDLE,
            "lowest_price": None,
            "highest_price": None,
            "entry_price": None,
            "stop_price": None,
            "trailing_price": None,
            "cooldown_until": None,
            "created_at": created_at,
            "updated_at": now,
        }
        return True


    def handle_scan_result(self, symbols) -> int:
        added = 0

        now = datetime.utcnow()

        for ticker in symbols:
            if not ticker.symbol:
                continue

            created = False

            if not self.contains(ticker.symbol):
                created = self.add(ticker.symbol)

            elif self.get_state(ticker.symbol) == WatchState.COOLDOWN:
                if self.cooldown_expired(
                    ticker.symbol,
                    now,
                ):
                    self.finish_cooldown(
                        ticker.symbol,
                    )
                else:
                    continue

            if self.has_strategy():
                self._strategy.on_ticker(
                    self,
                    ticker,
                )

            if created:
                added += 1

        return added

    def remove(self, symbol: str) -> bool:
        return self._coins.pop(symbol, None) is not None

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


    def set_exchange(self, exchange):
        self._exchange = exchange

    def get_exchange(self):
        return self._exchange

    def has_exchange(self):
        return self._exchange is not None

    def clear_exchange(self):
        self._exchange = None

    def set_scheduler(self, scheduler):
        self._scheduler = scheduler

    def get_scheduler(self):
        return self._scheduler

    def has_scheduler(self):
        return self._scheduler is not None

    def clear_scheduler(self):
        self._scheduler = None

    def set_event_bus(self, event_bus):
        self._event_bus = event_bus

    def get_event_bus(self):
        return self._event_bus

    def has_event_bus(self):
        return self._event_bus is not None

    def clear_event_bus(self):
        self._event_bus = None

    def set_rate_limiter(self, rate_limiter):
        self._rate_limiter = rate_limiter

    def get_rate_limiter(self):
        return self._rate_limiter

    def has_rate_limiter(self):
        return self._rate_limiter is not None

    def clear_rate_limiter(self):
        self._rate_limiter = None

    def set_retry_policy(self, retry_policy):
        self._retry_policy = retry_policy

    def get_retry_policy(self):
        return self._retry_policy

    def has_retry_policy(self):
        return self._retry_policy is not None

    def clear_retry_policy(self):
        self._retry_policy = None

    def set_timeout(self, timeout):
        self._timeout = timeout

    def get_timeout(self):
        return self._timeout

    def has_timeout(self):
        return self._timeout is not None

    def clear_timeout(self):
        self._timeout = None

    def set_timer(self, timer):
        self._timer = timer

    def get_timer(self):
        return self._timer

    def has_timer(self):
        return self._timer is not None

    def clear_timer(self):
        self._timer = None

    def set_stopwatch(self, stopwatch):
        self._stopwatch = stopwatch

    def get_stopwatch(self):
        return self._stopwatch

    def has_stopwatch(self):
        return self._stopwatch is not None

    def clear_stopwatch(self):
        self._stopwatch = None


    def set_strategy(self, strategy):
        self._strategy = strategy

    def get_strategy(self):
        return self._strategy

    def has_strategy(self):
        return self._strategy is not None

    def clear_strategy(self):
        self._strategy = None

    def set_config(self, config):
        self._config = config

    def get_config(self):
        return self._config

    def has_config(self):
        return self._config is not None

    def clear_config(self):
        self._config = None

    def dependencies(self):
        return {
            name: getattr(self, f"_{name}")
            for name in self._DEPENDENCY_NAMES
        }

    def dependency_count(self):
        return sum(
            value is not None
            for value in self.dependencies().values()
        )

    def configured_dependencies(self):
        return [
            name
            for name, value in self.dependencies().items()
            if value is not None
        ]

    def configured_dependency_count(self):
        return len(self.configured_dependencies())
