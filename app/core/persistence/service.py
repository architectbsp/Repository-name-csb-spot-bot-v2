from sqlalchemy.orm import Session

from app.core.persistence.database import Base
from app.core.persistence.database import SessionLocal
from app.core.persistence.database import engine
from app.core.persistence.repository import PositionRepository


class PersistenceService:
    def __init__(self) -> None:
        Base.metadata.create_all(bind=engine)

    def create_session(self) -> Session:
        return SessionLocal()

    def position_repository(self) -> PositionRepository:
        return PositionRepository(
            self.create_session(),
        )
