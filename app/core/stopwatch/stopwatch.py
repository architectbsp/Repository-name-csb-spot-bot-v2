from __future__ import annotations

from datetime import datetime


class Stopwatch:
    def __init__(self) -> None:
        self._started_at: datetime | None = None

    def start(self) -> None:
        self._started_at = datetime.now()

    def is_running(self) -> bool:
        return self._started_at is not None

    def reset(self) -> None:
        self._started_at = None

    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0

        return (datetime.now() - self._started_at).total_seconds()
