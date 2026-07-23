"""
ExchangeAdapter interface + Real / Paper implementations.

Paper trading listens to real venue WebSocket/REST prices (via a wrapped
live exchange) but fills market orders against a local virtual wallet.
Backtests can construct ``PaperExchangeAdapter`` without a live venue and
drive prices through ``set_mark_price``.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Protocol, runtime_checkable

from app.core.domain.candle import Candle
from app.core.exchange.base import BaseExchange
from app.core.exchange.models import (
    ConnectionStatus,
    ExchangeState,
    ExchangeType,
    MarketMetadata,
    OrderResult,
    TradeFill,
)
from app.core.exchange.stream import PriceStream


logger = logging.getLogger(__name__)


@runtime_checkable
class ExchangeAdapter(Protocol):
    """Stable surface shared by Real and Paper adapters."""

    state: ExchangeState

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def fetch_balance(self) -> dict: ...

    def fetch_markets(self) -> dict: ...

    def fetch_tickers(self) -> dict: ...

    def fetch_my_trades(
        self,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[TradeFill]: ...

    def get_price_stream(self) -> PriceStream | None: ...

    def get_market_metadata(self, symbol: str) -> MarketMetadata: ...

    def normalize_amount(self, symbol: str, amount: float) -> float: ...

    def normalize_price(self, symbol: str, price: float) -> float: ...

    def place_market_buy(self, symbol: str, amount: float) -> OrderResult: ...

    def place_market_sell(self, symbol: str, amount: float) -> OrderResult: ...

    def fetch_order(self, order_id: str, symbol: str) -> OrderResult: ...

    def cancel_order(self, order_id: str, symbol: str) -> OrderResult: ...

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
    ) -> list[Candle]: ...


def _split_symbol(symbol: str) -> tuple[str, str]:
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        return base, quote
    # Compact forms like BTCUSDT → best-effort USDT quote.
    for quote in ("USDT", "USD", "USDC", "BUSD", "EUR"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    return symbol, "USDT"


def _wallet_row(free: float) -> dict[str, float]:
    return {"free": free, "used": 0.0, "total": free}


class RealExchangeAdapter(BaseExchange):
    """Thin adapter around a concrete live venue (Binance, Bybit, ...)."""

    def __init__(self, live: BaseExchange) -> None:
        # Share the live state object so ConnectionStatus stays in sync.
        super().__init__(live.state)
        self._live = live
        self.client = live.client

    @property
    def live(self) -> BaseExchange:
        return self._live

    @property
    def is_paper(self) -> bool:
        return False

    @property
    def trading_mode(self) -> str:
        return "REAL"

    def connect(self) -> None:
        self._live.connect()

    def disconnect(self) -> None:
        self._live.disconnect()

    def fetch_balance(self):
        return self._live.fetch_balance()

    def fetch_markets(self):
        return self._live.fetch_markets()

    def fetch_tickers(self):
        return self._live.fetch_tickers()

    def fetch_my_trades(
        self,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[TradeFill]:
        return self._live.fetch_my_trades(symbol=symbol, limit=limit)

    def get_price_stream(self) -> PriceStream | None:
        return self._live.get_price_stream()

    def get_market_metadata(self, symbol: str) -> MarketMetadata:
        return self._live.get_market_metadata(symbol)

    def normalize_amount(self, symbol: str, amount: float) -> float:
        return self._live.normalize_amount(symbol, amount)

    def normalize_price(self, symbol: str, price: float) -> float:
        return self._live.normalize_price(symbol, price)

    def place_market_buy(self, symbol: str, amount: float) -> OrderResult:
        return self._live.place_market_buy(symbol, amount)

    def place_market_sell(self, symbol: str, amount: float) -> OrderResult:
        return self._live.place_market_sell(symbol, amount)

    def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        return self._live.fetch_order(order_id, symbol)

    def cancel_order(self, order_id: str, symbol: str) -> OrderResult:
        return self._live.cancel_order(order_id, symbol)

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
    ) -> list[Candle]:
        return self._live.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def ping_ms(self) -> float:
        return self._live.ping_ms()


class PaperExchangeAdapter(BaseExchange):
    """
    Real prices (optional live venue) + local simulated wallet/orders.

    When ``live`` is provided, markets/tickers/OHLCV/streams are delegated
    to that venue. Market buys/sells never touch the live account.
    """

    def __init__(
        self,
        live: BaseExchange | None = None,
        *,
        exchange_type: ExchangeType = ExchangeType.BINANCE,
        initial_quote: float = 10_000.0,
        quote: str = "USDT",
        fee_rate: float = 0.001,
        # Adverse market impact in basis points applied to paper fills
        # (buys pay up, sells receive less). Models flash-crash slippage
        # in backtests / stress sims; 0 disables.
        slippage_bps: float = 0.0,
    ) -> None:
        state = (
            live.state
            if live is not None
            else ExchangeState(exchange=exchange_type, enabled=True)
        )
        super().__init__(state)
        self._live = live
        self.client = live.client if live is not None else None
        self._quote = quote
        self._fee_rate = max(0.0, float(fee_rate))
        self._slippage_bps = max(0.0, float(slippage_bps))
        self._balances: dict[str, dict[str, float]] = {
            quote: _wallet_row(float(initial_quote)),
        }
        self._last_prices: dict[str, float] = {}
        self._orders: dict[str, OrderResult] = {}
        self._fills: list[TradeFill] = []
        self._order_seq = 0
        self._ohlcv_cache: dict[str, list[Candle]] = {}
        self._markets_override: dict[str, Any] | None = None

    @property
    def live(self) -> BaseExchange | None:
        return self._live

    @property
    def is_paper(self) -> bool:
        return True

    @property
    def trading_mode(self) -> str:
        return "PAPER"

    def set_mark_price(self, symbol: str, price: float) -> None:
        if price <= 0:
            raise ValueError(f"Mark price must be positive, got {price}")
        self._last_prices[symbol] = float(price)

    def seed_ohlcv(self, symbol: str, candles: list[Candle]) -> None:
        """Optional local candle cache used by backtests / ATR sizing."""
        self._ohlcv_cache[symbol] = list(candles)

    def connect(self) -> None:
        self.state.status = ConnectionStatus.CONNECTING
        self.state.last_error = None
        try:
            if self._live is not None:
                self._live.connect()
                self.state.status = self._live.state.status
                self.state.last_error = self._live.state.last_error
            else:
                self.state.status = ConnectionStatus.CONNECTED
        except Exception as exc:
            self.state.status = ConnectionStatus.ERROR
            self.state.last_error = str(exc)
            raise

    def disconnect(self) -> None:
        if self._live is not None:
            self._live.disconnect()
        self.state.status = ConnectionStatus.DISCONNECTED

    def fetch_balance(self):
        # Sprint 14 isolation: never read the live venue wallet in PAPER.
        # ccxt-shaped free/used/total maps plus per-asset rows.
        free = {asset: row["free"] for asset, row in self._balances.items()}
        used = {asset: row["used"] for asset, row in self._balances.items()}
        total = {asset: row["total"] for asset, row in self._balances.items()}
        payload: dict[str, Any] = {
            "free": free,
            "used": used,
            "total": total,
        }
        payload.update(self._balances)
        return payload

    def fetch_my_trades(
        self,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[TradeFill]:
        # Local paper fills only -- never live private trade history.
        fills = self._fills
        if symbol is not None:
            fills = [f for f in fills if f.symbol == symbol]
        if limit is not None:
            fills = fills[-limit:]
        return list(fills)

    def fetch_markets(self):
        if self._live is not None:
            return self._live.fetch_markets()
        if self._markets_override is None:
            self._markets_override = {}
        return self._markets_override

    def fetch_tickers(self):
        if self._live is not None:
            tickers = self._live.fetch_tickers()
            for symbol, ticker in (tickers or {}).items():
                last = None
                if isinstance(ticker, dict):
                    last = ticker.get("last") or ticker.get("close")
                if last is not None:
                    try:
                        self._last_prices[symbol] = float(last)
                    except (TypeError, ValueError):
                        pass
            return tickers

        now_ms = int(time.time() * 1000)
        return {
            symbol: {
                "symbol": symbol,
                "last": price,
                "close": price,
                "bid": price,
                "ask": price,
                "quoteVolume": 0.0,
                "percentage": 0.0,
                "timestamp": now_ms,
            }
            for symbol, price in self._last_prices.items()
        }

    def get_price_stream(self) -> PriceStream | None:
        # Paper mode listens to the real venue stream when available.
        if self._live is not None:
            return self._live.get_price_stream()
        return None

    def get_market_metadata(self, symbol: str) -> MarketMetadata:
        if self._live is not None:
            return self._live.get_market_metadata(symbol)

        base, quote = _split_symbol(symbol)
        return MarketMetadata(
            symbol=symbol,
            base=base,
            quote=quote,
            price_precision=8,
            amount_precision=8,
            minimum_amount=1e-8,
            minimum_cost=1.0,
            active=True,
        )

    def normalize_amount(self, symbol: str, amount: float) -> float:
        if self._live is not None:
            try:
                return self._live.normalize_amount(symbol, amount)
            except Exception:
                logger.debug(
                    "[PAPER] live normalize_amount failed; using local precision",
                    exc_info=True,
                )
        return _truncate(amount, 8)

    def normalize_price(self, symbol: str, price: float) -> float:
        if self._live is not None:
            try:
                return self._live.normalize_price(symbol, price)
            except Exception:
                logger.debug(
                    "[PAPER] live normalize_price failed; using local precision",
                    exc_info=True,
                )
        return _truncate(price, 8)

    def place_market_buy(self, symbol: str, amount: float) -> OrderResult:
        from app.core.exchange.spot_guard import (
            ORDER_TYPE_MARKET,
            assert_market_order_type,
        )

        assert_market_order_type(ORDER_TYPE_MARKET)
        amount = self.normalize_amount(symbol, amount)
        if amount <= 0:
            raise ValueError(f"Invalid buy amount for {symbol}: {amount}")

        price = self._apply_slippage(self._resolve_price(symbol), side="BUY")
        base, quote = self._base_quote(symbol)
        cost = amount * price
        fee = cost * self._fee_rate
        total_debit = cost + fee

        quote_free = self._free(quote)
        if quote_free < total_debit:
            raise RuntimeError(
                f"Paper wallet insufficient {quote}: need {total_debit}, "
                f"have {quote_free}"
            )

        self._debit(quote, total_debit)
        self._credit(base, amount)
        return self._record_fill(
            symbol=symbol,
            side="BUY",
            amount=amount,
            price=price,
            cost=cost,
            fee=fee,
            fee_currency=quote,
        )

    def place_market_sell(self, symbol: str, amount: float) -> OrderResult:
        from app.core.exchange.spot_guard import (
            ORDER_TYPE_MARKET,
            assert_market_order_type,
        )

        assert_market_order_type(ORDER_TYPE_MARKET)
        amount = self.normalize_amount(symbol, amount)
        if amount <= 0:
            raise ValueError(f"Invalid sell amount for {symbol}: {amount}")

        price = self._apply_slippage(self._resolve_price(symbol), side="SELL")
        base, quote = self._base_quote(symbol)
        base_free = self._free(base)
        if base_free < amount:
            raise RuntimeError(
                f"Paper wallet insufficient {base}: need {amount}, "
                f"have {base_free}"
            )

        proceeds = amount * price
        fee = proceeds * self._fee_rate
        net = proceeds - fee

        self._debit(base, amount)
        self._credit(quote, net)
        return self._record_fill(
            symbol=symbol,
            side="SELL",
            amount=amount,
            price=price,
            cost=proceeds,
            fee=fee,
            fee_currency=quote,
        )

    def fetch_order(self, order_id: str, symbol: str) -> OrderResult:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"Unknown paper order: {order_id}")
        return order

    def cancel_order(self, order_id: str, symbol: str) -> OrderResult:
        order = self.fetch_order(order_id, symbol)
        if order.status in {"CLOSED", "FILLED", "CANCELED", "CANCELLED"}:
            return order
        canceled = OrderResult(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            status="CANCELED",
            requested_quantity=order.requested_quantity,
            filled_quantity=0.0,
            average_price=None,
            cost=None,
            raw={**order.raw, "status": "canceled"},
        )
        self._orders[order_id] = canceled
        return canceled

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 200,
    ) -> list[Candle]:
        if self._live is not None:
            return self._live.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                limit=limit,
            )
        cached = self._ohlcv_cache.get(symbol, [])
        if not cached:
            return []
        return cached[-limit:] if limit else list(cached)

    def ping_ms(self) -> float:
        if self._live is not None:
            return self._live.ping_ms()
        started = time.perf_counter()
        self.fetch_balance()
        return (time.perf_counter() - started) * 1000.0

    def _base_quote(self, symbol: str) -> tuple[str, str]:
        try:
            meta = self.get_market_metadata(symbol)
            return meta.base, meta.quote
        except Exception:
            return _split_symbol(symbol)

    def _resolve_price(self, symbol: str) -> float:
        price = self._last_prices.get(symbol)
        if price is not None and price > 0:
            return price

        if self._live is not None:
            tickers = self._live.fetch_tickers()
            ticker = (tickers or {}).get(symbol) or {}
            last = ticker.get("last") or ticker.get("close")
            if last is not None:
                price = float(last)
                self._last_prices[symbol] = price
                return price

        raise RuntimeError(f"No mark price available for {symbol}")

    def _apply_slippage(self, price: float, *, side: str) -> float:
        if self._slippage_bps <= 0 or price <= 0:
            return price
        frac = self._slippage_bps / 10_000.0
        if side.upper() == "BUY":
            return price * (1.0 + frac)
        return price * (1.0 - frac)

    def _free(self, asset: str) -> float:
        row = self._balances.get(asset)
        return float(row["free"]) if row else 0.0

    def _credit(self, asset: str, amount: float) -> None:
        row = self._balances.setdefault(asset, _wallet_row(0.0))
        row["free"] += amount
        row["total"] = row["free"] + row["used"]

    def _debit(self, asset: str, amount: float) -> None:
        row = self._balances.setdefault(asset, _wallet_row(0.0))
        if row["free"] < amount:
            raise RuntimeError(f"Paper wallet underflow for {asset}")
        row["free"] -= amount
        row["total"] = row["free"] + row["used"]

    def _record_fill(
        self,
        *,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        cost: float,
        fee: float,
        fee_currency: str,
    ) -> OrderResult:
        self._order_seq += 1
        order_id = f"paper-{self._order_seq}"
        trade_id = f"paper-fill-{self._order_seq}"
        ts = int(time.time() * 1000)

        order = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            status="CLOSED",
            requested_quantity=amount,
            filled_quantity=amount,
            average_price=price,
            cost=cost,
            raw={
                "id": order_id,
                "symbol": symbol,
                "side": side.lower(),
                "status": "closed",
                "amount": amount,
                "filled": amount,
                "average": price,
                "cost": cost,
                "paper": True,
            },
        )
        self._orders[order_id] = order
        self._fills.append(
            TradeFill(
                trade_id=trade_id,
                order_id=order_id,
                symbol=symbol,
                side=side,
                price=price,
                quantity=amount,
                cost=cost,
                fee_cost=fee,
                fee_currency=fee_currency,
                timestamp=ts,
                raw={"paper": True},
            )
        )
        logger.info(
            "[PAPER] %s %s amount=%.8f price=%.8f fee=%.8f %s",
            side,
            symbol,
            amount,
            price,
            fee,
            fee_currency,
        )
        return order


def _truncate(value: float, decimals: int) -> float:
    if value == 0:
        return 0.0
    factor = 10**decimals
    return math.floor(value * factor + 1e-12) / factor
