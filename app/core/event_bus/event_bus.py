from __future__ import annotations

from collections.abc import Callable
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[..., Any]]] = {}

    def subscribe(
        self,
        event: str,
        callback: Callable[..., Any],
    ) -> None:
        self._subscribers.setdefault(event, []).append(callback)

    def unsubscribe(
        self,
        event: str,
        callback: Callable[..., Any],
    ) -> None:
        subscribers = self._subscribers.get(event)

        if subscribers is None:
            return

        if callback in subscribers:
            subscribers.remove(callback)

        if not subscribers:
            self._subscribers.pop(event, None)
