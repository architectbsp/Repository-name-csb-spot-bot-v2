from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.core.exchange.models import ExchangeType


class PositionState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CloseReason(StrEnum):
    """
    Every full (or documented partial) exit must record one of these.

    Sprint 3 / prompt set:
      STOP_LOSS, TAKE_PROFIT, PARTIAL_TP, TRAILING_STOP,
      MANUAL_CLOSE, EMERGENCY_EXIT, MAX_DAILY_LOSS
    Stage-aware / duration extras used by this bot:
      BREAK_EVEN_STOP, MAX_DURATION
    Backward-compatible aliases: MANUAL → MANUAL_CLOSE,
    EMERGENCY → EMERGENCY_EXIT.
    """

    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    PARTIAL_TP = "PARTIAL_TP"
    TRAILING_STOP = "TRAILING_STOP"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    MAX_DAILY_LOSS = "MAX_DAILY_LOSS"
    BREAK_EVEN_STOP = "BREAK_EVEN_STOP"
    MAX_DURATION = "MAX_DURATION"
    # Aliases (same value → Enum member alias)
    MANUAL = "MANUAL_CLOSE"
    EMERGENCY = "EMERGENCY_EXIT"


@dataclass(slots=True)
class PartialExitRecord:
    """One scale-out / partial take-profit leg while the position stays OPEN."""

    quantity: float
    exit_price: float
    realized_pnl: float
    reason: str
    remaining_quantity: float
    stop_price_after: float | None
    stop_stage_after: str
    at: datetime


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
    # Append-only in-memory history of partial exits (durable SoT for
    # completed trades remains TradeJournal.partial_exits).
    partial_exits: list[PartialExitRecord] = field(default_factory=list)
    # Which stop is currently active: "HARD" (the original fixed stop),
    # "BREAK_EVEN" (moved to entry price) or "TRAILING" (following the
    # highest price). Drives the CloseReason recorded when the stop
    # actually triggers.
    stop_stage: str = "HARD"
    # Optional fill fee from the opening BUY (quote currency) — forwarded
    # into TradeJournal.commission on entry.
    entry_commission: float | None = None

    @property
    def remaining_quantity(self) -> float:
        """Alias for open size after any scale-outs."""
        return self.quantity
