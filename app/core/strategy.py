from datetime import datetime
from decimal import Decimal

from app.core.position_manager import Position
from app.core.trading.models import TradeRequest, TradeSide
from app.core.watch_list import WatchState


class Strategy:
    _DEPENDENCY_NAMES = (
        "risk_manager",
        "position_manager",
        "exchange_manager",
        "order_validator",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False

        self._risk_manager = None
        self._position_manager = None
        self._exchange_manager = None
        self._order_validator = None
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

    def set_exchange_manager(self, exchange_manager) -> None:
        self._exchange_manager = exchange_manager

    def set_order_validator(self, order_validator) -> None:
        self._order_validator = order_validator

    def set_config(self, config) -> None:
        self._config = config

    def on_ticker(
        self,
        watch_list,
        ticker,
    ) -> None:
        if (
            self._position_manager is not None
            and self._position_manager.is_open(ticker.symbol)
        ):
            self._handle_position_open(
                watch_list,
                ticker,
            )
            return

        state = watch_list.get_state(ticker.symbol)

        if state is None:
            return

        if state == WatchState.IDLE:
            self._handle_idle(
                watch_list,
                ticker,
            )
            return

        if state == WatchState.WATCH_FALLING:
            self._handle_falling_watch(
                watch_list,
                ticker,
            )
            return

        if state == WatchState.WATCH_RISING:
            self._handle_rising_watch(
                watch_list,
                ticker,
            )

    def _handle_idle(
        self,
        watch_list,
        ticker,
    ) -> None:
        if ticker.change_24h > -self._config.watch_percent:
            return

        watch_list.begin_falling_watch(
            ticker.symbol,
            ticker.last_price,
        )

    def _handle_falling_watch(
        self,
        watch_list,
        ticker,
    ) -> None:
        watch_list.record_falling_price(
            ticker.symbol,
            ticker.last_price,
        )

        coin = watch_list.get(ticker.symbol)
        lowest = coin["lowest_price"]

        if ticker.last_price > lowest:
            watch_list.begin_rising_watch(
                ticker.symbol,
                ticker.last_price,
            )

    def _handle_rising_watch(
        self,
        watch_list,
        ticker,
    ) -> None:
        watch_list.record_rising_price(
            ticker.symbol,
            ticker.last_price,
        )

        coin = watch_list.get(ticker.symbol)
        lowest = coin["lowest_price"]

        recovery = (
            (ticker.last_price - lowest)
            / lowest
        ) * 100

        if recovery < self._config.entry_percent:
            return

        watch_list.promote_to_buy_pending(
            ticker.symbol,
            ticker.last_price,
        )

        trade = self.create_trade_request(
            symbol=ticker.symbol,
            quantity=Decimal("1"),
            side=TradeSide.BUY,
        )

        result = self.execute_trade(
            ticker.exchange,
            trade,
        )

        if not result:
            return

        stop_price = (
            ticker.last_price
            * (
                1
                - self._config.stop_loss_percent
                / 100
            )
        )

        watch_list.promote_to_position_open(
            ticker.symbol,
            ticker.last_price,
            stop_price,
        )

        if self._position_manager is not None:
            self._position_manager.add(
                Position(
                    symbol=ticker.symbol,
                    entry_price=ticker.last_price,
                    quantity=float(trade.quantity),
                    opened_at=datetime.utcnow(),
                    stop_price=stop_price,
                )
            )

    def _handle_position_open(
        self,
        watch_list,
        ticker,
    ) -> None:
        return

    def create_trade_request(
        self,
        *,
        symbol: str,
        quantity: Decimal,
        side: TradeSide = TradeSide.BUY,
    ) -> TradeRequest:
        return TradeRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
        )

    def execute_trade(
        self,
        exchange_type,
        trade: TradeRequest,
    ):
        if self._exchange_manager is None:
            raise RuntimeError("ExchangeManager is not configured.")

        if self._order_validator is None:
            raise RuntimeError("OrderValidator is not configured.")

        validated_trade = self._order_validator.validate(
            exchange_type,
            trade,
        )

        return self._exchange_manager.execute_trade(
            exchange_type,
            validated_trade,
        )
