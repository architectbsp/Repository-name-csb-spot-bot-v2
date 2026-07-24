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
        # Single source of truth for UI / single-venue call sites.
        # May reference a registered venue; if unset, falls back to first
        # enabled exchange (legacy behaviour).
        self._active: ExchangeType | None = None

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

    def enabled_exchange_types(self) -> list[ExchangeType]:
        """
        Sprint 18 -- every currently-enabled exchange type, in registry
        order. Prefer this over active_exchange_type() whenever the
        caller can (and should) operate on all venues.
        """
        enabled = self._registry.enabled()

        if not enabled:
            raise RuntimeError("No enabled exchange is registered.")

        return [exchange.state.exchange for exchange in enabled]

    def set_active_exchange_type(self, exchange_type: ExchangeType) -> None:
        """
        Select the single active exchange for UI and single-venue call sites.

        The venue should already be registered. Selection is stored even when
        the venue is currently disconnected so the UI can reflect intent;
        ``active_exchange_type()`` only returns it when registered.
        """
        if not isinstance(exchange_type, ExchangeType):
            raise TypeError(
                f"exchange_type must be ExchangeType, got {type(exchange_type)!r}"
            )
        self._active = exchange_type

    def selected_exchange_type(self) -> ExchangeType | None:
        """Currently selected exchange (may be unset)."""
        return self._active

    def active_exchange_type(self) -> ExchangeType:
        """
        The single active exchange for charts / balance / legacy call sites.

        Prefers the user-selected venue when it is registered; otherwise
        falls back to the first enabled exchange.
        """
        if self._active is not None and self._registry.get(self._active) is not None:
            return self._active
        return self.enabled_exchange_types()[0]

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

    def get_base_balance(
        self,
        exchange_type: ExchangeType,
        base: str,
    ) -> float:
        return self._get_exchange(exchange_type).fetch_base_balance(base)

    def ping_ms(self, exchange_type: ExchangeType | None = None) -> float:
        """REST RTT against one enabled venue (active if omitted)."""
        if exchange_type is None:
            exchange_type = self.active_exchange_type()
        return self._get_exchange(exchange_type).ping_ms()

    def place_market_buy(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
        params: dict | None = None,
    ):
        from app.core.exchange.spot_guard import (
            ORDER_TYPE_MARKET,
            assert_client_is_spot,
            assert_market_order_type,
            assert_spot_order_params,
        )

        assert_market_order_type(ORDER_TYPE_MARKET)
        assert_spot_order_params(params)
        exchange = self._get_exchange(exchange_type)
        assert_client_is_spot(getattr(exchange, "client", None))
        return exchange.place_market_buy(
            symbol,
            amount,
            params,
        )

    def place_market_sell(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        amount: float,
        params: dict | None = None,
    ):
        from app.core.exchange.spot_guard import (
            ORDER_TYPE_MARKET,
            assert_client_is_spot,
            assert_market_order_type,
            assert_spot_order_params,
        )

        assert_market_order_type(ORDER_TYPE_MARKET)
        assert_spot_order_params(params)
        exchange = self._get_exchange(exchange_type)
        assert_client_is_spot(getattr(exchange, "client", None))
        return exchange.place_market_sell(
            symbol,
            amount,
            params,
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

    def fetch_order_by_client_id(
        self,
        exchange_type: ExchangeType,
        client_order_id: str,
        symbol: str,
    ):
        exchange = self._get_exchange(exchange_type)
        fetcher = getattr(exchange, "fetch_order_by_client_id", None)
        if not callable(fetcher):
            return None
        return fetcher(client_order_id, symbol)

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

    def fetch_ohlcv(
        self,
        exchange_type: ExchangeType,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
    ):
        return self._get_exchange(
            exchange_type
        ).fetch_ohlcv(
            symbol,
            timeframe=timeframe,
            limit=limit,
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
        from app.core.exchange.spot_guard import (
            ORDER_TYPE_MARKET,
            assert_market_order_type,
            assert_spot_order_params,
        )
        from app.core.trading.models import OrderType

        order_type = getattr(trade, "order_type", OrderType.MARKET)
        value = (
            order_type.value
            if hasattr(order_type, "value")
            else order_type
        )
        assert_market_order_type(value or ORDER_TYPE_MARKET)
        assert_spot_order_params(getattr(trade, "params", None))

        params = None
        client_order_id = getattr(trade, "client_order_id", None)
        if client_order_id:
            params = {"clientOrderId": str(client_order_id)}
            assert_spot_order_params(params)

        if trade.side == TradeSide.BUY:
            return self.place_market_buy(
                exchange_type,
                trade.symbol,
                float(trade.quantity),
                params,
            )

        return self.place_market_sell(
            exchange_type,
            trade.symbol,
            float(trade.quantity),
            params,
        )
