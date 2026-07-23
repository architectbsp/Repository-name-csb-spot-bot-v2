"""R3 -- SQLite production hardening (WAL, busy_timeout, integrity, rollback)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.persistence.database import (
    _SQLITE_BUSY_TIMEOUT_MS,
    configure_database,
    create_db_engine,
    verify_sqlite_integrity,
)
from app.core.persistence.models import PositionEntity
from app.core.persistence.repository import PositionRepository, _commit
from app.core.persistence.service import PersistenceService


def test_sqlite_file_engine_enables_wal_and_foreign_keys():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "r3.db"
        engine = create_db_engine(f"sqlite:///{path}")
        with engine.connect() as conn:
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            foreign = conn.execute(text("PRAGMA foreign_keys")).scalar()
            busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
            sync = conn.execute(text("PRAGMA synchronous")).scalar()

        assert str(journal).lower() == "wal"
        assert int(foreign) == 1
        assert int(busy) == _SQLITE_BUSY_TIMEOUT_MS
        # NORMAL == 1 on SQLite
        assert int(sync) == 1
        engine.dispose()


def test_sqlite_memory_integrity_ok_and_service_starts():
    service = PersistenceService.from_url("sqlite:///:memory:")
    verify_sqlite_integrity(service.engine)
    repo = service.position_repository()
    assert repo.list() == []
    service.dispose()


def test_commit_rolls_back_on_failure(monkeypatch):
    from datetime import UTC, datetime

    service = PersistenceService.from_url("sqlite:///:memory:")
    session: Session = service.create_session()
    repo = PositionRepository(session)
    now = datetime.now(UTC)

    entity = PositionEntity(
        position_key="BINANCE:BTC/USDT",
        symbol="BTC/USDT",
        exchange="BINANCE",
        entry_price=1.0,
        quantity=1.0,
        stop_price=0.9,
        highest_price=1.0,
        opened_at=now,
        updated_at=now,
        realized_pnl=0.0,
        partial_exits_taken=0,
        stop_stage="HARD",
    )
    session.add(entity)
    _commit(session)

    def boom() -> None:
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(session, "commit", boom)

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        _commit(session)

    # Session usable again after rollback path.
    assert repo.get("BINANCE:BTC/USDT") is not None
    service.dispose()


def test_configure_database_disposes_previous_engine(monkeypatch):
    first = configure_database("sqlite:///:memory:")
    disposed = {"called": False}
    original_dispose = first.dispose

    def tracking_dispose() -> None:
        disposed["called"] = True
        original_dispose()

    monkeypatch.setattr(first, "dispose", tracking_dispose)
    second = configure_database("sqlite:///:memory:")
    assert disposed["called"] is True
    assert second is not first
