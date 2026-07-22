from datetime import UTC, datetime

from app.core.domain.position import Position, PositionState
from app.core.persistence.mapper import to_entity


MAX_OPEN_POSITIONS = 10  # docs/BUSINESS_RULES.md §3/§8: max 10 simultaneous positions.


class PositionManager:
    def __init__(self) -> None:
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

    def add(self, position: Position) -> bool:
        if position.symbol in self._positions:
            return False

        if len(self._positions) >= MAX_OPEN_POSITIONS:
            return False

        self._positions[position.symbol] = position

        if self._repository is not None:
            self._repository.save(
                to_entity(position),
            )

        return True

    def restore(self, position: Position) -> bool:
        if position.symbol in self._positions:
            return False

        if len(self._positions) >= MAX_OPEN_POSITIONS:
            return False

        self._positions[position.symbol] = position
        return True

    def get(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def contains(self, symbol: str) -> bool:
        return symbol in self._positions

    def remove(self, symbol: str) -> bool:
        if symbol not in self._positions:
            return False

        del self._positions[symbol]

        if self._repository is not None:
            self._repository.delete(symbol)

        return True


    def handle_position_closed(
        self,
        event: dict,
    ) -> None:
        self.remove(event["symbol"])

    def close(
        self,
        symbol: str,
        *,
        exit_price: float | None = None,
        reason: str | None = None,
    ) -> bool:
        position = self._positions.get(symbol)

        if position is None:
            return False

        position.state = PositionState.CLOSED
        position.closed_at = datetime.now(UTC)
        position.exit_price = exit_price
        position.close_reason = reason

        if exit_price is not None:
            # Sprint 3: position.pnl is the TOTAL realized PnL for the
            # whole trade, including any earlier partial scale-out(s)
            # (position.realized_pnl) plus the PnL from closing out
            # whatever quantity remains right now. This is what a Trade
            # Journal / dashboard should show as "how much did this
            # trade make" -- RiskManager tracks the daily-loss-limit
            # increment separately so a partial exit's PnL is never
            # double-counted there.
            final_chunk_pnl = (
                exit_price - position.entry_price
            ) * position.quantity

            position.pnl = position.realized_pnl + final_chunk_pnl

            position.pnl_percent = (
                (exit_price - position.entry_price)
                / position.entry_price
            ) * 100

        if self._repository is not None:
            self._repository.save(
                to_entity(position),
            )

        return True

    def scale_out(
        self,
        symbol: str,
        *,
        sell_quantity: float,
        exit_price: float,
        reason: str = "PARTIAL_TP",
    ) -> float | None:
        """
        Sprint 3 -- Scale Out / Partial Take Profit: sells off part of an
        open position without closing it. Reduces `quantity`, banks the
        realized PnL from the sold slice into `realized_pnl` (kept
        separate from `pnl`, which is only ever set when the position
        fully closes), and leaves the position OPEN with the remaining
        quantity so stop/trailing/break-even logic keeps managing it.

        Returns the realized PnL from this scale-out, or None if the
        position doesn't exist, isn't open, or `sell_quantity` is not
        strictly between 0 and the position's current quantity (selling
        the entire remaining quantity must go through close() instead,
        so a position is never left open with 0 quantity).
        """
        position = self._positions.get(symbol)

        if position is None or position.state != PositionState.OPEN:
            return None

        if sell_quantity <= 0 or sell_quantity >= position.quantity:
            return None

        realized = (exit_price - position.entry_price) * sell_quantity

        position.quantity -= sell_quantity
        position.realized_pnl += realized
        position.partial_exits_taken += 1

        if self._repository is not None:
            self._repository.save(
                to_entity(position),
            )

        return realized

    def is_open(self, symbol: str) -> bool:
        position = self._positions.get(symbol)

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
