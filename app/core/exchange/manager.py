import asyncio

from app.core.exchange.base import BaseExchange
from app.core.exchange.models import ExchangeType
from app.core.exchange.registry import ExchangeRegistry
from app.core.trading.models import TradeRequest, TradeSide


class ExchangeManager:
    def __init__(self, registry: ExchangeRegistry) -> None:
        self._registry = registry

    async def start(self) -> None:
        tasks = [
            exchange.connect()
            for exchange in self._registry.enabled()
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        tasks = [
            exchange.disconnect()
            for exchange in self._registry.enabled()
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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

    async def place_market_buy(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        exchange = self._get_exchange(exchange_type)
        return await exchange.place_market_buy(symbol, amount)

    async def place_market_sell(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        exchange = self._get_exchange(exchange_type)
        return await exchange.place_market_sell(symbol, amount)

    async def execute_trade(
        self,
        exchange_type: ExchangeType,
        trade: TradeRequest,
    ):
        if trade.side == TradeSide.BUY:
            return await self.place_market_buy(
                exchange_type,
                trade.symbol,
                float(trade.quantity),
            )

        return await self.place_market_sell(
            exchange_type,
            trade.symbol,
            float(trade.quantity),
        )
