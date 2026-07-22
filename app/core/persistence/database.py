"""
SQLAlchemy engine / session factory.

Sprint 13: the URL is resolved from env (`DATABASE_URL` or `DB_BACKEND`)
so SQLite, PostgreSQL and MariaDB share one ORM + repository stack.
Call `configure_database()` to rebuild the engine (tests / hot swap).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.persistence.config import load_database_config


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        # Flet UI + worker threads may share the same engine.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Drop stale pooled connections after a DB restart / network blip.
        kwargs["pool_pre_ping"] = True
    return kwargs


def create_db_engine(url: str) -> Engine:
    return create_engine(url, **_engine_kwargs(url))


def configure_database(url: str | None = None) -> Engine:
    """
    (Re)builds the process-wide engine and sessionmaker.

    When `url` is omitted, loads from environment via
    `load_database_config()`. Safe to call from tests with
    `sqlite:///:memory:`.
    """
    global _engine, _SessionLocal

    resolved = url if url is not None else load_database_config().url
    _engine = create_db_engine(resolved)
    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
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
