from app.core.market_scanner import MarketScanner
from app.core.position_manager import PositionManager
from app.core.watch_list import WatchList

from app.core.config.settings import Settings
from app.core.event_bus.event_bus import EventBus
from app.core.scheduler.scheduler import Scheduler
from app.core.retry_policy.retry_policy import RetryPolicy
from app.core.timeout.timeout import Timeout
from app.core.rate_limiter.rate_limiter import RateLimiter
from app.core.timer.timer import Timer
from app.core.stopwatch.stopwatch import Stopwatch


class BotEngine:
    def __init__(self):
        self.running = False

        self.config = Settings()
        self.event_bus = EventBus()
        self.scheduler = Scheduler()
        self.retry_policy = RetryPolicy()
        self.timeout = Timeout()
        self.rate_limiter = RateLimiter()
        self.timer = Timer()
        self.stopwatch = Stopwatch()

        self.market_scanner = MarketScanner()
        self.watch_list = WatchList()
        self.position_manager = PositionManager()

    def initialize(self):
        self.market_scanner.set_config(self.config)
        self.market_scanner.set_event_bus(self.event_bus)
        self.market_scanner.set_scheduler(self.scheduler)
        self.market_scanner.set_retry_policy(self.retry_policy)
        self.market_scanner.set_timeout(self.timeout)
        self.market_scanner.set_rate_limiter(self.rate_limiter)
        self.market_scanner.set_timer(self.timer)
        self.market_scanner.set_stopwatch(self.stopwatch)

        self.market_scanner.initialize()
        self.watch_list.initialize()
        self.position_manager.initialize()

    def shutdown(self):
        self.market_scanner.shutdown()
        self.watch_list.shutdown()
        self.position_manager.shutdown()

    def start(self):
        self.initialize()

        self.market_scanner.start()
        self.watch_list.start()
        self.position_manager.start()

        self.running = True
        print("Bot started")

    def stop(self):
        self.market_scanner.stop()
        self.watch_list.stop()
        self.position_manager.stop()

        self.shutdown()

        self.running = False
        print("Bot stopped")
