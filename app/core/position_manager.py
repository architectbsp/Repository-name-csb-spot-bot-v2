from datetime import UTC, datetime

from app.core.config.settings import AppSettings
from app.core.domain.position import (
    CloseReason,
    PartialExitRecord,
    Position,
    PositionState,
)
from app.core.exchange.market_key import market_key
from app.core.persistence.mapper import to_entity


# Fallback only when PositionManager has no live AppSettings wired.
# Prefer risk.max_open_positions via set_config / ConfigManager.
DEFAULT_MAX_OPEN_POSITIONS = 10
MAX_OPEN_POSITIONS = DEFAULT_MAX_OPEN_POSITIONS  # backward-compat for tests


class PositionManager:
    def __init__(self) -> None:
        # Sprint 18: keyed by market_key(exchange, symbol) so the same
        # coin can be open on two venues without colliding.
        self._positions: dict[str, Position] = {}
        self._repository = None
        self._config: AppSettings | None = None
        # Sprint 3: after emergency_exit_all, block new entries until
        # the operator explicitly unfreezes (RiskManager checks this).
        self._entries_frozen: bool = False
        self._initialized = False
        self._running = False

    def set_repository(self, repository) -> None:
        self._repository = repository

    def set_config(self, config: AppSettings | None) -> None:
        self._config = config

    def on_config_updated(self, event) -> None:
        """
        EventBus ``config.updated`` -- max_open_positions is read live
        from ``self._config.risk`` on every add/restore.
        """
        return None

    def _max_open_positions(self) -> int:
        if self._config is not None:
            return int(self._config.risk.max_open_positions)
        return DEFAULT_MAX_OPEN_POSITIONS

    @property
    def entries_frozen(self) -> bool:
        return self._entries_frozen

    def freeze_new_entries(self) -> None:
        self._entries_frozen = True

    def unfreeze_new_entries(self) -> None:
        self._entries_frozen = False

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False
        self._entries_frozen = False
        self._positions.clear()

    def start(self) -> None:
        if not self._initialized:
            raise RuntimeError("PositionManager is not initialized.")
        self._running = True

    def stop(self) -> None:
        self._running = False

    def _key_for(self, position: Position) -> str:
        return market_key(position.exchange, position.symbol)

    def _resolve_key(self, symbol: str, exchange=None) -> str | None:
        if exchange is not None:
            return market_key(exchange, symbol)

        if symbol in self._positions:
            return symbol

        matches = [
            key
            for key, position in self._positions.items()
            if position.symbol == symbol
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def add(self, position: Position) -> bool:
        key = self._key_for(position)

        if key in self._positions:
            return False

        if self.open_count() >= self._max_open_positions():
            return False

        self._positions[key] = position

        if self._repository is not None:
            self._repository.save(to_entity(position))

        return True

    def restore(self, position: Position) -> bool:
        key = self._key_for(position)

        if key in self._positions:
            return False

        if self.open_count() >= self._max_open_positions():
            return False

        self._positions[key] = position
        return True

    def get(self, symbol: str, exchange=None) -> Position | None:
        key = self._resolve_key(symbol, exchange)
        if key is None:
            return None
        return self._positions.get(key)

    def contains(self, symbol: str, exchange=None) -> bool:
        return self._resolve_key(symbol, exchange) is not None

    def remove(self, symbol: str, exchange=None) -> bool:
        key = self._resolve_key(symbol, exchange)
        if key is None or key not in self._positions:
            return False

        del self._positions[key]

        if self._repository is not None:
            self._repository.delete(key)

        return True

    def handle_position_closed(self, event: dict) -> None:
        exchange = event.get("exchange")
        position = event.get("position")
        if exchange is None and position is not None:
            exchange = getattr(position, "exchange", None)
        self.remove(event["symbol"], exchange=exchange)

    def close(
        self,
        symbol: str,
        *,
        exit_price: float | None = None,
        reason: str | CloseReason | None = None,
        exchange=None,
    ) -> bool:
        """
        Marks a position CLOSED. ``reason`` is required for production
        exits (Sprint 3 CloseReason contract).
        """
        if reason is None or reason == "":
            raise ValueError("close_reason is required when closing a position")

        key = self._resolve_key(symbol, exchange)
        if key is None:
            return False

        position = self._positions.get(key)
        if position is None:
            return False

        reason_value = (
            reason.value if isinstance(reason, CloseReason) else str(reason)
        )

        position.state = PositionState.CLOSED
        position.closed_at = datetime.now(UTC)
        position.exit_price = exit_price
        position.close_reason = reason_value

        if exit_price is not None:
            final_chunk_pnl = (
                exit_price - position.entry_price
            ) * position.quantity

            position.pnl = position.realized_pnl + final_chunk_pnl

            position.pnl_percent = (
                (exit_price - position.entry_price)
                / position.entry_price
            ) * 100

        if self._repository is not None:
            self._repository.save(to_entity(position))

        return True

    def scale_out(
        self,
        symbol: str,
        *,
        sell_quantity: float,
        exit_price: float,
        reason: str | CloseReason = CloseReason.PARTIAL_TP,
        exchange=None,
        protect_remaining: bool = True,
    ) -> float | None:
        """
        Partial exit: reduces remaining quantity, banks realized PnL,
        appends ``PartialExitRecord``, and (by default) lifts a HARD
        stop to break-even so the remainder is protected.
        """
        key = self._resolve_key(symbol, exchange)
        if key is None:
            return None

        position = self._positions.get(key)

        if position is None or position.state != PositionState.OPEN:
            return None

        if sell_quantity <= 0 or sell_quantity >= position.quantity:
            return None

        reason_value = (
            reason.value if isinstance(reason, CloseReason) else str(reason)
        )
        realized = (exit_price - position.entry_price) * sell_quantity

        position.quantity -= sell_quantity
        position.realized_pnl += realized
        position.partial_exits_taken += 1

        if protect_remaining:
            self._protect_remaining_after_partial(position)

        position.partial_exits.append(
            PartialExitRecord(
                quantity=sell_quantity,
                exit_price=exit_price,
                realized_pnl=realized,
                reason=reason_value,
                remaining_quantity=position.quantity,
                stop_price_after=position.stop_price,
                stop_stage_after=position.stop_stage,
                at=datetime.now(UTC),
            )
        )

        if self._repository is not None:
            self._repository.save(to_entity(position))

        return realized

    @staticmethod
    def _protect_remaining_after_partial(position: Position) -> None:
        """
        After banking partial profit, lift a HARD stop to break-even so
        the remaining size cannot give back the banked gain via the
        original hard stop. Trailing / break-even stages are left alone.
        """
        if position.stop_stage != "HARD":
            return
        position.stop_price = float(position.entry_price)
        position.stop_stage = "BREAK_EVEN"

    def is_open(self, symbol: str, exchange=None) -> bool:
        position = self.get(symbol, exchange=exchange)

        if position is None:
            return False

        return position.state == PositionState.OPEN

    def open_count(self) -> int:
        return sum(
            1
            for position in self._positions.values()
            if position.state == PositionState.OPEN
        )

    def get_open_positions(self) -> list[Position]:
        return [
            position
            for position in self._positions.values()
            if position.state == PositionState.OPEN
        ]

    def get_closed_positions(self) -> list[Position]:
        return [
            position
            for position in self._positions.values()
            if position.state == PositionState.CLOSED
        ]

    def clear(self) -> None:
        self._positions.clear()

    def size(self) -> int:
        return len(self._positions)

    def is_empty(self) -> bool:
        return len(self._positions) == 0

    def is_initialized(self) -> bool:
        return self._initialized

    def is_running(self) -> bool:
        return self._running
