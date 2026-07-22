from __future__ import annotations

from collections.abc import Callable

from app.core.config.settings import ExchangeSettings, load_exchange_settings_list
from app.core.exchange.base import BaseExchange
from app.core.exchange.binance import BinanceExchange
from app.core.exchange.bybit import BybitExchange
from app.core.exchange.kraken import KrakenExchange
from app.core.exchange.mexc import MEXCExchange
from app.core.exchange.models import ExchangeState, ExchangeType
from app.core.exchange.okx import OKXExchange


_ExchangeFactoryFn = Callable[[ExchangeState, ExchangeSettings], BaseExchange]

# docs/BUSINESS_RULES.md §10 "Multi Exchange Support": Binance, Bybit, OKX,
# Kraken and MEXC are supported. Sprint 18 allows multiple enabled
# connections at once; each keeps its own credentials, balance, stream
# and market state (isolation rule).
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
    """Builds a single exchange integration from `settings`."""
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


def create_exchanges(
    settings_list: list[ExchangeSettings] | None = None,
) -> list[BaseExchange]:
    """
    Sprint 18 -- builds every enabled exchange from env
    (`EXCHANGES=...` or legacy `EXCHANGE=...`). Deduplicates by
    ExchangeType (last wins) so a typo can't register Binance twice.
    """
    configured = settings_list if settings_list is not None else load_exchange_settings_list()

    by_type: dict[ExchangeType, BaseExchange] = {}
    for settings in configured:
        exchange = create_exchange(settings)
        by_type[exchange.state.exchange] = exchange

    if not by_type:
        raise ValueError("No exchanges configured.")

    return list(by_type.values())
