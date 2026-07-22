"""
Sprint 13 -- database URL / backend resolution and PersistenceService
wiring against an in-memory SQLite engine (no external DB required).
"""

import pytest
from sqlalchemy import inspect

from app.core.persistence.config import (
    backend_from_url,
    build_database_url,
    load_database_config,
    normalize_backend,
)
from app.core.persistence.database import configure_database, create_db_engine
from app.core.persistence.migrations import sync_schema
from app.core.persistence.protocols import (
    PositionRepositoryProtocol,
    SettingsRepositoryProtocol,
    TradeJournalRepositoryProtocol,
)
from app.core.persistence.service import PersistenceService


def test_normalize_backend_aliases():
    assert normalize_backend("postgres") == "postgresql"
    assert normalize_backend("MariaDB") == "mariadb"
    assert normalize_backend("sqlite") == "sqlite"


def test_normalize_backend_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_backend("oracle")


def test_build_database_url_prefers_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    monkeypatch.setenv("DB_BACKEND", "sqlite")

    assert build_database_url() == "postgresql+psycopg://u:p@h:5432/db"


def test_build_sqlite_default_and_custom_path(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.delenv("DB_PATH", raising=False)

    assert build_database_url() == "sqlite:///csb_spot_bot.db"
    assert build_database_url(path="/tmp/bot.db") == "sqlite:////tmp/bot.db"
    assert build_database_url(path=":memory:") == "sqlite:///:memory:"


def test_build_postgresql_and_mariadb_urls(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_BACKEND", "postgresql")
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_NAME", "csb")
    monkeypatch.setenv("DB_USER", "alice")
    monkeypatch.setenv("DB_PASSWORD", "s ecret")

    url = build_database_url()
    assert url.startswith("postgresql+psycopg://")
    assert "alice" in url
    assert "db.example:5433/csb" in url
    assert "s+ecret" in url or "s%20ecret" in url

    monkeypatch.setenv("DB_BACKEND", "mariadb")
    monkeypatch.setenv("DB_PORT", "3307")
    url = build_database_url()
    assert url.startswith("mysql+pymysql://")
    assert "3307" in url


def test_backend_from_url():
    assert backend_from_url("sqlite:///x.db") == "sqlite"
    assert backend_from_url("postgresql+psycopg://u:p@h/db") == "postgresql"
    assert backend_from_url("mysql+pymysql://u:p@h/db") == "mysql"


def test_load_database_config_round_trip(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    cfg = load_database_config()
    assert cfg.is_sqlite
    assert cfg.url == "sqlite:///:memory:"


def test_load_database_config_from_config_json(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_BACKEND", raising=False)

    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"database": {"backend": "postgresql", "host": "db.local", '
        '"port": 5432, "name": "csb", "user": "alice", "password": "s3cret"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_JSON_PATH", str(config_path))

    cfg = load_database_config()
    assert cfg.is_postgres
    assert "db.local:5432/csb" in cfg.url
    assert "alice" in cfg.url


def test_database_url_env_wins_over_config_json(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"database": {"backend": "postgresql", "host": "ignored"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_JSON_PATH", str(config_path))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    cfg = load_database_config()
    assert cfg.url == "sqlite:///:memory:"


def test_persistence_service_from_url_exposes_protocol_repos():
    service = PersistenceService.from_url("sqlite:///:memory:")

    assert isinstance(service.settings_repository(), SettingsRepositoryProtocol)
    assert isinstance(service.position_repository(), PositionRepositoryProtocol)
    assert isinstance(
        service.trade_journal_repository(), TradeJournalRepositoryProtocol
    )

    inspector = inspect(service.engine)
    assert "positions" in inspector.get_table_names()
    assert "bot_settings" in inspector.get_table_names()
    tables = set(inspector.get_table_names())
    assert "trade_journals" in tables
    assert "trade_logs" in tables
    assert "symbol_blacklist" in tables


def test_create_db_engine_sqlite_memory_syncs_schema():
    engine = create_db_engine("sqlite:///:memory:")
    sync_schema(engine)
    assert "positions" in inspect(engine).get_table_names()


def test_configure_database_switches_process_engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    engine = configure_database()
    assert engine.url.database is None or str(engine.url).endswith(":memory:")
