import logging
from abc import ABC, abstractmethod
from typing import Any

import ccxt

from app.core.exchange.models import (
    ExchangeState,
    MarketMetadata,
    OrderResult,
    TradeFill,
)
from app.core.exchange.stream import PriceStream


logger = logging.getLogger(__name__)


def truncate_to_precision(
    client: Any,
    symbol: str,
    value: float,
    *,
    precision_key: str,
) -> float:
    """
    Truncates (never rounds) `value` to the exchange's LOT_SIZE/stepSize
    (precision_key="amount") or PRICE_FILTER/tickSize
    (precision_key="price") precision for `symbol`.

    docs/BUSINESS_RULES.md §9 "Order Submission Armor": this truncation
    must only ever be applied at the moment an order is actually
    submitted to the exchange, never earlier while data is only being
    read, compared or logged. ccxt's own `price_to_precision` rounds by
    default (only `amount_to_precision` truncates), so TRUNCATE is
    requested explicitly here for both cases to guarantee we never submit
    a quantity/price the exchange would reject or that overspends the
    wallet.
    """
    market = client.market(symbol)
    precision = market["precision"][precision_key]

    result = client.decimal_to_precision(
        value,
        ccxt.TRUNCATE,
        precision,
        client.precisionMode,
        client.paddingMode,
    )

    return float(result)


def enable_sandbox_mode(client: Any, *, testnet: bool, exchange_name: str) -> None:
    """
    Safely enables ccxt's sandbox/testnet mode for `client` when `testnet`
    is True.

    Not every exchange ccxt integration ships a sandbox/test environment
    (e.g. Kraken spot and MEXC do not). Calling `set_sandbox_mode` on those
    either no-ops or raises depending on the ccxt version, so failures are
    caught and logged loudly instead of silently leaving the caller unsure
    whether real-money endpoints are in use.
    """
    if not testnet:
        return

    try:
        client.set_sandbox_mode(True)
    except Exception as exc:
        logger.warning(
            "[%s] Testnet requested but ccxt has no sandbox environment "
            "for this exchange (%s). Requests will target the LIVE "
            "endpoint -- do not trade real funds unless that is intended.",
            exchange_name,
            exc,
        )


class BaseExchange(ABC):
    def __init__(self, state: ExchangeState) -> None:
        self.state = state
        self._markets_cache: dict[str, Any] | None = None
        self._price_stream: PriceStream | None = None

    @abstractmethod
    def connect(self) -> None:
        ...

    @abstractmethod
    def disconnect(self) -> None:
        ...

    @abstractmethod
    def fetch_balance(self):
        ...

    def fetch_quote_balance(
        self,
        quote: str = "USDT",
    ) -> float:
        balance = self.fetch_balance()

        wallet = balance.get(quote)

        if wallet is None:
            return 0.0

        return float(wallet.get("free", 0.0))

    @abstractmethod
    def fetch_markets(self):
        ...

    @abstractmethod
    def fetch_tickers(self):
        ...

    @abstractmethod
    def fetch_my_trades(
        self,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[TradeFill]:
        ...

    def get_price_stream(self) -> PriceStream | None:
        return self._price_stream

    @abstractmethod
    def get_market_metadata(
        self,
        symbol: str,
    ) -> MarketMetadata:
        ...

    @abstractmethod
    def normalize_amount(
        self,
        symbol: str,
        amount: float,
    ) -> float:
        ...

    @abstractmethod
    def normalize_price(
        self,
        symbol: str,
        price: float,
    ) -> float:
        """
        Truncates `price` to this exchange's PRICE_FILTER/tickSize.
        Forward-looking infrastructure for any future limit-order support;
        market orders (the only order type currently placed, per
        docs/BUSINESS_RULES.md §10) do not submit a price. Must only be
        called at the moment of order submission (see truncate_to_precision).
        """
        ...

    @abstractmethod
    def place_market_buy(
        self,
        symbol: str,
        amount: float,
    ):
        ...

    @abstractmethod
    def place_market_sell(
        self,
        symbol: str,
        amount: float,
    ):
        ...

    def _normalize_order_result(
        self,
        order: dict,
    ) -> OrderResult:
        return OrderResult(
            order_id=str(order.get("id", "")),
            symbol=str(order.get("symbol", "")),
            side=str(order.get("side", "")).upper(),
            status=str(order.get("status", "")).upper(),
            requested_quantity=float(order.get("amount") or 0.0),
            filled_quantity=float(order.get("filled") or 0.0),
            average_price=(
                float(order["average"])
                if order.get("average") is not None
                else None
            ),
            cost=(
                float(order["cost"])
                if order.get("cost") is not None
                else None
            ),
            raw=order,
        )

    def _normalize_trade(
        self,
        trade: dict,
    ) -> TradeFill:
        fee = trade.get("fee") or {}

        return TradeFill(
            trade_id=str(trade.get("id", "")),
            order_id=(
                str(trade["order"])
                if trade.get("order") is not None
                else None
            ),
            symbol=str(trade.get("symbol", "")),
            side=str(trade.get("side", "")).upper(),
            price=float(trade.get("price") or 0.0),
            quantity=float(trade.get("amount") or 0.0),
            cost=float(trade.get("cost") or 0.0),
            fee_cost=(
                float(fee["cost"])
                if fee.get("cost") is not None
                else None
            ),
            fee_currency=fee.get("currency"),
            timestamp=trade.get("timestamp"),
            raw=trade,
        )
