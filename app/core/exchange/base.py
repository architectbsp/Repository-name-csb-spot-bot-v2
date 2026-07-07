from abc import ABC, abstractmethod

from app.core.exchange.models import ExchangeState


class BaseExchange(ABC):
    def __init__(self, state: ExchangeState) -> None:
        self.state = state

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def fetch_balance(self):
        ...

    @abstractmethod
    def fetch_markets(self):
        ...

    @abstractmethod
    def fetch_tickers(self):
        ...

    @abstractmethod
    def place_market_buy(self, symbol: str, amount: float):
        ...

    @abstractmethod
    def place_market_sell(self, symbol: str, amount: float):
        ...
