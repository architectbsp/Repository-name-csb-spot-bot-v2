"""
Sprint 5 -- Trade Journal: every trade's full decision history (why it was
bought, how long it was watched, how it exited) must be recorded and
retrievable, independent of whatever PositionManager does with the live
`positions` table.
"""

import pytest

from app.core.services.trade_journal import TradeJournal


class DummyTradeJournalRepository:
    """In-memory stand-in for TradeJournalRepository, tracking insert/
    update calls the same way the real SQLite-backed one would."""

    def __init__(self):
        self._rows = {}
        self._logs = []
        self._next_id = 1
        self._next_log_id = 1
        self.insert_calls = 0
        self.update_calls = 0
        self.insert_log_calls = 0

    def insert(self, entity) -> int:
        entity.id = self._next_id
        self._rows[entity.id] = entity
        self._next_id += 1
        self.insert_calls += 1
        return entity.id

    def update(self, entity) -> None:
        self._rows[entity.id] = entity
        self.update_calls += 1

    def insert_log(self, entity) -> int:
        entity.id = self._next_log_id
        self._next_log_id += 1
        self._logs.append(entity)
        self.insert_log_calls += 1
        return entity.id

    def list_logs(self, journal_id: int):
        return [log for log in self._logs if log.journal_id == journal_id]

    def list_all(self):
        return list(self._rows.values())

    def list_open(self):
        return [row for row in self._rows.values() if row.status == "OPEN"]

    def query(
        self,
        *,
        symbol=None,
        date_from=None,
        date_to=None,
        strategy=None,
        close_reason=None,
        status=None,
        exchange=None,
        limit=200,
    ):
        rows = list(self._rows.values())
        out = []
        for row in rows:
            if symbol and row.symbol != symbol:
                continue
            if exchange and row.exchange != exchange:
                continue
            if status and row.status != status:
                continue
            if close_reason and row.exit_reason != close_reason:
                continue
            if date_from is not None and row.entry_time < date_from:
                continue
            if date_to is not None and row.entry_time > date_to:
                continue
            if strategy:
                blob = getattr(row, "entry_conditions_json", None) or ""
                if strategy not in blob:
                    continue
            out.append(row)
        out.sort(key=lambda r: r.entry_time, reverse=True)
        return out[:limit]


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
        entry_conditions={"volume_24h": 1_000_000},
        wallet_quote_free=250.0,
    )

    assert repository.insert_calls == 1
    assert entry.id == 1
    assert entry.wallet_quote_free == 250.0
    assert entry.entry_conditions["volume_24h"] == 1_000_000
    assert repository.insert_log_calls >= 1

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


def test_record_price_update_tracks_extremes_and_peak_trough_counts():
    journal = TradeJournal()
    repository = DummyTradeJournalRepository()
    journal.set_repository(repository)

    journal.record_entry(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
    )

    # Same price -- no extreme change.
    entry = journal.record_price_update("BTCUSDT", 100.0)
    assert entry.peak_count == 0
    assert entry.trough_count == 0

    entry = journal.record_price_update("BTCUSDT", 110.0)
    assert entry.highest_price == 110.0
    assert entry.peak_count == 1

    entry = journal.record_price_update("BTCUSDT", 90.0)
    assert entry.lowest_price == 90.0
    assert entry.trough_count == 1
    assert entry.mfe_percent == 10.0
    assert entry.mae_percent == -10.0

    log_types = [log.event_type for log in repository.list_logs(entry.id)]
    assert "ENTRY" in log_types
    assert "PRICE_EXTREME" in log_types


def test_exit_records_duration_sec_mfe_mae_and_close_reason():
    from datetime import UTC, datetime, timedelta

    journal = TradeJournal()
    entry = journal.record_entry(
        symbol="ETHUSDT",
        entry_price=100.0,
        quantity=2.0,
        entry_reason="PATH_A_DIRECT_RISE",
        commission=0.1,
    )
    entry.entry_time = datetime.now(UTC) - timedelta(seconds=120)
    journal.record_price_update("ETHUSDT", 112.0)
    journal.record_price_update("ETHUSDT", 95.0)

    closed = journal.record_exit(
        "ETHUSDT",
        exit_price=105.0,
        reason="MANUAL_CLOSE",
        pnl=10.0,
        pnl_percent=5.0,
        exit_time=entry.entry_time + timedelta(seconds=120),
        commission=0.05,
    )

    assert closed.exit_reason == "MANUAL_CLOSE"
    assert closed.duration_sec == 120.0
    assert closed.mfe_percent == 12.0
    assert closed.mae_percent == -5.0
    assert closed.commission == pytest.approx(0.15)
    assert closed.pnl == 10.0
    assert closed.trigger_condition == "PATH_A_DIRECT_RISE"


def test_query_filters_by_symbol_strategy_and_close_reason():
    from datetime import UTC, datetime

    journal = TradeJournal()
    repository = DummyTradeJournalRepository()
    journal.set_repository(repository)

    journal.record_entry(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        entry_conditions={"strategy": "dip_hunter"},
    )
    journal.record_exit("BTCUSDT", exit_price=110.0, reason="TRAILING_STOP", pnl=10.0)

    journal.record_entry(
        symbol="ETHUSDT",
        entry_price=50.0,
        quantity=1.0,
        entry_reason="PATH_B_DIP_RECOVERY",
        entry_conditions={"strategy": "momentum"},
    )
    journal.record_exit("ETHUSDT", exit_price=40.0, reason="STOP_LOSS", pnl=-10.0)

    by_symbol = journal.query(symbol="BTCUSDT")
    assert len(by_symbol) == 1
    assert by_symbol[0].symbol == "BTCUSDT"

    by_reason = journal.query(close_reason="STOP_LOSS")
    assert len(by_reason) == 1
    assert by_reason[0].exit_reason == "STOP_LOSS"

    by_strategy = journal.query(strategy="momentum")
    assert len(by_strategy) == 1
    assert by_strategy[0].symbol == "ETHUSDT"

    # date filter: everything "from now" should exclude older if we backdate
    future = datetime.now(UTC).replace(year=2099)
    assert journal.query(date_from=future) == []


def test_load_open_entries_rehydrates_from_repository():
    journal = TradeJournal()
    repository = DummyTradeJournalRepository()
    journal.set_repository(repository)

    entry = journal.record_entry(
        symbol="BTCUSDT",
        entry_price=100.0,
        quantity=1.0,
        entry_reason="PATH_A_DIRECT_RISE",
        exchange="BINANCE",
    )
    # Simulate process restart: wipe memory, reload from repo.
    journal._open_entries.clear()
    assert journal.get_open("BTCUSDT", exchange="BINANCE") is None

    # Ensure repo row still OPEN.
    assert repository.list_open()
    loaded = journal.load_open_entries()
    assert loaded == 1
    restored = journal.get_open("BTCUSDT", exchange="BINANCE")
    assert restored is not None
    assert restored.id == entry.id
    assert restored.status == "OPEN"

    # Tick tracking continues after rehydrate.
    journal.record_price_update("BTCUSDT", 105.0, exchange="BINANCE")
    assert restored.highest_price == 105.0


def test_trade_journal_service_alias():
    from app.core.services.trade_journal import TradeJournalService

    assert TradeJournalService is TradeJournal
