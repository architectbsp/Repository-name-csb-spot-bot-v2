from abc import ABC, abstractmethod
from typing import Any

from app.core.exchange.models import ExchangeState, MarketMetadata, OrderResult
from app.core.exchange.stream import PriceStream


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
