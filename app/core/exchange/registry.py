from app.core.exchange.base import BaseExchange
from app.core.exchange.models import ExchangeType


class ExchangeRegistry:
    def __init__(self) -> None:
        self._exchanges: dict[ExchangeType, BaseExchange] = {}

    def register(
        self,
        exchange_type: ExchangeType,
        exchange: BaseExchange,
    ) -> None:
        self._exchanges[exchange_type] = exchange

    def unregister(self, exchange_type: ExchangeType) -> None:
        self._exchanges.pop(exchange_type, None)

    def get(self, exchange_type: ExchangeType) -> BaseExchange | None:
        return self._exchanges.get(exchange_type)

    def all(self) -> dict[ExchangeType, BaseExchange]:
        return dict(self._exchanges)

    def enabled(self) -> list[BaseExchange]:
        return [
            exchange
            for exchange in self._exchanges.values()
            if exchange.state.enabled
        ]
