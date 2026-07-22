"""
Unified Exchange Interface -- CCXT-shaped façade over venue adapters.

Sprint 18 already provides per-venue ``BaseExchange`` implementations
(Binance / Bybit / OKX / Kraken / MEXC) plus ``RealExchangeAdapter`` /
``PaperExchangeAdapter``. This module re-exports the stable surface so
callers can depend on one import path.
"""

from __future__ import annotations

from app.core.exchange.adapter import (
    ExchangeAdapter,
    PaperExchangeAdapter,
    RealExchangeAdapter,
)
from app.core.exchange.base import BaseExchange
from app.core.exchange.factory import (
    create_exchange,
    create_exchanges,
    supported_exchange_names,
)
from app.core.exchange.manager import ExchangeManager
from app.core.exchange.models import ExchangeType, MarketMetadata, OrderResult
from app.core.exchange.registry import ExchangeRegistry

# Alias kept for docs / prompt wording ("Unified Exchange Interface").
UnifiedExchange = BaseExchange

__all__ = [
    "BaseExchange",
    "ExchangeAdapter",
    "ExchangeManager",
    "ExchangeRegistry",
    "ExchangeType",
    "MarketMetadata",
    "OrderResult",
    "PaperExchangeAdapter",
    "RealExchangeAdapter",
    "UnifiedExchange",
    "create_exchange",
    "create_exchanges",
    "supported_exchange_names",
]
