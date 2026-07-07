import ccxt

from app.core.config.settings import ExchangeSettings
from app.core.exchange.base import BaseExchange
from app.core.exchange.models import ConnectionStatus, ExchangeState


class MEXCExchange(BaseExchange):
    def __init__(
        self,
        state: ExchangeState,
        settings: ExchangeSettings,
    ) -> None:
        super().__init__(state)
        self.settings = settings
        self.client = ccxt.mexc(
            {
                "apiKey": settings.api_key,
                "secret": settings.api_secret,
                "options": {
                    "defaultType": "spot",
                },
                "sandbox": settings.testnet,
            }
        )

    def connect(self) -> None:
        self.state.status = ConnectionStatus.CONNECTING
        self.state.last_error = None

        try:
            self.client.load_markets()
            self.state.status = ConnectionStatus.CONNECTED
        except Exception as exc:
            self.state.status = ConnectionStatus.ERROR
            self.state.last_error = str(exc)
            raise

    def disconnect(self) -> None:
        self.state.status = ConnectionStatus.DISCONNECTED

    def fetch_balance(self):
        return self.client.fetch_balance()

    def fetch_markets(self):
        return self.client.load_markets()

    def fetch_tickers(self):
        return self.client.fetch_tickers()

    def place_market_buy(self, symbol: str, amount: float):
        return None

    def place_market_sell(self, symbol: str, amount: float):
        return None
