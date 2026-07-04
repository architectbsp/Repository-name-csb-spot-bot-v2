from app.core.exchange.registry import ExchangeRegistry


class MarketScanner:
    def __init__(self, registry: ExchangeRegistry) -> None:
        self._registry = registry

    async def scan(self) -> None:
        for exchange in self._registry.enabled():
            await exchange.fetch_markets()
            await exchange.fetch_tickers()
