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

Readers: ``query()`` / ``list_*`` for UI and analytics (Sprint 5
``TradeJournalService`` alias).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.core.domain.trade_journal import (
    LOG_ENTRY,
    LOG_EXIT,
    LOG_PARTIAL_EXIT,
    LOG_PRICE_EXTREME,
    MODE_PAPER,
    STATUS_CLOSED,
    STATUS_OPEN,
    TradeJournalEntry,
    TradeLog,
)
from app.core.exchange.market_key import market_key
from app.core.exchange.trading_mode import (
    normalize_trading_mode,
    resolve_trading_mode,
)
from app.core.persistence.mapper import (
    journal_to_domain,
    journal_to_entity,
    trade_log_to_entity,
)


logger = logging.getLogger(__name__)


def _add_commission(entry: TradeJournalEntry, fee: float | None) -> None:
    if fee is None:
        return
    try:
        amount = float(fee)
    except (TypeError, ValueError):
        return
    if amount == 0:
        return
    current = entry.commission or 0.0
    entry.commission = current + amount


class TradeJournal:
    def __init__(self) -> None:
        self._repository = None
        # Sprint 18: one open trade per (exchange, symbol).
        self._open_entries: dict[str, TradeJournalEntry] = {}
        # Sprint 14: stamp new entries with the process trading mode.
        self._trading_mode = resolve_trading_mode().value

    def _entry_key(self, symbol: str, exchange=None) -> str:
        return market_key(exchange, symbol)

    def set_repository(self, repository) -> None:
        self._repository = repository

    def set_trading_mode(self, mode) -> None:
        self._trading_mode = normalize_trading_mode(mode).value

    @property
    def trading_mode(self) -> str:
        return self._trading_mode

    def load_open_entries(self) -> int:
        """
        Rehydrate in-memory open rows from SQLite after restart so
        MFE/MAE ticks and exits continue on restored positions.
        """
        if self._repository is None or not hasattr(self._repository, "list_open"):
            return 0
        loaded = 0
        for entity in self._repository.list_open():
            entry = journal_to_domain(entity)
            key = self._entry_key(entry.symbol, entry.exchange)
            self._open_entries[key] = entry
            loaded += 1
        if loaded:
            logger.info("[JOURNAL] Rehydrated %d open journal entr(y/ies)", loaded)
        return loaded

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
        commission: float | None = None,
        trading_mode: str | None = None,
    ) -> TradeJournalEntry:
        conditions = dict(entry_conditions or {})
        mode = normalize_trading_mode(
            trading_mode or self._trading_mode or MODE_PAPER
        ).value
        entry = TradeJournalEntry(
            symbol=symbol,
            entry_time=datetime.now(UTC),
            entry_price=entry_price,
            quantity=quantity,
            entry_reason=entry_reason,
            exchange=exchange,
            trading_mode=mode,
            watch_started_at=watch_started_at,
            wait_minutes=wait_minutes,
            rise_events=rise_events,
            fall_events=fall_events,
            entry_conditions=conditions,
            wallet_quote_free=wallet_quote_free,
            highest_price=entry_price,
            lowest_price=entry_price,
            commission=float(commission) if commission is not None else None,
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
                "commission": entry.commission,
                "trigger_condition": entry_reason,
            },
        )

        logger.info(
            "[JOURNAL] ENTRY symbol=%s exchange=%s mode=%s reason=%s price=%.8f "
            "qty=%.8f wait_minutes=%s wallet_free=%s rise_events=%d "
            "fall_events=%d",
            symbol,
            exchange,
            mode,
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
        In-trade tracking: hold extremes (highest/lowest = MFE/MAE price
        anchors) and peak/trough print counts. Persists + logs only when
        an extreme changes.
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

        hold_seconds = (datetime.now(UTC) - entry.entry_time).total_seconds()

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
                "mfe_percent": entry.mfe_percent,
                "mae_percent": entry.mae_percent,
                "peak_count": entry.peak_count,
                "trough_count": entry.trough_count,
                "duration_sec": hold_seconds,
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
        commission: float | None = None,
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
        _add_commission(entry, commission)
        partial = {
            "time": datetime.now(UTC).isoformat(),
            "exit_price": exit_price,
            "quantity": quantity,
            "realized_pnl": realized_pnl,
            "reason": reason,
            "commission": commission,
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
        commission: float | None = None,
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
        _add_commission(entry, commission)

        if self._repository is not None and entry.id is not None:
            self._repository.update(journal_to_entity(entry))

        self._append_log(
            entry,
            LOG_EXIT,
            message=str(reason),
            payload={
                "exit_price": exit_price,
                "exit_reason": reason,
                "close_reason": reason,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "duration_minutes": entry.duration_minutes,
                "duration_sec": entry.duration_sec,
                "highest_price": entry.highest_price,
                "lowest_price": entry.lowest_price,
                "mfe_percent": entry.mfe_percent,
                "mae_percent": entry.mae_percent,
                "peak_count": entry.peak_count,
                "trough_count": entry.trough_count,
                "commission": entry.commission,
            },
        )

        logger.info(
            "[JOURNAL] EXIT symbol=%s reason=%s price=%.8f pnl=%s "
            "pnl_percent=%s duration_sec=%s mfe=%.2f%% mae=%.2f%%",
            symbol,
            reason,
            exit_price,
            f"{pnl:.8f}" if pnl is not None else "n/a",
            f"{pnl_percent:.4f}" if pnl_percent is not None else "n/a",
            f"{entry.duration_sec:.1f}" if entry.duration_sec is not None else "n/a",
            entry.mfe_percent or 0.0,
            entry.mae_percent or 0.0,
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

    def query(
        self,
        *,
        symbol: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        strategy: str | None = None,
        close_reason: str | None = None,
        status: str | None = None,
        exchange: str | None = None,
        trading_mode: str | None = None,
        limit: int = 200,
    ) -> list[TradeJournalEntry]:
        """
        Sprint 5 query API for UI / analytics: filter by symbol, date
        range, strategy name (inside entry_conditions), close_reason,
        status, exchange, or trading_mode (PAPER|REAL).
        """
        if self._repository is not None and hasattr(self._repository, "query"):
            return [
                journal_to_domain(entity)
                for entity in self._repository.query(
                    symbol=symbol,
                    date_from=date_from,
                    date_to=date_to,
                    strategy=strategy,
                    close_reason=close_reason,
                    status=status,
                    exchange=exchange,
                    trading_mode=trading_mode,
                    limit=limit,
                )
            ]

        # In-memory fallback (tests without repo.query).
        rows = list(self._open_entries.values())
        if status == STATUS_CLOSED:
            rows = []
        elif status == STATUS_OPEN or status is None:
            pass
        out: list[TradeJournalEntry] = []
        mode_key = (
            normalize_trading_mode(trading_mode).value
            if trading_mode
            else None
        )
        for entry in rows:
            if symbol and entry.symbol != symbol:
                continue
            if exchange and entry.exchange != exchange:
                continue
            if mode_key and (entry.trading_mode or "") != mode_key:
                continue
            if close_reason and entry.exit_reason != close_reason:
                continue
            if strategy:
                blob = str(entry.entry_conditions)
                if strategy not in blob:
                    continue
            if date_from is not None and entry.entry_time < date_from:
                continue
            if date_to is not None and entry.entry_time > date_to:
                continue
            out.append(entry)
        out.sort(key=lambda e: e.entry_time, reverse=True)
        return out[: max(1, int(limit))]


# Brief / Sprint 5 service naming.
TradeJournalService = TradeJournal
