"""
Sprint 13 -- repository protocols.

Callers (PositionManager, SettingsStore, TradeJournal, PersistenceService)
depend on these interfaces, not on a concrete SQL dialect. The SQLAlchemy
implementations in `repository.py` satisfy them; a future non-SQL backend
could too.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.persistence.models import (
    PositionEntity,
    SettingsEntity,
    TradeJournalEntity,
    TradeLogEntity,
)


@runtime_checkable
class SettingsRepositoryProtocol(Protocol):
    def load(self) -> SettingsEntity | None: ...

    def save(self, entity: SettingsEntity) -> None: ...


@runtime_checkable
class PositionRepositoryProtocol(Protocol):
    def save(self, position: PositionEntity) -> None: ...

    def get(self, position_key: str) -> PositionEntity | None: ...

    def delete(self, position_key: str) -> bool: ...

    def list(self) -> list[PositionEntity]: ...


@runtime_checkable
class TradeJournalRepositoryProtocol(Protocol):
    def insert(self, entity: TradeJournalEntity) -> int: ...

    def update(self, entity: TradeJournalEntity) -> None: ...

    def get(self, entry_id: int) -> TradeJournalEntity | None: ...

    def get_open_by_symbol(self, symbol: str) -> TradeJournalEntity | None: ...

    def list_open(self) -> list[TradeJournalEntity]: ...

    def list_all(self) -> list[TradeJournalEntity]: ...

    def query(
        self,
        *,
        symbol: str | None = None,
        date_from=None,
        date_to=None,
        strategy: str | None = None,
        close_reason: str | None = None,
        status: str | None = None,
        exchange: str | None = None,
        limit: int = 200,
    ) -> list[TradeJournalEntity]: ...

    def get_last_closed_by_symbol(
        self,
        symbol: str,
    ) -> TradeJournalEntity | None: ...

    def insert_log(self, entity: TradeLogEntity) -> int: ...

    def list_logs(self, journal_id: int) -> list[TradeLogEntity]: ...
