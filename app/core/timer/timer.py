from datetime import datetime, timedelta


class Timer:
    def __init__(self, duration: timedelta):
        self._duration = duration
        self._started_at: datetime | None = None

    def start(self) -> None:
        self._started_at = datetime.now()

    def reset(self) -> None:
        self._started_at = None
