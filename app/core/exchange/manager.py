from app.core.exchange.base import BaseExchange
from app.core.exchange.models import ExchangeType, MarketMetadata
from app.core.exchange.registry import ExchangeRegistry
from app.core.exchange.stream import PriceStream
from app.core.market_data.service import MarketDataService
from app.core.trading.models import TradeRequest, TradeSide


class ExchangeManager:
    def __init__(self, registry: ExchangeRegistry) -> None:
        self._registry = registry
        self._market_data = MarketDataService()

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

    def enabled(self) -> list[BaseExchange]:
        return self._registry.enabled()

    def active_exchange_type(self) -> ExchangeType:
        """
        Returns the single currently-enabled exchange type.

        Per docs/BUSINESS_RULES.md §10, only one exchange connection is
        active at a time. Every caller that needs "the exchange we are
        trading on right now" (MarketScanner, WatchList's price-stream
        sync, BotEngine's price-stream start/stop) must resolve it through
        this single method instead of hardcoding an exchange, so no code
        path can ever mix data between exchanges.
        """
        enabled = self._registry.enabled()

        if not enabled:
            raise RuntimeError("No enabled exchange is registered.")

        return enabled[0].state.exchange

    def get_price_stream(
        self,
        exchange_type: ExchangeType,
    ) -> PriceStream | None:
        return self._get_exchange(
            exchange_type
        ).get_price_stream()

    def get_market_metadata(
        self,
        exchange_type: ExchangeType,
        symbol: str,
    ) -> MarketMetadata:
        return self._get_exchange(
            exchange_type
        ).get_market_metadata(symbol)

    def get_tickers(
        self,
        exchange_type: ExchangeType,
    ):
        exchange = self._get_exchange(exchange_type)

        return self._market_data.normalize_tickers(
            exchange_type,
            exchange.fetch_tickers(),
        )

    def normalize_amount(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ) -> float:
        return self._get_exchange(
            exchange_type
        ).normalize_amount(
            symbol,
            amount,
        )

    def normalize_price(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        price: float,
    ) -> float:
        return self._get_exchange(
            exchange_type
        ).normalize_price(
            symbol,
            price,
        )


    def fetch_my_trades(
        self,
        exchange_type: ExchangeType,
        symbol: str | None = None,
        limit: int | None = None,
    ):
        return self._get_exchange(
            exchange_type
        ).fetch_my_trades(
            symbol=symbol,
            limit=limit,
        )

    def get_quote_balance(
        self,
        exchange_type: ExchangeType,
        quote: str = "USDT",
    ) -> float:
        return self._get_exchange(
            exchange_type
        ).fetch_quote_balance(
            quote,
        )

    def place_market_buy(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        return self._get_exchange(
            exchange_type
        ).place_market_buy(
            symbol,
            amount,
        )

    def place_market_sell(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
    ):
        return self._get_exchange(
            exchange_type
        ).place_market_sell(
            symbol,
            amount,
        )

    def fetch_order(
        self,
        exchange_type: ExchangeType,
        order_id: str,
        symbol: str,
    ):
        return self._get_exchange(
            exchange_type
        ).fetch_order(
            order_id,
            symbol,
        )

    def cancel_order(
        self,
        exchange_type: ExchangeType,
        order_id: str,
        symbol: str,
    ):
        return self._get_exchange(
            exchange_type
        ).cancel_order(
            order_id,
            symbol,
        )



    def start_price_stream(
        self,
        exchange_type,
        symbols,
        callback,
    ):
        stream = self.get_price_stream(
            exchange_type,
        )

        if stream is None:
            return

        stream.start(
            symbols,
            callback,
        )

    def stop_price_stream(
        self,
        exchange_type,
    ):
        stream = self.get_price_stream(
            exchange_type,
        )

        if stream is None:
            return

        stream.stop()



    def update_price_stream(
        self,
        exchange_type: ExchangeType,
        symbols: list[str],
    ) -> None:
        stream = self.get_price_stream(exchange_type)

        if stream is None:
            return

        stream.update_symbols(symbols)

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
