from copy import deepcopy
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import functools
import logging
import threading
from typing import Any, Callable, TypeVar

from app.core.exchange.market_key import (
    exchange_name,
    market_key,
    parse_market_key,
    try_parse_exchange_type,
)
from app.core.scheduler.job import Job


logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


def _coins_locked(fn: _F) -> _F:
    """R1: serialize ``_coins`` access. Nested calls re-enter via RLock."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


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
    WatchState.BUY_PENDING: {WatchState.WATCH_RISING, WatchState.POSITION_OPEN},
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

    _COOLDOWN_JOB_NAME = "watch_list_cooldown"
    _COOLDOWN_CHECK_INTERVAL_SECONDS = 60
    _DEFAULT_COOLDOWN_HOURS = 4.0

    def __init__(self) -> None:
        self._coins: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
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
        self._telemetry = None

    def set_telemetry(self, telemetry) -> None:
        """Optional TelemetryService -- records scan→strategy pipeline ms."""
        self._telemetry = telemetry

    def initialize(self) -> None:
        with self._lock:
            self._initialized = True

        if self.has_scheduler() and not self._scheduler.has_job(
            self._COOLDOWN_JOB_NAME,
        ):
            job = Job(
                name=self._COOLDOWN_JOB_NAME,
                interval=self._COOLDOWN_CHECK_INTERVAL_SECONDS,
                callback=self.process_cooldowns,
            )
            self._scheduler.register(job)
            self._scheduler.schedule(job)

    def shutdown(self) -> None:
        with self._lock:
            self._running = False
            self._initialized = False
            self._coins.clear()

    def start(self) -> None:
        with self._lock:
            if not self._initialized:
                raise RuntimeError("WatchList is not initialized.")
            self._running = True

    def stop(self) -> None:
        with self._lock:
            self._running = False

    @_coins_locked
    def _normalize_key(self, symbol: str, exchange=None) -> str:
        """Sprint 18: resolve the dict key for a coin. Prefer an explicit
        exchange; otherwise accept an already-composed market_key, or
        fall back to the bare symbol (legacy single-exchange tests).

        When a market_key / (exchange, symbol) pair is requested but the
        coin was stored under the bare symbol (older tests / pre-tag
        rows), resolve to that bare key so Strategy ticks still match.
        """
        if exchange is not None:
            key = market_key(exchange, symbol)
            if key in self._coins:
                return key
            raw = symbol
            if ":" in symbol:
                try:
                    _, raw = parse_market_key(symbol)
                except ValueError:
                    raw = symbol
            if raw in self._coins:
                coin_ex = self._coins[raw].get("exchange")
                if coin_ex is None or exchange_name(coin_ex) == exchange_name(
                    exchange
                ):
                    return raw
            return key

        if ":" in symbol:
            try:
                parse_market_key(symbol)
            except ValueError:
                return symbol
            if symbol in self._coins:
                return symbol
            _, raw = parse_market_key(symbol)
            if raw in self._coins:
                return raw
            return symbol

        return symbol


    def add(self, symbol: str, exchange=None) -> bool:
        # Membership check + insert under one critical section (TOCTOU).
        # Exchange stream I/O stays outside the lock.
        now = datetime.now(UTC)

        with self._lock:
            key = self._normalize_key(symbol, exchange)

            if key in self._coins:
                return False

            if exchange is not None:
                raw_symbol = symbol
                exchange_value = exchange
            elif ":" in key:
                try:
                    ex_name, raw_symbol = parse_market_key(key)
                    exchange_value = try_parse_exchange_type(ex_name)
                except ValueError:
                    raw_symbol = symbol
                    exchange_value = None
            else:
                raw_symbol = symbol
                exchange_value = None

            self._coins[key] = {
                "state": WatchState.IDLE,
                "symbol": raw_symbol,
                "exchange": exchange_value,
                "lowest_price": None,
                "highest_price": None,
                "entry_price": None,
                "stop_price": None,
                "trailing_price": None,
                "cooldown_until": None,
                "created_at": now,
                "updated_at": now,
                # Sprint 5 -- Trade Journal: which entry path this watch cycle
                # is on, when it started, and how many new highs/lows were
                # recorded while watching. Reset every time a coin starts a
                # fresh watch cycle (begin_falling_watch / Path A's
                # begin_rising_watch / finish_cooldown).
                "watch_started_at": None,
                "entry_path": None,
                "rise_count": 0,
                "fall_count": 0,
            }

        self.sync_price_stream()
        return True



    def get_symbols(self) -> list[str]:
        """Raw trade symbols (not market keys) across every coin."""
        symbols: set[str] = set()
        with self._lock:
            for key, coin in self._coins.items():
                symbol = coin.get("symbol")
                if not symbol:
                    if ":" in key:
                        try:
                            _, symbol = parse_market_key(key)
                        except ValueError:
                            symbol = key
                    else:
                        symbol = key
                symbols.add(symbol)
        return sorted(symbols)

    def symbols_by_exchange(self) -> dict:
        """Sprint 18: {ExchangeType: [symbol, ...]} for per-venue WS sync."""
        grouped: dict = {}
        with self._lock:
            for key, coin in self._coins.items():
                exchange = coin.get("exchange")
                symbol = coin.get("symbol")
                if exchange is None and ":" in key:
                    ex_name, symbol = parse_market_key(key)
                    exchange = try_parse_exchange_type(ex_name)
                if exchange is None or not symbol:
                    continue
                grouped.setdefault(exchange, []).append(symbol)
        for exchange in grouped:
            grouped[exchange] = sorted(set(grouped[exchange]))
        return grouped

    def list_by_states(
        self,
        states: set[WatchState] | frozenset[WatchState],
    ) -> list[tuple[str, dict[str, Any]]]:
        """
        Sprint 12 -- Live Dashboard: returns a deep-copied snapshot of
        every coin currently in one of `states`, sorted by key. Each
        coin dict includes `symbol` + `exchange` for multi-venue UI.
        """
        with self._lock:
            return [
                (key, deepcopy(coin))
                for key, coin in sorted(self._coins.items())
                if coin["state"] in states
            ]

    def sync_price_stream(self) -> None:
        if self._exchange is None:
            return

        # Sprint 18: each venue gets only its own watch symbols
        # (isolation rule -- never subscribe Binance symbols on Bybit).
        grouped = self.symbols_by_exchange()

        if grouped:
            for exchange_type, symbols in grouped.items():
                self._exchange.update_price_stream(exchange_type, symbols)
            return

        # Legacy fallback when coins have no exchange tag yet.
        try:
            active_exchange_type = self._exchange.active_exchange_type()
        except RuntimeError:
            return

        with self._lock:
            symbols = sorted(self._coins.keys())

        self._exchange.update_price_stream(active_exchange_type, symbols)

    @_coins_locked
    def get(self, symbol: str, exchange=None):
        key = self._normalize_key(symbol, exchange)
        coin = self._coins.get(key)
        return deepcopy(coin) if coin else None

    @_coins_locked
    def get_state(self, symbol: str, exchange=None):
        key = self._normalize_key(symbol, exchange)
        if key not in self._coins:
            return None
        return self._coins[key]["state"]

    @_coins_locked
    def can_transition(self, symbol: str, target: WatchState) -> bool:
        key = self._normalize_key(symbol)
        if key not in self._coins:
            return False

        current = self._coins[key]["state"]
        return target in _ALLOWED_TRANSITIONS[current]

    @_coins_locked
    def transition(self, symbol: str, target: WatchState) -> bool:
        key = self._normalize_key(symbol)
        if not self.can_transition(key, target):
            return False

        self._coins[key]["state"] = target
        self._coins[key]["updated_at"] = datetime.now(UTC)
        return True


    @_coins_locked
    def begin_falling_watch(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.WATCH_FALLING):
            return False

        coin = self._coins[symbol]
        coin["lowest_price"] = price
        coin["highest_price"] = price
        coin["updated_at"] = datetime.now(UTC)

        # Sprint 5 -- Trade Journal: WATCH_FALLING is only ever reached
        # from IDLE (see _ALLOWED_TRANSITIONS), so this always marks the
        # start of a fresh Path B (dip-then-recovery) watch cycle.
        coin["entry_path"] = "PATH_B_DIP_RECOVERY"
        coin["watch_started_at"] = datetime.now(UTC)
        coin["rise_count"] = 0
        coin["fall_count"] = 0

        return True

    @_coins_locked
    def begin_rising_watch(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if symbol not in self._coins:
            return False

        # Captured before transition() overwrites "state" -- this is the
        # only way to tell whether this call is Path A (direct rise from
        # IDLE, no prior dip) or the continuation of Path B (arriving
        # here from WATCH_FALLING after a dip already being tracked).
        previous_state = self._coins[symbol]["state"]

        if not self.transition(symbol, WatchState.WATCH_RISING):
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None:
            coin["lowest_price"] = price

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price

        if previous_state == WatchState.IDLE:
            # Sprint 5 -- Trade Journal: Path A -- the coin never dipped,
            # so this call IS the start of the watch cycle.
            coin["entry_path"] = "PATH_A_DIRECT_RISE"
            coin["watch_started_at"] = datetime.now(UTC)
            coin["rise_count"] = 0
            coin["fall_count"] = 0

        coin["updated_at"] = datetime.now(UTC)

        return True


    @_coins_locked
    def record_falling_price(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if self.get_state(symbol) != WatchState.WATCH_FALLING:
            return False

        coin = self._coins[symbol]

        if price < coin["lowest_price"]:
            coin["lowest_price"] = price
            # Sprint 5 -- Trade Journal: counts how many times the dip
            # deepened while watching, for the Trade Journal's "kaç kere
            # düştü" field.
            coin["fall_count"] = coin.get("fall_count", 0) + 1

        coin["updated_at"] = datetime.now(UTC)
        return True

    @_coins_locked
    def record_rising_price(
        self,
        symbol: str,
        price: float,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if self.get_state(symbol) != WatchState.WATCH_RISING:
            return False

        coin = self._coins[symbol]

        if price > coin["highest_price"]:
            coin["highest_price"] = price
            # Sprint 5 -- Trade Journal: counts how many times a new high
            # was recorded while watching, for the Trade Journal's "kaç
            # defa yükseldi" field.
            coin["rise_count"] = coin.get("rise_count", 0) + 1

        coin["updated_at"] = datetime.now(UTC)
        return True


    @_coins_locked
    def promote_to_buy_pending(
        self,
        symbol: str,
        entry_price: float,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.BUY_PENDING):
            return False

        coin = self._coins[symbol]
        coin["entry_price"] = entry_price
        coin["updated_at"] = datetime.now(UTC)

        return True


    @_coins_locked
    def promote_to_position_open(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.POSITION_OPEN):
            return False

        coin = self._coins[symbol]
        coin["entry_price"] = entry_price
        coin["stop_price"] = stop_price
        coin["updated_at"] = datetime.now(UTC)

        return True

    @_coins_locked
    def cancel_buy_pending(self, symbol: str) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.WATCH_RISING):
            return False

        coin = self._coins[symbol]
        coin["entry_price"] = None
        coin["updated_at"] = datetime.now(UTC)
        return True


    @_coins_locked
    def activate_break_even(
        self,
        symbol: str,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.BREAK_EVEN):
            return False

        coin = self._coins[symbol]
        coin["stop_price"] = coin["entry_price"]
        coin["updated_at"] = datetime.now(UTC)

        return True


    @_coins_locked
    def activate_trailing(
        self,
        symbol: str,
        highest_price: float,
        trailing_price: float,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.TRAILING_ACTIVE):
            return False

        coin = self._coins[symbol]

        if (
            coin["highest_price"] is None
            or highest_price > coin["highest_price"]
        ):
            coin["highest_price"] = highest_price

        coin["trailing_price"] = trailing_price
        coin["updated_at"] = datetime.now(UTC)

        return True


    @_coins_locked
    def close_position(
        self,
        symbol: str,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.POSITION_CLOSED):
            return False

        self._coins[symbol]["updated_at"] = datetime.now(UTC)
        return True


    @_coins_locked
    def enter_cooldown(
        self,
        symbol: str,
        cooldown_until: datetime,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.COOLDOWN):
            return False

        coin = self._coins[symbol]
        coin["cooldown_until"] = cooldown_until
        coin["updated_at"] = datetime.now(UTC)

        return True

    @_coins_locked
    def finish_cooldown(
        self,
        symbol: str,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if not self.transition(symbol, WatchState.IDLE):
            return False

        coin = self._coins[symbol]
        coin["lowest_price"] = None
        coin["highest_price"] = None
        coin["entry_price"] = None
        coin["stop_price"] = None
        coin["trailing_price"] = None
        coin["cooldown_until"] = None
        coin["watch_started_at"] = None
        coin["entry_path"] = None
        coin["rise_count"] = 0
        coin["fall_count"] = 0
        coin["updated_at"] = datetime.now(UTC)

        return True

    @_coins_locked
    def update_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None or price < coin["lowest_price"]:
            coin["lowest_price"] = price

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price

        coin["updated_at"] = datetime.now(UTC)
        return True


    @_coins_locked
    def update_lowest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["lowest_price"] is None or price < coin["lowest_price"]:
            coin["lowest_price"] = price
            coin["updated_at"] = datetime.now(UTC)

        return True

    @_coins_locked
    def update_highest_price(self, symbol: str, price: float) -> bool:
        symbol = self._normalize_key(symbol)
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]

        if coin["highest_price"] is None or price > coin["highest_price"]:
            coin["highest_price"] = price
            coin["updated_at"] = datetime.now(UTC)

        return True


    @_coins_locked
    def set_entry_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["entry_price"] = price
        self._coins[symbol]["updated_at"] = datetime.now(UTC)
        return True

    @_coins_locked
    def set_stop_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["stop_price"] = price
        self._coins[symbol]["updated_at"] = datetime.now(UTC)
        return True

    @_coins_locked
    def set_trailing_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["trailing_price"] = price
        self._coins[symbol]["updated_at"] = datetime.now(UTC)
        return True


    @_coins_locked
    def start_cooldown(
        self,
        symbol: str,
        cooldown_until: datetime,
    ) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]
        coin["cooldown_until"] = cooldown_until
        coin["updated_at"] = datetime.now(UTC)

        return True

    @_coins_locked
    def clear_cooldown(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]
        coin["cooldown_until"] = None
        coin["updated_at"] = datetime.now(UTC)

        return True

    @_coins_locked
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


    @_coins_locked
    def cooldown_expired(
        self,
        symbol: str,
        now: datetime,
    ) -> bool:
        symbol = self._normalize_key(symbol)
        if symbol not in self._coins:
            return False

        cooldown_until = self._coins[symbol]["cooldown_until"]

        if cooldown_until is None:
            return True

        return now >= cooldown_until

    @_coins_locked
    def remaining_cooldown(
        self,
        symbol: str,
        now: datetime,
    ):
        symbol = self._normalize_key(symbol)
        if symbol not in self._coins:
            return None

        cooldown_until = self._coins[symbol]["cooldown_until"]

        if cooldown_until is None:
            return None

        remaining = cooldown_until - now

        if remaining.total_seconds() <= 0:
            return None

        return remaining


    @_coins_locked
    def set_lowest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["lowest_price"] = price
        self._coins[symbol]["updated_at"] = datetime.now(UTC)
        return True

    @_coins_locked
    def set_highest_price(self, symbol: str, price: float) -> bool:
        if symbol not in self._coins:
            return False

        self._coins[symbol]["highest_price"] = price
        self._coins[symbol]["updated_at"] = datetime.now(UTC)
        return True

    @_coins_locked
    def clear_price_tracking(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        coin = self._coins[symbol]
        coin["lowest_price"] = None
        coin["highest_price"] = None
        coin["updated_at"] = datetime.now(UTC)

        return True

    @_coins_locked
    def reset(self, symbol: str) -> bool:
        if symbol not in self._coins:
            return False

        previous = self._coins[symbol]
        created_at = previous["created_at"]
        now = datetime.now(UTC)

        self._coins[symbol] = {
            "state": WatchState.IDLE,
            "symbol": previous.get("symbol"),
            "exchange": previous.get("exchange"),
            "lowest_price": None,
            "highest_price": None,
            "entry_price": None,
            "stop_price": None,
            "trailing_price": None,
            "cooldown_until": None,
            "created_at": created_at,
            "updated_at": now,
            "watch_started_at": None,
            "entry_path": None,
            "rise_count": 0,
            "fall_count": 0,
        }
        return True




    @_coins_locked
    def handle_position_closed(
        self,
        event: dict,
    ) -> None:
        symbol = event["symbol"]
        exchange = event.get("exchange")
        if exchange is None:
            position = event.get("position")
            if position is not None:
                exchange = getattr(position, "exchange", None)

        key = self._normalize_key(symbol, exchange)

        if key not in self._coins:
            return

        if not self.close_position(key):
            return

        cooldown_until = datetime.now(UTC) + timedelta(
            hours=self._cooldown_hours(),
        )

        self.enter_cooldown(key, cooldown_until)

    def _cooldown_hours(self) -> float:
        if self._config is None:
            return self._DEFAULT_COOLDOWN_HOURS

        risk_config = getattr(self._config, "risk", self._config)

        return float(
            getattr(
                risk_config,
                "cooldown_hours",
                self._DEFAULT_COOLDOWN_HOURS,
            )
        )

    def process_cooldowns(self, now: datetime | None = None) -> int:
        """
        Transitions every coin whose cooldown period has expired back to
        IDLE. Registered as a periodic scheduler job so a coin becomes
        eligible for trading again exactly when its cooldown ends, instead
        of only lazily on the next market scan.
        """
        now = now or datetime.now(UTC)

        with self._lock:
            symbols_in_cooldown = [
                symbol
                for symbol, coin in self._coins.items()
                if coin["state"] == WatchState.COOLDOWN
            ]

        finished = 0

        for symbol in symbols_in_cooldown:
            if not self.cooldown_expired(symbol, now):
                continue

            if self.finish_cooldown(symbol):
                finished += 1

        return finished

    def handle_price_update(self, ticker) -> None:
        key = self._normalize_key(ticker.symbol, getattr(ticker, "exchange", None))

        if not self.contains(key):
            return

        if self.has_strategy():
            self._strategy.on_ticker(
                self,
                ticker,
            )

    def handle_scan_result(self, symbols) -> int:
        import time

        started = time.perf_counter()
        added = 0

        now = datetime.now(UTC)

        for ticker in symbols:
            if not ticker.symbol:
                continue

            exchange = getattr(ticker, "exchange", None)
            key = self._normalize_key(ticker.symbol, exchange)
            created = False

            if not self.contains(key):
                created = self.add(ticker.symbol, exchange=exchange)

            elif self.get_state(key) == WatchState.COOLDOWN:
                if self.cooldown_expired(key, now):
                    self.finish_cooldown(key)
                else:
                    continue

            if self.has_strategy():
                self._strategy.on_ticker(
                    self,
                    ticker,
                )

            if created:
                added += 1

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        telemetry = getattr(self, "_telemetry", None)
        if telemetry is not None:
            try:
                telemetry.record_pipeline_ms(elapsed_ms)
            except Exception:
                logger.debug(
                    "[WatchList] telemetry.record_pipeline_ms failed",
                    exc_info=True,
                )

        logger.info(
            "[WatchList] added=%d total=%d",
            added,
            self.size(),
        )

        return added

    @_coins_locked
    def remove(self, symbol: str, exchange=None) -> bool:
        key = self._normalize_key(symbol, exchange)
        return self._coins.pop(key, None) is not None

    @_coins_locked
    def contains(self, symbol: str, exchange=None) -> bool:
        key = self._normalize_key(symbol, exchange)
        return key in self._coins

    @_coins_locked
    def clear(self) -> None:
        self._coins.clear()

    @_coins_locked
    def size(self) -> int:
        return len(self._coins)

    @_coins_locked
    def is_initialized(self) -> bool:
        return self._initialized

    @_coins_locked
    def is_running(self) -> bool:
        return self._running

    @_coins_locked
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

    def on_config_updated(self, event) -> None:
        """
        EventBus ``config.updated`` -- cooldown / watch knobs are read
        live from ``self._config`` on each decision; no local cache.
        """
        return None

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
