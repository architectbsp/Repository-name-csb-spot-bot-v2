"""
Sprint 13 -- database backend selection.

Resolves a SQLAlchemy URL so the same repository layer can run on
SQLite (default), PostgreSQL or MariaDB/MySQL without call-site changes.

Precedence:
1. `DATABASE_URL` env (full SQLAlchemy URL) -- always wins
2. `config.json` → `database` section (when present)
3. `DB_BACKEND` + discrete `DB_*` env fields
4. Legacy default: `sqlite:///csb_spot_bot.db`
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus


logger = logging.getLogger(__name__)


SUPPORTED_BACKENDS = ("sqlite", "postgresql", "mariadb", "mysql")


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    backend: str
    url: str

    @property
    def is_sqlite(self) -> bool:
        return self.backend == "sqlite"

    @property
    def is_postgres(self) -> bool:
        return self.backend == "postgresql"

    @property
    def is_mysql_family(self) -> bool:
        return self.backend in {"mariadb", "mysql"}


def normalize_backend(name: str | None) -> str:
    raw = (name or "sqlite").strip().lower()
    aliases = {
        "postgres": "postgresql",
        "pgsql": "postgresql",
        "maria": "mariadb",
        "mariadb": "mariadb",
        "mysql": "mysql",
        "sqlite": "sqlite",
        "postgresql": "postgresql",
    }
    if raw not in aliases:
        raise ValueError(
            f"Unsupported DB_BACKEND {name!r}. "
            f"Supported: {', '.join(SUPPORTED_BACKENDS)}"
        )
    return aliases[raw]


def build_database_url(
    *,
    database_url: str | None = None,
    backend: str | None = None,
    host: str | None = None,
    port: str | int | None = None,
    name: str | None = None,
    user: str | None = None,
    password: str | None = None,
    path: str | None = None,
    driver: str | None = None,
) -> str:
    """
    Builds a SQLAlchemy URL. Keyword args override environment variables
    (useful for tests).
    """
    env_url = (database_url if database_url is not None else os.getenv("DATABASE_URL") or "").strip()
    if env_url:
        return env_url

    backend_name = normalize_backend(
        backend if backend is not None else os.getenv("DB_BACKEND", "sqlite")
    )

    if backend_name == "sqlite":
        db_path = (
            path
            if path is not None
            else (os.getenv("DB_PATH") or "csb_spot_bot.db")
        ).strip()
        if db_path in {":memory:", "sqlite:///:memory:"}:
            return "sqlite:///:memory:"
        if db_path.startswith("sqlite:"):
            return db_path
        return f"sqlite:///{db_path}"

    host = (host if host is not None else os.getenv("DB_HOST", "localhost")).strip()
    name = (name if name is not None else os.getenv("DB_NAME", "csb_spot_bot")).strip()
    user = (user if user is not None else os.getenv("DB_USER", "csb")).strip()
    password = (
        password if password is not None else os.getenv("DB_PASSWORD", "")
    )
    user_q = quote_plus(user)
    pass_q = quote_plus(password)

    if backend_name == "postgresql":
        port_val = str(
            port if port is not None else os.getenv("DB_PORT", "5432")
        ).strip()
        # psycopg v3 is preferred; fall back to plain postgresql:// so
        # operators can pin +psycopg2 via DATABASE_URL / DB_DRIVER.
        drv = (
            driver
            if driver is not None
            else (os.getenv("DB_DRIVER") or "psycopg")
        ).strip()
        scheme = f"postgresql+{drv}" if drv else "postgresql"
        return f"{scheme}://{user_q}:{pass_q}@{host}:{port_val}/{name}"

    # mariadb / mysql
    port_val = str(
        port if port is not None else os.getenv("DB_PORT", "3306")
    ).strip()
    drv = (
        driver
        if driver is not None
        else (os.getenv("DB_DRIVER") or "pymysql")
    ).strip()
    # SQLAlchemy accepts mysql+pymysql for both MySQL and MariaDB.
    scheme = f"mysql+{drv}" if drv else "mysql"
    return f"{scheme}://{user_q}:{pass_q}@{host}:{port_val}/{name}"


def backend_from_url(url: str) -> str:
    lowered = url.lower()
    if lowered.startswith("sqlite"):
        return "sqlite"
    if lowered.startswith("postgres"):
        return "postgresql"
    if "mariadb" in lowered.split("://", 1)[0]:
        return "mariadb"
    if lowered.startswith("mysql"):
        return "mysql"
    raise ValueError(f"Cannot infer DB backend from URL: {url!r}")


def _load_database_section_from_config_json() -> dict | None:
    """
    Optional `config.json` database block:

        {
          "database": {
            "backend": "postgresql",
            "host": "localhost",
            "port": 5432,
            "name": "csb_spot_bot",
            "user": "csb",
            "password": "secret",
            "url": "postgresql+psycopg://..."   // optional full override
          }
        }
    """
    env_path = (os.getenv("CONFIG_JSON_PATH") or "").strip()
    path = Path(env_path) if env_path else Path("config.json")
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("[DB] Failed to read %s for database config", path)
        return None
    section = payload.get("database") if isinstance(payload, dict) else None
    return section if isinstance(section, dict) else None


def load_database_config() -> DatabaseConfig:
    env_url = (os.getenv("DATABASE_URL") or "").strip()
    if env_url:
        return DatabaseConfig(backend=backend_from_url(env_url), url=env_url)

    section = _load_database_section_from_config_json()
    if section:
        section_url = (section.get("url") or "").strip()
        if section_url:
            return DatabaseConfig(
                backend=backend_from_url(section_url),
                url=section_url,
            )
        url = build_database_url(
            database_url="",  # force skip env DATABASE_URL (already empty)
            backend=section.get("backend"),
            host=section.get("host"),
            port=section.get("port"),
            name=section.get("name"),
            user=section.get("user"),
            password=section.get("password"),
            path=section.get("path"),
            driver=section.get("driver"),
        )
        # When section only has backend=sqlite, build_database_url still
        # consults DB_* env for missing fields -- intentional overlay.
        return DatabaseConfig(backend=backend_from_url(url), url=url)

    url = build_database_url()
    return DatabaseConfig(backend=backend_from_url(url), url=url)
