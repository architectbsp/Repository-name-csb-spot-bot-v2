from datetime import UTC, datetime

from app.core.persistence.models import PositionEntity
from app.core.domain.position import Position


def to_entity(position: Position) -> PositionEntity:
    now = datetime.now(UTC)

    return PositionEntity(
        symbol=position.symbol,
        entry_price=position.entry_price,
        quantity=position.quantity,
        stop_price=position.stop_price,
        highest_price=position.highest_price,
        opened_at=position.opened_at,
        updated_at=now,
    )


def to_domain(entity: PositionEntity) -> Position:
    return Position(
        symbol=entity.symbol,
        entry_price=entity.entry_price,
        quantity=entity.quantity,
        opened_at=entity.opened_at,
        stop_price=entity.stop_price,
        highest_price=entity.highest_price,
    )
