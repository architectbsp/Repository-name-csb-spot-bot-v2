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


@dataclass(slots=True)
class ExchangeState:
    exchange: ExchangeType
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED
    enabled: bool = False
    last_error: str | None = None
