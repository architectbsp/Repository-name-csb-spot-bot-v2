from datetime import datetime, timedelta


class Timer:
    def __init__(self, duration: timedelta):
        self._duration = duration
        self._started_at: datetime | None = None

    def start(self) -> None:
        self._started_at = datetime.now()

    def reset(self) -> None:
        self._started_at = None

    def is_started(self) -> bool:
        return self._started_at is not None

    def elapsed(self) -> timedelta:
        if self._started_at is None:
            return timedelta()

        return datetime.now() - self._started_at

    def remaining(self) -> timedelta:
        remaining = self._duration - self.elapsed()
        return max(remaining, timedelta())

    def is_expired(self) -> bool:
        return self.elapsed() >= self._duration
