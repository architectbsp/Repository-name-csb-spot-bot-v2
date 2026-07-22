from sqlalchemy.orm import Session

from app.core.domain.position import Position
from app.core.persistence.database import SessionLocal
from app.core.persistence.database import engine
from app.core.persistence.mapper import to_domain
from app.core.persistence.migrations import sync_schema
from app.core.persistence.repository import PositionRepository, SettingsRepository


class PersistenceService:
    def __init__(self) -> None:
        # Creates missing tables AND adds missing columns to tables from
        # an older schema version -- see migrations.py docstring.
        sync_schema(engine)

    def create_session(self) -> Session:
        return SessionLocal()

    def position_repository(self) -> PositionRepository:
        return PositionRepository(
            self.create_session(),
        )

    def settings_repository(self) -> SettingsRepository:
        return SettingsRepository(
            self.create_session(),
        )

    def load_positions(self) -> list[Position]:
        repository = self.position_repository()

        return [
            to_domain(entity)
            for entity in repository.list()
        ]
