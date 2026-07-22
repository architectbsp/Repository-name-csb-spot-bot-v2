from dataclasses import dataclass

from app.core.exchange.models import ExchangeType


@dataclass(slots=True, frozen=True)
class NormalizedTicker:
    exchange: ExchangeType
    symbol: str
    last_price: float
    volume_24h: float
    change_24h: float
    timestamp: int
    # Exact price string as sent by the exchange, before float parsing
    # (docs/BUSINESS_RULES.md §9: never round exchange-sourced data for
    # display/logging). `last_price` remains a float for arithmetic
    # everywhere else in the codebase; this field exists purely so log
    # lines and UI displays can show the untouched exchange value instead
    # of a reformatted float. None when the source data was already a
    # native number (e.g. some REST responses) with no raw string to
    # preserve.
    raw_last_price: str | None = None
