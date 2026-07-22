from sqlalchemy.orm import Session

from app.core.persistence.models import PositionEntity, SettingsEntity


_SETTINGS_ROW_ID = 1


class SettingsRepository:
    def __init__(
        self,
        session: Session,
    ) -> None:
        self._session = session

    def load(self) -> SettingsEntity | None:
        return self._session.get(SettingsEntity, _SETTINGS_ROW_ID)

    def save(self, entity: SettingsEntity) -> None:
        entity.id = _SETTINGS_ROW_ID
        self._session.merge(entity)
        self._session.commit()


class PositionRepository:
    def __init__(
        self,
        session: Session,
    ) -> None:
        self._session = session

    def save(
        self,
        position: PositionEntity,
    ) -> None:
        self._session.merge(position)
        self._session.commit()

    def get(
        self,
        symbol: str,
    ) -> PositionEntity | None:
        return self._session.get(
            PositionEntity,
            symbol,
        )

    def delete(
        self,
        symbol: str,
    ) -> bool:
        position = self.get(symbol)

        if position is None:
            return False

        self._session.delete(position)
        self._session.commit()
        return True

    def list(
        self,
    ) -> list[PositionEntity]:
        return (
            self._session.query(PositionEntity)
            .all()
        )
