"""
SQLAlchemy engine / session factory.

Sprint 13: the URL is resolved from env / config.json
(`DATABASE_URL`, `config.json` → `database`, or `DB_BACKEND`) so SQLite,
PostgreSQL and MariaDB share one ORM + repository stack.
Call `configure_database()` to rebuild the engine (tests / hot swap).

R3: SQLite file DBs use WAL + busy_timeout + foreign_keys + synchronous
NORMAL for long-running multi-thread (UI / Worker / WS) durability.
"""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.core.persistence.config import load_database_config


logger = logging.getLogger(__name__)

# SQLite busy wait (ms) when another connection holds a write lock.
_SQLITE_BUSY_TIMEOUT_MS = 5000
# pysqlite connection timeout (seconds) — complements busy_timeout.
_SQLITE_CONNECT_TIMEOUT_S = 30.0


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def _is_sqlite_memory_url(url: str) -> bool:
    return _is_sqlite_url(url) and (
        ":memory:" in url or url in {"sqlite://", "sqlite://"}
    )


def _sqlite_on_connect(dbapi_connection, connection_record) -> None:
    """
    Apply production PRAGMAs on every new DB-API connection.

    WAL allows concurrent readers while a writer is active (Worker + UI).
    busy_timeout turns immediate SQLITE_BUSY into a bounded wait.
    foreign_keys must be enabled per connection on SQLite.
    synchronous=NORMAL is the WAL-recommended durability/speed balance.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {"future": True}
    if _is_sqlite_url(url):
        # Flet UI + worker threads may share the same engine.
        kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": _SQLITE_CONNECT_TIMEOUT_S,
        }
        if _is_sqlite_memory_url(url):
            # Keep a single shared in-memory connection for the engine life.
            kwargs["poolclass"] = StaticPool
        else:
            # Avoid holding pooled SQLite connections across threads longer
            # than a transaction (reduces lock amplification).
            kwargs["poolclass"] = NullPool
    else:
        # Drop stale pooled connections after a DB restart / network blip.
        kwargs["pool_pre_ping"] = True
    return kwargs


def create_db_engine(url: str) -> Engine:
    engine = create_engine(url, **_engine_kwargs(url))
    if _is_sqlite_url(url):
        event.listen(engine, "connect", _sqlite_on_connect)
    return engine


def verify_sqlite_integrity(engine: Engine) -> None:
    """
    Startup recovery gate for SQLite: fail fast on corruption.
    No-op for other dialects / empty brand-new DBs that report ``ok``.
    """
    status = sqlite_quick_check_status(engine)
    if status in {"ok", "n/a"}:
        return
    logger.critical("[DB] SQLite quick_check failed: %s", status)
    raise RuntimeError(f"SQLite integrity check failed: {status}")


def sqlite_quick_check_status(engine: Engine) -> str:
    """
    R7: non-raising integrity probe for health snapshots.
    Returns ``ok``, ``n/a`` (non-sqlite), or the pragma detail string.
    """
    if engine.dialect.name != "sqlite":
        return "n/a"

    with engine.connect() as connection:
        row = connection.execute(text("PRAGMA quick_check")).fetchone()

    status = row[0] if row is not None else None
    if status is None:
        return "unknown"
    return str(status)


def checkpoint_sqlite_wal(engine: Engine) -> None:
    """Flush WAL into the main DB file (best-effort shutdown consistency)."""
    if engine.dialect.name != "sqlite":
        return
    if _is_sqlite_memory_url(str(engine.url)):
        return

    try:
        with engine.connect() as connection:
            connection.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            connection.commit()
    except Exception:
        logger.exception("[DB] WAL checkpoint failed during shutdown")


def configure_database(url: str | None = None) -> Engine:
    """
    (Re)builds the process-wide engine and sessionmaker.

    When `url` is omitted, loads from environment via
    `load_database_config()`. Safe to call from tests with
    `sqlite:///:memory:`. Disposes any previous process engine.
    """
    global _engine, _SessionLocal

    previous = _engine
    resolved = url if url is not None else load_database_config().url
    _engine = create_db_engine(resolved)
    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        future=True,
        expire_on_commit=True,
    )

    if previous is not None and previous is not _engine:
        try:
            previous.dispose()
        except Exception:
            logger.exception("[DB] Failed to dispose previous engine")

    return _engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        configure_database()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        configure_database()
    assert _SessionLocal is not None
    return _SessionLocal


def dispose_database() -> None:
    """Dispose the process-wide engine (tests / process shutdown)."""
    global _engine, _SessionLocal
    if _engine is not None:
        checkpoint_sqlite_wal(_engine)
        _engine.dispose()
    _engine = None
    _SessionLocal = None


# Back-compat module attributes used by older imports / PersistenceService.
# Lazily configured on first access via helpers above; also expose names
# that look like the historical `engine` / `SessionLocal` constants.

def __getattr__(name: str):
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_session_factory()
    if name == "DATABASE_URL":
        return load_database_config().url
    raise AttributeError(name)
