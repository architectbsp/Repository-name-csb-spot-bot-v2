from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.domain.position import Position
from app.core.persistence.database import (
    checkpoint_sqlite_wal,
    create_db_engine,
    get_engine,
    get_session_factory,
    verify_sqlite_integrity,
)
from app.core.persistence.mapper import to_domain
from app.core.persistence.migrations import sync_schema
from app.core.persistence.protocols import (
    PositionRepositoryProtocol,
    SettingsRepositoryProtocol,
    TradeJournalRepositoryProtocol,
)
from app.core.persistence.repository import (
    PositionRepository,
    SettingsRepository,
    SymbolBlacklistRepository,
    TradeJournalRepository,
)


class PersistenceService:
    """
    Sprint 13 -- single entry point for persistence.

    Repositories are returned as protocol types so callers never couple to
    a concrete SQL dialect. The engine URL comes from env (`DATABASE_URL`
    / `DB_BACKEND`) unless an explicit `engine` is injected (tests).
    """

    def __init__(
        self,
        engine: Engine | None = None,
        session_factory: sessionmaker | None = None,
    ) -> None:
        if engine is None:
            self._engine = get_engine()
            self._session_factory = session_factory or get_session_factory()
        else:
            self._engine = engine
            self._session_factory = session_factory or sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                future=True,
                expire_on_commit=True,
            )

        # Creates missing tables AND adds missing columns to tables from
        # an older schema version -- see migrations.py docstring.
        sync_schema(self._engine)
        # R3: refuse to run against a corrupted SQLite file.
        verify_sqlite_integrity(self._engine)

    @classmethod
    def from_url(cls, url: str) -> "PersistenceService":
        """Builds an isolated PersistenceService for an explicit URL
        without replacing the process-wide engine."""
        engine = create_db_engine(url)
        return cls(engine=engine)

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_session(self) -> Session:
        return self._session_factory()

    def position_repository(self) -> PositionRepositoryProtocol:
        return PositionRepository(self.create_session())

    def settings_repository(self) -> SettingsRepositoryProtocol:
        return SettingsRepository(self.create_session())

    def trade_journal_repository(self) -> TradeJournalRepositoryProtocol:
        return TradeJournalRepository(self.create_session())

    def symbol_blacklist_repository(self) -> SymbolBlacklistRepository:
        return SymbolBlacklistRepository(self.create_session())

    def load_positions(self) -> list[Position]:
        repository = self.position_repository()
        try:
            return [to_domain(entity) for entity in repository.list()]
        finally:
            repository.close()

    def dispose(self) -> None:
        """
        R3 shutdown consistency: checkpoint WAL (file SQLite) then dispose
        connections. Safe to call more than once.
        """
        checkpoint_sqlite_wal(self._engine)
        self._engine.dispose()
