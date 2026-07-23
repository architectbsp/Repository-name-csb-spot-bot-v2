from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[..., Any]]] = {}
        # R1: protect subscriber map against concurrent subscribe/publish
        # (WS callbacks, Worker, UI). Handlers run outside the lock.
        self._lock = threading.RLock()
        # R7: observability counters (no behavioral change).
        self._publish_count = 0
        self._handler_errors = 0

    def subscribe(
        self,
        event: str,
        callback: Callable[..., Any],
    ) -> None:
        with self._lock:
            self._subscribers.setdefault(event, []).append(callback)

    def unsubscribe(
        self,
        event: str,
        callback: Callable[..., Any],
    ) -> None:
        with self._lock:
            subscribers = self._subscribers.get(event)

            if subscribers is None:
                return

            if callback in subscribers:
                subscribers.remove(callback)

            if not subscribers:
                self._subscribers.pop(event, None)

    def publish(
        self,
        event: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        # Snapshot under lock, invoke outside — avoids holding the bus
        # lock across handlers (deadlock / re-entrancy safe).
        with self._lock:
            subscribers = tuple(self._subscribers.get(event, ()))
            self._publish_count += 1

        for callback in subscribers:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                with self._lock:
                    self._handler_errors += 1
                logger.error(
                    "[EventBus] Callback exception for event '%s': %s",
                    event,
                    type(e).__name__,
                    exc_info=True,
                )

    def has_subscribers(self, event: str) -> bool:
        with self._lock:
            return bool(self._subscribers.get(event))

    def stats(self) -> dict[str, int]:
        """R7: lightweight EventBus counters for health snapshots."""
        with self._lock:
            return {
                "publish_count": self._publish_count,
                "handler_errors": self._handler_errors,
                "topic_count": len(self._subscribers),
            }

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._publish_count = 0
            self._handler_errors = 0
