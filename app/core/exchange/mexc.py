import ccxt

from app.core.config.settings import ExchangeSettings
from app.core.exchange.base import (
    BaseExchange,
    enable_sandbox_mode,
    truncate_to_precision,
)
from app.core.exchange.mexc_price_stream import MEXCPriceStream
from app.core.exchange.models import ConnectionStatus, ExchangeState, MarketMetadata


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
                "enableRateLimit": True,
                "options": {
                    "defaultType": "spot",
                },
            }
        )

        # MEXC spot has no ccxt sandbox environment; enable_sandbox_mode
        # will log a warning instead of silently trading live if testnet
        # was requested.
        enable_sandbox_mode(
            self.client,
            testnet=settings.testnet,
            exchange_name="MEXC",
        )

        self._price_stream = MEXCPriceStream(testnet=settings.testnet)

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
        if self._markets_cache is None:
            self._markets_cache = self.client.load_markets()
        return self._markets_cache

    def fetch_tickers(self):
        return self.client.fetch_tickers()

    def fetch_my_trades(
        self,
        symbol: str | None = None,
        limit: int | None = None,
    ):
        return [
            self._normalize_trade(trade)
            for trade in self.client.fetch_my_trades(
                symbol=symbol,
                limit=limit,
            )
        ]


    def get_market_metadata(
        self,
        symbol: str,
    ) -> MarketMetadata:
        markets = self.fetch_markets()

        if symbol not in markets:
            raise ValueError(f"Market not found: {symbol}")

        market = markets[symbol]

        return MarketMetadata(
            symbol=market["symbol"],
            base=market["base"],
            quote=market["quote"],
            price_precision=market.get("precision", {}).get("price"),
            amount_precision=market.get("precision", {}).get("amount"),
            minimum_amount=market.get("limits", {}).get("amount", {}).get("min"),
            minimum_cost=market.get("limits", {}).get("cost", {}).get("min"),
            active=market.get("active", True),
        )

    def normalize_amount(
        self,
        symbol: str,
        amount: float,
    ) -> float:
        return float(
            self.client.amount_to_precision(
                symbol,
                amount,
            )
        )

    def normalize_price(
        self,
        symbol: str,
        price: float,
    ) -> float:
        return truncate_to_precision(
            self.client,
            symbol,
            price,
            precision_key="price",
        )

    def place_market_buy(
        self,
        symbol: str,
        amount: float,
    ):
        return self._normalize_order_result(
            self.client.create_market_buy_order(
                symbol,
                amount,
            )
        )

    def place_market_sell(
        self,
        symbol: str,
        amount: float,
    ):
        return self._normalize_order_result(
            self.client.create_market_sell_order(
                symbol,
                amount,
            )
        )
