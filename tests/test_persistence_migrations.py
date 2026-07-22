"""
Every Sprint that adds a new persisted field (partial_tp_*, realized_pnl,
stop_stage, ...) risks breaking any pre-existing on-disk SQLite database
from a previous run, because `Base.metadata.create_all()` only creates
missing *tables*, never missing *columns*. sync_schema() must patch an
old database up to the current model in-place, additively, without
touching existing data.
"""

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, inspect, text

from app.core.persistence.migrations import sync_schema


def test_sync_schema_creates_missing_tables_from_scratch():
    engine = create_engine("sqlite:///:memory:", future=True)

    sync_schema(engine)

    inspector = inspect(engine)
    assert "positions" in inspector.get_table_names()
    assert "bot_settings" in inspector.get_table_names()


def test_sync_schema_adds_missing_columns_to_an_old_table_without_losing_data():
    engine = create_engine("sqlite:///:memory:", future=True)

    # Simulate a database created by an *older* version of the app: a
    # `bot_settings` table missing the columns Sprint 3 introduces
    # (partial_tp_activation_percent, partial_tp_sell_percent).
    legacy_metadata = MetaData()
    Table(
        "bot_settings",
        legacy_metadata,
        Column("id", Integer, primary_key=True),
        Column("watch_percent", Float, nullable=False),
    )
    legacy_metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO bot_settings (id, watch_percent) VALUES (1, 2.5)")
        )

    sync_schema(engine)

    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("bot_settings")}
    assert "partial_tp_activation_percent" in columns
    assert "partial_tp_sell_percent" in columns

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT watch_percent FROM bot_settings WHERE id = 1")
        ).fetchone()

    # Pre-existing data must survive the migration untouched.
    assert row[0] == 2.5


def test_sync_schema_is_idempotent():
    engine = create_engine("sqlite:///:memory:", future=True)

    sync_schema(engine)
    # Calling it again (e.g. on every app startup) must not raise even
    # though every table/column already exists.
    sync_schema(engine)

    inspector = inspect(engine)
    assert "bot_settings" in inspector.get_table_names()


def test_sync_schema_backfills_not_null_column_with_a_default_on_old_rows():
    engine = create_engine("sqlite:///:memory:", future=True)

    legacy_metadata = MetaData()
    Table(
        "positions",
        legacy_metadata,
        Column("id", Integer, primary_key=True),
        Column("symbol", String(20), nullable=False),
    )
    legacy_metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO positions (id, symbol) VALUES (1, 'BTCUSDT')")
        )

    sync_schema(engine)

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT stop_stage, realized_pnl FROM positions WHERE id = 1")
        ).fetchone()

    # NOT NULL columns added by the migration must backfill existing rows
    # with a usable default rather than leaving them NULL (which would
    # violate the ORM's non-nullable mapping the next time this row is
    # loaded).
    assert row[0] is not None
    assert row[1] is not None
