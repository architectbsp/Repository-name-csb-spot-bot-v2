import logging
from datetime import timedelta

from app.core.market_scanner import MarketScanner
from app.core.position_manager import PositionManager
from app.core.watch_list import WatchList
from app.core.risk_manager import RiskManager
from app.core.strategy import Strategy

from app.core.config.settings import AppSettings
from app.core.config.settings_store import SettingsStore
from app.core.event_bus.event_bus import EventBus
from app.core.scheduler.scheduler import Scheduler
from app.core.retry_policy.retry_policy import RetryPolicy
from app.core.timeout.timeout import Timeout
from app.core.rate_limiter.rate_limiter import RateLimiter
from app.core.timer.timer import Timer
from app.core.stopwatch.stopwatch import Stopwatch
from app.core.exchange.factory import create_exchange
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.registry import ExchangeRegistry
from app.core.services.chart_service import ChartService
from app.core.services.order_validator import OrderValidator
from app.core.services.performance_analytics import PerformanceAnalytics
from app.core.services.trade_journal import TradeJournal
from app.core.persistence.service import PersistenceService
from app.core.worker import Worker


logger = logging.getLogger(__name__)


class BotEngine:
    def __init__(self):
        self.running = False

        self.config = AppSettings()

        # docs/BUSINESS_RULES.md: no strategy/risk parameter may stay
        # hardcoded. Any previously saved values are loaded on top of the
        # compiled-in defaults *in place* (self.config keeps being the
        # same shared object every module below receives), so later
        # Settings-screen edits take effect immediately without a
        # restart -- see SettingsStore for details.
        self.persistence = PersistenceService()
        self.settings_store = SettingsStore(
            self.persistence.settings_repository(),
        )
        self.settings_store.load_into(self.config)

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

        # Only one exchange connection is active at a time
        # (docs/BUSINESS_RULES.md §10). Which exchange class gets
        # instantiated is decided entirely by the EXCHANGE environment
        # variable via create_exchange() -- nothing else in this class may
        # hardcode a specific exchange, so WatchList/Strategy/RiskManager
        # and the price stream always operate on exactly the exchange the
        # operator configured.
        active_exchange = create_exchange(self.config.exchange)

        self.exchange_registry.register(
            active_exchange.state.exchange,
            active_exchange,
        )

        self.exchange = ExchangeManager(self.exchange_registry)
        self.order_validator = OrderValidator(self.exchange)

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

        # Sprint 5 -- Trade Journal: a permanent record of every trade's
        # decision history, independent from position_manager (whose rows
        # disappear the instant a position closes).
        self.trade_journal = TradeJournal()
        self.trade_journal.set_repository(
            self.persistence.trade_journal_repository(),
        )

        # Sprint 7 -- Performance Analytics: reads exclusively from the
        # Trade Journal's permanent closed-trade history; never touches
        # positions/orders/risk state itself.
        self.performance_analytics = PerformanceAnalytics()
        self.performance_analytics.set_trade_journal(self.trade_journal)

        # Sprint 6 -- Coin charts: assembles OHLCV candles (own exchange
        # only, per the data-isolation rule) plus Entry/Stop/TP/Trailing
        # overlay levels for the "click a coin to see its chart" UI.
        self.chart_service = ChartService()
        self.chart_service.set_exchange_manager(self.exchange)
        self.chart_service.set_position_manager(self.position_manager)
        self.chart_service.set_trade_journal(self.trade_journal)
        self.chart_service.set_config(self.config)

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
        self.risk_manager.set_order_validator(
            self.order_validator,
        )
        self.risk_manager.set_trade_journal(self.trade_journal)

        self.strategy = Strategy()
        self.strategy.set_risk_manager(self.risk_manager)
        self.strategy.set_position_manager(self.position_manager)
        self.strategy.set_trade_journal(self.trade_journal)

        self.watch_list.set_strategy(self.strategy)

    def start_price_stream(self) -> None:
        self.exchange.start_price_stream(
            self.exchange.active_exchange_type(),
            self.watch_list.get_symbols(),
            self.event_bus.publish,
        )

    def stop_price_stream(self) -> None:
        self.exchange.stop_price_stream(
            self.exchange.active_exchange_type(),
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
        logger.info("BotEngine started successfully")

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

        logger.info("BotEngine stopped successfully")
