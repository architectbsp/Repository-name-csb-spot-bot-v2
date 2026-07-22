from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.core.exchange.models import ExchangeType


class PositionState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CloseReason(StrEnum):
    """
    Every full (or documented partial) exit must record one of these.

    Prompt / production set:
      STOP_LOSS, TRAILING_STOP, PARTIAL_TP, MANUAL, EMERGENCY, MAX_DAILY_LOSS
    Plus stage-aware extras used by this bot:
      BREAK_EVEN_STOP, MAX_DURATION
    """

    STOP_LOSS = "STOP_LOSS"
    BREAK_EVEN_STOP = "BREAK_EVEN_STOP"
    TRAILING_STOP = "TRAILING_STOP"
    PARTIAL_TP = "PARTIAL_TP"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    MAX_DURATION = "MAX_DURATION"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"


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
    # Which exchange this position was opened on (docs/BUSINESS_RULES.md
    # §9 isolated data flow). Used to guard against ever acting on a
    # position using price ticks from a different exchange.
    exchange: ExchangeType | None = None
    # Sprint 3 -- Scale Out / Partial Take Profit: PnL already banked
    # from partial exits while the position is still OPEN (separate from
    # `pnl`, which is only set once the position fully closes).
    realized_pnl: float = 0.0
    # How many partial scale-out sells have already been executed for
    # this position. Used to make sure automatic partial take-profit
    # only fires once per position.
    partial_exits_taken: int = 0
    # Which stop is currently active: "HARD" (the original fixed stop),
    # "BREAK_EVEN" (moved to entry price) or "TRAILING" (following the
    # highest price). Drives the CloseReason recorded when the stop
    # actually triggers.
    stop_stage: str = "HARD"
