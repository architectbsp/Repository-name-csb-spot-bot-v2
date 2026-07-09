from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread
from typing import Any

from app.core.exchange.stream import PriceStream


class BinancePriceStream(PriceStream):
    def __init__(self) -> None:
        self._running = False
        self._symbols: list[str] = []
        self._callback: Callable[[dict[str, Any]], None] | None = None

        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(
        self,
        symbols: list[str],
        callback: Callable[[dict[str, Any]], None],
    ) -> None:
        if self._running:
            return

        self._symbols = list(symbols)
        self._callback = callback

        self._stop_event.clear()

        self._thread = Thread(
            target=self._worker,
            daemon=True,
            name="BinancePriceStream",
        )

        self._running = True
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=5)

        self._thread = None

    def _worker(self) -> None:
        while not self._stop_event.wait(1):
            pass

    @property
    def running(self) -> bool:
        return self._running
