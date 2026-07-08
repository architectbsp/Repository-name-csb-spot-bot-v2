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
