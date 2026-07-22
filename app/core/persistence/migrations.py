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
    """
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
