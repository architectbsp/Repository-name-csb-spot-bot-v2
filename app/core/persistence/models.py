from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import String
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.core.persistence.database import Base


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
