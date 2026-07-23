from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.core.persistence.database import Base


class SettingsEntity(Base):
    """
    Single-row table holding every user-editable strategy/risk parameter
    (docs/BUSINESS_RULES.md): no such parameter may stay hardcoded in
    source -- this row is the persisted source of truth the Settings
    screen reads from and writes to, and it is loaded once at startup
    into the live (shared, mutable) AppSettings instance so every module
    picks up the same values without a restart.
    """

    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # StrategySettings
    watch_percent: Mapped[float] = mapped_column(Float, nullable=False)
    entry_percent: Mapped[float] = mapped_column(Float, nullable=False)
    min_volume_usd: Mapped[float] = mapped_column(Float, nullable=False)
    max_position_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    # Trading hours (UTC). Defaults keep older DBs upgradeable.
    trading_hours_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weekend_closed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quiet_start_hour_utc: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    quiet_end_hour_utc: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # RiskSettings
    stop_loss_percent: Mapped[float] = mapped_column(Float, nullable=False)
    trailing_activation_percent: Mapped[float] = mapped_column(Float, nullable=False)
    trailing_percent: Mapped[float] = mapped_column(Float, nullable=False)
    cooldown_hours: Mapped[float] = mapped_column(Float, nullable=False)
    max_open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    max_daily_loss_percent: Mapped[float] = mapped_column(Float, nullable=False)
    max_balance_utilization_percent: Mapped[float] = mapped_column(Float, nullable=False)
    max_volume_share_percent: Mapped[float] = mapped_column(Float, nullable=False)
    # Sprint 8 -- Advanced Position Sizing. Defaults keep existing DBs
    # upgradeable via sync_schema() without wiping the settings row.
    position_sizing_mode: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    risk_per_trade_percent: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    atr_period: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    atr_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    volatility_target_percent: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    volatility_lookback: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    # Kelly Criterion sizing (mode=4). Fraction of full Kelly to deploy
    # (0.5 = half-Kelly) and minimum closed trades before Kelly activates.
    kelly_fraction: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    kelly_min_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    partial_tp_activation_percent: Mapped[float] = mapped_column(Float, nullable=False)
    partial_tp_sell_percent: Mapped[float] = mapped_column(Float, nullable=False)

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class SymbolBlacklistEntity(Base):
    """Operator-managed coin blacklist (Settings UI)."""

    __tablename__ = "symbol_blacklist"

    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    note: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PositionEntity(Base):
    __tablename__ = "positions"

    # Sprint 18: composite identity so the same symbol can be open on
    # two exchanges at once (`BINANCE:BTC/USDT`). `symbol` alone is no
    # longer unique across venues.
    position_key: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    symbol: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    exchange: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="UNKNOWN",
    )

    entry_price: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    quantity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    stop_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    highest_price: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    opened_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Sprint 3 -- Scale Out / Partial Take Profit / accurate close reason.
    realized_pnl: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )

    partial_exits_taken: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    stop_stage: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="HARD",
    )


class TradeJournalEntity(Base):
    """
    One row per trade (BUY through final SELL), kept forever regardless of
    what happens to the corresponding `PositionEntity` row. Table name is
    `trade_journals` (legacy `trade_journal` is renamed on sync).
    """

    __tablename__ = "trade_journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)

    entry_time: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    entry_reason: Mapped[str] = mapped_column(String(40), nullable=False)

    watch_started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wait_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    rise_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fall_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # BUY-time context: indicator/volume filters + wallet snapshot.
    entry_conditions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    wallet_quote_free: Mapped[float | None] = mapped_column(Float, nullable=True)

    # In-trade extremes (MFE/MAE style) + peak/trough print counts.
    highest_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    lowest_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trough_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(10), nullable=False, default="OPEN")

    partial_exit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    partial_exit_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # JSON-encoded list[dict] -- kept as free-form text so the schema
    # doesn't need a child table for what is purely journal detail, never
    # queried relationally.
    partial_exits_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    exit_time: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Accumulated fill fees (quote currency) across the trade lifecycle.
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)


class TradeLogEntity(Base):
    """
    Append-only event stream for a trade_journals row: ENTRY, PRICE_EXTREME,
    PARTIAL_EXIT, EXIT (and future event types).
    """

    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    journal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
