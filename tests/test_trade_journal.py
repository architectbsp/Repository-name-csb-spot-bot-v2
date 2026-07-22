"""
Sprint 5 -- Trade Journal: every trade's full decision history (why it was
bought, how long it was watched, how it exited) must be recorded and
retrievable, independent of whatever PositionManager does with the live
`positions` table.
"""

from app.core.services.trade_journal import TradeJournal


class DummyTradeJournalRepository:
    """In-memory stand-in for TradeJournalRepository, tracking insert/
    update calls the same way the real SQLite-backed one would."""

    def __init__(self):
        self._rows = {}
        self._next_id = 1
        self.insert_calls = 0
        self.update_calls = 0

    def insert(self, entity) -> int:
        entity.id = self._next_id
        self._rows[entity.id] = entity
        self._next_id += 1
        self.insert_calls += 1
        return entity.id

    def update(self, entity) -> None:
        self._rows[entity.id] = entity
        self.update_calls += 1

    def list_all(self):
        return list(self._rows.values())


def test_record_entry_creates_an_open_journal_entry():
    journal = TradeJournal()

    entry = journal.record_entry(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        exchange="BINANCE",
        rise_events=3,
        fall_events=0,
    )

    assert entry.symbol == "BTCUSDT"
    assert entry.status == "OPEN"
    assert entry.rise_events == 3
    assert journal.get_open("BTCUSDT") is entry


def test_record_exit_closes_the_entry_and_computes_duration():
    from datetime import UTC, datetime, timedelta

    journal = TradeJournal()

    entry_time = datetime.now(UTC) - timedelta(minutes=45)
    entry = journal.record_entry(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_B_DIP_RECOVERY",
    )
    entry.entry_time = entry_time  # backdate for a deterministic duration

    closed = journal.record_exit(
        "BTCUSDT",
        exit_price=110.0,
        reason="TRAILING_STOP",
        pnl=10.0,
        pnl_percent=10.0,
        exit_time=entry_time + timedelta(minutes=45),
    )

    assert closed.status == "CLOSED"
    assert closed.exit_reason == "TRAILING_STOP"
    assert closed.pnl == 10.0
    assert closed.duration_minutes == 45.0
    # Once closed, it is no longer considered "open".
    assert journal.get_open("BTCUSDT") is None


def test_record_exit_for_unknown_symbol_returns_none():
    journal = TradeJournal()

    assert journal.record_exit("NOPE", exit_price=1.0, reason="HARD_STOP") is None


def test_record_partial_exit_accumulates_without_closing():
    journal = TradeJournal()
    journal.record_entry(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=10.0,
        entry_reason="PATH_A_DIRECT_RISE",
    )

    entry = journal.record_partial_exit(
        "BTCUSDT",
        exit_price=110.0,
        quantity=5.0,
        realized_pnl=50.0,
    )

    assert entry.status == "OPEN"
    assert entry.partial_exit_count == 1
    assert entry.partial_exit_pnl == 50.0
    assert len(entry.partial_exits) == 1
    assert journal.get_open("BTCUSDT") is entry

    # A second partial exit accumulates rather than overwriting.
    journal.record_partial_exit(
        "BTCUSDT",
        exit_price=115.0,
        quantity=2.0,
        realized_pnl=30.0,
    )

    assert entry.partial_exit_count == 2
    assert entry.partial_exit_pnl == 80.0


def test_record_partial_exit_for_unknown_symbol_returns_none():
    journal = TradeJournal()

    assert (
        journal.record_partial_exit(
            "NOPE", exit_price=1.0, quantity=1.0, realized_pnl=0.0
        )
        is None
    )


def test_journal_persists_through_the_repository_when_configured():
    journal = TradeJournal()
    repository = DummyTradeJournalRepository()
    journal.set_repository(repository)

    entry = journal.record_entry(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
    )

    assert repository.insert_calls == 1
    assert entry.id == 1

    journal.record_partial_exit(
        "BTCUSDT", exit_price=105.0, quantity=0.5, realized_pnl=2.5
    )
    assert repository.update_calls == 1

    journal.record_exit("BTCUSDT", exit_price=110.0, reason="TRAILING_STOP")
    assert repository.update_calls == 2

    all_entries = journal.list_all()
    assert len(all_entries) == 1
    assert all_entries[0].status == "CLOSED"
    assert all_entries[0].partial_exit_count == 1
