from app.core.exchange.base import BaseExchange
from app.core.exchange.models import ExchangeType, MarketMetadata
from app.core.exchange.registry import ExchangeRegistry
from app.core.trading.models import TradeRequest, TradeSide


class ExchangeManager:
    def __init__(self, registry: ExchangeRegistry) -> None:
        self._registry = registry

    def start(self) -> None:
        for exchange in self._registry.enabled():
            exchange.connect()

    def stop(self) -> None:
        for exchange in self._registry.enabled():
            exchange.disconnect()

    def _get_exchange(
        self,
        exchange_type: ExchangeType,
    ) -> BaseExchange:
        exchange = self._registry.get(exchange_type)

        if exchange is None:
            raise ValueError(
                f"Exchange not registered: {exchange_type.name}"
            )

        return exchange

    def get_market_metadata(
        self,
        exchange_type: ExchangeType,
        symbol: str,
    ) -> MarketMetadata:
        exchange = self._get_exchange(exchange_type)
        return exchange.get_market_metadata(symbol)

    def normalize_amount(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ) -> float:
        exchange = self._get_exchange(exchange_type)
        return exchange.normalize_amount(
            symbol,
            amount,
        )

    def place_market_buy(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        exchange = self._get_exchange(exchange_type)
        return exchange.place_market_buy(symbol, amount)

    def place_market_sell(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        exchange = self._get_exchange(exchange_type)
        return exchange.place_market_sell(symbol, amount)

    def execute_trade(
        self,
        exchange_type: ExchangeType,
        trade: TradeRequest,
    ):
        if trade.side == TradeSide.BUY:
            return self.place_market_buy(
                exchange_type,
                trade.symbol,
                float(trade.quantity),
            )

        return self.place_market_sell(
            exchange_type,
            trade.symbol,
            float(trade.quantity),
        )
