from __future__ import annotations

import os
from collections.abc import Callable

from app.core.config.settings import ExchangeSettings, load_exchange_settings_list
from app.core.exchange.adapter import PaperExchangeAdapter, RealExchangeAdapter
from app.core.exchange.base import BaseExchange
from app.core.exchange.binance import BinanceExchange
from app.core.exchange.bybit import BybitExchange
from app.core.exchange.kraken import KrakenExchange
from app.core.exchange.mexc import MEXCExchange
from app.core.exchange.models import ExchangeState, ExchangeType
from app.core.exchange.okx import OKXExchange
from app.core.exchange.trading_mode import (
    TradingMode,
    paper_trading_enabled,
    require_real_api_credentials,
    resolve_trading_mode,
)


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


def paper_initial_balance() -> float:
    raw = (os.getenv("PAPER_INITIAL_BALANCE") or "10000").strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            f"Invalid PAPER_INITIAL_BALANCE={raw!r}; expected a number"
        ) from exc
    if value <= 0:
        raise ValueError("PAPER_INITIAL_BALANCE must be positive")
    return value


def _create_live_exchange(settings: ExchangeSettings) -> BaseExchange:
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


def create_exchange(settings: ExchangeSettings) -> BaseExchange:
    """
    Builds a single exchange integration from `settings`.

    PAPER → ``PaperExchangeAdapter`` (optional live prices, virtual fills).
    REAL → ``RealExchangeAdapter`` after API key/secret validation.
    """
    mode = resolve_trading_mode()
    if mode is TradingMode.REAL:
        require_real_api_credentials(settings)

    live = _create_live_exchange(settings)

    if mode is TradingMode.PAPER:
        return PaperExchangeAdapter(
            live,
            initial_quote=paper_initial_balance(),
        )

    return RealExchangeAdapter(live)


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


__all__ = [
    "TradingMode",
    "create_exchange",
    "create_exchanges",
    "paper_initial_balance",
    "paper_trading_enabled",
    "require_real_api_credentials",
    "resolve_trading_mode",
    "supported_exchange_names",
]
