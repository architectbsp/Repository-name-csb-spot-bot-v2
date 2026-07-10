from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PositionState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(slots=True)
class Position:
    symbol: str
    entry_price: float
    quantity: float
    opened_at: datetime
    stop_price: float | None = None
    highest_price: float | None = None
    closed_at: datetime | None = None
    exit_price: float | None = None
    pnl: float | None = None
    pnl_percent: float | None = None
    close_reason: str | None = None
    state: PositionState = PositionState.OPEN
