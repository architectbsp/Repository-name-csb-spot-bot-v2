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
    tables = set(inspector.get_table_names())
    assert "positions" in tables
    assert "bot_settings" in tables
    assert "trade_journals" in tables
    assert "trade_logs" in tables
    assert "symbol_blacklist" in tables


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

    inspector = inspect(engine)
    pk = inspector.get_pk_constraint("positions")
    assert pk["constrained_columns"] == ["position_key"]

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT position_key, stop_stage, realized_pnl "
                "FROM positions WHERE symbol = 'BTCUSDT'"
            )
        ).fetchone()

    # Sprint 18 rebuilds the PK to position_key and backfills NOT NULL
    # columns so pre-existing open rows survive startup.
    assert row[0] == "UNKNOWN:BTCUSDT"
    assert row[1] is not None
    assert row[2] is not None


def test_sync_schema_migrates_symbol_pk_positions_to_position_key():
    engine = create_engine("sqlite:///:memory:", future=True)

    legacy_metadata = MetaData()
    Table(
        "positions",
        legacy_metadata,
        Column("symbol", String(30), primary_key=True),
        Column("exchange", String(20), nullable=False),
        Column("entry_price", Float, nullable=False),
        Column("quantity", Float, nullable=False),
        Column("opened_at", String(40), nullable=False),
        Column("updated_at", String(40), nullable=False),
    )
    legacy_metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO positions "
                "(symbol, exchange, entry_price, quantity, opened_at, updated_at) "
                "VALUES ('BTC/USDT', 'BINANCE', 100.0, 1.0, '2024-01-01', '2024-01-01')"
            )
        )

    sync_schema(engine)

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT position_key, symbol, exchange FROM positions"
            )
        ).fetchone()

    assert row == ("BINANCE:BTC/USDT", "BTC/USDT", "BINANCE")


def test_sync_schema_renames_legacy_trade_journal_table():
    engine = create_engine("sqlite:///:memory:", future=True)

    legacy_metadata = MetaData()
    Table(
        "trade_journal",
        legacy_metadata,
        Column("id", Integer, primary_key=True),
        Column("symbol", String(30), nullable=False),
        Column("entry_time", String(40), nullable=False),
        Column("entry_price", Float, nullable=False),
        Column("quantity", Float, nullable=False),
        Column("entry_reason", String(40), nullable=False),
        Column("status", String(10), nullable=False),
        Column("rise_events", Integer, nullable=False, default=0),
        Column("fall_events", Integer, nullable=False, default=0),
        Column("partial_exit_count", Integer, nullable=False, default=0),
        Column("partial_exit_pnl", Float, nullable=False, default=0.0),
    )
    legacy_metadata.create_all(bind=engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO trade_journal "
                "(id, symbol, entry_time, entry_price, quantity, entry_reason, "
                "status, rise_events, fall_events, partial_exit_count, "
                "partial_exit_pnl) "
                "VALUES (1, 'BTCUSDT', '2024-01-01', 100.0, 1.0, "
                "'PATH_A_DIRECT_RISE', 'OPEN', 0, 0, 0, 0.0)"
            )
        )

    sync_schema(engine)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "trade_journals" in tables
    assert "trade_journal" not in tables
    assert "trade_logs" in tables

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT symbol, status FROM trade_journals WHERE id = 1")
        ).fetchone()

    assert row == ("BTCUSDT", "OPEN")
