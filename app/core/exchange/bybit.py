from app.core.exchange.base import BaseExchange
from app.core.exchange.models import ConnectionStatus, ExchangeState


class BybitExchange(BaseExchange):
    def __init__(self, state: ExchangeState) -> None:
        super().__init__(state)

    def connect(self) -> None:
        self.state.status = ConnectionStatus.CONNECTED

    def disconnect(self) -> None:
        self.state.status = ConnectionStatus.DISCONNECTED

    def fetch_balance(self):
        return None

    def fetch_markets(self):
        return []

    def fetch_tickers(self):
        return {}

    def place_market_buy(self, symbol: str, amount: float):
        return None

    def place_market_sell(self, symbol: str, amount: float):
        return None
