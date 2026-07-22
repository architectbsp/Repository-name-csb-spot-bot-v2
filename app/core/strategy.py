from app.core.watch_list import WatchState



def _cfg(config):
    return getattr(config, "strategy", config)


class Strategy:
    """
    Generates entry signals only.

    Per docs/BUSINESS_RULES.md #11 and docs/ARCHITECTURE.md, Strategy must
    never send exchange orders, manage positions or perform risk
    validation itself. Every candidate BUY signal is handed to
    RiskManager.open_position(), which owns trade-permission checks,
    position sizing, order validation, order submission and position
    registration. Strategy only reacts to the resulting Position (or None)
    to update WatchList bookkeeping.
    """

    _DEPENDENCY_NAMES = (
        "risk_manager",
        "position_manager",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False

        self._risk_manager = None
        self._position_manager = None
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

    def set_position_manager(self, position_manager) -> None:
        self._position_manager = position_manager

    def set_config(self, config) -> None:
        self._config = config

    def on_ticker(
        self,
        watch_list,
        ticker,
    ) -> None:
        state = watch_list.get_state(ticker.symbol)

        if state is None:
            return

        if state in (
            WatchState.POSITION_OPEN,
            WatchState.BREAK_EVEN,
        ):
            self._handle_position_open(
                watch_list,
                ticker,
            )
            return

        if (
            self._position_manager is not None
            and self._position_manager.is_open(ticker.symbol)
        ):
            return

        if state == WatchState.IDLE:
            self._handle_idle(watch_list, ticker)
            return

        if state == WatchState.WATCH_FALLING:
            self._handle_falling_watch(watch_list, ticker)
            return

        if state == WatchState.WATCH_RISING:
            self._handle_rising_watch(watch_list, ticker)

    def _handle_idle(self, watch_list, ticker) -> None:
        if ticker.change_24h > -_cfg(self._config).watch_percent:
            return

        watch_list.begin_falling_watch(
            ticker.symbol,
            ticker.last_price,
        )

    def _handle_falling_watch(self, watch_list, ticker) -> None:
        watch_list.record_falling_price(
            ticker.symbol,
            ticker.last_price,
        )

        coin = watch_list.get(ticker.symbol)

        if ticker.last_price > coin["lowest_price"]:
            watch_list.begin_rising_watch(
                ticker.symbol,
                ticker.last_price,
            )

    def _handle_rising_watch(self, watch_list, ticker) -> None:
        watch_list.record_rising_price(
            ticker.symbol,
            ticker.last_price,
        )

        coin = watch_list.get(ticker.symbol)

        recovery = (
            (ticker.last_price - coin["lowest_price"])
            / coin["lowest_price"]
        ) * 100

        if recovery < _cfg(self._config).entry_percent:
            return

        watch_list.promote_to_buy_pending(
            ticker.symbol,
            ticker.last_price,
        )

        if self._risk_manager is None:
            watch_list.cancel_buy_pending(ticker.symbol)
            return

        # Strategy never talks to the exchange directly (BUSINESS_RULES.md
        # #11). RiskManager performs the balance check, position sizing,
        # order validation, order submission and position registration,
        # and returns the resulting Position (or None if rejected/unfilled).
        position = self._risk_manager.open_position(
            exchange_type=ticker.exchange,
            symbol=ticker.symbol,
            price=ticker.last_price,
            stop_loss_percent=_cfg(self._config).stop_loss_percent,
        )

        if position is None:
            watch_list.cancel_buy_pending(ticker.symbol)
            return

        watch_list.promote_to_position_open(
            ticker.symbol,
            position.entry_price,
            position.stop_price,
        )

    def _handle_position_open(
        self,
        watch_list,
        ticker,
    ) -> None:
        if self._position_manager is None:
            return

        position = self._position_manager.get(
            ticker.symbol,
        )

        if position is None:
            return

        if ticker.last_price > position.entry_price:
            watch_list.update_highest_price(
                ticker.symbol,
                ticker.last_price,
            )

    def on_price_tick(
        self,
        ticker: dict,
    ) -> None:
        symbol = ticker["symbol"]

        if not self._watch_list.contains(symbol):
            return

        if self._position_manager.has_position(symbol):
            self._risk_manager.on_price_tick(ticker)
            return

        self.evaluate_live_signal(ticker)

    def evaluate_live_signal(
        self,
        ticker: dict,
    ) -> None:
        """
        Live websocket strategy entry point.

        Scanner (REST):
            eligible coin discovery

        WebSocket:
            entry timing
        """
        return
