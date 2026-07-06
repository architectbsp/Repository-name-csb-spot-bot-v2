from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PositionState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass(slots=True)
class Position:
    symbol: str
    entry_price: float
    quantity: float
    opened_at: datetime
    stop_price: float | None = None
    state: PositionState = PositionState.OPEN


MAX_OPEN_POSITIONS = 10


class PositionManager:
    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._initialized = False
        self._running = False

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
        return True

    def get(self, symbol: str) -> Position | None:
        return self._positions.get(symbol)

    def contains(self, symbol: str) -> bool:
        return symbol in self._positions

    def remove(self, symbol: str) -> bool:
        if symbol not in self._positions:
            return False

        del self._positions[symbol]
        return True


    def close(
        self,
        symbol: str,
    ) -> bool:
        position = self._positions.get(symbol)

        if position is None:
            return False

        position.state = PositionState.CLOSED
        return True

    def is_open(
        self,
        symbol: str,
    ) -> bool:
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
