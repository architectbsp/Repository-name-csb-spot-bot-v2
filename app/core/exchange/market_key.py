"""
Sprint 18 -- composite market identity.

A symbol like BTC/USDT can exist on Binance and Bybit at the same time.
WatchList, PositionManager, OrderExecution quarantine and the dashboard
ticker cache must never collide those into one row -- every piece of
per-market state is keyed by (exchange, symbol) via `market_key()`.
"""

from __future__ import annotations

from app.core.exchange.models import ExchangeType


def exchange_name(exchange) -> str:
    """Normalizes ExchangeType | str | None into an uppercase name."""
    if exchange is None:
        return "UNKNOWN"
    if isinstance(exchange, ExchangeType):
        return exchange.name
    if isinstance(exchange, str):
        text = exchange.strip()
        if not text:
            return "UNKNOWN"
        # Accept "ExchangeType.BINANCE", "BINANCE", "binance".
        if "." in text:
            text = text.rsplit(".", 1)[-1]
        return text.upper()
    name = getattr(exchange, "name", None)
    if isinstance(name, str) and name:
        return name.upper()
    return str(exchange).upper()


def market_key(exchange, symbol: str) -> str:
    """Stable string key: `BINANCE:BTC/USDT`."""
    return f"{exchange_name(exchange)}:{symbol}"


def parse_market_key(key: str) -> tuple[str, str]:
    """Splits a market_key back into (exchange_name, symbol)."""
    exchange, _, symbol = key.partition(":")
    if not _ or not symbol:
        raise ValueError(f"Invalid market_key: {key!r}")
    return exchange, symbol


def try_parse_exchange_type(exchange) -> ExchangeType | None:
    name = exchange_name(exchange)
    try:
        return ExchangeType[name]
    except KeyError:
        return None
