"""
Trade Journal: permanent decision history for every trade, independent of
`positions` (which is deleted on close). Persisted as `trade_journals` +
append-only `trade_logs` (entry / in-trade extremes / partial / exit).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


# Why the BUY happened -- docs/BUSINESS_RULES.md §2's two entry paths.
ENTRY_PATH_A_DIRECT_RISE = "PATH_A_DIRECT_RISE"
ENTRY_PATH_B_DIP_RECOVERY = "PATH_B_DIP_RECOVERY"

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"

# trade_logs.event_type values
LOG_ENTRY = "ENTRY"
LOG_PRICE_EXTREME = "PRICE_EXTREME"
LOG_PARTIAL_EXIT = "PARTIAL_EXIT"
LOG_EXIT = "EXIT"


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

    # Snapshot at BUY: volume / path / price filters that justified entry.
    # Brief alias: "indicators" / trigger snapshot.
    entry_conditions: dict = field(default_factory=dict)
    # Free quote wallet (e.g. USDT) immediately after / around the BUY.
    wallet_quote_free: float | None = None

    # In-trade MFE / MAE style extremes (updated on price ticks).
    highest_price: float | None = None
    lowest_price: float | None = None
    # How many times a new high / new low was printed while OPEN.
    peak_count: int = 0
    trough_count: int = 0

    status: str = STATUS_OPEN

    # Scale Out / Partial Take Profit activity while the trade was open.
    partial_exit_count: int = 0
    partial_exit_pnl: float = 0.0
    partial_exits: list[dict] = field(default_factory=list)

    # Fees accumulated across entry / partial / exit fills (quote currency).
    commission: float | None = None

    # Populated once the trade fully closes.
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    duration_minutes: float | None = None
    pnl: float | None = None
    pnl_percent: float | None = None

    @property
    def trigger_condition(self) -> str:
        """Brief alias for ``entry_reason``."""
        return self.entry_reason

    @property
    def duration_sec(self) -> float | None:
        if self.duration_minutes is None:
            return None
        return float(self.duration_minutes) * 60.0

    @property
    def mfe_percent(self) -> float | None:
        """Max Favorable Excursion vs entry (long): peak % above entry."""
        if self.highest_price is None or self.entry_price <= 0:
            return None
        return ((self.highest_price - self.entry_price) / self.entry_price) * 100.0

    @property
    def mae_percent(self) -> float | None:
        """Max Adverse Excursion vs entry (long): trough % below entry."""
        if self.lowest_price is None or self.entry_price <= 0:
            return None
        return ((self.lowest_price - self.entry_price) / self.entry_price) * 100.0

    @property
    def mfe_usd(self) -> float | None:
        if self.highest_price is None:
            return None
        return (self.highest_price - self.entry_price) * self.quantity

    @property
    def mae_usd(self) -> float | None:
        if self.lowest_price is None:
            return None
        return (self.lowest_price - self.entry_price) * self.quantity


@dataclass(slots=True)
class TradeLog:
    journal_id: int
    event_type: str
    created_at: datetime
    message: str | None = None
    payload: dict = field(default_factory=dict)
    id: int | None = None


# Brief / Sprint 5 naming aliases.
TradeJournalLog = TradeLog
