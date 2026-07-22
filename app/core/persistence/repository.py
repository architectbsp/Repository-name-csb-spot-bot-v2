from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.persistence.models import (
    PositionEntity,
    SettingsEntity,
    SymbolBlacklistEntity,
    TradeJournalEntity,
    TradeLogEntity,
)


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
        position_key: str,
    ) -> PositionEntity | None:
        return self._session.get(
            PositionEntity,
            position_key,
        )

    def delete(
        self,
        position_key: str,
    ) -> bool:
        position = self.get(position_key)

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


class SymbolBlacklistRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[SymbolBlacklistEntity]:
        return (
            self._session.query(SymbolBlacklistEntity)
            .order_by(SymbolBlacklistEntity.symbol.asc())
            .all()
        )

    def add(self, symbol: str, note: str | None = None) -> None:
        entity = SymbolBlacklistEntity(
            symbol=symbol,
            note=note,
            created_at=datetime.now(UTC),
        )
        self._session.merge(entity)
        self._session.commit()

    def remove(self, symbol: str) -> bool:
        entity = self._session.get(SymbolBlacklistEntity, symbol)
        if entity is None:
            return False
        self._session.delete(entity)
        self._session.commit()
        return True


class TradeJournalRepository:
    """
    Sprint 5 -- Trade Journal persistence. Unlike PositionRepository,
    rows are never deleted: a trade's history is kept permanently, even
    long after the position itself has closed.
    """

    def __init__(
        self,
        session: Session,
    ) -> None:
        self._session = session

    def insert(self, entity: TradeJournalEntity) -> int:
        """Adds a brand-new journal row (the entry side of a trade) and
        returns the autoincrement id the caller must remember to update
        this same row later (partial exits, final exit). `entity.id` must
        be unset (None) so SQLAlchemy assigns a fresh autoincrement id
        instead of colliding with an existing row."""
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity.id

    def update(self, entity: TradeJournalEntity) -> None:
        self._session.merge(entity)
        self._session.commit()

    def get(self, entry_id: int) -> TradeJournalEntity | None:
        return self._session.get(TradeJournalEntity, entry_id)

    def get_open_by_symbol(self, symbol: str) -> TradeJournalEntity | None:
        return (
            self._session.query(TradeJournalEntity)
            .filter_by(symbol=symbol, status="OPEN")
            .order_by(TradeJournalEntity.id.desc())
            .first()
        )

    def list_all(self) -> list[TradeJournalEntity]:
        return (
            self._session.query(TradeJournalEntity)
            .order_by(TradeJournalEntity.entry_time.desc())
            .all()
        )

    def get_last_closed_by_symbol(
        self,
        symbol: str,
    ) -> TradeJournalEntity | None:
        """
        Sprint 6 (coin charts): once a symbol's position has closed there
        is nothing left in PositionManager/TradeJournal's in-memory
        `_open_entries` to build a chart overlay from, so the chart falls
        back to this -- the most recently closed journal row for that
        symbol.
        """
        return (
            self._session.query(TradeJournalEntity)
            .filter_by(symbol=symbol, status="CLOSED")
            .order_by(TradeJournalEntity.exit_time.desc())
            .first()
        )

    def insert_log(self, entity: TradeLogEntity) -> int:
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity.id

    def list_logs(self, journal_id: int) -> list[TradeLogEntity]:
        return (
            self._session.query(TradeLogEntity)
            .filter_by(journal_id=journal_id)
            .order_by(TradeLogEntity.id.asc())
            .all()
        )
