from datetime import datetime, timedelta


class Timer:
    def __init__(self, duration: timedelta):
        self._duration = duration
        self._started_at: datetime | None = None

    @property
    def duration(self) -> timedelta:
        return self._duration

    @property
    def started_at(self) -> datetime | None:
        return self._started_at

    def start(self) -> None:
        self._started_at = datetime.now()

    def stop(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._started_at = None

    def restart(self) -> None:
        self.start()

    def is_started(self) -> bool:
        return self._started_at is not None

    def is_stopped(self) -> bool:
        return not self.is_started()

    def is_idle(self) -> bool:
        return self._started_at is None

    def elapsed(self) -> timedelta:
        if self._started_at is None:
            return timedelta()

        return datetime.now() - self._started_at

    def remaining(self) -> timedelta:
        remaining = self._duration - self.elapsed()
        return max(remaining, timedelta())

    def is_expired(self) -> bool:
        return self.elapsed() >= self._duration

    def has_remaining(self) -> bool:
        return not self.is_expired()

    def is_running(self) -> bool:
        return self.is_started() and not self.is_expired()

    def is_finished(self) -> bool:
        return self.is_expired()

    def __len__(self) -> int:
        return int(self.remaining().total_seconds())

    def __bool__(self) -> bool:
        return self.is_started()

    def __str__(self) -> str:
        return str(self.remaining())

    def __repr__(self) -> str:
        return (
            f"Timer(duration={self._duration}, "
            f"started_at={self._started_at})"
        )
