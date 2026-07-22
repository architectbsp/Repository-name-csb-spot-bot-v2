"""
Trade Journal -- permanent ledger for every trade.

Tables:
  - trade_journals: one row per trade (entry → close)
  - trade_logs: append-only event stream (ENTRY / PRICE_EXTREME /
    PARTIAL_EXIT / EXIT)

Writers:
  - Strategy.record_entry (BUY fill + why)
  - RiskManager.record_price_update (in-trade MFE/MAE + peaks)
  - RiskManager.record_partial_exit / record_exit
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.domain.trade_journal import (
    LOG_ENTRY,
    LOG_EXIT,
    LOG_PARTIAL_EXIT,
    LOG_PRICE_EXTREME,
    STATUS_CLOSED,
    TradeJournalEntry,
    TradeLog,
)
from app.core.exchange.market_key import market_key
from app.core.persistence.mapper import (
    journal_to_domain,
    journal_to_entity,
    trade_log_to_entity,
)


logger = logging.getLogger(__name__)


class TradeJournal:
    def __init__(self) -> None:
        self._repository = None
        # Sprint 18: one open trade per (exchange, symbol).
        self._open_entries: dict[str, TradeJournalEntry] = {}

    def _entry_key(self, symbol: str, exchange=None) -> str:
        return market_key(exchange, symbol)

    def set_repository(self, repository) -> None:
        self._repository = repository

    def _append_log(
        self,
        entry: TradeJournalEntry,
        event_type: str,
        *,
        message: str | None = None,
        payload: dict | None = None,
    ) -> None:
        if self._repository is None or entry.id is None:
            return
        if not hasattr(self._repository, "insert_log"):
            return

        log = TradeLog(
            journal_id=entry.id,
            event_type=event_type,
            created_at=datetime.now(UTC),
            message=message,
            payload=payload or {},
        )
        self._repository.insert_log(trade_log_to_entity(log))

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
        entry_conditions: dict | None = None,
        wallet_quote_free: float | None = None,
    ) -> TradeJournalEntry:
        conditions = dict(entry_conditions or {})
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
            entry_conditions=conditions,
            wallet_quote_free=wallet_quote_free,
            highest_price=entry_price,
            lowest_price=entry_price,
        )

        if self._repository is not None:
            entry.id = self._repository.insert(journal_to_entity(entry))

        self._open_entries[self._entry_key(symbol, exchange)] = entry

        self._append_log(
            entry,
            LOG_ENTRY,
            message=entry_reason,
            payload={
                "entry_price": entry_price,
                "quantity": quantity,
                "wait_minutes": wait_minutes,
                "rise_events": rise_events,
                "fall_events": fall_events,
                "entry_conditions": conditions,
                "wallet_quote_free": wallet_quote_free,
            },
        )

        logger.info(
            "[JOURNAL] ENTRY symbol=%s exchange=%s reason=%s price=%.8f "
            "qty=%.8f wait_minutes=%s wallet_free=%s rise_events=%d "
            "fall_events=%d",
            symbol,
            exchange,
            entry_reason,
            entry_price,
            quantity,
            f"{wait_minutes:.1f}" if wait_minutes is not None else "n/a",
            f"{wallet_quote_free:.4f}" if wallet_quote_free is not None else "n/a",
            rise_events,
            fall_events,
        )

        return entry

    def record_price_update(
        self,
        symbol: str,
        price: float,
        *,
        exchange=None,
    ) -> TradeJournalEntry | None:
        """
        In-trade tracking: hold extremes (highest/lowest) and peak/trough
        print counts. Persists + logs only when an extreme changes.
        """
        entry = self._resolve_open(symbol, exchange)
        if entry is None:
            return None

        changed = False
        if entry.highest_price is None or price > entry.highest_price:
            entry.highest_price = price
            entry.peak_count += 1
            changed = True
        if entry.lowest_price is None or price < entry.lowest_price:
            entry.lowest_price = price
            entry.trough_count += 1
            changed = True

        if not changed:
            return entry

        hold_minutes = (
            datetime.now(UTC) - entry.entry_time
        ).total_seconds() / 60.0

        if self._repository is not None and entry.id is not None:
            self._repository.update(journal_to_entity(entry))

        self._append_log(
            entry,
            LOG_PRICE_EXTREME,
            message="new_extreme",
            payload={
                "price": price,
                "highest_price": entry.highest_price,
                "lowest_price": entry.lowest_price,
                "peak_count": entry.peak_count,
                "trough_count": entry.trough_count,
                "hold_minutes": hold_minutes,
            },
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
        exchange=None,
    ) -> TradeJournalEntry | None:
        entry = self._resolve_open(symbol, exchange)
        if entry is None:
            logger.warning(
                "[JOURNAL] Partial exit for %s with no open journal entry "
                "-- was it opened before the journal was wired in?",
                symbol,
            )
            return None

        entry.partial_exit_count += 1
        entry.partial_exit_pnl += realized_pnl
        partial = {
            "time": datetime.now(UTC).isoformat(),
            "exit_price": exit_price,
            "quantity": quantity,
            "realized_pnl": realized_pnl,
            "reason": reason,
        }
        entry.partial_exits.append(partial)

        if self._repository is not None and entry.id is not None:
            self._repository.update(journal_to_entity(entry))

        self._append_log(
            entry,
            LOG_PARTIAL_EXIT,
            message=str(reason),
            payload=partial,
        )

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
        exchange=None,
    ) -> TradeJournalEntry | None:
        key = self._entry_key(symbol, exchange)
        entry = self._open_entries.pop(key, None)

        if entry is None and exchange is None:
            matches = [
                k for k, e in self._open_entries.items() if e.symbol == symbol
            ]
            if len(matches) == 1:
                entry = self._open_entries.pop(matches[0])

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

        self._append_log(
            entry,
            LOG_EXIT,
            message=str(reason),
            payload={
                "exit_price": exit_price,
                "exit_reason": reason,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "duration_minutes": entry.duration_minutes,
                "highest_price": entry.highest_price,
                "lowest_price": entry.lowest_price,
                "peak_count": entry.peak_count,
                "trough_count": entry.trough_count,
            },
        )

        logger.info(
            "[JOURNAL] EXIT symbol=%s reason=%s price=%.8f pnl=%s "
            "pnl_percent=%s duration_minutes=%.1f",
            symbol,
            reason,
            exit_price,
            f"{pnl:.8f}" if pnl is not None else "n/a",
            f"{pnl_percent:.4f}" if pnl_percent is not None else "n/a",
            entry.duration_minutes,
        )

        return entry

    def _resolve_open(
        self,
        symbol: str,
        exchange=None,
    ) -> TradeJournalEntry | None:
        entry = self._open_entries.get(self._entry_key(symbol, exchange))
        if entry is not None:
            return entry
        if exchange is None:
            matches = [
                e for e in self._open_entries.values() if e.symbol == symbol
            ]
            return matches[0] if len(matches) == 1 else None
        return None

    def get_open(self, symbol: str, exchange=None) -> TradeJournalEntry | None:
        return self._resolve_open(symbol, exchange)

    def get_last_closed(self, symbol: str) -> TradeJournalEntry | None:
        if self._repository is None:
            return None

        entity = self._repository.get_last_closed_by_symbol(symbol)
        if entity is None:
            return None
        return journal_to_domain(entity)

    def list_logs(self, journal_id: int) -> list[TradeLog]:
        if self._repository is None or not hasattr(self._repository, "list_logs"):
            return []
        from app.core.persistence.mapper import trade_log_to_domain

        return [
            trade_log_to_domain(entity)
            for entity in self._repository.list_logs(journal_id)
        ]

    def list_open(self) -> list[TradeJournalEntry]:
        return list(self._open_entries.values())

    def list_all(self) -> list[TradeJournalEntry]:
        if self._repository is None:
            return list(self._open_entries.values())

        return [
            journal_to_domain(entity)
            for entity in self._repository.list_all()
        ]
