from __future__ import annotations

from datetime import datetime


class Timer:
    def __init__(
        self,
        duration: float,
    ) -> None:
        self._duration = duration
        self._started_at: datetime | None = None
