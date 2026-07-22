"""
Lightweight, Alembic-free schema sync.

`Base.metadata.create_all()` only creates *missing tables* -- it never
adds columns to a table that already exists. `sync_schema()` closes that
gap for every supported backend (SQLite, PostgreSQL, MariaDB/MySQL): for
every mapped column it runs `ALTER TABLE ... ADD COLUMN ...` when needed.

Sprint 18: the `positions` primary key changed to `position_key`. SQLite
(and other engines that already have the old shape) rebuild that table
in place; fresh Postgres/MariaDB installs just get the correct schema
from create_all().
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.persistence.database import Base

# Importing the models module registers every table on Base.metadata.
import app.core.persistence.models  # noqa: F401,E402


logger = logging.getLogger(__name__)


def sync_schema(engine: Engine) -> None:
    """
    Creates any missing tables, then adds any missing columns to tables
    that already exist. Safe to call on every startup.
    """
    # Each structural migration runs in its own transaction. Nested
    # inspect(engine) / DDL inside one shared SQLite transaction can leave
    # staging tables behind (positions__sprint18) with an empty target.
    with engine.begin() as connection:
        _migrate_positions_primary_key(connection, engine)

    with engine.begin() as connection:
        _migrate_trade_journal_table_rename(connection, engine)

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    preparer = engine.dialect.identifier_preparer

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue

            existing_columns = {
                column_info["name"]
                for column_info in inspector.get_columns(table.name)
            }

            for column in table.columns:
                if column.name in existing_columns:
                    continue

                ddl_type = column.type.compile(dialect=engine.dialect)
                default_clause = _default_clause(column)
                table_sql = preparer.quote(table.name)
                column_sql = preparer.quote(column.name)

                logger.warning(
                    "[DB MIGRATION] Adding missing column %s.%s (%s) to "
                    "existing database (%s)",
                    table.name,
                    column.name,
                    ddl_type,
                    engine.dialect.name,
                )

                connection.execute(
                    text(
                        f"ALTER TABLE {table_sql} "
                        f"ADD COLUMN {column_sql} {ddl_type}"
                        f"{default_clause}"
                    )
                )


def _migrate_positions_primary_key(connection, engine: Engine) -> None:
    """
    Rebuilds `positions` when it still uses a pre-Sprint-18 primary key
    (`symbol` or `id`) so open rows survive as `BINANCE:BTC/USDT`-style
    keys. No-op when the table is missing or already on `position_key`.
    """
    # Inspect the live connection (not a pooled side-connection) so SQLite
    # DDL in this transaction stays consistent.
    inspector = inspect(connection)
    if "positions" not in inspector.get_table_names():
        return

    pk = inspector.get_pk_constraint("positions") or {}
    pk_cols = list(pk.get("constrained_columns") or [])
    columns = {
        column_info["name"]
        for column_info in inspector.get_columns("positions")
    }

    if pk_cols == ["position_key"] and "position_key" in columns:
        return

    logger.warning(
        "[DB MIGRATION] Rebuilding positions table for Sprint 18 "
        "position_key primary key (was pk=%s, dialect=%s)",
        pk_cols or "?",
        engine.dialect.name,
    )

    rows = connection.execute(text("SELECT * FROM positions")).mappings().all()
    preparer = engine.dialect.identifier_preparer
    positions = preparer.quote("positions")
    staging = preparer.quote("positions__sprint18")

    _rename_table(connection, engine, "positions", "positions__sprint18")

    Base.metadata.tables["positions"].create(bind=connection, checkfirst=False)

    now = datetime.now(UTC)
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        exchange = (row.get("exchange") or "UNKNOWN")
        if isinstance(exchange, str):
            exchange = exchange.strip().upper() or "UNKNOWN"
        else:
            exchange = "UNKNOWN"
        position_key = row.get("position_key") or f"{exchange}:{symbol}"
        opened_at = row.get("opened_at") or row.get("updated_at") or now
        updated_at = row.get("updated_at") or opened_at

        connection.execute(
            text(
                f"INSERT INTO {positions} ("
                "position_key, symbol, exchange, entry_price, quantity, "
                "stop_price, highest_price, opened_at, updated_at, "
                "realized_pnl, partial_exits_taken, stop_stage"
                ") VALUES ("
                ":position_key, :symbol, :exchange, :entry_price, :quantity, "
                ":stop_price, :highest_price, :opened_at, :updated_at, "
                ":realized_pnl, :partial_exits_taken, :stop_stage"
                ")"
            ),
            {
                "position_key": position_key,
                "symbol": symbol,
                "exchange": exchange,
                "entry_price": float(row.get("entry_price") or 0.0),
                "quantity": float(row.get("quantity") or 0.0),
                "stop_price": row.get("stop_price"),
                "highest_price": row.get("highest_price"),
                "opened_at": opened_at,
                "updated_at": updated_at,
                "realized_pnl": float(row.get("realized_pnl") or 0.0),
                "partial_exits_taken": int(row.get("partial_exits_taken") or 0),
                "stop_stage": row.get("stop_stage") or "HARD",
            },
        )

    connection.execute(text(f"DROP TABLE {staging}"))


def _rename_table(connection, engine: Engine, old: str, new: str) -> None:
    preparer = engine.dialect.identifier_preparer
    old_sql = preparer.quote(old)
    new_sql = preparer.quote(new)
    dialect = engine.dialect.name

    # Drop any leftover staging table from a previous interrupted migration.
    connection.execute(text(f"DROP TABLE IF EXISTS {new_sql}"))

    if dialect in {"mysql", "mariadb"}:
        connection.execute(text(f"RENAME TABLE {old_sql} TO {new_sql}"))
        return

    # SQLite + PostgreSQL
    connection.execute(text(f"ALTER TABLE {old_sql} RENAME TO {new_sql}"))


def _migrate_trade_journal_table_rename(connection, engine: Engine) -> None:
    """
    Renames legacy `trade_journal` → `trade_journals` when the old table
    still exists and the new name does not. No-op otherwise.
    """
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "trade_journal" not in tables or "trade_journals" in tables:
        return

    preparer = engine.dialect.identifier_preparer
    old_sql = preparer.quote("trade_journal")
    new_sql = preparer.quote("trade_journals")

    logger.warning(
        "[DB MIGRATION] Renaming table %s -> %s (%s)",
        "trade_journal",
        "trade_journals",
        engine.dialect.name,
    )
    connection.execute(text(f"ALTER TABLE {old_sql} RENAME TO {new_sql}"))


def _default_clause(column) -> str:
    """
    Best-effort DEFAULT clause so existing rows are backfilled with a
    sane value instead of NULL when the column is declared NOT NULL.
    """
    if column.default is not None and column.default.is_scalar:
        value = column.default.arg

        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f" DEFAULT '{escaped}'"

        if isinstance(value, bool):
            return f" DEFAULT {1 if value else 0}"

        if isinstance(value, (int, float)):
            return f" DEFAULT {value}"

    if not column.nullable:
        return " DEFAULT 0"

    return ""
