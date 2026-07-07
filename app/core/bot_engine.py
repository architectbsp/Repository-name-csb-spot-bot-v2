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
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.registry import ExchangeRegistry


class BotEngine:
    def __init__(self):
        self.running = False

        self.config = AppSettings()
        self.event_bus = EventBus()
        self.scheduler = Scheduler()
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
        self.exchange = ExchangeManager(self.exchange_registry)

        self.market_scanner = MarketScanner()
        self.watch_list = WatchList()
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager()
        self.strategy = Strategy()

    def initialize(self):
        for module in (
            self.market_scanner,
            self.watch_list,
            self.risk_manager,
            self.strategy,
        ):
            module.set_config(self.config)

        self.strategy.set_risk_manager(self.risk_manager)
        self.strategy.set_exchange_manager(self.exchange)
        self.watch_list.set_strategy(self.strategy)

        self.event_bus.subscribe(
            "market_scanner.scan_completed",
            self.watch_list.handle_scan_result,
        )

        for module in (
            self.market_scanner,
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.initialize()

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

        self.running = True
        print("Bot started")

    def stop(self):
        for module in (
            self.market_scanner,
            self.watch_list,
            self.position_manager,
            self.risk_manager,
            self.strategy,
        ):
            module.stop()

        self.shutdown()

        self.running = False
        print("Bot stopped")
