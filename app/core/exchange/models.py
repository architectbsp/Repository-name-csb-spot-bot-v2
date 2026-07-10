from dataclasses import dataclass
from enum import Enum, auto


class ExchangeType(Enum):
    BINANCE = auto()
    BYBIT = auto()
    KRAKEN = auto()
    MEXC = auto()
    OKX = auto()


class ConnectionStatus(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


@dataclass(slots=True, frozen=True)
class MarketMetadata:
    symbol: str
    base: str
    quote: str
    price_precision: float | None
    amount_precision: float | None
    minimum_amount: float | None
    minimum_cost: float | None
    active: bool


@dataclass(slots=True, frozen=True)
class OrderResult:
    order_id: str
    symbol: str
    side: str
    status: str
    requested_quantity: float
    filled_quantity: float
    average_price: float | None
    cost: float | None
    raw: dict


@dataclass(slots=True, frozen=True)
class TradeFill:
    trade_id: str
    order_id: str | None
    symbol: str
    side: str
    price: float
    quantity: float
    cost: float
    fee_cost: float | None
    fee_currency: str | None
    timestamp: int | None
    raw: dict


@dataclass(slots=True)
class ExchangeState:
    exchange: ExchangeType
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    enabled: bool = False
    last_error: str | None = None
