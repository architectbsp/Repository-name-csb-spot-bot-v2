from __future__ import annotations

import time


class RetryPolicy:
    """
    Retry helper with exponential backoff.

    `delay` is the base wait after the first failure; subsequent waits
    are `delay * (backoff_factor ** (attempt - 1))`, capped by
    `max_delay` when set.
    """

    def __init__(
        self,
        max_attempts: int,
        delay: float,
        *,
        backoff_factor: float = 2.0,
        max_delay: float | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._delay = delay
        self._backoff_factor = max(1.0, float(backoff_factor))
        self._max_delay = max_delay

    def max_attempts(self) -> int:
        return self._max_attempts

    def delay(self) -> float:
        return self._delay

    def backoff_factor(self) -> float:
        return self._backoff_factor

    def delay_for_attempt(self, attempt: int) -> float:
        """Wait after a failed `attempt` (1-based) before the next try."""
        if attempt < 1:
            attempt = 1
        wait = self._delay * (self._backoff_factor ** (attempt - 1))
        if self._max_delay is not None:
            wait = min(wait, self._max_delay)
        return wait

    def is_last_attempt(self, attempt: int) -> bool:
        return attempt >= self._max_attempts

    def reset(self) -> None:
        pass

    def execute(self, operation):
        if not callable(operation):
            return operation

        last_error = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return operation()
            except Exception as exc:
                last_error = exc
                if self.is_last_attempt(attempt):
                    raise
                wait = self.delay_for_attempt(attempt)
                if wait > 0:
                    time.sleep(wait)

        raise last_error
