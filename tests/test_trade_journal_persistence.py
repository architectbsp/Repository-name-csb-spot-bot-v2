"""
Sprint 5 -- Trade Journal persistence: rows must survive a mapper
round-trip (including the JSON-encoded partial_exits list) and the
repository must never delete a row once written -- a trade's history is
permanent, unlike `positions` which drops a row the instant it closes.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.domain.trade_journal import TradeJournalEntry
from app.core.persistence.database import Base
from app.core.persistence.mapper import journal_to_domain, journal_to_entity
from app.core.persistence.repository import TradeJournalRepository


def make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, future=True)()


def test_journal_entry_round_trips_through_the_mapper():
    entry = TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=datetime.now(UTC),
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        exchange="BINANCE",
        rise_events=4,
        fall_events=0,
        partial_exits=[{"exit_price": 105.0, "quantity": 0.5}],
        partial_exit_count=1,
        partial_exit_pnl=2.5,
    )

    entity = journal_to_entity(entry)
    restored = journal_to_domain(entity)

    assert restored.symbol == "BTCUSDT"
    assert restored.entry_reason == "PATH_A_DIRECT_RISE"
    assert restored.rise_events == 4
    assert restored.partial_exits == [{"exit_price": 105.0, "quantity": 0.5}]
    assert restored.partial_exit_pnl == 2.5


def test_repository_insert_then_update_persists_the_full_lifecycle():
    session = make_session()
    repository = TradeJournalRepository(session)

    entry = TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=datetime.now(UTC),
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_B_DIP_RECOVERY",
    )

    entry.id = repository.insert(journal_to_entity(entry))
    assert entry.id is not None

    entry.status = "CLOSED"
    entry.exit_price = 110.0
    entry.exit_reason = "TRAILING_STOP"
    repository.update(journal_to_entity(entry))

    reloaded = journal_to_domain(repository.get(entry.id))
    assert reloaded.status == "CLOSED"
    assert reloaded.exit_price == 110.0
    assert reloaded.exit_reason == "TRAILING_STOP"


def test_repository_never_deletes_a_closed_trade():
    session = make_session()
    repository = TradeJournalRepository(session)

    entry = TradeJournalEntry(
        symbol="ETHUSDT",
        entry_time=datetime.now(UTC),
        entry_price=50.0,
        quantity=2.0,
        entry_reason="PATH_A_DIRECT_RISE",
    )
    entry_id = repository.insert(journal_to_entity(entry))

    entry.id = entry_id
    entry.status = "CLOSED"
    repository.update(journal_to_entity(entry))

    # Unlike PositionRepository.delete(), TradeJournalRepository exposes
    # no delete method at all -- closed trades stay in list_all() forever.
    assert not hasattr(repository, "delete")
    all_rows = repository.list_all()
    assert len(all_rows) == 1
    assert all_rows[0].status == "CLOSED"


def test_get_open_by_symbol_only_returns_the_open_row():
    session = make_session()
    repository = TradeJournalRepository(session)

    old_trade = TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=datetime.now(UTC),
        entry_price=90.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        status="CLOSED",
    )
    repository.insert(journal_to_entity(old_trade))

    new_trade = TradeJournalEntry(
        symbol="BTCUSDT",
        entry_time=datetime.now(UTC),
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_B_DIP_RECOVERY",
        status="OPEN",
    )
    repository.insert(journal_to_entity(new_trade))

    found = repository.get_open_by_symbol("BTCUSDT")
    assert found is not None
    assert found.status == "OPEN"
    assert found.entry_price == 100.0
