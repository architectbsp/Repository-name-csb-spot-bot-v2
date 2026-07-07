from app.core.exchange.base import BaseExchange
from app.core.exchange.models import ConnectionStatus, ExchangeState


class BybitExchange(BaseExchange):
    def __init__(self, state: ExchangeState) -> None:
        super().__init__(state)

    async def connect(self) -> None:
        self.state.status = ConnectionStatus.CONNECTED

    async def disconnect(self) -> None:
        self.state.status = ConnectionStatus.DISCONNECTED

    async def fetch_balance(self):
        return None

    async def fetch_markets(self):
        return []

    async def fetch_tickers(self):
        return {}

    async def place_market_buy(self, symbol: str, amount: float):
        return None

    async def place_market_sell(self, symbol: str, amount: float):
        return None
