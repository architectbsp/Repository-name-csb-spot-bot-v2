"""
Sprint 5 -- Trade Journal: a permanent, append-only record of every trade's
full decision history, independent from `positions` (which only tracks
currently-open positions and deletes a row the moment it closes -- see
PositionManager.handle_position_closed). This is what a future UI screen,
export, or performance-analytics module (Sprint 7) reads from to answer
"why did the bot buy/sell this, and how did it go".
"""

from dataclasses import dataclass, field
from datetime import datetime


# Why the BUY happened -- docs/BUSINESS_RULES.md §2's two entry paths.
ENTRY_PATH_A_DIRECT_RISE = "PATH_A_DIRECT_RISE"
ENTRY_PATH_B_DIP_RECOVERY = "PATH_B_DIP_RECOVERY"

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"


@dataclass(slots=True)
class TradeJournalEntry:
    symbol: str
    entry_time: datetime
    entry_price: float
    quantity: float
    entry_reason: str
    id: int | None = None
    exchange: str | None = None
    # When the coin first entered WATCH_FALLING/WATCH_RISING, before this
    # BUY was decided -- used to compute wait_minutes.
    watch_started_at: datetime | None = None
    # How long the bot watched the coin before pulling the trigger.
    wait_minutes: float | None = None
    # How many times a new high was recorded while watching (WATCH_RISING).
    rise_events: int = 0
    # How many times a new low was recorded while watching (WATCH_FALLING,
    # Path B only -- always 0 for Path A since there was no dip to track).
    fall_events: int = 0

    status: str = STATUS_OPEN

    # Scale Out / Partial Take Profit activity while the trade was open.
    partial_exit_count: int = 0
    partial_exit_pnl: float = 0.0
    partial_exits: list[dict] = field(default_factory=list)

    # Populated once the trade fully closes.
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    duration_minutes: float | None = None
    pnl: float | None = None
    pnl_percent: float | None = None
