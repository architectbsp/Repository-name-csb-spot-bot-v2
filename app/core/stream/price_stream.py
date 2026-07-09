from __future__ import annotations

from typing import Iterable


class PriceStream:
    """
    Placeholder implementation.

    Sonraki adımda Binance Spot WebSocket bağlantısı
    bu sınıfa eklenecek.
    """

    def __init__(self, exchange, event_bus):
        self._exchange = exchange
        self._event_bus = event_bus
        self._running = False

    def start(self, symbols: Iterable[str]) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    @property
    def running(self) -> bool:
        return self._running
