import logging
from datetime import UTC, datetime
from decimal import Decimal

from app.core.domain.position import Position
from app.core.trading.models import TradeRequest, TradeSide


logger = logging.getLogger(__name__)


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
        "order_validator",
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
        self._order_validator = None
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

    def set_order_validator(self, order_validator):
        self._order_validator = order_validator

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
            logger.warning("[RISK] Trade rejected: daily_loss_limit reached")
            return False

        if open_positions >= self._risk.max_open_positions:
            logger.warning("[RISK] Trade rejected: max_open_positions reached")
            return False

        if not self.has_sufficient_balance(balance):
            logger.warning("[RISK] Trade rejected: insufficient_balance")
            return False

        logger.debug("[RISK] Trade accepted")
        return True

    @staticmethod
    def create_trade_request(
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

    @staticmethod
    def _is_filled_buy_result(result) -> bool:
        if result is None:
            return False

        return (
            str(getattr(result, "status", "")).upper() in {"CLOSED", "FILLED"}
            and float(getattr(result, "filled_quantity", 0.0) or 0.0) > 0.0
        )

    def open_position(
        self,
        *,
        exchange_type,
        symbol: str,
        price: float,
        stop_loss_percent: float,
    ) -> Position | None:
        """
        Full buy-side trade-permission and execution workflow.

        This is the single entry point through which a new position may be
        opened: balance validation, position sizing, trade-permission
        checks, order validation and order submission all happen here.

        BUSINESS_RULES.md #11 forbids Strategy from sending exchange orders
        directly, so Strategy must only call this method with a candidate
        signal and react to the returned Position (or None on rejection).
        """
        if (
            self._exchange_manager is None
            or self._position_manager is None
            or self._order_validator is None
        ):
            logger.error(
                "[RISK] open_position missing required dependencies "
                "(exchange_manager=%s position_manager=%s order_validator=%s)",
                self._exchange_manager is not None,
                self._position_manager is not None,
                self._order_validator is not None,
            )
            return None

        balance = self._exchange_manager.get_quote_balance(exchange_type)

        if not self.can_open_trade(
            balance=balance,
            daily_loss_percent=0.0,
            open_positions=self._position_manager.open_count(),
        ):
            return None

        position_value = self.calculate_position_size(balance)

        if position_value <= 0:
            return None

        quantity = position_value / price

        trade = self.create_trade_request(
            symbol=symbol,
            quantity=Decimal(str(quantity)),
        )

        validated_trade = self._order_validator.validate(
            exchange_type,
            trade,
        )

        result = self._exchange_manager.execute_trade(
            exchange_type,
            validated_trade,
        )

        if not self._is_filled_buy_result(result):
            logger.warning(
                "[RISK] Buy order not filled for %s (status=%s)",
                symbol,
                getattr(result, "status", None),
            )
            return None

        entry_price = result.average_price

        if entry_price is None or entry_price <= 0:
            entry_price = price

        stop_price = entry_price * (1 - stop_loss_percent / 100)

        position = Position(
            symbol=symbol,
            entry_price=entry_price,
            quantity=float(result.filled_quantity),
            opened_at=datetime.now(UTC),
            stop_price=stop_price,
            exchange=exchange_type,
        )

        if not self._position_manager.add(position):
            logger.error(
                "[RISK] PositionManager rejected new position for %s",
                symbol,
            )
            return None

        logger.info(
            "[BUY EXECUTED] symbol=%s entry=%.8f qty=%.8f stop=%.8f",
            symbol,
            entry_price,
            position.quantity,
            stop_price,
        )

        return position

    def on_price_tick(
        self,
        ticker,
    ) -> None:
        logger.debug(
            "[RISK] Dependencies check: position_manager=%s exchange_manager=%s",
            self._position_manager is not None,
            self._exchange_manager is not None,
        )

        if (
            self._position_manager is None
            or self._exchange_manager is None
        ):
            return

        symbol = ticker.symbol

        position = self._position_manager.get(symbol)

        if position is None:
            return

        if not self._running:
            return

        # Isolated data flow guard (docs/BUSINESS_RULES.md §9): a price
        # tick from exchange A must never be allowed to trigger a
        # stop-loss/trailing/break-even action on a position opened on
        # exchange B. Older positions with no recorded exchange (e.g.
        # legacy data) are still processed to avoid silently orphaning
        # them.
        if (
            position.exchange is not None
            and getattr(ticker, "exchange", None) is not None
            and position.exchange != ticker.exchange
        ):
            logger.debug(
                "[RISK] Ignoring tick for %s from %s; position was opened "
                "on %s",
                symbol,
                ticker.exchange,
                position.exchange,
            )
            return

        self.update_position(
            position,
            ticker,
        )

    def update_position(
        self,
        position,
        ticker,
    ) -> None:
        self.check_break_even(position, ticker)
        self.check_trailing(position, ticker)
        self.check_stop_loss(position, ticker)

    def check_stop_loss(self, position, ticker) -> None:
        if position.stop_price is None:
            return

        last_price = ticker.last_price

        logger.debug(
            "[STOP CHECK] symbol=%s last=%.8f stop=%.8f triggered=%s",
            position.symbol,
            last_price,
            position.stop_price,
            last_price <= position.stop_price,
        )

        if last_price > position.stop_price:
            return

        logger.info("[SELL TRIGGER] symbol=%s last=%.8f stop=%.8f", position.symbol, last_price, position.stop_price)

        if position.state.name != "OPEN":
            return

        trade = TradeRequest(
            symbol=position.symbol,
            quantity=Decimal(str(position.quantity)),
            side=TradeSide.SELL,
        )

        logger.info("[SELL EXECUTE] symbol=%s quantity=%.8f", position.symbol, position.quantity)

        result = self._exchange_manager.execute_trade(
            ticker.exchange,
            trade,
        )

        if result is not None:
            logger.debug(
                "[SELL STATUS] status=%s price=%.8f filled=%.8f",
                getattr(result, "status", None),
                getattr(result, "average_price", None) or 0.0,
                getattr(result, "filled_quantity", None) or 0.0,
            )

        if result is None:
            logger.error("[SELL FAILED] No result from exchange")
            return

        if result.status not in {"CLOSED", "FILLED"}:
            logger.warning("[SELL INCOMPLETE] status=%s", result.status)
            return

        exit_price = result.average_price

        if exit_price is None or exit_price <= 0:
            exit_price = last_price

        self._position_manager.close(
            position.symbol,
            exit_price=exit_price,
            reason="STOP_LOSS",
        )

        if self._event_bus is not None:
            self._event_bus.publish(
                "position.closed",
                {
                    "symbol": position.symbol,
                    "reason": "STOP_LOSS",
                    "price": last_price,
                    "position": position,
                },
            )

    def check_break_even(self, position, ticker) -> None:
        activation = self._risk.break_even_activation_percent

        profit = (
            (ticker.last_price - position.entry_price)
            / position.entry_price
        ) * 100

        if profit < activation:
            return

        if position.stop_price is None:
            position.stop_price = position.entry_price
            logger.debug("[BREAK-EVEN] Activated for %s", position.symbol)
            return

        if position.stop_price < position.entry_price:
            position.stop_price = position.entry_price
            logger.debug("[BREAK-EVEN] Updated for %s", position.symbol)

    def check_trailing(self, position, ticker) -> None:
        activation = self._risk.trailing_activation_percent

        profit = (
            (ticker.last_price - position.entry_price)
            / position.entry_price
        ) * 100

        if profit < activation:
            return

        current_highest = getattr(position, "highest_price", None)

        if current_highest is None:
            current_highest = ticker.last_price

        highest_price = max(
            ticker.last_price,
            current_highest,
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
            logger.debug("[TRAILING] Updated for %s to %.8f", position.symbol, trailing_stop)
