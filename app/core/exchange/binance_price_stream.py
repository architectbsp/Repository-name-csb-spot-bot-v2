from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.exchange.stream import PriceStream


class BinancePriceStream(PriceStream):
    def __init__(self) -> None:
        self._running = False
        self._symbols: list[str] = []
        self._callback: Callable[[dict[str, Any]], None] | None = None

    def start(
        self,
        symbols: list[str],
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        self._symbols = list(symbols)
        self._callback = callback
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        return self._running
