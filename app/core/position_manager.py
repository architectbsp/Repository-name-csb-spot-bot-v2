from datetime import UTC, datetime

from app.core.domain.position import Position, PositionState
from app.core.exchange.market_key import market_key
from app.core.persistence.mapper import to_entity


MAX_OPEN_POSITIONS = 10  # docs/BUSINESS_RULES.md §3/§8: max 10 simultaneous positions.


class PositionManager:
    def __init__(self) -> None:
        # Sprint 18: keyed by market_key(exchange, symbol) so the same
        # coin can be open on two venues without colliding.
        self._positions: dict[str, Position] = {}
        self._repository = None
        self._initialized = False
        self._running = False

    def set_repository(self, repository) -> None:
        self._repository = repository

    def initialize(self) -> None:
        self._initialized = True

    def shutdown(self) -> None:
        self._running = False
        self._initialized = False
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

        if len(self._positions) >= MAX_OPEN_POSITIONS:
            return False

        self._positions[key] = position

        if self._repository is not None:
            self._repository.save(to_entity(position))

        return True

    def restore(self, position: Position) -> bool:
        key = self._key_for(position)

        if key in self._positions:
            return False

        if len(self._positions) >= MAX_OPEN_POSITIONS:
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
        reason: str | None = None,
        exchange=None,
    ) -> bool:
        key = self._resolve_key(symbol, exchange)
        if key is None:
            return False

        position = self._positions.get(key)
        if position is None:
            return False

        position.state = PositionState.CLOSED
        position.closed_at = datetime.now(UTC)
        position.exit_price = exit_price
        position.close_reason = reason

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
        reason: str = "PARTIAL_TP",
        exchange=None,
    ) -> float | None:
        key = self._resolve_key(symbol, exchange)
        if key is None:
            return None

        position = self._positions.get(key)

        if position is None or position.state != PositionState.OPEN:
            return None

        if sell_quantity <= 0 or sell_quantity >= position.quantity:
            return None

        realized = (exit_price - position.entry_price) * sell_quantity

        position.quantity -= sell_quantity
        position.realized_pnl += realized
        position.partial_exits_taken += 1

        if self._repository is not None:
            self._repository.save(to_entity(position))

        return realized

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
