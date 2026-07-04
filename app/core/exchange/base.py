from abc import ABC, abstractmethod

from app.core.exchange.models import ExchangeState


class BaseExchange(ABC):
    def __init__(self, state: ExchangeState) -> None:
        self.state = state

    @abstractmethod
    async def connect(self) -> None:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def fetch_balance(self):
        ...

    @abstractmethod
    async def fetch_markets(self):
        ...

    @abstractmethod
    async def fetch_tickers(self):
        ...

    @abstractmethod
    async def place_market_buy(self, symbol: str, amount: float):
        ...

    @abstractmethod
    async def place_market_sell(self, symbol: str, amount: float):
        ...
