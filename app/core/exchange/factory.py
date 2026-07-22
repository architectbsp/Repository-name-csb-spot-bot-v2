from __future__ import annotations

from collections.abc import Callable

from app.core.config.settings import ExchangeSettings
from app.core.exchange.base import BaseExchange
from app.core.exchange.binance import BinanceExchange
from app.core.exchange.bybit import BybitExchange
from app.core.exchange.kraken import KrakenExchange
from app.core.exchange.mexc import MEXCExchange
from app.core.exchange.models import ExchangeState, ExchangeType
from app.core.exchange.okx import OKXExchange


_ExchangeFactoryFn = Callable[[ExchangeState, ExchangeSettings], BaseExchange]

# docs/BUSINESS_RULES.md §10 "Multi Exchange Support": Binance, Bybit, OKX,
# Kraken and MEXC are supported, but "only one exchange connection is
# active at a time". The EXCHANGE environment variable selects which one.
_EXCHANGE_CLASSES: dict[str, tuple[ExchangeType, _ExchangeFactoryFn]] = {
    "binance": (ExchangeType.BINANCE, BinanceExchange),
    "bybit": (ExchangeType.BYBIT, BybitExchange),
    "okx": (ExchangeType.OKX, OKXExchange),
    "kraken": (ExchangeType.KRAKEN, KrakenExchange),
    "mexc": (ExchangeType.MEXC, MEXCExchange),
}


def supported_exchange_names() -> list[str]:
    return sorted(_EXCHANGE_CLASSES.keys())


def create_exchange(settings: ExchangeSettings) -> BaseExchange:
    """
    Builds the single active exchange integration selected via the
    EXCHANGE environment variable.

    This is the only place in the codebase allowed to decide which
    exchange class to instantiate; BotEngine must never hardcode a
    specific exchange, so that WatchList/Strategy/RiskManager and their
    price stream always operate on exactly the exchange the operator
    configured, and never mix data between exchanges.
    """
    name = (settings.exchange or "").strip().lower()

    if name not in _EXCHANGE_CLASSES:
        raise ValueError(
            f"Unsupported EXCHANGE '{settings.exchange}'. "
            f"Supported values: {', '.join(supported_exchange_names())}"
        )

    exchange_type, exchange_class = _EXCHANGE_CLASSES[name]

    return exchange_class(
        ExchangeState(
            exchange=exchange_type,
            enabled=True,
        ),
        settings,
    )
