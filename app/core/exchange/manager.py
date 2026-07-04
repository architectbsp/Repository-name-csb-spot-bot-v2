import asyncio

from app.core.exchange.registry import ExchangeRegistry


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
