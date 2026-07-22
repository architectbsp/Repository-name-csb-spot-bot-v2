"""
Sprint 6 -- Coin charts: everything ChartService assembles for one
symbol's "TradingView-like" chart -- the price candles plus the
Entry/Stop/Take-Profit/Trailing overlay levels for whichever trade (open
position, or most recent closed Trade Journal entry) that symbol has.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.core.domain.candle import Candle


STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"


@dataclass(slots=True)
class ChartData:
    symbol: str
    candles: list[Candle] = field(default_factory=list)

    # None when the symbol has never had a tracked trade (nothing to
    # overlay -- just the raw price line).
    status: str | None = None

    entry_price: float | None = None
    entry_time: datetime | None = None

    stop_price: float | None = None
    # "HARD" / "BREAK_EVEN" / "TRAILING" -- which stop is currently
    # governing this position (see Position.stop_stage / §8).
    stop_stage: str | None = None

    # Reference for the trailing stop's "shadow" -- the position's
    # highest price reached so far (or at exit, for a closed trade).
    trailing_reference_price: float | None = None

    # Where the trailing stop would first activate, computed from
    # entry_price and the configured trailing_activation_percent.
    take_profit_price: float | None = None

    # Only populated once the trade has fully closed.
    exit_price: float | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None
