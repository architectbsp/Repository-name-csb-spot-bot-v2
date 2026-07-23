"""
Sprint 13 -- Repository Pattern CRUD coverage (Settings / Position / Journal).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.domain.trade_journal import STATUS_CLOSED, STATUS_OPEN
from app.core.persistence.database import Base
from app.core.persistence.models import (
    PositionEntity,
    SettingsEntity,
    TradeJournalEntity,
)
from app.core.persistence.repository import (
    PositionRepository,
    SettingsRepository,
    TradeJournalRepository,
)


def make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, future=True)()


def test_settings_repository_save_and_load_round_trip():
    session = make_session()
    repo = SettingsRepository(session)
    assert repo.load() is None

    now = datetime.now(UTC)
    entity = SettingsEntity(
        id=1,
        watch_percent=2.5,
        entry_percent=6.0,
        min_volume_usd=250_000.0,
        max_position_hours=24,
        scan_interval_seconds=300,
        trading_hours_enabled=0,
        disable_weekend_trading=0,
        trading_start_time="08:00",
        trading_end_time="23:00",
        weekend_closed=0,
        quiet_start_hour_utc=2,
        quiet_end_hour_utc=5,
        blacklist_symbols="",
        filtered_patterns="",
        stop_loss_percent=10.0,
        trailing_activation_percent=2.0,
        trailing_percent=2.5,
        cooldown_hours=4.0,
        max_open_positions=10,
        max_daily_loss_percent=20.0,
        max_balance_utilization_percent=99.5,
        max_volume_share_percent=0.1,
        position_sizing_mode=1,
        risk_per_trade_percent=1.0,
        atr_period=14,
        atr_multiplier=2.0,
        volatility_target_percent=2.0,
        volatility_lookback=20,
        kelly_fraction=0.5,
        kelly_min_trades=10,
        dynamic_lookback_trades=0,
        partial_tp_activation_percent=0.0,
        partial_tp_sell_percent=50.0,
        updated_at=now,
    )
    repo.save(entity)

    loaded = repo.load()
    assert loaded is not None
    assert loaded.watch_percent == 2.5
    assert loaded.max_open_positions == 10
    assert loaded.trading_start_time == "08:00"

    loaded.watch_percent = 3.0
    loaded.updated_at = datetime.now(UTC)
    repo.save(loaded)
    assert repo.load().watch_percent == 3.0


def test_position_repository_save_get_list_delete():
    session = make_session()
    repo = PositionRepository(session)
    now = datetime.now(UTC)

    entity = PositionEntity(
        position_key="BINANCE:BTC/USDT",
        symbol="BTC/USDT",
        exchange="BINANCE",
        entry_price=100.0,
        quantity=0.5,
        stop_price=90.0,
        highest_price=100.0,
        opened_at=now,
        updated_at=now,
        realized_pnl=0.0,
        partial_exits_taken=0,
        stop_stage="HARD",
    )
    repo.save(entity)

    got = repo.get("BINANCE:BTC/USDT")
    assert got is not None
    assert got.symbol == "BTC/USDT"
    assert got.entry_price == 100.0

    rows = repo.list()
    assert len(rows) == 1

    got.highest_price = 110.0
    got.updated_at = datetime.now(UTC)
    repo.save(got)
    assert repo.get("BINANCE:BTC/USDT").highest_price == 110.0

    assert repo.delete("BINANCE:BTC/USDT") is True
    assert repo.get("BINANCE:BTC/USDT") is None
    assert repo.delete("BINANCE:BTC/USDT") is False
    assert repo.list() == []


def test_trade_journal_repository_insert_update_query():
    session = make_session()
    repo = TradeJournalRepository(session)
    now = datetime.now(UTC)

    open_row = TradeJournalEntity(
        symbol="ETH/USDT",
        exchange="BINANCE",
        entry_time=now,
        entry_price=50.0,
        quantity=2.0,
        entry_reason="PATH_A",
        status=STATUS_OPEN,
    )
    open_id = repo.insert(open_row)
    assert open_id > 0

    found = repo.get_open_by_symbol("ETH/USDT")
    assert found is not None
    assert found.id == open_id

    found.status = STATUS_CLOSED
    found.exit_time = datetime.now(UTC)
    found.exit_price = 55.0
    found.exit_reason = "TRAILING_STOP"
    found.pnl = 10.0
    found.pnl_percent = 10.0
    repo.update(found)

    assert repo.get_open_by_symbol("ETH/USDT") is None
    closed = repo.get(open_id)
    assert closed is not None
    assert closed.status == STATUS_CLOSED
    assert closed.pnl == 10.0

    # Second open trade for query filters.
    other = TradeJournalEntity(
        symbol="SOL/USDT",
        exchange="BYBIT",
        entry_time=now,
        entry_price=10.0,
        quantity=1.0,
        entry_reason="PATH_B",
        status=STATUS_CLOSED,
        exit_time=now,
        exit_price=9.0,
        exit_reason="STOP_LOSS",
        pnl=-1.0,
    )
    repo.insert(other)

    by_symbol = repo.query(symbol="ETH/USDT")
    assert len(by_symbol) == 1
    assert by_symbol[0].symbol == "ETH/USDT"

    by_reason = repo.query(close_reason="STOP_LOSS")
    assert len(by_reason) == 1
    assert by_reason[0].symbol == "SOL/USDT"

    assert len(repo.list_all()) == 2
    assert len(repo.list_open()) == 0
