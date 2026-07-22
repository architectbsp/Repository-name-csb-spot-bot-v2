import json
from datetime import UTC, datetime

from app.core.domain.position import Position
from app.core.domain.trade_journal import TradeJournalEntry
from app.core.exchange.market_key import market_key, try_parse_exchange_type
from app.core.persistence.models import PositionEntity, TradeJournalEntity


def to_entity(position: Position) -> PositionEntity:
    now = datetime.now(UTC)
    exchange = position.exchange
    key = market_key(exchange, position.symbol)

    return PositionEntity(
        position_key=key,
        symbol=position.symbol,
        exchange=key.split(":", 1)[0],
        entry_price=position.entry_price,
        quantity=position.quantity,
        stop_price=position.stop_price,
        highest_price=position.highest_price,
        opened_at=position.opened_at,
        updated_at=now,
        realized_pnl=position.realized_pnl,
        partial_exits_taken=position.partial_exits_taken,
        stop_stage=position.stop_stage,
    )


def to_domain(entity: PositionEntity) -> Position:
    exchange = try_parse_exchange_type(
        getattr(entity, "exchange", None)
    )

    return Position(
        symbol=entity.symbol,
        entry_price=entity.entry_price,
        quantity=entity.quantity,
        opened_at=entity.opened_at,
        stop_price=entity.stop_price,
        highest_price=entity.highest_price,
        realized_pnl=entity.realized_pnl,
        partial_exits_taken=entity.partial_exits_taken,
        stop_stage=entity.stop_stage,
        exchange=exchange,
    )


def journal_to_entity(entry: TradeJournalEntry) -> TradeJournalEntity:
    return TradeJournalEntity(
        id=entry.id,
        symbol=entry.symbol,
        exchange=entry.exchange,
        entry_time=entry.entry_time,
        entry_price=entry.entry_price,
        quantity=entry.quantity,
        entry_reason=entry.entry_reason,
        watch_started_at=entry.watch_started_at,
        wait_minutes=entry.wait_minutes,
        rise_events=entry.rise_events,
        fall_events=entry.fall_events,
        status=entry.status,
        partial_exit_count=entry.partial_exit_count,
        partial_exit_pnl=entry.partial_exit_pnl,
        partial_exits_json=json.dumps(entry.partial_exits) if entry.partial_exits else None,
        exit_time=entry.exit_time,
        exit_price=entry.exit_price,
        exit_reason=entry.exit_reason,
        duration_minutes=entry.duration_minutes,
        pnl=entry.pnl,
        pnl_percent=entry.pnl_percent,
    )


def journal_to_domain(entity: TradeJournalEntity) -> TradeJournalEntry:
    return TradeJournalEntry(
        id=entity.id,
        symbol=entity.symbol,
        exchange=entity.exchange,
        entry_time=entity.entry_time,
        entry_price=entity.entry_price,
        quantity=entity.quantity,
        entry_reason=entity.entry_reason,
        watch_started_at=entity.watch_started_at,
        wait_minutes=entity.wait_minutes,
        rise_events=entity.rise_events,
        fall_events=entity.fall_events,
        status=entity.status,
        partial_exit_count=entity.partial_exit_count,
        partial_exit_pnl=entity.partial_exit_pnl,
        partial_exits=json.loads(entity.partial_exits_json) if entity.partial_exits_json else [],
        exit_time=entity.exit_time,
        exit_price=entity.exit_price,
        exit_reason=entity.exit_reason,
        duration_minutes=entity.duration_minutes,
        pnl=entity.pnl,
        pnl_percent=entity.pnl_percent,
    )
