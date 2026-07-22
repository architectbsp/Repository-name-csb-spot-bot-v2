"""
Sprint 12 -- Live Dashboard: one read-only snapshot of everything the
UI panels need to render, assembled by DashboardService from BotEngine
modules. Panels never poke PositionManager / WatchList / RiskManager
directly -- they only consume this DTO (keeps the UI layer thin and
unit-testable without a live exchange).
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class CoinRow:
    symbol: str
    price_display: str
    change_24h_percent: float
    volume_24h: float
    signal: str  # BUY / WAIT / HOLD
    status: str  # WatchState name or derived label


@dataclass(slots=True)
class OpenPositionRow:
    symbol: str
    entry_price: float
    current_price: float | None
    pnl_percent: float | None
    stop_stage: str
    quantity: float


@dataclass(slots=True)
class WatchRow:
    symbol: str
    direction: str  # RISE / DIP (spot is long-only; direction is the watch path)
    change_display: str
    status: str


@dataclass(slots=True)
class CooldownRow:
    symbol: str
    cooldown_until: datetime | None
    remaining_seconds: float | None


@dataclass(slots=True)
class TradeHistoryRow:
    symbol: str
    pnl_percent: float | None
    result: str  # KÂR / STOP / KAPANDI
    exit_reason: str | None


@dataclass(slots=True)
class Report24h:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0


@dataclass(slots=True)
class LogRow:
    time_display: str
    level: str
    message: str


@dataclass(slots=True)
class DashboardSnapshot:
    generated_at: datetime

    bot_running: bool = False
    exchange_name: str = "-"
    testnet: bool = False
    api_connected: bool = False

    quote_balance: float | None = None
    available_balance: float | None = None

    # Signed realized PnL so far today (can be positive). None until the
    # RiskManager has established a UTC trading day.
    daily_realized_pnl: float | None = None
    daily_pnl_percent: float | None = None
    day_start_balance: float | None = None

    open_position_count: int = 0
    active_signal_count: int = 0

    coins: list[CoinRow] = field(default_factory=list)
    open_positions: list[OpenPositionRow] = field(default_factory=list)
    watch_list: list[WatchRow] = field(default_factory=list)
    cooldowns: list[CooldownRow] = field(default_factory=list)
    trade_history: list[TradeHistoryRow] = field(default_factory=list)
    report_24h: Report24h = field(default_factory=Report24h)
    logs: list[LogRow] = field(default_factory=list)
