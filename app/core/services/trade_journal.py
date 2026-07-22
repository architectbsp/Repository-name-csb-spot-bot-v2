"""
Sprint 5 -- Trade Journal.

Records the full decision history of every trade: why it was bought
(which entry path, how long it was watched, how many times price rose or
fell while watching), and, once it closes, how it went (which stop fired,
how long it was held, the realized PnL). This is intentionally decoupled
from PositionManager: a Position row disappears the instant it closes
(see PositionManager.handle_position_closed), while a TradeJournalEntry
is kept forever -- it is the historical ledger a future UI screen,
export, or Performance Analytics module (Sprint 7) reads from.

Wiring (see BotEngine):
    - Strategy calls record_entry() the moment a BUY is filled and the
      position is promoted to POSITION_OPEN -- Strategy is the only
      module that knows *why* the bot decided to buy (entry path, watch
      duration, rise/fall counts all live on WatchList's per-coin state).
    - RiskManager calls record_partial_exit() (Scale Out / Partial Take
      Profit) and record_exit() (every full close, regardless of which
      stop/manual/emergency/max-duration path triggered it) -- RiskManager
      is the sole owner of every exit.
"""

import logging
from datetime import UTC, datetime

from app.core.domain.trade_journal import STATUS_CLOSED, TradeJournalEntry
from app.core.persistence.mapper import journal_to_domain, journal_to_entity


logger = logging.getLogger(__name__)


class TradeJournal:
    def __init__(self) -> None:
        self._repository = None
        # Only one open trade per symbol can exist at a time (matches
        # PositionManager's one-open-position-per-symbol invariant), so a
        # simple dict keyed by symbol is enough to find the entry a
        # partial/final exit needs to update.
        self._open_entries: dict[str, TradeJournalEntry] = {}

    def set_repository(self, repository) -> None:
        self._repository = repository

    def record_entry(
        self,
        *,
        symbol: str,
        entry_price: float,
        quantity: float,
        entry_reason: str,
        exchange: str | None = None,
        watch_started_at: datetime | None = None,
        wait_minutes: float | None = None,
        rise_events: int = 0,
        fall_events: int = 0,
    ) -> TradeJournalEntry:
        entry = TradeJournalEntry(
            symbol=symbol,
            entry_time=datetime.now(UTC),
            entry_price=entry_price,
            quantity=quantity,
            entry_reason=entry_reason,
            exchange=exchange,
            watch_started_at=watch_started_at,
            wait_minutes=wait_minutes,
            rise_events=rise_events,
            fall_events=fall_events,
        )

        if self._repository is not None:
            entry.id = self._repository.insert(journal_to_entity(entry))

        self._open_entries[symbol] = entry

        logger.info(
            "[JOURNAL] ENTRY symbol=%s reason=%s price=%.8f qty=%.8f "
            "wait_minutes=%s rise_events=%d fall_events=%d",
            symbol,
            entry_reason,
            entry_price,
            quantity,
            f"{wait_minutes:.1f}" if wait_minutes is not None else "n/a",
            rise_events,
            fall_events,
        )

        return entry

    def record_partial_exit(
        self,
        symbol: str,
        *,
        exit_price: float,
        quantity: float,
        realized_pnl: float,
        reason: str = "PARTIAL_TP",
    ) -> TradeJournalEntry | None:
        entry = self._open_entries.get(symbol)

        if entry is None:
            logger.warning(
                "[JOURNAL] Partial exit for %s with no open journal entry "
                "-- was it opened before the journal was wired in?",
                symbol,
            )
            return None

        entry.partial_exit_count += 1
        entry.partial_exit_pnl += realized_pnl
        entry.partial_exits.append(
            {
                "time": datetime.now(UTC).isoformat(),
                "exit_price": exit_price,
                "quantity": quantity,
                "realized_pnl": realized_pnl,
                "reason": reason,
            }
        )

        if self._repository is not None and entry.id is not None:
            self._repository.update(journal_to_entity(entry))

        logger.info(
            "[JOURNAL] PARTIAL EXIT symbol=%s qty=%.8f price=%.8f "
            "realized_pnl=%.8f (exit #%d)",
            symbol,
            quantity,
            exit_price,
            realized_pnl,
            entry.partial_exit_count,
        )

        return entry

    def record_exit(
        self,
        symbol: str,
        *,
        exit_price: float,
        reason: str,
        pnl: float | None = None,
        pnl_percent: float | None = None,
        exit_time: datetime | None = None,
    ) -> TradeJournalEntry | None:
        entry = self._open_entries.pop(symbol, None)

        if entry is None:
            logger.warning(
                "[JOURNAL] Exit for %s with no open journal entry -- was "
                "it opened before the journal was wired in?",
                symbol,
            )
            return None

        exit_time = exit_time or datetime.now(UTC)

        entry.status = STATUS_CLOSED
        entry.exit_time = exit_time
        entry.exit_price = exit_price
        entry.exit_reason = reason
        entry.pnl = pnl
        entry.pnl_percent = pnl_percent
        entry.duration_minutes = (
            exit_time - entry.entry_time
        ).total_seconds() / 60.0

        if self._repository is not None and entry.id is not None:
            self._repository.update(journal_to_entity(entry))

        logger.info(
            "[JOURNAL] EXIT symbol=%s reason=%s price=%.8f pnl=%s "
            "duration_minutes=%.1f",
            symbol,
            reason,
            exit_price,
            f"{pnl:.8f}" if pnl is not None else "n/a",
            entry.duration_minutes,
        )

        return entry

    def get_open(self, symbol: str) -> TradeJournalEntry | None:
        return self._open_entries.get(symbol)

    def list_open(self) -> list[TradeJournalEntry]:
        return list(self._open_entries.values())

    def list_all(self) -> list[TradeJournalEntry]:
        if self._repository is None:
            return list(self._open_entries.values())

        return [
            journal_to_domain(entity)
            for entity in self._repository.list_all()
        ]
