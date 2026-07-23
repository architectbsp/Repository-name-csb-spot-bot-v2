import logging
from datetime import timedelta

from app.core.market_scanner import MarketScanner
from app.core.position_manager import PositionManager
from app.core.watch_list import WatchList
from app.core.risk_manager import RiskManager
from app.core.strategy import Strategy
from app.core.strategies.factory import parse_enabled_strategies
from app.core.strategies.orchestrator import MultiStrategyOrchestrator

from app.core.config.config_manager import CONFIG_UPDATED_EVENT, ConfigManager
from app.core.config.settings import AppSettings
from app.core.config.settings_store import SettingsStore
from app.core.event_bus.event_bus import EventBus
from app.core.scheduler.scheduler import Scheduler
from app.core.retry_policy.retry_policy import RetryPolicy
from app.core.timeout.timeout import Timeout
from app.core.rate_limiter.rate_limiter import RateLimiter
from app.core.timer.timer import Timer
from app.core.stopwatch.stopwatch import Stopwatch
from app.core.exchange.factory import create_exchanges
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.registry import ExchangeRegistry
from app.core.services.chart_service import ChartService
from app.core.services.dashboard_service import DashboardService
from app.core.services.order_validator import OrderValidator
from app.core.services.analytics_service import AnalyticsService
from app.core.services.position_reconciler import PositionReconciler
from app.core.services.symbol_filter import SymbolFilter
from app.core.services.telegram_client import TelegramClient
from app.core.services.telegram_notifier import TelegramNotifier
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

        # ConfigManager singleton: Settings UI + EventBus `config.updated`
        # for runtime reload (Strategy / Scanner / RiskManager observers).
        self.config_manager = ConfigManager.instance()
        self.config_manager.configure(
            self.config,
            self.settings_store,
            self.event_bus,
        )
        self.scheduler = Scheduler()
        self.worker = Worker(self.scheduler)
        self.retry_policy = RetryPolicy(
            self.config.retry_policy.max_attempts,
            self.config.retry_policy.delay,
            backoff_factor=2.0,
            max_delay=300.0,
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

        # Sprint 18 (docs/BUSINESS_RULES.md §10): one or many exchanges
        # may be connected at once (EXCHANGES=binance,bybit,... or legacy
        # EXCHANGE=...). Each keeps its own credentials, balance, stream
        # and market state -- WatchList/Strategy/RiskManager always act
        # on the ticker's own venue (isolation rule).
        for exchange in create_exchanges():
            self.exchange_registry.register(
                exchange.state.exchange,
                exchange,
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

        # Performance Analytics (AnalyticsService): closed-trade metrics
        # for the dashboard / Kelly sizing. Alias kept for older callers.
        self.analytics_service = AnalyticsService()
        self.analytics_service.set_trade_journal(self.trade_journal)
        self.performance_analytics = self.analytics_service

        # Leveraged-token regex + operator blacklist (Settings UI).
        self.symbol_filter = SymbolFilter()
        self.symbol_filter.set_repository(
            self.persistence.symbol_blacklist_repository(),
        )
        self.market_scanner.set_symbol_filter(self.symbol_filter)

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

        # Multi-strategy: when STRATEGIES lists 2+ names, replace the
        # single lane with parallel pipelines (independent WatchList /
        # RiskManager / budget). Dashboard binds to the primary pipeline.
        self.strategy_orchestrator: MultiStrategyOrchestrator | None = None
        self._strategy_names = parse_enabled_strategies()
        if len(self._strategy_names) > 1:
            self._activate_multi_strategy_pipelines()

        # Sprint 12 -- Live Dashboard: read-only snapshot aggregator the
        # Flet UI polls every couple of seconds. Also caches ticker.updated
        # so panels never REST-fetch prices on each refresh. Wired after
        # risk_manager/strategy so every dependency is already constructed.
        self.dashboard_service = DashboardService()
        self.dashboard_service.set_exchange_manager(self.exchange)
        self.dashboard_service.set_position_manager(self.position_manager)
        self.dashboard_service.set_watch_list(self.watch_list)
        self.dashboard_service.set_trade_journal(self.trade_journal)
        self.dashboard_service.set_risk_manager(self.risk_manager)
        self.dashboard_service.set_market_scanner(self.market_scanner)
        self.dashboard_service.set_analytics_service(self.analytics_service)
        self.dashboard_service.set_config(self.config)
        self.dashboard_service.set_bot_running_fn(lambda: self.running)

        # Sprint 11 -- Telegram: opt-in via TELEGRAM_BOT_TOKEN +
        # TELEGRAM_CHAT_ID. Notifier only sends; trading paths never
        # depend on Telegram being reachable.
        self.telegram_client = TelegramClient(
            self.config.telegram.bot_token,
            self.config.telegram.chat_id,
        )
        self.telegram_notifier = TelegramNotifier(self.telegram_client)
        self.telegram_notifier.set_config(self.config)
        self.telegram_notifier.set_event_bus(self.event_bus)
        self.telegram_notifier.set_scheduler(self.scheduler)
        self.telegram_notifier.set_exchange_manager(self.exchange)
        self.telegram_notifier.set_trade_journal(self.trade_journal)
        self.telegram_notifier.set_risk_manager(self.risk_manager)
        self.telegram_notifier.set_position_manager(self.position_manager)

        # Balance ↔ local OPEN positions sync (Unknown Order / DB drift).
        self.position_reconciler = PositionReconciler()
        self.position_reconciler.set_exchange_manager(self.exchange)
        self.position_reconciler.set_position_manager(self.position_manager)
        self.position_reconciler.set_event_bus(self.event_bus)
        self.position_reconciler.set_scheduler(self.scheduler)

    def _activate_multi_strategy_pipelines(self) -> None:
        """Swap the singleton strategy lane for N isolated pipelines."""
        orch = MultiStrategyOrchestrator()
        orch.build(
            self.exchange,
            base_config=self.config,
            strategy_names=self._strategy_names,
        )
        primary = orch.primary()
        if primary is None:
            raise RuntimeError("Multi-strategy orchestrator built zero pipelines")

        # Keep scheduler/event wiring on the primary watch list so
        # cooldown jobs and stream symbol grouping still work.
        primary.watch_list.set_scheduler(self.scheduler)
        primary.watch_list.set_event_bus(self.event_bus)
        primary.watch_list.set_rate_limiter(self.rate_limiter)
        primary.watch_list.set_retry_policy(self.retry_policy)
        primary.watch_list.set_timeout(self.timeout)
        primary.watch_list.set_timer(self.timer)
        primary.watch_list.set_stopwatch(self.stopwatch)

        primary.risk_manager.set_scheduler(self.scheduler)
        primary.risk_manager.set_event_bus(self.event_bus)
        primary.risk_manager.set_rate_limiter(self.rate_limiter)
        primary.risk_manager.set_retry_policy(self.retry_policy)
        primary.risk_manager.set_timeout(self.timeout)
        primary.risk_manager.set_timer(self.timer)
        primary.risk_manager.set_stopwatch(self.stopwatch)

        self.strategy_orchestrator = orch
        self.watch_list = primary.watch_list
        self.strategy = primary.strategy
        self.risk_manager = primary.risk_manager
        self.position_manager = primary.position_manager
        self.trade_journal = primary.trade_journal
        self.order_validator = OrderValidator(self.exchange)
        self.analytics_service.set_trade_journal(self.trade_journal)
        self.performance_analytics = self.analytics_service
        if hasattr(self, "chart_service") and self.chart_service is not None:
            self.chart_service.set_position_manager(self.position_manager)
            self.chart_service.set_trade_journal(self.trade_journal)

        logger.info(
            "[BotEngine] Multi-strategy active: %s",
            ", ".join(self._strategy_names),
        )

    def start_price_stream(self) -> None:
        # Per-venue streams only (isolation): never subscribe exchange A's
        # symbols on exchange B's websocket. Multi-strategy unions symbols
        # across every pipeline watch list.
        grouped: dict = {}
        watch_lists = (
            [p.watch_list for p in self.strategy_orchestrator.pipelines]
            if self.strategy_orchestrator is not None
            else [self.watch_list]
        )
        for watch_list in watch_lists:
            for exchange_type, symbols in watch_list.symbols_by_exchange().items():
                bucket = grouped.setdefault(exchange_type, [])
                for symbol in symbols:
                    if symbol not in bucket:
                        bucket.append(symbol)

        if grouped:
            for exchange_type, symbols in grouped.items():
                self.exchange.start_price_stream(
                    exchange_type,
                    symbols,
                    self.event_bus.publish,
                )
            return

        for exchange_type in self.exchange.enabled_exchange_types():
            self.exchange.start_price_stream(
                exchange_type,
                [],
                self.event_bus.publish,
            )

    def stop_price_stream(self) -> None:
        for exchange_type in self.exchange.enabled_exchange_types():
            self.exchange.stop_price_stream(exchange_type)

    def initialize(self):
        for module in (
            self.market_scanner,
            self.watch_list,
            self.risk_manager,
            self.strategy,
            self.position_manager,
        ):
            module.set_config(self.config)

        if self.strategy_orchestrator is not None:
            self.event_bus.subscribe(
                "market_scanner.scan_completed",
                self.strategy_orchestrator.handle_scan_result,
            )
            self.event_bus.subscribe(
                "ticker.updated",
                self.strategy_orchestrator.handle_price_update,
            )
            self.event_bus.subscribe(
                "position.closed",
                self.strategy_orchestrator.handle_position_closed,
            )
            self.event_bus.subscribe(
                CONFIG_UPDATED_EVENT,
                self.strategy_orchestrator.on_config_updated,
            )
        else:
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
            self.event_bus.subscribe(
                CONFIG_UPDATED_EVENT,
                self.strategy.on_config_updated,
            )
            self.event_bus.subscribe(
                CONFIG_UPDATED_EVENT,
                self.watch_list.on_config_updated,
            )
            self.event_bus.subscribe(
                CONFIG_UPDATED_EVENT,
                self.risk_manager.on_config_updated,
            )
            self.event_bus.subscribe(
                CONFIG_UPDATED_EVENT,
                self.position_manager.on_config_updated,
            )

        self.event_bus.subscribe(
            "ticker.updated",
            self.dashboard_service.on_ticker_updated,
        )
        self.event_bus.subscribe(
            "order.needs_manual_review",
            self.dashboard_service.on_order_needs_manual_review,
        )

        # ConfigUpdatedEvent: modules already share live AppSettings;
        # handlers refresh anything that was snapshotted at initialize
        # (e.g. scanner job interval).
        self.event_bus.subscribe(
            CONFIG_UPDATED_EVENT,
            self.market_scanner.on_config_updated,
        )

        # OrderExecution is built lazily; attach it before reconciler init.
        order_execution = self.risk_manager.order_execution
        order_execution.set_position_manager(self.position_manager)
        order_execution.set_on_ambiguous(
            lambda _market, _result: self.position_reconciler.reconcile_once()
        )
        self.position_reconciler.set_order_execution(order_execution)

        self.market_scanner.initialize()
        if self.strategy_orchestrator is not None:
            self.strategy_orchestrator.initialize()
        else:
            for module in (
                self.watch_list,
                self.position_manager,
                self.risk_manager,
                self.strategy,
            ):
                module.initialize()

        self.telegram_notifier.initialize()
        self.position_reconciler.initialize()

        for position in self.persistence.load_positions():
            self.position_manager.restore(position)

    def shutdown(self):
        self.position_reconciler.shutdown()
        self.telegram_notifier.shutdown()
        self.market_scanner.shutdown()
        if self.strategy_orchestrator is not None:
            self.strategy_orchestrator.shutdown()
        else:
            for module in (
                self.watch_list,
                self.position_manager,
                self.risk_manager,
                self.strategy,
            ):
                module.shutdown()

    def start(self):
        self.initialize()

        self.market_scanner.start()
        if self.strategy_orchestrator is not None:
            self.strategy_orchestrator.start()
        else:
            for module in (
                self.watch_list,
                self.position_manager,
                self.risk_manager,
                self.strategy,
            ):
                module.start()
        self.telegram_notifier.start()
        self.position_reconciler.start()

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

        self.position_reconciler.stop()
        self.telegram_notifier.stop()
        self.market_scanner.stop()
        if self.strategy_orchestrator is not None:
            self.strategy_orchestrator.stop()
        else:
            for module in (
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
