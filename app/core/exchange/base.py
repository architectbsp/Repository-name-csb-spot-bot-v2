import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import ccxt

from app.core.domain.candle import Candle
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
        # Every concrete subclass assigns its own ccxt client instance to
        # this attribute in its __init__ (after calling super().__init__).
        # Declared here so fetch_order/cancel_order below (Sprint 4 order
        # reconciliation) can be implemented once instead of duplicated
        # per exchange.
        self.client: Any = None

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

    def fetch_base_balance(self, base: str) -> float:
        """Free balance of a base asset (e.g. BTC from BTC/USDT)."""
        balance = self.fetch_balance()
        wallet = balance.get(base)
        if wallet is None:
            return 0.0
        return float(wallet.get("free", 0.0))

    def ping_ms(self) -> float:
        """Round-trip latency to the exchange REST API (ms)."""
        started = time.perf_counter()
        if self.client is not None and hasattr(self.client, "fetch_time"):
            self.client.fetch_time()
        else:
            self.fetch_balance()
        return (time.perf_counter() - started) * 1000.0

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
        Market orders (the only legal order type -- docs/BUSINESS_RULES.md
        §3 / §10) do not submit a price; this helper exists for display /
        overlay math and must only truncate at submission boundaries
        (see truncate_to_precision).
        """
        ...

    def _guard_spot_market_order(self, params=None) -> None:
        """Sprint 13 -- refuse futures/margin clients and non-market params."""
        from app.core.exchange.spot_guard import (
            ORDER_TYPE_MARKET,
            SpotOnlyViolationException,
            assert_client_is_spot,
            assert_market_order_type,
            assert_spot_order_params,
        )

        assert_client_is_spot(getattr(self, "client", None))
        assert_market_order_type(ORDER_TYPE_MARKET)
        assert_spot_order_params(params)

    def place_limit_order(self, *args, **kwargs):
        """Limit orders are permanently disabled for this spot bot."""
        from app.core.exchange.spot_guard import SpotOnlyViolationException

        raise SpotOnlyViolationException(
            "Market-order guard: limit orders are not allowed"
        )

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        """
        Catch-all: any non-market create_order attempt is rejected before
        it reaches the exchange client.
        """
        from app.core.exchange.spot_guard import (
            assert_market_order_type,
            assert_spot_order_params,
        )

        assert_market_order_type(type)
        assert_spot_order_params(params)
        # Even for market, prefer the dedicated helpers.
        side_u = str(side).upper()
        if side_u == "BUY":
            return self.place_market_buy(symbol, amount)
        if side_u == "SELL":
            return self.place_market_sell(symbol, amount)
        from app.core.exchange.spot_guard import SpotOnlyViolationException

        raise SpotOnlyViolationException(
            f"Spot-only guard: unsupported side '{side}'"
        )

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

    def fetch_order(
        self,
        order_id: str,
        symbol: str,
    ) -> OrderResult:
        """
        Sprint 4 order reconciliation: re-fetches the current state of a
        previously submitted order. Used when the initial submission
        response reports the order as still open (e.g. thin order book on
        a market order) instead of immediately filled, so the caller can
        poll for a bounded time before deciding whether to cancel it.
        """
        return self._normalize_order_result(
            self.client.fetch_order(order_id, symbol)
        )

    def cancel_order(
        self,
        order_id: str,
        symbol: str,
    ) -> OrderResult:
        """
        Sprint 4: cancels an order that never filled within the pending
        poll window. Callers must retry this a bounded number of times
        (network hiccups can make a single cancel attempt fail) and treat
        repeated failure as needing manual reconciliation rather than
        silently assuming the order went away.
        """
        return self._normalize_order_result(
            self.client.cancel_order(order_id, symbol)
        )

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
    ) -> list[Candle]:
        """
        Sprint 6 (coin charts): fetches recent candles for `symbol` from
        this exchange's own REST API via ccxt. Only ever called for the
        currently-active exchange -- see ExchangeManager.active_exchange_type
        and docs/BUSINESS_RULES.md's data-isolation rule -- so a chart never
        mixes candles from one exchange with a position opened on another.

        Returns an empty list (never raises) on any network/API failure;
        the chart UI already renders a friendly "no data" state for that.
        """
        try:
            raw_rows = self.client.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit,
            )
        except Exception:
            logger.exception(
                "fetch_ohlcv failed for %s (timeframe=%s)",
                symbol,
                timeframe,
            )
            return []

        return [Candle.from_ccxt_row(row) for row in raw_rows or []]

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
