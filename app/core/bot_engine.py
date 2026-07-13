from datetime import timedelta

from app.core.market_scanner import MarketScanner
from app.core.position_manager import PositionManager
from app.core.watch_list import WatchList
from app.core.risk_manager import RiskManager
from app.core.strategy import Strategy

from app.core.config.settings import AppSettings
from app.core.event_bus.event_bus import EventBus
from app.core.scheduler.scheduler import Scheduler
from app.core.retry_policy.retry_policy import RetryPolicy
from app.core.timeout.timeout import Timeout
from app.core.rate_limiter.rate_limiter import RateLimiter
from app.core.timer.timer import Timer
from app.core.stopwatch.stopwatch import Stopwatch
from app.core.exchange.binance import BinanceExchange
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeState, ExchangeType
from app.core.exchange.registry import ExchangeRegistry
from app.core.services.order_validator import OrderValidator
from app.core.persistence.service import PersistenceService
from app.core.worker import Worker


class BotEngine:
    def __init__(self):
        self.running = False

        self.config = AppSettings()
        self.event_bus = EventBus()
        self.scheduler = Scheduler()
        self.worker = Worker(self.scheduler)
        self.retry_policy = RetryPolicy(
            self.config.retry_policy.max_attempts,
            self.config.retry_policy.delay,
        )
        self.timeout = Timeout(
            self.config.timeout.seconds,
        )
        self.rate_limiter = RateLimiter(
            self.config.rate_limiter.max_requests,
            self.config.rate_limiter.period,
        )
        self.timer = Timer(
            timedelta(seconds=self.config.timer.duration_seconds)
        )
        self.stopwatch = Stopwatch()
        self.exchange_registry = ExchangeRegistry()

        self.exchange_registry.register(
            ExchangeType.BINANCE,
            BinanceExchange(
                ExchangeState(
                    exchange=ExchangeType.BINANCE,
                    enabled=True,
                ),
                self.config.exchange,
            ),
        )

        self.exchange = ExchangeManager(self.exchange_registry)
        self.order_validator = OrderValidator(self.exchange)

        self.persistence = PersistenceService()

        self.market_scanner = MarketScanner()
        self.market_scanner.set_exchange(self.exchange)
        self.market_scanner.set_scheduler(self.scheduler)
        self.market_scanner.set_event_bus(self.event_bus)
        self.market_scanner.set_rate_limiter(self.rate_limiter)
        self.market_scanner.set_retry_policy(self.retry_policy)
        self.market_scanner.set_timeout(self.timeout)
        self.market_scanner.set_timer(self.timer)
        self.market_scanner.set_stopwatch(self.stopwatch)

        self.watch_list = WatchList()
        self.watch_list.set_exchange(self.exchange)
        self.watch_list.set_scheduler(self.scheduler)
        self.watch_list.set_event_bus(self.event_bus)
        self.watch_list.set_rate_limiter(self.rate_limiter)
        self.watch_list.set_retry_policy(self.retry_policy)
        self.watch_list.set_timeout(self.timeout)
        self.watch_list.set_timer(self.timer)
        self.watch_list.set_stopwatch(self.stopwatch)

        self.position_manager = PositionManager()
        self.position_manager.set_repository(
            self.persistence.position_repository(),
        )

        self.risk_manager = RiskManager()
        self.risk_manager.set_exchange(self.exchange)
        self.risk_manager.set_exchange_manager(
            self.exchange,
        )
        self.risk_manager.set_scheduler(self.scheduler)
        self.risk_manager.set_event_bus(self.event_bus)
        self.risk_manager.set_rate_limiter(self.rate_limiter)
        self.risk_manager.set_retry_policy(self.retry_policy)
        self.risk_manager.set_timeout(self.timeout)
        self.risk_manager.set_timer(self.timer)
        self.risk_manager.set_stopwatch(self.stopwatch)
        self.risk_manager.set_position_manager(
            self.position_manager,
        )

        self.strategy = Strategy()
        self.strategy.set_risk_manager(self.risk_manager)
        self.strategy.set_position_manager(self.position_manager)
        self.strategy.set_exchange_manager(self.exchange)
        self.strategy.set_order_validator(self.order_validator)

        self.watch_list.set_strategy(self.strategy)

    def start_price_stream(self) -> None:
        self.exchange.start_price_stream(
            self.exchange.enabled()[0].state.exchange,
            self.watch_list.get_symbols(),
            self.event_bus.publish,
        )

    def stop_price_stream(self) -> None:
        self.exchange.stop_price_stream(
            self.exchange.enabled()[0].state.exchange,
        )

    def initialize(self):
        for module in (
            self.market_scanner,
            self.watch_list,
            self.risk_manager,
            self.strategy,
        ):
            module.set_config(self.config)

        self.event_bus.subscribe(
            "market_scanner.scan_completed",
            self.watch_list.handle_scan_result,
        )

        self.event_bus.subscribe(
            "ticker.updated",
            self.watch_list.handle_price_update,
        )

        self.event_bus.subscribe(
            "ticker.updated",
            self.risk_manager.on_price_tick,
        )

        self.event_bus.subscribe(
            "position.closed",
            self.watch_list.handle_position_closed,
        )

        self.event_bus.subscribe(
            "position.closed",
            self.position_manager.handle_position_closed,
        )

        for module in (
            self.market_scanner,
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.initialize()

        for position in self.persistence.load_positions():
            self.position_manager.restore(position)

    def shutdown(self):
        for module in (
            self.market_scanner,
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.shutdown()

    def start(self):
        self.initialize()

        for module in (
            self.market_scanner,
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.start()

        self.scheduler.start()
        self.worker.start()
        self.exchange.start()

        self.market_scanner.scan_once()

        self.start_price_stream()

        self.running = True
        print("Bot started")

    def stop(self):
        if not self.running:
            return

        self.running = False

        for module in (
            self.market_scanner,
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.stop()

        self.worker.stop()
        self.scheduler.stop()
        self.stop_price_stream()
        self.exchange.stop()

        self.shutdown()

        print("Bot stopped")
