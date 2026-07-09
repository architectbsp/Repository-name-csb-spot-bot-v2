from __future__ import annotations

import time


class RetryPolicy:
    def __init__(
        self,
        max_attempts: int,
        delay: float,
    ) -> None:
        self._max_attempts = max_attempts
        self._delay = delay

    def max_attempts(self) -> int:
        return self._max_attempts

    def delay(self) -> float:
        return self._delay

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
                if self._delay > 0:
                    time.sleep(self._delay)

        raise last_error
