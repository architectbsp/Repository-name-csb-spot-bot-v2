"""
Lightweight, dependency-free schema sync for the SQLite database.

This project intentionally does not pull in Alembic. `Base.metadata.create_all()`
only ever *creates missing tables* -- it never adds columns to a table that
already exists. Every time a Sprint adds a new persisted field (e.g.
`partial_tp_activation_percent`, `realized_pnl`, `stop_stage`, ...) any
pre-existing `csb_spot_bot.db` from a previous run would otherwise start
raising `sqlite3.OperationalError: no such column: ...` the moment that
column is read or written, corrupting the whole app on startup.

`sync_schema()` closes that gap for SQLite: for every mapped table/column
declared on the ORM models, it checks `PRAGMA table_info(<table>)` and runs
`ALTER TABLE ... ADD COLUMN ...` for anything that's missing, using the
column's default value (or NULL) so existing rows stay valid. It never
drops or renames a column -- it is purely additive, matching how every
Sprint so far has evolved the schema (new optional-with-default fields).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.persistence.database import Base

# Importing the models module (for its side effect of registering every
# table on Base.metadata) is required here: whichever module imports
# sync_schema first must not have to remember to also import
# app.core.persistence.models itself, or Base.metadata.sorted_tables
# would silently be empty and create_all()/the column-diff below would
# see nothing to do.
import app.core.persistence.models  # noqa: F401,E402


logger = logging.getLogger(__name__)


def sync_schema(engine: Engine) -> None:
    """
    Creates any missing tables, then adds any missing columns to tables
    that already exist. Safe to call on every startup.

    Sprint 18: the `positions` primary key changed from `symbol` (or a
    legacy `id`) to composite `position_key`. SQLite cannot ALTER a PK,
    so that table is rebuilt in place when the old shape is detected.
    """
    with engine.begin() as connection:
        _migrate_positions_primary_key(connection, engine)

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                # Just created above by create_all(); every column is
                # already present.
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

                logger.warning(
                    "[DB MIGRATION] Adding missing column %s.%s (%s) to "
                    "existing database",
                    table.name,
                    column.name,
                    ddl_type,
                )

                connection.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        f'ADD COLUMN "{column.name}" {ddl_type}'
                        f"{default_clause}"
                    )
                )


def _migrate_positions_primary_key(connection, engine: Engine) -> None:
    """
    Rebuilds `positions` when it still uses a pre-Sprint-18 primary key
    (`symbol` or `id`) so open rows survive as `BINANCE:BTC/USDT`-style
    keys. No-op when the table is missing or already on `position_key`.
    """
    inspector = inspect(engine)
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
        "position_key primary key (was pk=%s)",
        pk_cols or "?",
    )

    # Snapshot existing rows with whatever columns are present.
    rows = connection.execute(text("SELECT * FROM positions")).mappings().all()

    connection.execute(text('DROP TABLE IF EXISTS "positions__sprint18"'))
    connection.execute(text('ALTER TABLE "positions" RENAME TO "positions__sprint18"'))

    # Recreate the mapped schema (empty) under the original name.
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
                'INSERT INTO "positions" ('
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

    connection.execute(text('DROP TABLE "positions__sprint18"'))


def _default_clause(column) -> str:
    """
    Best-effort DEFAULT clause so SQLite backfills existing rows with a
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
        # NOT NULL without a usable scalar default -- fall back to 0 so
        # the ALTER TABLE doesn't fail outright; this only matters for
        # backfilling old rows and every such field added so far is
        # numeric.
        return " DEFAULT 0"

    return ""
