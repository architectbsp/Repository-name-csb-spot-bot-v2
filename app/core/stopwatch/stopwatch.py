from __future__ import annotations

from datetime import datetime


class Stopwatch:
    def __init__(self) -> None:
        self._started_at: datetime | None = None

    def start(self) -> None:
        self._started_at = datetime.now()
