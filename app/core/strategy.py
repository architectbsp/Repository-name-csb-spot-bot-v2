from decimal import Decimal

from app.core.trading.models import TradeRequest, TradeSide


class Strategy:
    _DEPENDENCY_NAMES = (
        "risk_manager",
        "exchange_manager",
        "order_validator",
        "config",
    )

    def __init__(self) -> None:
        self._initialized = False
        self._running = False

        self._risk_manager = None
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

    def set_exchange_manager(self, exchange_manager) -> None:
        self._exchange_manager = exchange_manager

    def set_order_validator(self, order_validator) -> None:
        self._order_validator = order_validator

    def set_config(self, config) -> None:
        self._config = config

    def should_buy(
        self,
        price: float,
        *,
        balance: float = 0.0,
        daily_loss_percent: float = 0.0,
        open_positions: int = 0,
    ) -> bool:
        if price <= 42000:
            return False

        if self._risk_manager is None:
            return True

        return self._risk_manager.can_open_trade(
            balance=balance,
            daily_loss_percent=daily_loss_percent,
            open_positions=open_positions,
        )

    def should_sell(self, price: float) -> bool:
        return price < 42000

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
