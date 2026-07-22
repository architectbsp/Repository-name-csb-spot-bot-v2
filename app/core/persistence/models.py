from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import String
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
