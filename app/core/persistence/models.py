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

    # RiskSettings
    stop_loss_percent: Mapped[float] = mapped_column(Float, nullable=False)
    trailing_activation_percent: Mapped[float] = mapped_column(Float, nullable=False)
    trailing_percent: Mapped[float] = mapped_column(Float, nullable=False)
    cooldown_hours: Mapped[float] = mapped_column(Float, nullable=False)
    max_open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    max_daily_loss_percent: Mapped[float] = mapped_column(Float, nullable=False)
    max_balance_utilization_percent: Mapped[float] = mapped_column(Float, nullable=False)
    max_volume_share_percent: Mapped[float] = mapped_column(Float, nullable=False)
    partial_tp_activation_percent: Mapped[float] = mapped_column(Float, nullable=False)
    partial_tp_sell_percent: Mapped[float] = mapped_column(Float, nullable=False)

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class PositionEntity(Base):
    __tablename__ = "positions"

    symbol: Mapped[str] = mapped_column(
        String(30),
        primary_key=True,
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
    Sprint 5 -- Trade Journal: one row per trade (BUY through final SELL),
    kept forever regardless of what happens to the corresponding
    `PositionEntity` row (which is deleted the moment the position
    closes). `symbol` is intentionally NOT the primary key here -- the
    same symbol is traded many times over the bot's lifetime.
    """

    __tablename__ = "trade_journal"

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
